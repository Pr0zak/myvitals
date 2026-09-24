import asyncio
import bisect
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..analytics import compare
from ..analytics.sleep import _night_window as _sleep_night_window
from ..auth import require_any
from ..db import models
from ..db.session import get_session
from ..config import settings
from ..schemas import TodaySummary

router = APIRouter(dependencies=[Depends(require_any)])
log = logging.getLogger(__name__)

# Most stale days one /summary/range call will rebuild inline. See the
# comment at the recompute loop — the cap is about not exceeding the
# client's patience, not about the work being optional.
MAX_LAZY_RECOMPUTES = 60

# Serializes lazy compute_daily_summary recomputes triggered on read. Phone +
# web both hit /summary/today on load; without this they each run the recompute
# (wasted work, and a window for double-inserting alerts). Single-user app, so
# one global lock is plenty — recompute is fast and rare.
_lazy_compute_lock = asyncio.Lock()


def _local_tz() -> Any:
    """The user's timezone, falling back to UTC when it will not resolve."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(settings.tz) if settings.tz != "UTC" else timezone.utc
    except Exception:
        return timezone.utc


def _resolve_last_sync(
    hb: models.SyncHeartbeat | None,
    last_hr_sample_at: datetime | None,
) -> datetime | None:
    """Sync-freshness fallback, mirroring what `/query/last-sync` reads.

    Three rungs, most direct signal first: the phone's own record of when
    it last *succeeded*; if it has never succeeded but has tried, when it
    last *attempted*; and only with no `sync_heartbeat` row at all — an
    install predating that table, or one that hasn't posted yet — the last
    watch HR sample, so the field still resolves to something rather than
    regressing to "never synced" (SA-L6 correction; `SideNav.vue` keeps the
    same `lastAttemptAt ?? lastSyncAt` order for the identical reason).
    """
    if hb is not None:
        if hb.last_success_at is not None:
            return hb.last_success_at
        if hb.attempt_at is not None:
            return hb.attempt_at
    return last_hr_sample_at


async def current_last_sync(db: AsyncSession) -> datetime | None:
    return (await _sync_signals(db))[0]


async def _sync_signals(
    db: AsyncSession,
) -> tuple[datetime | None, datetime | None]:
    """`(last_sync, last_hr_sample_at)`.

    `last_sync` is the one "synced Xm ago" timestamp, shared by
    `/summary/today` and `/summary/tiles` (UI-3) so the two can never
    disagree.

    Filtered through the same predicate as `/query/last-sync` (UX-D9):
    without it the local debug build's heartbeat could supply the home
    screen's "last sync" — the SA-O2 ghost, on a path that fix missed.
    """
    last_hr_sample_at = (await db.execute(
        select(func.max(models.HeartRate.time))
    )).scalar()
    hb = (await db.execute(
        select(models.SyncHeartbeat)
        .where(models.real_install_heartbeat_filter())
        .order_by(models.SyncHeartbeat.attempt_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    return _resolve_last_sync(hb, last_hr_sample_at), last_hr_sample_at


def resolve_day(requested: date | None = None) -> tuple[date, Any, bool]:
    """Resolve a day-facing request to ``(day, tzinfo, is_today)``.

    A user-facing "today" is the user's LOCAL day, never the UTC one. The
    container runs TZ=UTC while the user is Central, so the UTC date rolls at
    7pm CDT and any endpoint deriving a calendar day from UTC starts
    answering for tomorrow every evening. That bug has shipped three separate
    times -- ``/summary/today``, then ``/summary/readiness`` in v0.7.369, and
    ``today_snapshot`` was still carrying a bare ``date.today()`` when TD-3
    found it. Every day-facing endpoint calls this now rather than repeating
    the block.

    ``is_today`` matters as much as the date. Several endpoints repair a
    stale ``daily_summary`` row and splice in a live step count before
    answering, and both of those are only ever correct for the current day --
    doing either while looking at last Tuesday would rewrite history from
    today's samples.
    """
    tz = _local_tz()
    today = datetime.now(tz).date()
    day = requested or today
    return day, tz, day == today


async def _today_row_is_stale(
    db: AsyncSession, saved: "models.DailySummary | None",
    today_local: date, day_start: datetime, day_end: datetime,
) -> bool:
    """A daily_summary row is stale when underlying data exists today
    but the row hasn't picked it up yet — typically because the 03:00
    cron ran before the user finished sleeping. Recomputing on read
    closes that gap (the cron stays as a backstop for older dates)."""
    # Sleep — most common reason for stale rows. User finishes sleep
    # late morning; 03:00 cron computed before any sleep_stages landed.
    if saved is None or saved.sleep_duration_s is None:
        sleep_count = (await db.execute(
            select(func.count())
            .select_from(models.SleepStage)
            .where(models.SleepStage.time >= day_start)
            .where(models.SleepStage.time <= day_end)
        )).scalar() or 0
        if sleep_count > 0:
            return True
    # HRV — overnight metric, same story as sleep.
    if saved is None or saved.hrv_avg is None:
        hrv_count = (await db.execute(
            select(func.count(models.Hrv.time))
            .where(models.Hrv.time >= day_start)
            .where(models.Hrv.time <= day_end)
        )).scalar() or 0
        if hrv_count > 0:
            return True
    # Steps — a different shape of staleness from the two above, and the
    # reason the row can be wrong for months. Sleep and HRV land once and
    # the row is then final; steps accumulate all day, so a row written at
    # 00:05 (or by the startup job) holds a partial count, and once sleep
    # and HRV HAVE landed neither branch above ever fires again. The row
    # can never repair itself: 32 of the last 100 stored days were short,
    # the worst by 17,733 steps, while /query/steps rendered the right
    # number on the Steps screen for the same day.
    #
    # Recounted through the same helper `compute_daily_summary` writes
    # with, and compared with a tolerance — an exact test would rebuild
    # the row on every page load while the user is out walking.
    from ..analytics.jobs import canonical_steps_total, steps_total_is_stale

    canonical = await canonical_steps_total(db, day_start, day_end)
    if steps_total_is_stale(saved.steps_total if saved else None, canonical):
        return True
    return False


def _hrv_night_window(day: date, local_tz: Any) -> tuple[datetime, datetime]:
    """A local-clock 22:00→09:00 net for the night ending on `day`.

    `baselines.py:_night_window` (SA-N1) now prefers the exact canonical
    SleepSession boundary and only falls back to a local clock window when
    no session exists — a per-day answer that needs a DB lookup per
    candidate day, which is exactly the O(days) round-trip cost this
    staleness scan exists to avoid. This is deliberately a wider, cheaper
    APPROXIMATION rather than that exact function: staleness detection only
    needs to know a night ending on `day` produced SOME sample, not its
    precise bounds, and SA-N1 measured this user's actual sessions at a
    median 22:41→06:20 local — comfortably inside this window regardless of
    which branch the live computation takes. A real night with no sample
    anywhere in an 11-hour local-clock span is not a case this scan needs
    to catch. Local time, not UTC, on purpose — hard-coding a UTC clock
    hour here is the exact SA-N1 bug applied to a second call site.
    """
    start = datetime.combine(day - timedelta(days=1), time(hour=22), tzinfo=local_tz)
    end = datetime.combine(day, time(hour=9), tzinfo=local_tz)
    return start, end


def _owning_days(
    times: list[datetime],
    night_window: Any,
    since: date,
    until: date,
) -> set[date]:
    """Which day in `[since, until]` does each raw sample's NIGHT belong to?

    SA-N2. `compute_daily_summary` attributes a night to the day it ENDS
    (`_stages_for_night` / `nightly_hrv`, both windowed via a `night_window`
    function of exactly this shape), but the staleness scan this feeds used
    to ask for the sample's OWN local calendar date instead. For every
    evening sample that mismatch is off by one day: the write always lands
    on D+1 while the scan keeps flagging D, which has no sleep_stage/hrv
    row of its own and so can never stop looking stale.

    Takes a `night_window(day) -> (start, end)` function rather than
    re-deriving hours here, and the caller passes each metric's OWN
    function — sleep and HRV do not share a window (`sleep.py`'s is
    18:00→14:00 UTC; HRV's is `_hrv_night_window` above) — so this also
    keeps working if sleep's window definition changes.

    A sample that falls in neither day's window (the gap between one
    night's end and the next one's start) belongs to no day, same as it
    contributes to no day's write.
    """
    if not times:
        return set()
    # Every candidate day's window, computed once — pure Python, no DB —
    # and sorted by start (it already is: window(d).start = d-1 at a fixed
    # hour, strictly increasing with d) so each sample is placed with a
    # bisect instead of a scan over the whole calendar range. Normalised to
    # UTC immediately: `times` are already UTC (straight from the DB), and
    # comparing two tz-AWARE datetimes recomputes both sides' `utcoffset()`
    # on every comparison — cheap for a fixed UTC offset, measurably not for
    # a `ZoneInfo` (HRV's local-clock window), which re-derives the DST rule
    # for that instant each time. A year of HRV samples against a
    # ZoneInfo-tagged window measured 220ms of that recomputation alone;
    # doing the tz conversion 365 times up front instead of ~25,000 times
    # in the bisect loop dropped it to noise.
    days: list[date] = []
    starts: list[datetime] = []
    ends: list[datetime] = []
    d = since
    while d <= until:
        start, end = night_window(d)
        days.append(d)
        starts.append(start.astimezone(timezone.utc))
        ends.append(end.astimezone(timezone.utc))
        d += timedelta(days=1)

    owning: set[date] = set()
    for ts in times:
        i = bisect.bisect_right(starts, ts) - 1
        if i >= 0 and ts <= ends[i]:
            owning.add(days[i])
    return owning


async def live_steps_today(
    db: AsyncSession, day_start: datetime, end: datetime,
) -> int:
    """Today's step count from the raw samples, not the stored column.

    `daily_summary.steps_total` is only written by `compute_daily_summary`,
    which is no longer scheduled and whose lazy re-run is gated on missing
    sleep / HRV — so mid-day the stored column is whatever it was when that
    last fired, or absent entirely. /summary/today has always computed this
    live; /summary/tiles read the column and consequently showed a step
    count hours out of date next to a live one on the same screen.

    Picks a single canonical source so the count matches the user's wrist
    rather than summing phone and watch pedometers, which fire on different
    minute boundaries and would roughly double the total.
    """
    from ..analytics.jobs import pick_canonical_steps_source

    canonical = await pick_canonical_steps_source(db, day_start, end)
    if not canonical:
        return 0
    total = await db.execute(
        select(func.coalesce(func.sum(models.Steps.count), 0))
        .where(models.Steps.source == canonical)
        .where(models.Steps.time >= day_start)
        .where(models.Steps.time <= end)
    )
    return int(total.scalar() or 0)


async def _ensure_fresh_today_row(
    db: AsyncSession, today_local: date, day_start: datetime, day_end: datetime,
) -> "models.DailySummary | None":
    """Return today's daily_summary row, recomputing it first if stale.

    Shared by `/today` and `/tiles`. An endpoint that reads the stored row
    directly instead of coming through here shows a staler picture than the
    rest of the app — which is exactly the "two surfaces disagree about the
    same day" bug the architecture rule exists to prevent. It bit /tiles
    immediately: weight and blood pressure read as absent while
    /summary/today was already reporting both.
    """
    saved = (await db.execute(
        select(models.DailySummary).where(models.DailySummary.date == today_local)
    )).scalar_one_or_none()
    if not await _today_row_is_stale(db, saved, today_local, day_start, day_end):
        return saved
    async with _lazy_compute_lock:
        try:
            # Re-read under the lock — another request may have just
            # recomputed while we waited, making our compute redundant.
            saved = (await db.execute(
                select(models.DailySummary)
                .where(models.DailySummary.date == today_local)
            )).scalar_one_or_none()
            if await _today_row_is_stale(db, saved, today_local, day_start, day_end):
                from ..analytics.jobs import compute_daily_summary
                await compute_daily_summary(today_local)
                saved = (await db.execute(
                    select(models.DailySummary)
                    .where(models.DailySummary.date == today_local)
                )).scalar_one_or_none()
                log.info("recomputed stale daily_summary for %s", today_local)
        except Exception as e:  # noqa: BLE001
            log.warning("on-demand daily_summary recompute failed: %s", e)
    return saved


@router.get("/today", response_model=TodaySummary)
async def today(db: AsyncSession = Depends(get_session)) -> TodaySummary:
    """
    Returns the saved daily_summary row for today if the analytics job
    has run; otherwise computes a best-effort live snapshot.
    """
    # Resolve "today" in the user's configured TZ rather than UTC.
    # With TZ=UTC, on Central time the UTC day starts at 7pm CDT the
    # previous evening, so 5 hours of yesterday's steps were leaking
    # into today's count.
    try:
        from zoneinfo import ZoneInfo
        local_tz = ZoneInfo(settings.tz) if settings.tz != "UTC" else timezone.utc
    except Exception:
        local_tz = timezone.utc
    now_local = datetime.now(local_tz)
    today_local = now_local.date()
    midnight_local = datetime.combine(today_local, datetime.min.time(), tzinfo=local_tz)
    end = datetime.now(timezone.utc)

    day_end = datetime.combine(today_local, datetime.max.time(), tzinfo=local_tz)

    # 1. Persisted summary, with stale-row repair: if today's row is
    # missing sleep / HRV but the underlying tables have data, it is
    # recomputed on-demand. Replaces the cron-only model where a 03:00
    # row missed late-morning sleep data.
    saved = await _ensure_fresh_today_row(db, today_local, midnight_local, day_end)

    # 2. Compute live values as a fallback / supplement.
    steps_total = await live_steps_today(db, midnight_local, end)

    # last_sync means sync freshness, not "when did HR last land" — those two
    # only agree while the watch is actively writing HR. This used to be a
    # bare max(HeartRate.time), so a watch that stopped writing HR while the
    # phone kept syncing fine every 15 minutes rendered as "amber, synced
    # 58h ago" on both home screens — the exact "phone stopped vs upstream
    # stopped" confusion HEALTH-1 exists to prevent (SA-L6).
    last_sync, last_hr_sample_at = await _sync_signals(db)

    # Today's row may exist (e.g., backfill ran mid-day) but be sparse —
    # the Pixel Watch hasn't yet synced today's RHR/HRV/sleep. Pull the
    # most recent row that has a recovery_score and use ITS values for
    # any field today's row leaves null. Steps/last_sync still reflect
    # today's live counts.
    fallback = (await db.execute(
        select(models.DailySummary)
        .where(models.DailySummary.recovery_score.is_not(None))
        .order_by(models.DailySummary.date.desc())
        .limit(1)
    )).scalar_one_or_none()

    # Weight / body-fat / blood-pressure are sporadic "latest" stats — recorded
    # only on days with a weigh-in / cuff reading. daily_summary carries them
    # only on those days and the recovery-row fallback reaches at most one prior
    # day, so a reading from last week reads as "—". Fall back to the most recent
    # reading overall so the latest known value always shows. The Body cards
    # present these as the last reading (same treatment as weight), not
    # necessarily today's. Skin-temp delta gets the same carry-forward below
    # (today's night often has no computed delta).
    latest_body = (await db.execute(
        select(models.BodyMetric.weight_kg, models.BodyMetric.body_fat_pct,
               models.BodyMetric.time)
        .where(models.BodyMetric.weight_kg.is_not(None))
        .order_by(models.BodyMetric.time.desc())
        .limit(1)
    )).first()
    latest_bp = (await db.execute(
        select(models.BloodPressure.systolic, models.BloodPressure.diastolic,
               models.BloodPressure.time)
        .order_by(models.BloodPressure.time.desc())
        .limit(1)
    )).first()
    latest_body_on = latest_body[2].date().isoformat() if latest_body else None
    latest_bp_on = latest_bp[2].date().isoformat() if latest_bp else None

    # Skin-temp delta is computed per night but not every night (needs a
    # baseline + an overnight reading), so today's row is often null even
    # though a recent night has one. Carry forward the latest non-null delta.
    latest_skin = (await db.execute(
        select(models.DailySummary.skin_temp_delta_avg, models.DailySummary.date)
        .where(models.DailySummary.skin_temp_delta_avg.is_not(None))
        .order_by(models.DailySummary.date.desc())
        .limit(1)
    )).first()
    latest_skin_on = latest_skin[1].isoformat() if latest_skin else None

    # Which fields came from an earlier day rather than today's row. The
    # carry-forward is intentional — a missing overnight sync shouldn't blank
    # the whole screen — but it has to be visible, or the clients state
    # yesterday's HRV, sleep and readiness as today's fact.
    carried_from: dict[str, str] = {}

    def pick(field: str):
        v = getattr(saved, field, None) if saved else None
        if v is None and fallback is not None:
            v = getattr(fallback, field, None)
            if v is not None:
                carried_from[field] = fallback.date.isoformat()
        if v is None and latest_body is not None:
            if field == "weight_kg":
                carried_from[field] = latest_body_on
                return latest_body[0]
            if field == "body_fat_pct":
                carried_from[field] = latest_body_on
                return latest_body[1]
        if v is None and latest_bp is not None:
            if field == "bp_systolic_avg":
                carried_from[field] = latest_bp_on
                return latest_bp[0]
            if field == "bp_diastolic_avg":
                carried_from[field] = latest_bp_on
                return latest_bp[1]
        if v is None and field == "skin_temp_delta_avg" and latest_skin is not None:
            carried_from[field] = latest_skin_on
            return latest_skin[0]
        return v

    if saved or fallback:
        return TodaySummary(
            date=(saved.date if saved else (fallback.date if fallback else today_local)),
            resting_hr=pick("resting_hr"),
            hrv_avg=pick("hrv_avg"),
            recovery_score=pick("recovery_score"),
            sleep_duration_s=pick("sleep_duration_s"),
            sleep_score=pick("sleep_score"),
            # Steps always use today's live count — never fall back to
            # yesterday's row, that would show stale step counts as "today's".
            steps_total=steps_total,
            weight_kg=pick("weight_kg"),
            body_fat_pct=pick("body_fat_pct"),
            bp_systolic_avg=pick("bp_systolic_avg"),
            bp_diastolic_avg=pick("bp_diastolic_avg"),
            skin_temp_delta_avg=pick("skin_temp_delta_avg"),
            readiness_score=pick("readiness_score"),
            training_stress_score=pick("training_stress_score"),
            ctl=pick("ctl"), atl=pick("atl"), tsb=pick("tsb"),
            sleep_consistency_score=pick("sleep_consistency_score"),
            sleep_debt_h=pick("sleep_debt_h"),
            fasting_hours=pick("fasting_hours"),
            last_sync=last_sync,
            last_hr_sample_at=last_hr_sample_at,
            # Last, so every pick() above has already recorded into it.
            carried_from=carried_from,
        )

    # No saved summaries at all — return live counts only.
    return TodaySummary(
        date=today_local,
        steps_total=steps_total,
        last_sync=last_sync,
        last_hr_sample_at=last_hr_sample_at,
    )


@router.get("/readiness")
async def readiness_detail(
    date_: date | None = Query(None, alias="date"),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Today's readiness with the drivers that produced it, plus a 7-day
    series for the sparkline.

    Exists because the clients rendered readiness as a bare number: the
    drivers were computed inside `readiness_score` and discarded, so there
    was no way to answer "why is it 42 today?" without opening the code.
    Derived server-side per the architecture rule — nothing here is
    recomputed in Compose or Vue.
    """
    from ..analytics.advanced import readiness_breakdown

    today, local_tz, is_today = resolve_day(date_)
    # Stale-row repair, but only for the current day. Without it readiness
    # could report "no inputs" from a row that /summary/today had already
    # recomputed — the surfaces-disagree bug again, with the hero as the one
    # telling the wrong story. Running it for a PAST day would be worse than
    # not running it at all: it would rebuild a historical row from whatever
    # samples exist now.
    if is_today:
        midnight_local = datetime.combine(today, datetime.min.time(), tzinfo=local_tz)
        day_end = datetime.combine(today, datetime.max.time(), tzinfo=local_tz)
        row = await _ensure_fresh_today_row(db, today, midnight_local, day_end)
    else:
        row = await db.get(models.DailySummary, today)
    breakdown = await readiness_breakdown(
        db, today,
        hrv=row.hrv_avg if row else None,
        rhr=row.resting_hr if row else None,
        sleep_score=row.sleep_score if row else None,
        sleep_duration_s=row.sleep_duration_s if row else None,
    )

    # Trailing 7 days of stored readiness for the sparkline. Stored, not
    # recomputed — these are the numbers the rest of the app already shows.
    since = today - timedelta(days=6)
    hist = (await db.execute(
        select(models.DailySummary.date, models.DailySummary.readiness_score)
        .where(models.DailySummary.date >= since)
        .where(models.DailySummary.date <= today)
        .order_by(models.DailySummary.date)
    )).all()
    # Pad every day in the window. Skipping absent rows makes the sparkline
    # close its gaps — implying continuity the data doesn't have — and puts
    # the "today" emphasis on the last day that HAPPENED to have a row.
    # `tiles.py:_series` already pads; this is the same contract.
    by_day = {d: v for d, v in hist}
    series = [
        {
            "date": (since + timedelta(days=i)).isoformat(),
            "score": (
                round(by_day[since + timedelta(days=i)], 1)
                if by_day.get(since + timedelta(days=i)) is not None else None
            ),
        }
        for i in range((today - since).days + 1)
    ]

    return {
        "date": today.isoformat(),
        "score": breakdown["score"],
        "band": breakdown["band"],
        "reason": breakdown.get("reason"),
        "drivers": breakdown["drivers"],
        "series": series,
        # The literal weights, so the "how is this calculated" sheet is
        # generated from the same source as the score rather than a
        # hand-copied string that can drift.
        "weights": {
            "hrv": 0.40, "rhr": 0.30,
            "sleep_score": 0.15, "sleep_duration": 0.15,
        },
        "bands": {"low": "≤29", "moderate": "30–64", "high": "≥65"},
    }


@router.get("/tiles")
async def summary_tiles(
    date_: date | None = Query(None, alias="date"),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Per-tile value + 14-day series + whether that value is good.

    The vitals grid rendered bare numbers, which are unreadable without
    knowing the user's own normal and which direction is better. All of
    that judgement is made here rather than in Compose or Vue, so the two
    grids cannot disagree — see the architecture rule in CLAUDE.md.
    """
    from ..analytics.tiles import tile_stats

    day, local_tz, is_today = resolve_day(date_)
    midnight_local = datetime.combine(day, datetime.min.time(), tzinfo=local_tz)

    steps_now: int | None = None
    if is_today:
        # Same stale-row repair `/summary/today` does. Without it the tiles
        # read a row the rest of the app has already moved past — weight and
        # blood pressure showed as absent while /summary/today reported both.
        # Both this and the live step count are today-only by nature: a past
        # day's row is finished, and splicing this minute's step total into
        # last Tuesday would be a fabrication.
        day_end = datetime.combine(day, datetime.max.time(), tzinfo=local_tz)
        await _ensure_fresh_today_row(db, day, midnight_local, day_end)
        steps_now = await live_steps_today(db, midnight_local, datetime.now(timezone.utc))

    profile = await db.get(models.UserProfile, 1)
    tiles = await tile_stats(db, day, profile, steps_override=steps_now)

    # "Vitals 3 of 5 in range" — the reference's Health status line. Counted
    # here rather than in the clients: it is a roll-up of server verdicts,
    # and two surfaces disagreeing on the count would be the same bug class
    # as two surfaces disagreeing on a value.
    from ..analytics.tiles import FOCUS_AREAS, GROUP_ORDER

    judged = [t for t in tiles if t.get("status")]
    # "3 tracked" per Focus area — counted from tiles that actually have a
    # value today, so the subtitle reports something real instead of a
    # constant. Counted server-side for the same reason the grouping is.
    with_data = {t["key"] for t in tiles if t.get("value") is not None}
    focus = {
        area: {
            "tracked": sum(1 for k in keys if k in with_data),
            "total": len(keys),
        }
        for area, keys in FOCUS_AREAS.items()
    }
    # Weekly steps progress, for the hero ring. Summed from the tile series
    # that is already loaded rather than a second query, and expressed
    # against seven days of the user's OWN daily goal — not an invented
    # weekly target.
    steps_tile = next((t for t in tiles if t["key"] == "steps"), None)
    week_done = int(sum(
        p["value"] for p in (steps_tile or {}).get("series", [])[-7:]
        if p.get("value") is not None
    ))
    week_goal = int((steps_tile or {}).get("target") or 0) * 7
    week = {
        "label": "Weekly steps",
        "done": week_done,
        "goal": week_goal,
        "pct": round(week_done / week_goal * 100, 1) if week_goal else 0.0,
    }

    # UI-3 — Body's hero says "synced Xm ago" beside the in-range count.
    # The same resolver /summary/today uses, so the home and Body cannot
    # name two different sync times.
    last_sync = await current_last_sync(db)

    return {
        "date": day.isoformat(),
        "tiles": tiles,
        "week": week,
        "last_sync": last_sync.isoformat() if last_sync else None,
        "group_order": GROUP_ORDER,
        "focus_areas": focus,
        "summary": {
            "judged": len(judged),
            "in_range": sum(1 for t in judged if t["status"] != "watch"),
            "total": len(tiles),
        },
    }


@router.get("/events")
async def summary_events(
    date_: date | None = Query(None, alias="date"),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Plain-language cards for today's sleep, with hypnogram segments.

    Deterministic and free — no LLM. See analytics/events.py for why, and
    for the stage-overlap clamping the raw rows need.
    """
    from ..analytics.events import day_events

    day, local_tz, _is_today = resolve_day(date_)
    return {
        "date": day.isoformat(),
        "events": await day_events(db, day, local_tz),
    }


class EventFeedbackIn(BaseModel):
    """`up`, `down`, or null to clear a previous vote."""
    vote: str | None = None


@router.post("/events/{event_id:path}/feedback")
async def event_feedback(
    event_id: str,
    body: EventFeedbackIn,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Record 👍/👎 on a narrative card.

    Stored as a generic annotation rather than in a new table — the
    annotations row is already {ts, type, payload, note}, which is exactly
    this shape, so no migration. Re-voting writes a newer row and the
    reader takes the latest, so a card carries one vote rather than a pile.

    `event_id` uses :path because the id embeds an ISO timestamp with
    colons; without it the route would not match.
    """
    from ..analytics.events import FEEDBACK_TYPE

    if body.vote not in (None, "up", "down"):
        raise HTTPException(status_code=422, detail="vote must be up, down or null")

    db.add(models.Annotation(
        ts=datetime.now(timezone.utc),
        type=FEEDBACK_TYPE,
        payload={"event_id": event_id, "vote": body.vote},
    ))
    await db.commit()
    return {"ok": True, "event_id": event_id, "vote": body.vote}


@router.get("/range", response_model=list[TodaySummary])
async def summary_range(
    since: date = Query(...),
    until: date | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> list[TodaySummary]:
    """Daily summaries between two dates (inclusive). Recomputes any
    date in the range whose row is missing OR whose underlying sleep /
    HRV data is newer than the row — same on-demand recompute logic as
    /summary/today, applied to the full window. Replaces the 03:00
    daily_summary cron (which would silently miss days when ingest
    landed late)."""
    try:
        from zoneinfo import ZoneInfo
        local_tz = ZoneInfo(settings.tz) if settings.tz != "UTC" else timezone.utc
    except Exception:
        local_tz = timezone.utc
    end = until or datetime.now(local_tz).date()

    # Load existing rows in the window (one query).
    existing_rows = (await db.execute(
        select(models.DailySummary)
        .where(models.DailySummary.date >= since)
        .where(models.DailySummary.date <= end)
    )).scalars().all()
    by_date = {r.date: r for r in existing_rows}

    # Identify dates needing a recompute. For each date in the range:
    #   - missing row → recompute
    #   - row's sleep_duration_s is null but a night ending on this date has
    #     sleep_stages data → recompute
    #   - row's hrv_avg is null but a night ending on this date has vitals_hrv
    #     data → recompute
    #   - row's steps_total is absent or differs from a fresh canonical
    #     recount by more than the tolerance → recompute
    # Batched staleness scan: instead of firing up to 2 count() queries per
    # day (O(days) round-trips — ~730 on a 1-year Trends load), pull the raw
    # sleep_stage / hrv samples across the whole window in two queries, then
    # decide per-day in Python.
    tzname = settings.tz if local_tz is not timezone.utc else "UTC"
    window_start = datetime.combine(since, datetime.min.time(), tzinfo=local_tz)
    window_end = datetime.combine(end, datetime.max.time(), tzinfo=local_tz)

    # SA-N2: a night is attributed to the day it ENDS
    # (`_stages_for_night(day)` / `nightly_hrv(day)` both read a window that
    # ends ON `day`), not to the sample's own local calendar date. The old
    # version of this scan cast each raw sample to its own date, so every
    # evening sample flagged the day it occurred on (D) while the write
    # always landed on the day the night ends (D+1) — D has no row of its
    # own to ever satisfy the check, so it was rescanned and recomputed on
    # every single call, forever. `_owning_days` maps samples the same way
    # the write does, and each metric passes its OWN window function since
    # sleep and HRV do not share one (see its docstring). Padded a day each
    # side of the query window because a night ending on `since` starts
    # the evening BEFORE `since`, and one ending after `end`'s local
    # midnight can still belong to `end`.
    pad_start = window_start - timedelta(days=1)
    pad_end = window_end + timedelta(days=1)
    sleep_times = (await db.execute(
        select(models.SleepStage.time)
        .where(models.SleepStage.time >= pad_start)
        .where(models.SleepStage.time <= pad_end)
    )).scalars().all()
    hrv_times = (await db.execute(
        select(models.Hrv.time)
        .where(models.Hrv.time >= pad_start)
        .where(models.Hrv.time <= pad_end)
    )).scalars().all()
    sleep_days = _owning_days(sleep_times, _sleep_night_window, since, end)
    hrv_days = _owning_days(
        hrv_times, lambda d: _hrv_night_window(d, local_tz), since, end)
    # Steps are not a set of "days that have data" like the two above but a
    # per-day NUMBER, because the stored column goes stale by being partial
    # rather than by being null — see the steps branch of
    # `_today_row_is_stale`. One query for the whole window, same canonical
    # source + plain SUM arithmetic `compute_daily_summary` writes.
    from ..analytics.jobs import canonical_steps_by_day, steps_total_is_stale

    steps_by_day = await canonical_steps_by_day(
        db, window_start, window_end, tzname)

    cur = since
    needs_recompute: list[date] = []
    while cur <= end:
        row = by_date.get(cur)
        if (row is None or row.sleep_duration_s is None) and cur in sleep_days:
            needs_recompute.append(cur)
        elif (row is None or row.hrv_avg is None) and cur in hrv_days:
            needs_recompute.append(cur)
        elif steps_total_is_stale(
            row.steps_total if row else None, steps_by_day.get(cur)
        ):
            needs_recompute.append(cur)
        cur = cur + timedelta(days=1)

    if needs_recompute:
        # Bounded per request. A year of Trends loaded for the first time
        # after this shipped can find a hundred wrong days at once, and
        # rebuilding them all inline would stall the request past the point
        # the client gives up — after which the retry finds the same work
        # again and nothing ever finishes. Oldest first, because
        # `update_training_load` seeds each day off yesterday's stored row,
        # so walking forward heals the chain; the days left over stop
        # qualifying one batch at a time on subsequent loads.
        todo = needs_recompute[:MAX_LAZY_RECOMPUTES]
        async with _lazy_compute_lock:
            try:
                from ..analytics.jobs import compute_daily_summary
                for d in todo:
                    try:
                        await compute_daily_summary(d)
                    except Exception as e:  # noqa: BLE001
                        log.warning("recompute %s failed: %s", d, e)
                log.info("/summary/range recomputed %d of %d stale days",
                         len(todo), len(needs_recompute))
            except Exception as e:  # noqa: BLE001
                log.warning("on-demand summary_range recompute failed: %s", e)

    result = await db.execute(
        select(models.DailySummary)
        .where(models.DailySummary.date >= since)
        .where(models.DailySummary.date <= end)
        .order_by(models.DailySummary.date)
    )
    rows = result.scalars().all()
    # Each day's own step target (UX-D10). The Steps screens drew one flat
    # `steps_goal` line and counted "days ≥ goal" against it, ignoring the
    # per-weekday schedule the home tile already honours — so a day could
    # read as hit on home and missed on Steps. Resolved here, once, by the
    # same function the tile uses.
    from ..analytics.tiles import resolve_steps_goal
    prof = await db.get(models.UserProfile, 1)
    extra = (prof.extra if prof and prof.extra else {}) or {}
    return [
        TodaySummary(
            date=r.date,
            steps_goal=resolve_steps_goal(extra, r.date),
            resting_hr=r.resting_hr,
            hrv_avg=r.hrv_avg,
            recovery_score=r.recovery_score,
            sleep_duration_s=r.sleep_duration_s,
            sleep_score=r.sleep_score,
            steps_total=r.steps_total,
            weight_kg=r.weight_kg,
            body_fat_pct=r.body_fat_pct,
            bp_systolic_avg=r.bp_systolic_avg,
            bp_diastolic_avg=r.bp_diastolic_avg,
            skin_temp_delta_avg=r.skin_temp_delta_avg,
            readiness_score=r.readiness_score,
            training_stress_score=r.training_stress_score,
            ctl=r.ctl, atl=r.atl, tsb=r.tsb,
            sleep_consistency_score=r.sleep_consistency_score,
            sleep_debt_h=r.sleep_debt_h,
            fasting_hours=r.fasting_hours,
        )
        for r in rows
    ]


@router.get("/range/stats")
async def summary_range_stats(
    since: date = Query(...),
    until: date | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """UI-4 — the numbers the Steps / Heart rate / Sleep detail screens print
    for a window, computed once here instead of in Compose and Vue.

    Read from exactly the rows those screens chart: the steps and resting-HR
    blocks from `/summary/range` itself (called, not re-queried, so the
    recompute and per-day goal logic are shared), the sleep block from
    `/query/sleep/range` over the same LOCAL days. A night belongs to the
    local day it ends on, so the sleep window runs from 18:00 the evening
    before `since` to 18:00 on `until`.
    """
    from ..analytics import detail_stats
    from ..localtime import local_today, local_tz
    from .query import get_sleep_range

    end = until or local_today()
    rows = await summary_range(since=since, until=end, db=db)
    tz = local_tz()
    sleep_start = datetime.combine(since - timedelta(days=1), time(18, 0), tzinfo=tz)
    sleep_end = datetime.combine(end, time(18, 0), tzinfo=tz)
    nights = await get_sleep_range(since=sleep_start, until=sleep_end, db=db)
    window_days = (end - since).days + 1

    # UI-F1 — resting HR against the previous window of the same length
    # (the `window_days` LOCAL days ending the day before `since`), read
    # through /summary/range like the current window so both sides use the
    # same recompute. `better` and `tone` are decided in detail_stats.
    prev_until = since - timedelta(days=1)
    prev_since = prev_until - timedelta(days=window_days - 1)
    prev_rows = await summary_range(since=prev_since, until=prev_until, db=db)
    resting = detail_stats.resting_hr_stats(rows)
    resting["vs_previous"] = {
        **detail_stats.window_change(
            [r.resting_hr for r in rows], [r.resting_hr for r in prev_rows],
            better="down"),
        "prev_since": prev_since.isoformat(),
        "prev_until": prev_until.isoformat(),
    }

    # UI-F1 — mean session HR per activity category over the same LOCAL
    # days, from every activity source that carries an avg HR.
    from ..localtime import local_midnight
    acts = (await db.execute(
        select(models.Activity.type, models.Activity.avg_hr)
        .where(models.Activity.start_at >= local_midnight(since))
        .where(models.Activity.start_at < local_midnight(end + timedelta(days=1)))
        .where(models.Activity.avg_hr.is_not(None))
    )).all()

    return {
        "since": since.isoformat(),
        "until": end.isoformat(),
        "steps": detail_stats.steps_stats(rows, window_days),
        "resting_hr": resting,
        "sleep": detail_stats.sleep_stats(nights),
        "hr_by_activity": detail_stats.hr_by_activity_type(
            (t, hr) for t, hr in acts),
    }


def _as_compare_rows(rows: list[Any]) -> list[dict[str, Any]]:
    """DailySummary ORM rows → the dict shape analytics.compare expects.

    Matches ``claude.py:_daily_rows`` field-for-field on purpose: the AI
    payload builders and this endpoint must compute deltas from identical
    inputs, or the number in a Coach card contradicts the number on the
    Compare page for the same week.
    """
    return [
        {
            "date": str(r.date),
            "rhr": r.resting_hr,
            "hrv": r.hrv_avg,
            "recovery": r.recovery_score,
            "readiness": r.readiness_score,
            "sleep_h": (r.sleep_duration_s / 3600.0) if r.sleep_duration_s else None,
            "sleep_score": r.sleep_score,
            "sleep_consistency": r.sleep_consistency_score,
            "sleep_debt_h": r.sleep_debt_h,
            "steps": r.steps_total,
            "tsb": r.tsb,
            "ctl": r.ctl,
            "atl": r.atl,
            "weight_kg": r.weight_kg,
            "body_fat_pct": r.body_fat_pct,
        }
        for r in rows
    ]


@router.get("/compare")
async def summary_compare(
    days: int = Query(7, ge=1, le=365),
    vs: str = Query("previous", pattern="^(previous|last_year)$"),
    until: date | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Period-over-period deltas across the daily-summary metrics (CMP-1).

    ``vs=previous`` compares the trailing ``days`` against the block of
    the same length immediately before it. ``vs=last_year`` compares
    against the same window shifted back 364 days, so weekdays line up.

    The window ends on the user's LOCAL today unless ``until`` is given.
    Deriving it from ``datetime.now(timezone.utc).date()`` would roll the
    window forward at 7pm Central and silently compare a window that
    includes a day that has barely started.
    """
    end, _tz, _is_today = resolve_day(until)
    since = end - timedelta(days=days - 1)
    base_since, base_end = compare.baseline_window(since, end, vs)

    # One query spanning both windows, split in Python. Two queries would
    # be no faster and would open a window where a late-arriving recompute
    # lands between them.
    rows = (await db.execute(
        select(models.DailySummary)
        .where(models.DailySummary.date >= base_since)
        .where(models.DailySummary.date <= end)
        .order_by(models.DailySummary.date)
    )).scalars().all()

    current_rows = _as_compare_rows([r for r in rows if since <= r.date <= end])
    baseline_rows = _as_compare_rows(
        [r for r in rows if base_since <= r.date <= base_end]
    )

    metrics = compare.compare_windows(
        current_rows, baseline_rows, window_days=days,
    )

    return {
        "days": days,
        "vs": vs,
        "current": {"since": since.isoformat(), "until": end.isoformat()},
        "baseline": {
            "since": base_since.isoformat(),
            "until": base_end.isoformat(),
        },
        "metrics": metrics,
        "order": [m.key for m in compare.COMPARE_METRICS],
    }


@router.get("/today/snapshot")
async def today_snapshot(
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """TODAY-4: bundled Today-page data in a single round-trip.

    Today.vue used to fire 16 parallel HTTP requests on mount; that
    works but every call pays the TLS+route-handler overhead and the
    waterfall pegs at the slowest one. This endpoint dispatches the
    same handlers in-process via asyncio.gather and returns a single
    union JSON.

    Each section is best-effort — any handler that raises lands as
    null/empty in its slot so a single broken subsystem doesn't take
    down the whole snapshot. The frontend can opt into this endpoint
    while keeping the per-call fallback for backward compat.
    """
    from datetime import timedelta as _td
    # Avoid circular imports — these modules in turn import .summary.
    from .annotations import list_annotations as _journal_list
    from .fasting import current_fast as _fasting_current
    from .profile import get_profile as _profile_get
    from .query import (
        get_blood_pressure as _bp_get,
        get_heartrate as _hr_get,
        get_hrv as _hrv_get,
        get_last_sleep as _sleep_last,
        get_steps as _steps_get,
        get_weight as _weight_get,
    )
    from .sober import get_current as _sober_current
    from .ai import list_goals as _goals_list

    now = datetime.now(timezone.utc)
    day_ago = now - _td(days=1)
    seven_ago = (now - _td(days=7)).date()
    thirty_ago = now - _td(days=30)
    # date.today() reads the CONTAINER's clock, and the container runs
    # TZ=UTC — so this was the local-day bug wearing a different hat, silent
    # every evening after the UTC rollover.
    today_local, _tz, _is_today = resolve_day()

    # SQLAlchemy AsyncSession can't run concurrent ops, so each parallel
    # handler gets its own session. The request-scoped `db` is only used
    # for the synchronous `today()` call which we do first to avoid
    # contention.
    from ..db.session import SessionLocal

    async def safe(name: str, fn):
        try:
            async with SessionLocal() as own_db:
                return name, await fn(own_db)
        except Exception as e:  # noqa: BLE001
            log.warning("snapshot section %s failed: %s", name, e)
            return name, None

    results = await asyncio.gather(
        safe("today", lambda s: today(db=s)),
        safe("summary7d", lambda s: summary_range(since=seven_ago, until=None, db=s)),
        safe("hr24", lambda s: _hr_get(since=day_ago, until=None, bucket_seconds=None, db=s)),
        safe("hrv24", lambda s: _hrv_get(since=day_ago, until=None, db=s)),
        safe("steps24", lambda s: _steps_get(since=day_ago, until=None, db=s)),
        safe("sleep_last", lambda s: _sleep_last(db=s)),
        safe("weight30", lambda s: _weight_get(since=thirty_ago, until=None, db=s)),
        safe("bp30", lambda s: _bp_get(since=thirty_ago, until=None, db=s)),
        safe("annotations1d", lambda s: _journal_list(
            since=day_ago, until=None, type=None, limit=50, db=s,
        )),
        safe("profile", lambda s: _profile_get(db=s)),
        safe("sober", lambda s: _sober_current(addiction="alcohol", db=s)),
        safe("fasting", lambda s: _fasting_current(db=s)),
        safe("goals", lambda s: _goals_list(active_only=True, db=s)),
    )

    snapshot: dict[str, Any] = {"generated_at": now.isoformat()}
    for name, value in results:
        snapshot[name] = value
    return snapshot


@router.get("/day")
async def day_snapshot(
    date_: date | None = Query(None, alias="date"),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Everything about one calendar day, in a single round-trip (DAY-1).

    The day-parameterised twin of ``/today/snapshot``. It reuses that
    endpoint's shape deliberately — ``asyncio.gather`` over per-section
    ``safe()`` wrappers, each with its own session — so one broken
    subsystem lands as ``null`` in its slot rather than failing the whole
    page. On a health dashboard a missing card is recoverable; a blank
    screen because the Strava token expired is not.

    Differences from ``/today/snapshot``, all of them consequences of the
    day being arbitrary:

    * Windows are bounded by the day itself rather than "trailing 24h", so
      opening last Tuesday shows Tuesday, not the 24 hours before now.
    * No stale-row repair and no live step splice. Both only make sense
      for the current day — running them against a past date would
      rewrite history from today's samples.
    * ``sleep`` is the night that ENDED on this day, which is how a person
      reads "Tuesday's sleep": the night of Monday into Tuesday.
    """
    from datetime import timedelta as _td
    # Avoid circular imports — these modules in turn import .summary.
    from .annotations import list_annotations as _journal_list
    from .query import (
        get_blood_pressure as _bp_get,
        get_heartrate as _hr_get,
        get_hrv as _hrv_get,
        get_sleep_range as _sleep_range,
        get_steps as _steps_get,
        get_weight as _weight_get,
    )
    from ..db.session import SessionLocal

    day, tz, is_today = resolve_day(date_)
    day_start = datetime.combine(day, datetime.min.time(), tzinfo=tz)
    day_end = datetime.combine(day, datetime.max.time(), tzinfo=tz)

    async def safe(name: str, fn):
        try:
            async with SessionLocal() as own_db:
                return name, await fn(own_db)
        except Exception as e:  # noqa: BLE001
            log.warning("day snapshot section %s failed for %s: %s", name, day, e)
            return name, None

    results = await asyncio.gather(
        safe("tiles", lambda s: summary_tiles(date_=day, db=s)),
        safe("events", lambda s: summary_events(date_=day, db=s)),
        safe("readiness", lambda s: readiness_detail(date_=day, db=s)),
        safe("hr", lambda s: _hr_get(
            since=day_start, until=day_end, bucket_seconds=None, db=s)),
        safe("hrv", lambda s: _hrv_get(since=day_start, until=day_end, db=s)),
        safe("steps", lambda s: _steps_get(since=day_start, until=day_end, db=s)),
        # The night that ENDED on this day. A person asking about Tuesday's
        # sleep means Monday night into Tuesday morning, so the window opens
        # the previous evening.
        safe("sleep", lambda s: _sleep_range(
            since=(day_start - _td(days=1)), until=day_end, db=s)),
        safe("weight", lambda s: _weight_get(since=day_start, until=day_end, db=s)),
        safe("blood_pressure", lambda s: _bp_get(
            since=day_start, until=day_end, db=s)),
        safe("annotations", lambda s: _journal_list(
            since=day_start, until=day_end, type=None, limit=100, db=s)),
        safe("activities", lambda s: _day_activities(s, day_start, day_end)),
        safe("workout", lambda s: _day_workout(s, day)),
    )

    snapshot: dict[str, Any] = {
        "date": day.isoformat(),
        "is_today": is_today,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    for name, value in results:
        snapshot[name] = value
    return snapshot


async def _day_activities(
    db: AsyncSession, day_start: datetime, day_end: datetime,
) -> list[dict[str, Any]]:
    """Activities that STARTED on this day.

    Bounded on start_at rather than overlap: an activity that begins at
    23:40 belongs to the day it started, and counting it on both days
    would double it in any per-day total.
    """
    rows = (await db.execute(
        select(models.Activity)
        .where(models.Activity.start_at >= day_start)
        .where(models.Activity.start_at <= day_end)
        .order_by(models.Activity.start_at)
    )).scalars().all()
    return [
        {
            "source": a.source,
            "source_id": a.source_id,
            "type": a.type,
            "name": a.name,
            "start_at": a.start_at.isoformat(),
            "duration_s": a.duration_s,
            "distance_m": a.distance_m,
            "elevation_gain_m": a.elevation_gain_m,
            "kcal": a.kcal,
            "avg_hr": a.avg_hr,
            "trail_id": a.trail_id,
        }
        for a in rows
    ]


async def _day_workout(db: AsyncSession, day: date) -> dict[str, Any] | None:
    """The strength session planned or completed on this day, if any.

    A compact summary rather than the full hydrated workout: the day view
    is a digest, and the workout page is one tap away for the detail.
    """
    w = (await db.execute(
        select(models.StrengthWorkout)
        .where(models.StrengthWorkout.date == day)
        .where(models.StrengthWorkout.status != "regenerated")
        .order_by(models.StrengthWorkout.id.desc())
        .limit(1)
    )).scalar_one_or_none()
    if w is None:
        return None
    return {
        "id": w.id,
        "date": w.date.isoformat(),
        "status": w.status,
        "split_focus": w.split_focus,
        "notes": w.notes,
    }


@router.get("/sleep-need")
async def sleep_need(
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """A data-derived sleep-need estimate, or why one cannot be made.

    Reported as information, never applied. The typed target keeps
    driving the debt figure, the tile band and the sleep goal unless the
    user changes it themselves — adopting a derived number silently would
    rewrite all three in one deploy.
    """
    from ..analytics.advanced import derive_sleep_need

    day, _tz, _is_today = resolve_day()
    need = await derive_sleep_need(db, day)
    prof = await db.get(models.UserProfile, 1)
    typed = float(prof.sleep_target_h) if prof and prof.sleep_target_h else 8.0

    return {
        "derived_hours": need.hours,
        "usable": need.usable,
        "reason": need.reason,
        "free_day_mean_h": need.free_day_mean_h,
        "work_day_mean_h": need.work_day_mean_h,
        "n_nights": need.n_nights,
        # What is actually in use, so the client never has to guess which
        # number the rest of the app is computing against.
        "target_hours": typed,
        "target_source": "manual",
    }


@router.get("/training-load")
async def training_load(
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Weekly training load against a personal target band.

    Google Health dropped daily cardio goals for weekly load targets, on the
    grounds that a daily number punishes an ordinary rest day. This is that,
    expressed in the units this app already computes.

    The band is not invented. ATL is a 7-day exponentially-weighted load and
    CTL a 42-day one, so ATL/CTL is exactly the acute-to-chronic workload
    ratio, whose 0.8-1.3 "sweet spot" is the standard reading in the training
    literature. Expressing that ratio back in load units gives a target band of
    0.8-1.3 x (CTL x 7) — the same judgement, in the number the user sees.

    Returns null bounds rather than a guess when there is no chronic load to
    compare against: a first week of training has no meaningful target.
    """
    try:
        from zoneinfo import ZoneInfo
        local_tz = ZoneInfo(settings.tz) if settings.tz != "UTC" else timezone.utc
    except Exception:  # noqa: BLE001
        local_tz = timezone.utc
    today = datetime.now(local_tz).date()
    since = today - timedelta(days=6)

    # Computed from SOURCE rows across a 42-day window, not read from
    # daily_summary.training_stress_score. That column is only rewritten when a
    # day's summary is recomputed, and the staleness heuristic watches sleep and
    # HRV — so making strength sessions count would not have reached a single
    # historical day, and this card would have reported zero for a week the user
    # demonstrably trained.
    from ..analytics.advanced import training_load_by_day
    chronic_days = 42
    by_day = await training_load_by_day(
        db, today - timedelta(days=chronic_days - 1), today,
    )

    daily = [
        {
            "date": (since + timedelta(days=i)).isoformat(),
            "load": by_day.get(since + timedelta(days=i), 0.0),
        }
        for i in range(7)
    ]
    week_load = round(sum(x["load"] for x in daily), 1)

    # Rolling-average acute:chronic ratio (Gabbett), rather than the EWMA pair
    # stored on daily_summary: the stored CTL/ATL were accumulated while
    # strength counted for nothing, so they understate chronic load until they
    # re-converge. A rolling mean over source rows is correct immediately.
    chronic_total = sum(by_day.values())
    chronic_week = chronic_total / (chronic_days / 7.0)

    target_low = target_high = acwr = None
    band = "unknown"
    if chronic_week > 0:
        target_low = round(chronic_week * 0.8, 1)
        target_high = round(chronic_week * 1.3, 1)
        acwr = round(week_load / chronic_week, 2)
        band = (
            "under" if week_load < target_low
            else "optimal" if week_load <= target_high
            else "overreaching"
        )

    latest = (await db.execute(
        select(models.DailySummary.ctl, models.DailySummary.atl)
        .where(models.DailySummary.date <= today)
        .order_by(models.DailySummary.date.desc()).limit(1)
    )).first()
    ctl = float(latest[0]) if latest and latest[0] is not None else None
    atl = float(latest[1]) if latest and latest[1] is not None else None

    return {
        "week_load": week_load,
        "target_low": target_low,
        "target_high": target_high,
        "acwr": acwr,
        "band": band,
        "ctl": ctl,
        "atl": atl,
        "daily": daily,
    }
