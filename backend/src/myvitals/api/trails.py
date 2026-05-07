"""Trail status endpoints — list, history, subscribe, refresh, alerts.

Pulls from the trails / trail_status_snapshots / trail_subscriptions /
trail_alerts tables populated by integrations/rainoutline.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_any
from ..db import models
from ..db.session import get_session

router = APIRouter(prefix="/trails", dependencies=[Depends(require_any)])


# ------------------------------------------------------------------
# List + detail
# ------------------------------------------------------------------

@router.get("")
async def list_trails(db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Every trail with its most recent snapshot + subscription state."""
    trails = (await db.execute(
        select(models.Trail).order_by(models.Trail.name)
    )).scalars().all()
    if not trails:
        return {"count": 0, "trails": []}

    # Most recent snapshot per trail in a single round-trip via DISTINCT ON.
    # SQLAlchemy 2.x: use a subquery + window function or rely on PG's
    # DISTINCT ON (PostgreSQL-specific). Stick to a simple per-trail query
    # for clarity; trail count is ~30, perf is fine.
    out: list[dict[str, Any]] = []
    sub_ids = set((await db.execute(
        select(models.TrailSubscription.trail_id)
    )).scalars().all())
    sub_notify = {
        tid: notify for tid, notify in (await db.execute(
            select(models.TrailSubscription.trail_id, models.TrailSubscription.notify_on)
        )).all()
    }

    for t in trails:
        latest = (await db.execute(
            select(models.TrailStatusSnapshot)
            .where(models.TrailStatusSnapshot.trail_id == t.id)
            .order_by(models.TrailStatusSnapshot.fetched_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        out.append({
            "id": t.id,
            "extension": t.extension,
            "name": t.name,
            "slug": t.slug,
            "last_seen_at": t.last_seen_at,
            "subscribed": t.id in sub_ids,
            "notify_on": sub_notify.get(t.id),
            "status": latest.status if latest else None,
            "comment": latest.comment if latest else None,
            "source_ts": latest.source_ts if latest else None,
            "fetched_at": latest.fetched_at if latest else None,
        })
    return {"count": len(out), "trails": out}


@router.get("/{trail_id}/history")
async def trail_history(
    trail_id: int, days: int = 30,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """All snapshots for a trail in the last `days` days, oldest first."""
    t = await db.get(models.Trail, trail_id)
    if t is None:
        raise HTTPException(status_code=404, detail="trail not found")
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await db.execute(
        select(models.TrailStatusSnapshot)
        .where(models.TrailStatusSnapshot.trail_id == trail_id)
        .where(models.TrailStatusSnapshot.fetched_at >= since)
        .order_by(models.TrailStatusSnapshot.fetched_at)
    )).scalars().all()
    return {
        "trail_id": trail_id, "name": t.name,
        "snapshots": [
            {
                "fetched_at": s.fetched_at, "status": s.status,
                "comment": s.comment, "source_ts": s.source_ts,
            }
            for s in rows
        ],
    }


# ------------------------------------------------------------------
# Subscriptions
# ------------------------------------------------------------------

class SubscribeBody(BaseModel):
    notify_on: str = "any"   # any | open_only | close_only


@router.post("/{trail_id}/subscribe")
async def subscribe(
    trail_id: int, body: SubscribeBody,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if body.notify_on not in {"any", "open_only", "close_only"}:
        raise HTTPException(status_code=400, detail="notify_on must be any|open_only|close_only")
    t = await db.get(models.Trail, trail_id)
    if t is None:
        raise HTTPException(status_code=404, detail="trail not found")
    sub = await db.get(models.TrailSubscription, trail_id)
    if sub is None:
        sub = models.TrailSubscription(
            trail_id=trail_id,
            subscribed_at=datetime.now(timezone.utc),
            notify_on=body.notify_on,
        )
        db.add(sub)
    else:
        sub.notify_on = body.notify_on
    await db.commit()
    return {"trail_id": trail_id, "subscribed": True, "notify_on": sub.notify_on}


@router.delete("/{trail_id}/subscribe", status_code=204)
async def unsubscribe(
    trail_id: int, db: AsyncSession = Depends(get_session),
) -> None:
    sub = await db.get(models.TrailSubscription, trail_id)
    if sub is not None:
        await db.delete(sub)
        await db.commit()


# ------------------------------------------------------------------
# Refresh + alerts
# ------------------------------------------------------------------

@router.post("/refresh")
async def refresh_now(db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Pull-to-refresh: triggers an out-of-band poll. Same code as the
    scheduler runs on its 15-min cadence."""
    from ..integrations.rainoutline import poll_and_persist
    return await poll_and_persist()


@router.get("/alerts")
async def list_alerts(
    unacked_only: bool = False, limit: int = 50,
    db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Recent trail-status flips for subscribed trails."""
    stmt = select(models.TrailAlert).order_by(models.TrailAlert.created_at.desc()).limit(limit)
    if unacked_only:
        stmt = stmt.where(models.TrailAlert.acked_at.is_(None))
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return []
    # Hydrate trail name in one query
    trail_ids = list({r.trail_id for r in rows})
    trails_by_id = {
        t.id: t for t in (await db.execute(
            select(models.Trail).where(models.Trail.id.in_(trail_ids))
        )).scalars().all()
    }
    return [
        {
            "id": r.id,
            "trail_id": r.trail_id,
            "trail_name": trails_by_id[r.trail_id].name if r.trail_id in trails_by_id else None,
            "from_status": r.from_status,
            "to_status": r.to_status,
            "source_ts": r.source_ts,
            "created_at": r.created_at,
            "phone_notified_at": r.phone_notified_at,
            "acked_at": r.acked_at,
        }
        for r in rows
    ]


@router.post("/alerts/{alert_id}/ack")
async def ack_alert(
    alert_id: int, db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    a = await db.get(models.TrailAlert, alert_id)
    if a is None:
        raise HTTPException(status_code=404, detail="alert not found")
    a.acked_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "acked"}


@router.post("/alerts/mark-notified")
async def mark_notified(
    body: dict[str, list[int]],
    db: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    """Phone calls this after posting system notifications so we don't
    re-notify the same alert. Body: {ids: [1, 2, 3]}."""
    ids = body.get("ids") or []
    now = datetime.now(timezone.utc)
    n = 0
    for aid in ids:
        a = await db.get(models.TrailAlert, aid)
        if a is not None and a.phone_notified_at is None:
            a.phone_notified_at = now
            n += 1
    await db.commit()
    return {"marked": n}
