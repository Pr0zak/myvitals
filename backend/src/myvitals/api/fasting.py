"""Intermittent-fasting API — single user, single active fast at a time.

Endpoints
---------
POST /fasting/start    Start a new fast (409 if one already active)
POST /fasting/end      End the active fast (or a specific session by id)
GET  /fasting/current  The active fast, enriched with elapsed + stage
GET  /fasting/history  Paginated list of past fasts
GET  /fasting/stats    Aggregates — completion rate, avg duration, streak
POST /fasting/logs     Record an in-fast hunger / mood / hydration log
GET  /fasting/logs     Logs for a session, ordered by time

Stage thresholds are derived server-side so phone + web render the
same labels — see FASTING_STAGES.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_any
from ..db import models
from ..db.session import get_session

router = APIRouter(prefix="/fasting", dependencies=[Depends(require_any)])


# Stage thresholds — hours into the fast → human-facing label.
# Sources: Schoenfeld 2017 review; Longo 2020 fasting review.
FASTING_STAGES: list[tuple[float, str]] = [
    (0.0, "fed"),
    (4.0, "gut_rest"),
    (12.0, "glycogen_depleting"),
    (16.0, "ketosis"),
    (18.0, "autophagy"),
    (24.0, "deep_autophagy"),
    (36.0, "extended_36"),
    (48.0, "extended_48"),
    (72.0, "extended_72"),
]


def _stage_for(hours: float) -> tuple[str, float | None]:
    """Returns (current_stage_label, next_stage_at_hours_or_None)."""
    cur = FASTING_STAGES[0][1]
    nxt: float | None = None
    for h, label in FASTING_STAGES:
        if hours >= h:
            cur = label
        elif nxt is None:
            nxt = h
            break
    return cur, nxt


# ── Schemas ──

class StartBody(BaseModel):
    protocol: str = "16:8"
    target_hours: float | None = None
    target_eating_window_h: float | None = None
    notes: str | None = None
    started_at: datetime | None = None    # override "now" for backdated starts


class EndBody(BaseModel):
    session_id: int | None = None
    ended_at: datetime | None = None
    notes: str | None = None


class FastingSessionOut(BaseModel):
    id: int
    started_at: str
    ended_at: str | None
    protocol: str
    mode: str
    target_hours: float | None
    target_eating_window_h: float | None
    notes: str | None
    # derived
    elapsed_h: float
    current_stage: str
    next_stage_at_h: float | None
    is_active: bool


class LogBody(BaseModel):
    session_id: int
    time: datetime | None = None
    hunger: int | None = None
    mood: int | None = None
    hydration_ml: int | None = None
    notes: str | None = None


class LogOut(BaseModel):
    id: int
    session_id: int
    time: str
    hunger: int | None
    mood: int | None
    hydration_ml: int | None
    notes: str | None


class StatsOut(BaseModel):
    sessions_count: int
    completed_count: int
    avg_duration_h: float | None
    median_duration_h: float | None
    longest_h: float | None
    current_streak_days: int
    last_completed_at: str | None


# ── Helpers ──

def _enrich(row: models.FastingSession) -> dict[str, Any]:
    end = row.ended_at or datetime.now(timezone.utc)
    elapsed_s = max(0.0, (end - row.started_at).total_seconds())
    elapsed_h = elapsed_s / 3600.0
    stage, next_at = _stage_for(elapsed_h)
    return {
        "id": row.id,
        "started_at": row.started_at.isoformat(),
        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
        "protocol": row.protocol,
        "mode": row.mode,
        "target_hours": row.target_hours,
        "target_eating_window_h": row.target_eating_window_h,
        "notes": row.notes,
        "elapsed_h": round(elapsed_h, 3),
        "current_stage": stage,
        "next_stage_at_h": next_at,
        "is_active": row.ended_at is None,
    }


async def _active(db: AsyncSession) -> models.FastingSession | None:
    return (await db.execute(
        select(models.FastingSession)
        .where(models.FastingSession.ended_at.is_(None))
        .limit(1)
    )).scalar_one_or_none()


# ── Endpoints ──

@router.post("/start", response_model=FastingSessionOut)
async def start_fast(
    body: StartBody, db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if await _active(db) is not None:
        raise HTTPException(
            status_code=409,
            detail="a fast is already active; end it before starting another",
        )
    row = models.FastingSession(
        started_at=body.started_at or datetime.now(timezone.utc),
        protocol=body.protocol,
        mode="active",
        target_hours=body.target_hours,
        target_eating_window_h=body.target_eating_window_h,
        notes=body.notes,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        # Defensive — the partial unique index catches a race we already
        # check above; the explicit 409 above is the first line.
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="a fast is already active (concurrent start lost the race)",
        ) from None
    await db.refresh(row)
    return _enrich(row)


@router.post("/end", response_model=FastingSessionOut)
async def end_fast(
    body: EndBody, db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if body.session_id is not None:
        # Composite PK (id, started_at) — get_by-id-only would need a query.
        row = (await db.execute(
            select(models.FastingSession)
            .where(models.FastingSession.id == body.session_id)
            .limit(1)
        )).scalar_one_or_none()
    else:
        row = await _active(db)
    if row is None:
        raise HTTPException(status_code=404, detail="no matching fast")
    if row.ended_at is not None:
        # Idempotent — return the already-ended row instead of 409.
        return _enrich(row)
    row.ended_at = body.ended_at or datetime.now(timezone.utc)
    if body.notes:
        row.notes = (row.notes + "\n" + body.notes) if row.notes else body.notes
    await db.commit()
    await db.refresh(row)
    return _enrich(row)


@router.get("/current", response_model=FastingSessionOut | None)
async def current_fast(
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any] | None:
    row = await _active(db)
    if row is None:
        return None
    return _enrich(row)


@router.get("/history", response_model=list[FastingSessionOut])
async def history(
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    rows = (await db.execute(
        select(models.FastingSession)
        .order_by(desc(models.FastingSession.started_at))
        .limit(limit)
    )).scalars().all()
    return [_enrich(r) for r in rows]


@router.get("/stats", response_model=StatsOut)
async def stats(
    days: int = Query(90, ge=7, le=730),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await db.execute(
        select(models.FastingSession)
        .where(models.FastingSession.started_at >= since)
        .order_by(desc(models.FastingSession.started_at))
    )).scalars().all()

    completed = [r for r in rows if r.ended_at is not None]
    durations_h = [
        (r.ended_at - r.started_at).total_seconds() / 3600.0
        for r in completed
    ]
    durations_h.sort()

    avg = sum(durations_h) / len(durations_h) if durations_h else None
    median = durations_h[len(durations_h) // 2] if durations_h else None
    longest = max(durations_h) if durations_h else None

    # Streak — count back from today over consecutive days that have a
    # completed fast ending that day.
    by_day: dict[str, bool] = {}
    for r in completed:
        d = r.ended_at.date().isoformat()
        by_day[d] = True
    streak = 0
    today = datetime.now(timezone.utc).date()
    cursor = today
    while by_day.get(cursor.isoformat()):
        streak += 1
        cursor = cursor - timedelta(days=1)

    last_done = max((r.ended_at for r in completed), default=None)

    return {
        "sessions_count": len(rows),
        "completed_count": len(completed),
        "avg_duration_h": round(avg, 2) if avg is not None else None,
        "median_duration_h": round(median, 2) if median is not None else None,
        "longest_h": round(longest, 2) if longest is not None else None,
        "current_streak_days": streak,
        "last_completed_at": last_done.isoformat() if last_done else None,
    }


@router.post("/logs", response_model=LogOut)
async def add_log(
    body: LogBody, db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    # Validate session exists.
    sess = (await db.execute(
        select(models.FastingSession)
        .where(models.FastingSession.id == body.session_id)
        .limit(1)
    )).scalar_one_or_none()
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    row = models.FastingLog(
        session_id=body.session_id,
        time=body.time or datetime.now(timezone.utc),
        hunger=body.hunger,
        mood=body.mood,
        hydration_ml=body.hydration_ml,
        notes=body.notes,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {
        "id": row.id,
        "session_id": row.session_id,
        "time": row.time.isoformat(),
        "hunger": row.hunger,
        "mood": row.mood,
        "hydration_ml": row.hydration_ml,
        "notes": row.notes,
    }


@router.get("/logs", response_model=list[LogOut])
async def list_logs(
    session_id: int = Query(...),
    db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    rows = (await db.execute(
        select(models.FastingLog)
        .where(models.FastingLog.session_id == session_id)
        .order_by(desc(models.FastingLog.time))
    )).scalars().all()
    return [
        {
            "id": r.id,
            "session_id": r.session_id,
            "time": r.time.isoformat(),
            "hunger": r.hunger,
            "mood": r.mood,
            "hydration_ml": r.hydration_ml,
            "notes": r.notes,
        }
        for r in rows
    ]
