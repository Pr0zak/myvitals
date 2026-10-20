"""Avinox e-bike integration API routes.

Provides endpoints for:
1. Inbound push webhooks from the Avinox server when a new ride is ingested.
2. Connection status and configuration management.
3. On-demand sync and historical backfill from the Avinox server.
"""
from __future__ import annotations

import logging
import secrets
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_any
from ..config import settings
from ..db import models
from ..db.session import get_session
from ..integrations import avinox as avinox_int

log = logging.getLogger(__name__)

# Webhook router — unauthenticated at framework level, gated by secret
_webhook_router = APIRouter(prefix="/integrations/avinox", tags=["avinox"])

# Management router — authenticated via require_any (ingest or query token)
router = APIRouter(
    prefix="/integrations/avinox",
    dependencies=[Depends(require_any)],
    tags=["avinox"],
)


def _check_push_auth(
    authorization: str | None,
    x_secret: str | None,
    cfg: models.AvinoxConfig,
) -> None:
    token: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    candidate = token or x_secret

    if not candidate:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing authorization token or secret")

    valid_secrets = [s for s in (cfg.webhook_secret, settings.ingest_token) if s]
    if not any(secrets.compare_digest(candidate, s) for s in valid_secrets):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid token or secret")


@_webhook_router.post("/push")
async def avinox_push(
    payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(None),
    x_avinox_secret: str | None = Header(None, alias="X-Avinox-Secret"),
    x_ingest_token: str | None = Header(None, alias="X-Ingest-Token"),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Receive an e-bike ride pushed from the Avinox server."""
    cfg = await avinox_int.get_or_create_config(db)
    secret_header = x_avinox_secret or x_ingest_token
    _check_push_auth(authorization, secret_header, cfg)

    try:
        res = await avinox_int.ingest_ride_payload(db, payload)
        await db.commit()
        return {"ok": True, "result": res}
    except Exception as e:
        await db.rollback()
        log.warning("avinox_push_failed: %s", e)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"failed to ingest ride: {e}") from e


@_webhook_router.post("/webhook/{secret}")
async def avinox_webhook(
    secret: str,
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """URL-path gated webhook receiver for Avinox pushes."""
    cfg = await avinox_int.get_or_create_config(db)
    if not cfg.webhook_secret or not secrets.compare_digest(secret, cfg.webhook_secret):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "bad secret")

    try:
        res = await avinox_int.ingest_ride_payload(db, payload)
        await db.commit()
        return {"ok": True, "result": res}
    except Exception as e:
        await db.rollback()
        log.warning("avinox_webhook_failed: %s", e)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"failed to ingest ride: {e}") from e


@router.get("/status")
async def get_status(db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Connection status and ride counts for Avinox integration."""
    cfg = await avinox_int.get_or_create_config(db)

    # Count total avinox rides and fetch newest
    total_rides = await db.scalar(
        select(func.count()).select_from(models.Activity).where(models.Activity.source == "avinox")
    ) or 0

    newest = (await db.execute(
        select(models.Activity)
        .where(models.Activity.source == "avinox")
        .order_by(models.Activity.start_at.desc())
        .limit(1)
    )).scalars().first()

    webhook_path = f"/integrations/avinox/webhook/{cfg.webhook_secret}" if cfg.webhook_secret else "/integrations/avinox/push"

    return {
        "connected": bool(cfg.last_push_at or cfg.last_sync_at or total_rides > 0),
        "server_url": cfg.server_url,
        "query_token_set": bool(cfg.query_token),
        "webhook_path": webhook_path,
        "push_endpoint": "/integrations/avinox/push",
        "last_sync_at": cfg.last_sync_at.isoformat() if cfg.last_sync_at else None,
        "last_push_at": cfg.last_push_at.isoformat() if cfg.last_push_at else None,
        "last_error": cfg.last_error,
        "auto_sync_enabled": cfg.auto_sync_enabled,
        "total_rides": total_rides,
        "newest_ride_at": newest.start_at.isoformat() if newest else None,
    }


class AvinoxConfigIn(BaseModel):
    server_url: str | None = None
    query_token: str | None = None
    auto_sync_enabled: bool | None = None


@router.put("/config")
async def update_config(
    body: AvinoxConfigIn, db: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Update Avinox connection configuration."""
    cfg = await avinox_int.get_or_create_config(db)
    if body.server_url is not None:
        cfg.server_url = body.server_url.strip() or None
    if body.query_token is not None:
        cfg.query_token = body.query_token.strip() or None
    if body.auto_sync_enabled is not None:
        cfg.auto_sync_enabled = body.auto_sync_enabled
    await db.commit()
    return await get_status(db)


@router.post("/sync")
async def trigger_sync(
    full: bool = Query(False, description="Re-sync all rides"),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Pull rides on demand from the Avinox server."""
    try:
        return await avinox_int.sync_from_avinox(db, full=full)
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Avinox sync failed: {e}") from e
