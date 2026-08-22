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
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
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
    # Optional, and an empty value means "keep what is stored".
    #
    # The UI never echoes the secret back — it is write-only from the
    # browser's point of view — and tells the user that leaving the field
    # blank keeps the saved one. This handler used to overwrite
    # unconditionally, so the SECOND save (after the field had been cleared
    # on the first) silently wiped the secret, leaving a config that looked
    # complete but could not authorise. The promise the UI makes has to be
    # implemented here, because this is where it can actually be kept.
    client_secret: str | None = None
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
    secret = (body.client_secret or "").strip()
    if secret:
        cfg.client_secret = secret
    elif not cfg.client_secret:
        raise HTTPException(400, "A client secret is required the first time.")
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
        "poll_interval_min": int(getattr(creds, "poll_interval_min", 60) or 60) if creds else 60,
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


class BackfillIn(BaseModel):
    """An explicit date range, not a `days` number.

    "Backfill 90 days" cannot express "the fortnight I was on holiday and
    the phone was off", which is the shape a real gap has. Dates also make
    a re-run idempotent to describe: the same range means the same window
    regardless of when it is pressed.
    """

    since: date
    until: date


#: Days pulled per API round. The range is walked in windows rather than
#: requested whole for three reasons: the API rate-limits readily, a
#: failure mid-range then costs one window instead of the lot, and progress
#: is only visible at all if there is something to report between windows.
_BACKFILL_WINDOW_D = 7


async def _run_backfill(job_id: int, since: date, until: date) -> None:
    """Walk the range window by window, reporting progress as it goes.

    Runs against its own session: this is a background task, so the
    request-scoped session is long closed by the time it starts.

    A window that fails is recorded and the walk CONTINUES. One
    rate-limited or malformed window should not abandon the other twelve —
    and because ingest upserts, re-running the range later repairs the gap
    without duplicating anything that landed.
    """
    from ..api.imports import _finish_job, _update_job_counts
    from ..db.session import SessionLocal

    totals: dict[str, int] = {}
    failures: list[str] = []
    cursor = since
    windows = 0

    try:
        while cursor < until:
            window_end = min(cursor + timedelta(days=_BACKFILL_WINDOW_D), until)
            try:
                async with SessionLocal() as db:
                    written = await gh.ingest_range(db, cursor, window_end)
                for k, v in (written or {}).items():
                    totals[k] = totals.get(k, 0) + int(v or 0)
            except Exception as e:  # noqa: BLE001
                failures.append(f"{cursor.isoformat()}: {type(e).__name__}")
                log.warning("backfill window %s..%s failed: %s", cursor, window_end, e)

            windows += 1
            cursor = window_end
            # Progress after every window, so a long run is visibly moving
            # rather than indistinguishable from a hung one.
            await _update_job_counts(
                job_id, {**totals, "_windows_done": windows,
                         "_windows_failed": len(failures)},
            )

        status = "done" if not failures else "partial"
        await _finish_job(
            job_id, status,
            {**totals, "_windows_done": windows, "_windows_failed": len(failures)},
            error=("; ".join(failures[:5]) or None),
        )
    except Exception as e:  # noqa: BLE001
        log.exception("Google Health backfill failed")
        await _finish_job(job_id, "failed", totals, error=f"{type(e).__name__}: {e}")


@router.post("/google-health/backfill", dependencies=[Depends(require_query)])
async def backfill(
    body: BackfillIn,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Start a tracked backfill over an explicit date range.

    Returns immediately with a job id; poll `/imports/jobs/{id}` for
    progress. The previous `/google-health/sync?days=N` ran inline, so a
    long range was a single HTTP request that could outlive its own
    timeout with no way to tell a slow run from a dead one.
    """
    creds = await db.get(models.GoogleHealthCredentials, 1)
    if creds is None or not creds.refresh_token:
        raise HTTPException(400, "Google Health is not connected")
    if body.until <= body.since:
        raise HTTPException(400, "until must be after since")

    # A year is already ~52 windows and several hundred API calls. Beyond
    # that the run stops being something to watch and becomes something to
    # schedule, which is a different feature.
    span = (body.until - body.since).days
    if span > 366:
        raise HTTPException(400, "range is limited to 366 days per run")

    from ..api.imports import _create_job

    job_id = await _create_job(
        "google_health",
        f"{body.since.isoformat()}..{body.until.isoformat()}",
        None,
    )
    background.add_task(_run_backfill, job_id, body.since, body.until)
    return {
        "job_id": job_id,
        "since": body.since.isoformat(),
        "until": body.until.isoformat(),
        "windows": -(-span // _BACKFILL_WINDOW_D),
        "poll": f"/import/jobs/{job_id}",
    }


class PollToggle(BaseModel):
    enabled: bool
    # Minutes between polls. Floored at 15 in the handler: a poll fetches ten
    # data types over a three-day window and the API rate-limits readily, so
    # a tighter cadence spends quota without producing data that moves that
    # fast.
    interval_min: int | None = None


@router.post("/google-health/poll", dependencies=[Depends(require_query)])
async def set_poll(
    body: PollToggle, db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    creds = await db.get(models.GoogleHealthCredentials, 1)
    if creds is None:
        raise HTTPException(400, "Google Health is not connected")
    creds.poll_enabled = body.enabled
    if body.interval_min is not None:
        creds.poll_interval_min = max(15, min(1440, int(body.interval_min)))
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
