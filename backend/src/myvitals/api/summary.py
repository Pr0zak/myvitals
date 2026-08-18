import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_any
from ..db import models
from ..db.session import get_session
from ..config import settings
from ..schemas import TodaySummary

router = APIRouter(dependencies=[Depends(require_any)])
log = logging.getLogger(__name__)

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
    return False


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

    last_sync_result = await db.execute(select(func.max(models.HeartRate.time)))
    last_sync = last_sync_result.scalar()

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
        select(models.DailySummary.skin_temp_delta_avg)
        .where(models.DailySummary.skin_temp_delta_avg.is_not(None))
        .order_by(models.DailySummary.date.desc())
        .limit(1)
    )).scalar()

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
            return latest_skin
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
            # Last, so every pick() above has already recorded into it.
            carried_from=carried_from,
        )

    # No saved summaries at all — return live counts only.
    return TodaySummary(
        date=today_local,
        steps_total=steps_total,
        last_sync=last_sync,
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
    from ..analytics.advanced import readiness_band, readiness_breakdown

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

    return {
        "date": day.isoformat(),
        "tiles": tiles,
        "week": week,
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
    #   - row's sleep_duration_s is null but sleep_stages has data → recompute
    #   - row's hrv_avg is null but vitals_hrv has data → recompute
    #   (same heuristic as _today_row_is_stale, applied per date)
    # Batched staleness scan: instead of firing up to 2 count() queries per
    # day (O(days) round-trips — ~730 on a 1-year Trends load), pull the set
    # of local dates that have *any* sleep_stage / hrv sample across the whole
    # window in two GROUP-BY queries, then decide per-day in Python. Same
    # heuristic as _today_row_is_stale, just hoisted out of the loop.
    from datetime import timedelta as _td
    tzname = settings.tz if local_tz is not timezone.utc else "UTC"
    window_start = datetime.combine(since, datetime.min.time(), tzinfo=local_tz)
    window_end = datetime.combine(end, datetime.max.time(), tzinfo=local_tz)

    sleep_days: set[date] = set((await db.execute(
        select(cast(func.timezone(tzname, models.SleepStage.time), Date))
        .where(models.SleepStage.time >= window_start)
        .where(models.SleepStage.time <= window_end)
        .distinct()
    )).scalars().all())
    hrv_days: set[date] = set((await db.execute(
        select(cast(func.timezone(tzname, models.Hrv.time), Date))
        .where(models.Hrv.time >= window_start)
        .where(models.Hrv.time <= window_end)
        .distinct()
    )).scalars().all())

    cur = since
    needs_recompute: list[date] = []
    while cur <= end:
        row = by_date.get(cur)
        if (row is None or row.sleep_duration_s is None) and cur in sleep_days:
            needs_recompute.append(cur)
        elif (row is None or row.hrv_avg is None) and cur in hrv_days:
            needs_recompute.append(cur)
        cur = cur + _td(days=1)

    if needs_recompute:
        async with _lazy_compute_lock:
            try:
                from ..analytics.jobs import compute_daily_summary
                for d in needs_recompute:
                    try:
                        await compute_daily_summary(d)
                    except Exception as e:  # noqa: BLE001
                        log.warning("recompute %s failed: %s", d, e)
                log.info("/summary/range recomputed %d stale days",
                         len(needs_recompute))
            except Exception as e:  # noqa: BLE001
                log.warning("on-demand summary_range recompute failed: %s", e)

    result = await db.execute(
        select(models.DailySummary)
        .where(models.DailySummary.date >= since)
        .where(models.DailySummary.date <= end)
        .order_by(models.DailySummary.date)
    )
    rows = result.scalars().all()
    return [
        TodaySummary(
            date=r.date,
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
