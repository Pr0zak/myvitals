import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_any
from ..db import models
from ..db.session import get_session
from ..config import settings
from ..schemas import TodaySummary

router = APIRouter(dependencies=[Depends(require_any)])
log = logging.getLogger(__name__)


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

    # 1. Try the persisted summary first.
    result = await db.execute(
        select(models.DailySummary).where(models.DailySummary.date == today_local)
    )
    saved = result.scalar_one_or_none()

    # 1b. Stale-row repair: if today's row is missing sleep / HRV but the
    # underlying tables have data, recompute on-demand. Replaces the
    # cron-only model where a 03:00 row missed late-morning sleep data.
    if await _today_row_is_stale(db, saved, today_local, midnight_local, day_end):
        try:
            from ..analytics.jobs import compute_daily_summary
            await compute_daily_summary(today_local)
            # Re-read the now-updated row.
            saved = (await db.execute(
                select(models.DailySummary)
                .where(models.DailySummary.date == today_local)
            )).scalar_one_or_none()
            log.info("recomputed stale daily_summary for %s", today_local)
        except Exception as e:  # noqa: BLE001
            log.warning("on-demand daily_summary recompute failed: %s", e)

    # 2. Compute live values as a fallback / supplement.
    # Pick a single canonical step source so the dashboard matches the
    # user's wrist. Pixel Watch 3 syncs via Fitbit, Wear OS via "wearable"
    # apps, Samsung via "samsung.android.wearable" — match all three.
    # Untagged ("unknown") rows are excluded outright; they're usually
    # leftover backfill from before source tagging.
    # If no watch-class source is present, fall back to the source with
    # the highest total (closer to a single-device count than per-minute
    # MAX across mixed sources, which over-counts when sources fire at
    # different cadences).
    sources_q = await db.execute(
        select(
            models.Steps.source,
            func.coalesce(func.sum(models.Steps.count), 0).label("total"),
        )
        .where(models.Steps.time >= midnight_local)
        .where(models.Steps.time <= end)
        .where(models.Steps.source != "unknown")
        .group_by(models.Steps.source)
    )
    source_totals: list[tuple[str, int]] = [
        (s, int(t)) for s, t in sources_q.all() if s
    ]

    def _is_watch(name: str) -> bool:
        n = name.lower()
        return any(
            tag in n
            for tag in ("wearable", "fit.wearable", "fitbit", "watch", "wear")
        )

    canonical = next((s for s, _ in source_totals if _is_watch(s)), None)
    if canonical is None and source_totals:
        canonical = max(source_totals, key=lambda x: x[1])[0]

    if canonical:
        single = await db.execute(
            select(func.coalesce(func.sum(models.Steps.count), 0))
            .where(models.Steps.source == canonical)
            .where(models.Steps.time >= midnight_local)
            .where(models.Steps.time <= end)
        )
        steps_total = int(single.scalar() or 0)
    else:
        steps_total = 0

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

    def pick(field: str):
        v = getattr(saved, field, None) if saved else None
        if v is None and fallback is not None:
            return getattr(fallback, field, None)
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
        )

    # No saved summaries at all — return live counts only.
    return TodaySummary(
        date=today_local,
        steps_total=steps_total,
        last_sync=last_sync,
    )


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
    from datetime import timedelta as _td
    cur = since
    needs_recompute: list[date] = []
    while cur <= end:
        row = by_date.get(cur)
        day_start = datetime.combine(cur, datetime.min.time(), tzinfo=local_tz)
        day_end = datetime.combine(cur, datetime.max.time(), tzinfo=local_tz)
        if await _today_row_is_stale(db, row, cur, day_start, day_end):
            needs_recompute.append(cur)
        cur = cur + _td(days=1)

    if needs_recompute:
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
    today_local = date.today()

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
        safe("hr24", lambda s: _hr_get(since=day_ago, until=None, db=s)),
        safe("hrv24", lambda s: _hrv_get(since=day_ago, until=None, db=s)),
        safe("steps24", lambda s: _steps_get(since=day_ago, until=None, db=s)),
        safe("sleep_last", lambda s: _sleep_last(db=s)),
        safe("weight30", lambda s: _weight_get(since=thirty_ago, until=None, db=s)),
        safe("bp30", lambda s: _bp_get(since=thirty_ago, until=None, db=s)),
        safe("annotations1d", lambda s: _journal_list(
            since=day_ago, type=None, limit=50, db=s,
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
