from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_any
from ..db import models
from ..db.session import get_session
from ..schemas import (
    HeartRateSeries,
    HrvSeries,
    SleepNight,
    SleepStageBucket,
    StepsSeries,
    TimePoint,
)

router = APIRouter(dependencies=[Depends(require_any)])


def _trim_lounging(
    session: list[tuple[datetime, str, int]],
) -> list[tuple[datetime, str, int]]:
    """Trim trailing in-bed-but-not-asleep fragments from a sleep session.

    The watch keeps logging "light" / "awake" stages while the user is
    lying in bed half-awake after their actual sleep ended, which inflates
    the session length by an hour or more. The most reliable wake-up
    marker is the last "deep" or "rem" stage — after that, nothing is
    real sleep. Allow up to 20 min of trailing light past that point
    (natural light-sleep stage that often closes a real sleep cycle),
    then truncate the rest.
    """
    if not session:
        return session
    last_real_idx = -1
    for i, (_, stage, _) in enumerate(session):
        if stage in ("deep", "rem"):
            last_real_idx = i
    if last_real_idx < 0:
        return session  # whole session is light/awake — keep as-is
    keep_until = last_real_idx
    last_real_end = session[last_real_idx][0] + timedelta(seconds=session[last_real_idx][2])
    for j in range(last_real_idx + 1, len(session)):
        ts, stage, _ = session[j]
        if stage == "light" and (ts - last_real_end) <= timedelta(minutes=20):
            keep_until = j
        else:
            break
    return session[: keep_until + 1]


def _resolve_range(
    since: datetime | None, until: datetime | None, default_window: timedelta
) -> tuple[datetime, datetime]:
    # Callers (esp. the phone) sometimes pass a date-only string like
    # "2026-03-01"; FastAPI parses that as a tz-naive datetime, which
    # fails the comparison below against `datetime.now(timezone.utc)`.
    # Force any naive input into UTC.
    def _aware(dt: datetime | None) -> datetime | None:
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    since = _aware(since)
    until = _aware(until)
    end = until or datetime.now(timezone.utc)
    start = since or (end - default_window)
    if start >= end:
        raise HTTPException(status_code=400, detail="`since` must be before `until`")
    return start, end


@router.get("/heartrate", response_model=HeartRateSeries)
async def get_heartrate(
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> HeartRateSeries:
    start, end = _resolve_range(since, until, timedelta(hours=24))
    result = await db.execute(
        select(models.HeartRate.time, models.HeartRate.bpm)
        .where(models.HeartRate.time >= start)
        .where(models.HeartRate.time <= end)
        .order_by(models.HeartRate.time)
    )
    rows = result.all()
    points = [TimePoint(time=t, value=v) for t, v in rows]

    if not points:
        return HeartRateSeries(points=[])

    values = [p.value for p in points]
    return HeartRateSeries(
        points=points,
        avg=sum(values) / len(values),
        min_bpm=min(values),
        max_bpm=max(values),
    )


@router.get("/hrv", response_model=HrvSeries)
async def get_hrv(
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> HrvSeries:
    start, end = _resolve_range(since, until, timedelta(days=7))
    result = await db.execute(
        select(models.Hrv.time, models.Hrv.rmssd_ms)
        .where(models.Hrv.time >= start)
        .where(models.Hrv.time <= end)
        .order_by(models.Hrv.time)
    )
    rows = result.all()
    points = [TimePoint(time=t, value=v) for t, v in rows]
    avg = sum(p.value for p in points) / len(points) if points else None
    return HrvSeries(points=points, avg=avg)


@router.get("/steps", response_model=StepsSeries)
async def get_steps(
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> StepsSeries:
    """Per-minute step counts for the window. The total uses per-minute
    MAX dedup across HC sources (watch + phone pedometer + Fitbit) so
    the value matches /summary/today and the Vitals badge."""
    start, end = _resolve_range(since, until, timedelta(hours=24))
    # Per-minute aggregation: sum across all rows in the same minute,
    # then take that as the canonical bucket count. Dedupe across
    # sources by keeping the MAX of any rows within the same minute.
    minute_col = func.date_trunc("minute", models.Steps.time)
    result = await db.execute(
        select(minute_col.label("m"),
               func.max(models.Steps.count).label("c"))
        .where(models.Steps.time >= start)
        .where(models.Steps.time <= end)
        .group_by(minute_col)
        .order_by(minute_col)
    )
    rows = result.all()
    points = [TimePoint(time=t, value=float(c)) for t, c in rows]
    total = sum(int(p.value) for p in points)
    return StepsSeries(points=points, total=total)


@router.get("/sleep/last", response_model=SleepNight | None)
async def get_last_sleep(
    db: AsyncSession = Depends(get_session),
) -> SleepNight | None:
    """Most recent sleep — prefer canonical SleepSession boundaries when
    available (HC reports them per-session), fall back to walking stage
    rows + clustering by 2h gaps when no session row exists."""
    # 1. Try canonical session boundary first.
    sess = (await db.execute(
        select(models.SleepSession)
        .order_by(models.SleepSession.start_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if sess is not None:
        # Pixel Watch sometimes ends a SleepSession at the first long
        # awake period (e.g. middle-of-night bathroom break) but keeps
        # ingesting stage data for the rest of the night. Extend the
        # window forward through any contiguous stages whose gap from
        # the running end is within 90 min, capped at 4h past the
        # original session end. This matches what the watch face shows.
        forward = await db.execute(
            select(models.SleepStage.time, models.SleepStage.stage, models.SleepStage.duration_s)
            .where(models.SleepStage.time > sess.end_at)
            .where(models.SleepStage.time <= sess.end_at + timedelta(hours=4))
            .order_by(models.SleepStage.time)
        )
        eff_end = sess.end_at
        for ts, stage, dur in forward.all():
            if ts - eff_end > timedelta(minutes=90):
                break
            eff_end = max(eff_end, ts + timedelta(seconds=dur))
        # Pull stages that fall within the (possibly extended) window.
        result = await db.execute(
            select(models.SleepStage.time, models.SleepStage.stage, models.SleepStage.duration_s)
            .where(models.SleepStage.time >= sess.start_at)
            .where(models.SleepStage.time <= eff_end)
            .order_by(models.SleepStage.time)
        )
        session = result.all()
        # Aggregate per-stage with overlap clamping.
        by_stage: dict[str, int] = {}
        for i, (ts, stage, dur) in enumerate(session):
            if i + 1 < len(session):
                clamped = min(dur, max(0, int((session[i + 1][0] - ts).total_seconds())))
            else:
                clamped = min(dur, max(0, int((eff_end - ts).total_seconds())))
            by_stage[stage] = by_stage.get(stage, 0) + clamped
        return SleepNight(
            date=sess.start_at.date(),
            start=sess.start_at,
            end=eff_end,
            total_s=int((eff_end - sess.start_at).total_seconds()),
            stages=[SleepStageBucket(stage=k, duration_s=v) for k, v in by_stage.items()],
        )

    # 2. Fallback: stage-walk. Same as before.
    cutoff = datetime.now(timezone.utc) - timedelta(hours=36)
    result = await db.execute(
        select(models.SleepStage.time, models.SleepStage.stage, models.SleepStage.duration_s)
        .where(models.SleepStage.time >= cutoff)
        .order_by(models.SleepStage.time)
    )
    rows = result.all()
    if not rows:
        return None

    # Walk newest-first, accumulate while consecutive stages are within 2h.
    rows_sorted = sorted(rows, key=lambda r: r[0], reverse=True)
    session: list[tuple[datetime, str, int]] = [rows_sorted[0]]
    for prev, cur in zip(rows_sorted[:-1], rows_sorted[1:], strict=False):
        gap = prev[0] - cur[0]
        if gap > timedelta(hours=2):
            break
        session.append(cur)

    session.sort(key=lambda r: r[0])
    session = _trim_lounging(session)
    start_t = session[0][0]
    end_t = session[-1][0] + timedelta(seconds=session[-1][2])

    # Aggregate by stage with overlap-clamping. The DB can have stages from
    # multiple sources (Pixel Watch + Garmin import + Fitbit import) that
    # decompose the same night slightly differently — same stage type at
    # near-identical times. Naively summing inflates total sleep by hours.
    # Clamp each stage's duration to the gap before the next stage starts.
    by_stage: dict[str, int] = {}
    for i, (ts, stage, dur) in enumerate(session):
        if i + 1 < len(session):
            next_ts = session[i + 1][0]
            clamped = min(dur, max(0, int((next_ts - ts).total_seconds())))
        else:
            clamped = dur
        by_stage[stage] = by_stage.get(stage, 0) + clamped

    # Wall-clock total beats summed-stages for accuracy when stages overlap.
    total_s = max(int((end_t - start_t).total_seconds()), sum(by_stage.values()))

    return SleepNight(
        date=start_t.date(),
        start=start_t,
        end=end_t,
        total_s=total_s,
        stages=[SleepStageBucket(stage=k, duration_s=v) for k, v in by_stage.items()],
    )


@router.get("/sleep/raw")
async def get_sleep_raw(
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Raw per-stage rows (un-grouped) — used to draw hypnograms."""
    start, end = _resolve_range(since, until, timedelta(hours=36))
    result = await db.execute(
        select(models.SleepStage.time, models.SleepStage.stage, models.SleepStage.duration_s)
        .where(models.SleepStage.time >= start)
        .where(models.SleepStage.time <= end)
        .order_by(models.SleepStage.time)
    )
    return [
        {"time": t.isoformat(), "stage": s, "duration_s": d}
        for t, s, d in result.all()
    ]


@router.get("/sleep/range", response_model=list[SleepNight])
async def get_sleep_range(
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> list[SleepNight]:
    """All sleep sessions in the time range, oldest first. Uses canonical
    SleepSession rows when available; falls back to clustering stages."""
    start, end = _resolve_range(since, until, timedelta(days=30))

    # 1. Canonical sessions in range — preferred.
    sess_rows = (await db.execute(
        select(models.SleepSession)
        .where(models.SleepSession.start_at >= start)
        .where(models.SleepSession.start_at <= end)
        .order_by(models.SleepSession.start_at)
    )).scalars().all()
    if sess_rows:
        # Pre-fetch stages once for efficiency.
        all_stages = (await db.execute(
            select(models.SleepStage.time, models.SleepStage.stage, models.SleepStage.duration_s)
            .where(models.SleepStage.time >= start)
            .where(models.SleepStage.time <= end)
            .order_by(models.SleepStage.time)
        )).all()
        out: list[SleepNight] = []
        for s in sess_rows:
            in_window = [(t, st, d) for t, st, d in all_stages if s.start_at <= t <= s.end_at]
            by_stage: dict[str, int] = {}
            for i, (ts, stage, dur) in enumerate(in_window):
                if i + 1 < len(in_window):
                    clamped = min(dur, max(0, int((in_window[i + 1][0] - ts).total_seconds())))
                else:
                    clamped = min(dur, max(0, int((s.end_at - ts).total_seconds())))
                by_stage[stage] = by_stage.get(stage, 0) + clamped
            out.append(SleepNight(
                date=s.start_at.date(),
                start=s.start_at,
                end=s.end_at,
                total_s=int((s.end_at - s.start_at).total_seconds()),
                stages=[SleepStageBucket(stage=k, duration_s=v) for k, v in by_stage.items()],
            ))
        return out

    # 2. Fallback: cluster stages by 2h gaps.
    result = await db.execute(
        select(models.SleepStage.time, models.SleepStage.stage, models.SleepStage.duration_s)
        .where(models.SleepStage.time >= start)
        .where(models.SleepStage.time <= end)
        .order_by(models.SleepStage.time)
    )
    rows = result.all()
    if not rows:
        return []

    # Group rows into sessions: a 2-hour gap between consecutive stage starts breaks the night.
    sessions: list[list[tuple[datetime, str, int]]] = []
    current: list[tuple[datetime, str, int]] = []
    for ts, stage, dur in rows:
        if current and (ts - current[-1][0]) > timedelta(hours=2):
            sessions.append(current)
            current = []
        current.append((ts, stage, dur))
    if current:
        sessions.append(current)

    out: list[SleepNight] = []
    for session in sessions:
        session = _trim_lounging(session)
        start_t = session[0][0]
        end_t = session[-1][0] + timedelta(seconds=session[-1][2])
        by_stage: dict[str, int] = {}
        for i, (ts, stage, dur) in enumerate(session):
            if i + 1 < len(session):
                next_ts = session[i + 1][0]
                clamped = min(dur, max(0, int((next_ts - ts).total_seconds())))
            else:
                clamped = dur
            by_stage[stage] = by_stage.get(stage, 0) + clamped
        total_s = max(int((end_t - start_t).total_seconds()), sum(by_stage.values()))
        out.append(SleepNight(
            date=start_t.date(),
            start=start_t,
            end=end_t,
            total_s=total_s,
            stages=[SleepStageBucket(stage=k, duration_s=v) for k, v in by_stage.items()],
        ))
    return out


@router.get("/weight")
async def get_weight(
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Body-metric series: weight, body fat, BMI, lean mass."""
    start, end = _resolve_range(since, until, timedelta(days=90))
    result = await db.execute(
        select(
            models.BodyMetric.time, models.BodyMetric.weight_kg,
            models.BodyMetric.body_fat_pct, models.BodyMetric.bmi,
            models.BodyMetric.lean_mass_kg, models.BodyMetric.source,
        )
        .where(models.BodyMetric.time >= start)
        .where(models.BodyMetric.time <= end)
        .order_by(models.BodyMetric.time)
    )
    rows = result.all()
    points = [
        {"time": t.isoformat(), "weight_kg": w, "body_fat_pct": bf,
         "bmi": b, "lean_mass_kg": lm, "source": src}
        for t, w, bf, b, lm, src in rows
    ]
    weights = [r[1] for r in rows if r[1] is not None]
    return {
        "points": points,
        "latest_kg": weights[-1] if weights else None,
        "min_kg": min(weights) if weights else None,
        "max_kg": max(weights) if weights else None,
        "avg_kg": sum(weights) / len(weights) if weights else None,
    }


@router.get("/blood-pressure")
async def get_blood_pressure(
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Blood-pressure cuff readings (OMRON Connect via HC, or manual entry)."""
    start, end = _resolve_range(since, until, timedelta(days=90))
    result = await db.execute(
        select(
            models.BloodPressure.time, models.BloodPressure.systolic,
            models.BloodPressure.diastolic, models.BloodPressure.pulse_bpm,
            models.BloodPressure.source, models.BloodPressure.notes,
        )
        .where(models.BloodPressure.time >= start)
        .where(models.BloodPressure.time <= end)
        .order_by(models.BloodPressure.time)
    )
    rows = result.all()
    points = [
        {"time": t.isoformat(), "systolic": s, "diastolic": d,
         "pulse_bpm": p, "source": src, "notes": n}
        for t, s, d, p, src, n in rows
    ]
    sys_vals = [r[1] for r in rows]
    dia_vals = [r[2] for r in rows]
    return {
        "points": points,
        "latest": points[-1] if points else None,
        "avg_sys": sum(sys_vals) / len(sys_vals) if sys_vals else None,
        "avg_dia": sum(dia_vals) / len(dia_vals) if dia_vals else None,
    }


# Manual-entry shortcut so the dashboard doesn't have to build a Bearer ingest path.
class BloodPressureIn(BaseModel):
    systolic: int
    diastolic: int
    pulse_bpm: int | None = None
    notes: str | None = None
    time: datetime | None = None


@router.post("/blood-pressure")
async def post_blood_pressure(
    body: BloodPressureIn,
    db: AsyncSession = Depends(get_session),
) -> dict:
    ts = body.time or datetime.now(timezone.utc)
    row = models.BloodPressure(
        time=ts, systolic=body.systolic, diastolic=body.diastolic,
        pulse_bpm=body.pulse_bpm, source="manual", notes=body.notes,
    )
    await db.merge(row)
    await db.commit()
    return {"status": "ok", "time": ts.isoformat()}


@router.get("/skin-temp")
async def get_skin_temp(
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Skin temperature delta (°C from baseline) — overnight wrist sensor reading."""
    start, end = _resolve_range(since, until, timedelta(days=30))
    result = await db.execute(
        select(models.SkinTemp.time, models.SkinTemp.celsius_delta)
        .where(models.SkinTemp.time >= start)
        .where(models.SkinTemp.time <= end)
        .order_by(models.SkinTemp.time)
    )
    rows = result.all()
    return {
        "points": [{"time": t.isoformat(), "value": v} for t, v in rows],
    }


@router.get("/last-sync")
async def get_last_sync(db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Most recent vitals timestamp + companion-app sync health.

    last_sync       — newest record across HR / HRV / SpO2 / Steps
    last_attempt    — when the phone last *tried* to sync (heartbeat)
    last_success    — when the phone last *succeeded* in syncing
    permissions_lost — true if the most recent attempt saw HC denials
    perms_missing   — names of the HC perms still revoked, if any
    error_summary   — first ~few error lines from the most recent attempt
    """
    tables = [models.HeartRate, models.Hrv, models.Spo2, models.Steps]
    latest: datetime | None = None
    for t in tables:
        result = await db.execute(select(func.max(t.time)))
        ts = result.scalar()
        if ts and (latest is None or ts > latest):
            latest = ts

    hb = (await db.execute(
        select(models.SyncHeartbeat)
        .order_by(models.SyncHeartbeat.attempt_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    return {
        "last_sync": latest,
        "last_attempt": hb.attempt_at if hb else None,
        "last_success": hb.last_success_at if hb else None,
        "permissions_lost": bool(hb.permissions_lost) if hb else False,
        "perms_granted": hb.perms_granted if hb else None,
        "perms_required": hb.perms_required if hb else None,
        "perms_missing": hb.perms_missing if hb else None,
        "error_summary": hb.error_summary if hb else None,
        "app_version": hb.app_version if hb else None,
    }
