"""Concept2 Logbook integration — credential storage + connect endpoint.

Long-lived personal tokens (issued from the Concept2 dev console at
https://log.concept2.com/developers/) cover the single-user case here;
OAuth refresh fields are present in the model for a future flow.

Token validation hits GET /api/users/me — on success we persist the
token plus the returned user_id / display name so the Settings UI can
show "connected as {name}".
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_any
from ..db import models
from ..db.session import get_session
from ..integrations import concept2 as concept2_int

router = APIRouter(
    prefix="/integrations/concept2",
    dependencies=[Depends(require_any)],
    tags=["concept2"],
)

LOGBOOK_BASE = "https://log.concept2.com"


def _mask(token: str | None) -> str | None:
    if not token:
        return None
    if len(token) <= 12:
        return "*" * len(token)
    return f"{token[:6]}…{token[-4:]}"


async def _fetch_user(token: str) -> dict[str, Any]:
    """Validate the token and return the Concept2 user payload."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            f"{LOGBOOK_BASE}/api/users/me",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.c2logbook.v1+json"},
        )
    if r.status_code == 401:
        raise HTTPException(status_code=400, detail="Concept2 rejected the token")
    if r.status_code >= 400:
        raise HTTPException(
            status_code=400,
            detail=f"Concept2 API error {r.status_code}: {r.text[:160]}",
        )
    body = r.json()
    return body.get("data") or body  # both shapes are observed in the wild


@router.get("/status")
async def get_status(db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    cred = await db.get(models.Concept2Credentials, 1)
    if cred is None:
        return {"connected": False}
    return {
        "connected": True,
        "user_id": cred.user_id,
        "user_name": cred.user_name,
        "token_masked": _mask(cred.access_token),
        "last_sync_at": cred.last_sync_at,
        "connected_at": cred.connected_at,
    }


class ConnectBody(BaseModel):
    access_token: str
    refresh_token: str | None = None


@router.put("/token")
async def connect(
    body: ConnectBody, db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Validate and persist a Concept2 personal access token. Returns the
    same shape as /status so the UI can refresh in one round-trip."""
    token = body.access_token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="access_token is required")

    user = await _fetch_user(token)
    user_id = user.get("id")
    user_name = user.get("first_name") or user.get("username") or user.get("email")

    now = datetime.now(timezone.utc)
    cred = await db.get(models.Concept2Credentials, 1)
    if cred is None:
        cred = models.Concept2Credentials(
            id=1,
            user_id=user_id,
            user_name=user_name,
            access_token=token,
            refresh_token=body.refresh_token,
            connected_at=now,
        )
        db.add(cred)
    else:
        cred.user_id = user_id
        cred.user_name = user_name
        cred.access_token = token
        if body.refresh_token is not None:
            cred.refresh_token = body.refresh_token
        cred.connected_at = now
    await db.commit()
    return await get_status(db)


@router.delete("/token")
async def disconnect(db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    cred = await db.get(models.Concept2Credentials, 1)
    if cred is not None:
        await db.delete(cred)
        await db.commit()
    return {"connected": False}


@router.post("/sync")
async def sync(
    full: bool = False,
    type_filter: str | None = "rower",
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Run an immediate sync. `full=true` ignores last_sync_at and pulls
    every page (use for the first backfill); otherwise incremental."""
    cred = await db.get(models.Concept2Credentials, 1)
    if cred is None:
        raise HTTPException(status_code=400, detail="Concept2 not connected")
    upserted = await concept2_int.sync_results(
        db, cred=cred,
        type_filter=type_filter or None,
        incremental=not full,
    )
    return {"upserted": upserted, "last_sync_at": cred.last_sync_at}
