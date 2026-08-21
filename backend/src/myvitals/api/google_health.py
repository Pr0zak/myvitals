"""Google Health API — connection, probe and sync.

A phone-independent route to the user's own watch data. See
``integrations/google_health.py`` for why this exists and what was verified
before it was built.

Routes use ``require_any`` rather than ``require_query`` so the phone can
read status too — the recurring trap recorded in CLAUDE.md.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from urllib.parse import parse_qs, urlparse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_any, require_query
from ..db import models
from ..db.session import get_session
from ..integrations import google_health as gh

log = logging.getLogger(__name__)
router = APIRouter()

# The OAuth `state` is minted here and checked on the callback. Google will
# happily redirect anyone to our callback URL; without this an attacker can
# make the single user of this app bind THEIR Google account to it.
_PENDING_STATES: dict[str, datetime] = {}
_STATE_TTL = timedelta(minutes=15)


def _mint_state() -> str:
    now = datetime.now(timezone.utc)
    for k, v in list(_PENDING_STATES.items()):
        if now - v > _STATE_TTL:
            _PENDING_STATES.pop(k, None)
    state = secrets.token_urlsafe(24)
    _PENDING_STATES[state] = now
    return state


def _burn_state(state: str) -> bool:
    issued = _PENDING_STATES.pop(state, None)
    return issued is not None and datetime.now(timezone.utc) - issued <= _STATE_TTL


class GoogleHealthAppConfigIn(BaseModel):
    client_id: str
    client_secret: str
    callback_url: str


@router.get("/google-health/config", dependencies=[Depends(require_query)])
async def get_config(db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    cfg = await db.get(models.GoogleHealthConfig, 1)
    return {
        "configured": bool(cfg and cfg.client_id and cfg.client_secret),
        "client_id": cfg.client_id if cfg else None,
        # Never echoed. It is write-only from the UI's point of view.
        "client_secret_set": bool(cfg and cfg.client_secret),
        "callback_url": cfg.callback_url if cfg else None,
    }


@router.post("/google-health/config", dependencies=[Depends(require_query)])
async def set_config(
    body: GoogleHealthAppConfigIn, db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    cfg = await db.get(models.GoogleHealthConfig, 1)
    if cfg is None:
        cfg = models.GoogleHealthConfig(id=1)
        db.add(cfg)
    cfg.client_id = body.client_id.strip()
    cfg.client_secret = body.client_secret.strip()
    cfg.callback_url = body.callback_url.strip().rstrip("/")
    cfg.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return await get_config(db)


@router.post("/google-health/authorize-url", dependencies=[Depends(require_query)])
async def authorize_url(db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """The consent URL, returned rather than redirected to.

    The paste flow needs the user to open this themselves and then bring back
    the URL Google lands on, so handing over the link beats a 302 the browser
    would follow away from Settings.
    """
    cfg = await db.get(models.GoogleHealthConfig, 1)
    if cfg is None or not cfg.client_id or not cfg.callback_url:
        raise HTTPException(400, "Google Health app credentials are not configured")
    return {"url": gh.authorize_url(cfg.client_id, cfg.callback_url, _mint_state())}


@router.get("/auth/google-health/callback")
async def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """OAuth landing. Deliberately unauthenticated — Google redirects the
    browser here and cannot carry our token — so the `state` check is the
    only thing standing between this and an account-binding attack."""
    if error:
        raise HTTPException(400, f"Google returned: {error}")
    if not code or not state:
        raise HTTPException(400, "missing code or state")
    if not _burn_state(state):
        raise HTTPException(400, "unknown or expired state — start again from Settings")

    cfg = await db.get(models.GoogleHealthConfig, 1)
    if cfg is None or not cfg.callback_url:
        raise HTTPException(400, "Google Health app credentials are not configured")
    try:
        creds = await gh.exchange_code(db, code, cfg.callback_url)
    except gh.GoogleHealthError as e:
        raise HTTPException(400, str(e)) from e
    return {"connected": True, "scope": creds.scope}


class ExchangeIn(BaseModel):
    """Either the whole redirected URL, or the bare code and state.

    Pasting the URL is what people actually do, so accept that and pull the
    parameters out rather than making them dissect a query string.
    """
    redirected_url: str | None = None
    code: str | None = None
    state: str | None = None


@router.post("/google-health/exchange", dependencies=[Depends(require_query)])
async def exchange(
    body: ExchangeIn, db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Finish the OAuth dance from a redirect this server never received.

    Google will not accept a LAN hostname as a redirect URI -- it requires a
    public top-level domain over HTTPS, with `localhost` the sole exception.
    That leaves a self-hosted install three choices: expose the app to the
    internet behind a real certificate, tunnel the loopback port, or capture
    the code by hand.

    This is the third. The user registers a `http://localhost/...` redirect,
    Google sends the browser there, nothing is listening so the page fails --
    and the authorization code is sitting in the address bar. Pasting that
    URL here completes the exchange.

    It is the only one of the three that requires no infrastructure and no
    exposure, which for an app holding years of personal health data is worth
    more than the small awkwardness of a copy and paste.
    """
    code, state = body.code, body.state
    if body.redirected_url:
        parsed = urlparse(body.redirected_url.strip())
        params = parse_qs(parsed.query)
        if params.get("error"):
            raise HTTPException(400, f"Google returned: {params['error'][0]}")
        code = code or (params.get("code") or [None])[0]
        state = state or (params.get("state") or [None])[0]
    if not code:
        raise HTTPException(
            400,
            "No authorization code found. Paste the whole URL the browser "
            "ended up on, including everything after the '?'.",
        )
    if not state or not _burn_state(state):
        raise HTTPException(
            400,
            "That link's state token is unknown or has expired. Press Connect "
            "again and paste the new URL within 15 minutes.",
        )

    cfg = await db.get(models.GoogleHealthConfig, 1)
    if cfg is None or not cfg.callback_url:
        raise HTTPException(400, "Google Health app credentials are not configured")
    try:
        # Must be byte-identical to the redirect_uri used in the authorize
        # request, or Google rejects the exchange.
        creds = await gh.exchange_code(db, code, cfg.callback_url)
    except gh.GoogleHealthError as e:
        raise HTTPException(400, str(e)) from e
    return {"connected": True, "scope": creds.scope}


@router.get("/google-health/status", dependencies=[Depends(require_any)])
async def status(db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    cfg = await db.get(models.GoogleHealthConfig, 1)
    creds = await db.get(models.GoogleHealthCredentials, 1)
    return {
        "configured": bool(cfg and cfg.client_id and cfg.client_secret),
        "connected": bool(creds and creds.refresh_token),
        "scope": creds.scope if creds else None,
        "connected_at": creds.connected_at if creds else None,
        "last_sync_at": creds.last_sync_at if creds else None,
        # Surfaced, not just logged — the Strava-cookie lesson.
        "last_error": creds.last_error if creds else None,
        "poll_enabled": bool(creds and creds.poll_enabled),
        "ingested_types": [s.api_type for s in gh.INGEST_TYPES],
    }


@router.post("/google-health/probe", dependencies=[Depends(require_query)])
async def probe(
    days: int = Query(7, ge=1, le=30),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """What does this account actually serve?

    The one question that could not be answered from documentation: whether
    this user's Fitbit-sourced Pixel Watch data reaches the API, and for
    which types. Run it before trusting anything else here.
    """
    try:
        return {"days": days, "types": await gh.probe_available_types(db, days=days)}
    except gh.GoogleHealthError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/google-health/sync", dependencies=[Depends(require_query)])
async def sync(
    days: int = Query(7, ge=1, le=180),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    until = datetime.now(timezone.utc).date() + timedelta(days=1)
    since = until - timedelta(days=days + 1)
    try:
        written = await gh.ingest_range(db, since, until)
    except gh.GoogleHealthError as e:
        raise HTTPException(400, str(e)) from e
    return {"since": since.isoformat(), "until": until.isoformat(), "written": written}


class PollToggle(BaseModel):
    enabled: bool


@router.post("/google-health/poll", dependencies=[Depends(require_query)])
async def set_poll(
    body: PollToggle, db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    creds = await db.get(models.GoogleHealthCredentials, 1)
    if creds is None:
        raise HTTPException(400, "Google Health is not connected")
    creds.poll_enabled = body.enabled
    await db.commit()
    return await status(db)


@router.delete("/google-health", status_code=204, dependencies=[Depends(require_query)])
async def disconnect(db: AsyncSession = Depends(get_session)) -> None:
    """Drop the tokens. Leaves the app registration and any ingested data
    alone: the readings are the user's own history, not Google's copy."""
    creds = await db.get(models.GoogleHealthCredentials, 1)
    if creds is not None:
        await db.delete(creds)
        await db.commit()
