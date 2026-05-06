"""Sober-time tracking — current streak, history, reset, import."""
import csv
import io
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_any
from ..db import models
from ..db.session import get_session

# Both the dashboard and the phone need to hit /sober/* — the phone only
# stores the ingest token, the dashboard sends the query token. require_any
# accepts either.
router = APIRouter(prefix="/sober", dependencies=[Depends(require_any)])


class SoberStreakOut(BaseModel):
    id: int
    addiction: str
    start_at: datetime
    end_at: datetime | None
    notes: str | None
    days: float


def _streak_days(s: models.SoberStreak, now: datetime) -> float:
    end = s.end_at or now
    return (end - s.start_at).total_seconds() / 86400.0


def _to_out(s: models.SoberStreak, now: datetime) -> SoberStreakOut:
    return SoberStreakOut(
        id=s.id, addiction=s.addiction, start_at=s.start_at,
        end_at=s.end_at, notes=s.notes, days=round(_streak_days(s, now), 2),
    )


@router.get("/current")
async def get_current(
    addiction: str = "alcohol",
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """The currently-active streak. If none exists yet, returns null."""
    now = datetime.now(timezone.utc)
    stmt = (
        select(models.SoberStreak)
        .where(models.SoberStreak.addiction == addiction)
        .where(models.SoberStreak.end_at.is_(None))
        .limit(1)
    )
    s = (await db.execute(stmt)).scalar_one_or_none()
    if s is None:
        return {"active": None, "addiction": addiction}
    seconds = (now - s.start_at).total_seconds()
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    return {
        "active": _to_out(s, now).model_dump(),
        "addiction": addiction,
        "now": now,
        "elapsed_seconds": int(seconds),
        "days": days,
        "hours": hours,
        "minutes": minutes,
    }


@router.get("/history", response_model=list[SoberStreakOut])
async def list_history(
    addiction: str = "alcohol",
    limit: int = 500,
    db: AsyncSession = Depends(get_session),
) -> list[SoberStreakOut]:
    """All streaks, newest first. Includes the current (open) one if any."""
    now = datetime.now(timezone.utc)
    stmt = (
        select(models.SoberStreak)
        .where(models.SoberStreak.addiction == addiction)
        .order_by(models.SoberStreak.start_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [_to_out(r, now) for r in rows]


@router.get("/stats")
async def stats(
    addiction: str = "alcohol",
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Summary: total resets, longest streak, average streak, current streak days."""
    now = datetime.now(timezone.utc)
    rows = (await db.execute(
        select(models.SoberStreak)
        .where(models.SoberStreak.addiction == addiction)
        .order_by(models.SoberStreak.start_at)
    )).scalars().all()
    if not rows:
        return {
            "addiction": addiction, "total_resets": 0,
            "longest_days": 0, "avg_days": 0, "current_days": 0,
            "first_started_at": None, "total_tracked_days": 0,
        }
    closed = [r for r in rows if r.end_at is not None]
    durations = [_streak_days(r, now) for r in closed]
    longest = max((_streak_days(r, now) for r in rows), default=0)
    current = next((r for r in rows if r.end_at is None), None)
    return {
        "addiction": addiction,
        "total_resets": len(closed),
        "longest_days": round(longest, 2),
        "avg_days": round(sum(durations) / len(durations), 2) if durations else 0,
        "current_days": round(_streak_days(current, now), 2) if current else 0,
        "current_started_at": current.start_at if current else None,
        "first_started_at": rows[0].start_at,
        "total_tracked_days": round(sum(_streak_days(r, now) for r in rows), 2),
    }


class ResetBody(BaseModel):
    addiction: str = "alcohol"
    notes: str | None = None
    at: datetime | None = None  # default: now


@router.post("/reset")
async def reset(
    body: ResetBody, db: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Close the current streak and open a new one. Idempotent on double-tap
    within ~5s (re-uses the just-opened streak instead of creating yet another)."""
    at = body.at or datetime.now(timezone.utc)
    cur = (await db.execute(
        select(models.SoberStreak)
        .where(models.SoberStreak.addiction == body.addiction)
        .where(models.SoberStreak.end_at.is_(None))
        .limit(1)
    )).scalar_one_or_none()

    if cur is not None:
        # Guard against accidental double-tap creating a 0-second streak
        if (at - cur.start_at).total_seconds() < 5:
            return {"ok": True, "current_id": cur.id, "noop": True}
        cur.end_at = at
        cur.notes = body.notes if body.notes is not None else cur.notes

    new_streak = models.SoberStreak(
        addiction=body.addiction, start_at=at, end_at=None,
    )
    db.add(new_streak)
    await db.commit()
    await db.refresh(new_streak)
    return {"ok": True, "current_id": new_streak.id, "started_at": new_streak.start_at}


class StreakUpdate(BaseModel):
    start_at: datetime | None = None
    end_at: datetime | None = None
    notes: str | None = None


@router.patch("/streak/{streak_id}", response_model=SoberStreakOut)
async def update_streak(
    streak_id: int,
    body: StreakUpdate,
    db: AsyncSession = Depends(get_session),
) -> SoberStreakOut:
    s = await db.get(models.SoberStreak, streak_id)
    if s is None:
        raise HTTPException(status_code=404, detail="streak not found")
    data = body.model_dump(exclude_unset=True)
    if "start_at" in data and data["start_at"] is not None:
        s.start_at = data["start_at"]
    if "end_at" in data:
        s.end_at = data["end_at"]
    if "notes" in data:
        s.notes = data["notes"]
    await db.commit()
    await db.refresh(s)
    return _to_out(s, datetime.now(timezone.utc))


@router.delete("/streak/{streak_id}", status_code=204)
async def delete_streak(
    streak_id: int, db: AsyncSession = Depends(get_session)
) -> None:
    s = await db.get(models.SoberStreak, streak_id)
    if s is None:
        raise HTTPException(status_code=404, detail="streak not found")
    await db.delete(s)
    await db.commit()


@router.post("/import")
async def import_csv(
    file: UploadFile,
    addiction: str = "alcohol",
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Import a CSV in the Sober Time / 'I Am Sober' export format.

    Expected columns (case-insensitive): addiction, reset, start, end, days, notes.
    The latest row whose end_at is the most recent becomes the close of the
    *previous* streak; a new active streak starts immediately after that — i.e.
    we treat the CSV's "end" as the slip timestamp and open a new streak from
    that point. If the CSV's last row has no end (active streak in source),
    we skip the auto-open.
    """
    raw = (await file.read()).decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    keys = [k.lower().strip() for k in (reader.fieldnames or [])]
    required = {"start", "end"}
    if not required.issubset(set(keys)):
        raise HTTPException(
            status_code=400,
            detail=f"CSV missing required columns ({required}); got {keys}",
        )

    # Wipe existing rows for this addiction so re-imports are idempotent.
    await db.execute(
        models.SoberStreak.__table__.delete().where(
            models.SoberStreak.addiction == addiction
        )
    )

    rows: list[models.SoberStreak] = []
    last_end: datetime | None = None
    for row in reader:
        # Re-key lower-case so the rest of this loop doesn't care about case
        r = {k.lower().strip(): (v or "").strip() for k, v in row.items()}
        try:
            start = datetime.fromisoformat(r["start"]).replace(tzinfo=timezone.utc) \
                if "T" not in r["start"] and "+" not in r["start"] \
                else datetime.fromisoformat(r["start"])
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            end_str = r.get("end") or ""
            end = None
            if end_str:
                end = datetime.fromisoformat(end_str)
                if end.tzinfo is None:
                    end = end.replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"bad date in row {r}: {exc}"
            ) from exc
        rows.append(models.SoberStreak(
            addiction=addiction, start_at=start, end_at=end, notes=r.get("notes") or None,
        ))
        if end and (last_end is None or end > last_end):
            last_end = end

    db.add_all(rows)

    # If every row in the CSV is closed, open a new active streak from the
    # most recent end. (The "I Am Sober" / Sober Time apps store closed
    # historical resets only; the current run is implied to start at the
    # last 'end'.)
    started_active = False
    if rows and all(r.end_at is not None for r in rows) and last_end is not None:
        active = models.SoberStreak(addiction=addiction, start_at=last_end, end_at=None)
        db.add(active)
        started_active = True

    await db.commit()
    return {
        "imported": len(rows),
        "started_active_from": last_end if started_active else None,
        "addiction": addiction,
    }
