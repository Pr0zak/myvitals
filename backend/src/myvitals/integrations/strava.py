"""Strava OAuth client + activity ingest.

Single-user; OAuth tokens live in `strava_credentials` (id=1), and the app's
client_id/client_secret/callback_url live in `strava_app_config` (id=1).
The DB row wins over STRAVA_* env vars so the dashboard can edit credentials
without an SSH-and-restart cycle.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import models
from ..db.session import SessionLocal

log = logging.getLogger(__name__)

_AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
_TOKEN_URL = "https://www.strava.com/oauth/token"
_API_BASE = "https://www.strava.com/api/v3"

# Scopes we ask for. activity:read_all includes private activities + history.
_SCOPE = "read,activity:read_all"


@dataclass
class AppCreds:
    client_id: str
    client_secret: str
    callback_url: str
    source: str  # "db" | "env"


async def get_app_credentials(db: AsyncSession) -> AppCreds | None:
    """Returns the OAuth app credentials. DB row beats env vars."""
    result = await db.execute(
        select(models.StravaAppConfig).where(models.StravaAppConfig.id == 1)
    )
    row = result.scalar_one_or_none()
    if row is not None:
        return AppCreds(
            client_id=row.client_id,
            client_secret=row.client_secret,
            callback_url=row.callback_url or settings.strava_callback_url,
            source="db",
        )
    if settings.strava_client_id and settings.strava_client_secret:
        return AppCreds(
            client_id=settings.strava_client_id,
            client_secret=settings.strava_client_secret,
            callback_url=settings.strava_callback_url,
            source="env",
        )
    return None


async def upsert_app_credentials(
    db: AsyncSession,
    client_id: str,
    client_secret: str,
    callback_url: str | None,
) -> None:
    stmt = insert(models.StravaAppConfig).values(
        id=1,
        client_id=client_id.strip(),
        client_secret=client_secret.strip(),
        callback_url=(callback_url or "").strip() or None,
        updated_at=datetime.now(timezone.utc),
    ).on_conflict_do_update(
        index_elements=["id"],
        set_={
            "client_id": client_id.strip(),
            "client_secret": client_secret.strip(),
            "callback_url": (callback_url or "").strip() or None,
            "updated_at": datetime.now(timezone.utc),
        },
    )
    await db.execute(stmt)
    await db.commit()


async def clear_app_credentials(db: AsyncSession) -> None:
    row = (await db.execute(
        select(models.StravaAppConfig).where(models.StravaAppConfig.id == 1)
    )).scalar_one_or_none()
    if row is not None:
        await db.delete(row)
        await db.commit()


def authorize_url(creds: AppCreds, state: str = "myvitals") -> str:
    params = {
        "client_id": creds.client_id,
        "response_type": "code",
        "redirect_uri": creds.callback_url,
        "scope": _SCOPE,
        "approval_prompt": "auto",
        "state": state,
    }
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{_AUTHORIZE_URL}?{qs}"


async def exchange_code(creds: AppCreds, code: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(_TOKEN_URL, data={
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "code": code,
            "grant_type": "authorization_code",
        })
        r.raise_for_status()
        return r.json()


async def _refresh_access_token(creds: AppCreds, refresh_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(_TOKEN_URL, data={
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        })
        r.raise_for_status()
        return r.json()


async def store_initial_credentials(db: AsyncSession, payload: dict[str, Any]) -> None:
    athlete = payload.get("athlete") or {}
    name = " ".join(filter(None, [athlete.get("firstname"), athlete.get("lastname")])) or None
    expires_at = datetime.fromtimestamp(payload["expires_at"], tz=timezone.utc)

    stmt = insert(models.StravaCredentials).values(
        id=1,
        athlete_id=athlete.get("id") or 0,
        athlete_name=name,
        access_token=payload["access_token"],
        refresh_token=payload["refresh_token"],
        expires_at=expires_at,
        scope=payload.get("scope"),
        connected_at=datetime.now(timezone.utc),
    ).on_conflict_do_update(
        index_elements=["id"],
        set_={
            "athlete_id": athlete.get("id") or 0,
            "athlete_name": name,
            "access_token": payload["access_token"],
            "refresh_token": payload["refresh_token"],
            "expires_at": expires_at,
            "scope": payload.get("scope"),
            "connected_at": datetime.now(timezone.utc),
        },
    )
    await db.execute(stmt)
    await db.commit()


async def get_credentials(db: AsyncSession) -> models.StravaCredentials | None:
    result = await db.execute(
        select(models.StravaCredentials).where(models.StravaCredentials.id == 1)
    )
    return result.scalar_one_or_none()


async def _ensure_fresh_token(
    db: AsyncSession,
    app_creds: AppCreds,
    user_creds: models.StravaCredentials,
) -> str:
    """Return a usable access token, refreshing if it expires within 5 min."""
    now = datetime.now(timezone.utc)
    if user_creds.expires_at - now > timedelta(minutes=5):
        return user_creds.access_token

    log.info("Refreshing Strava access token (expires at %s)", user_creds.expires_at)
    payload = await _refresh_access_token(app_creds, user_creds.refresh_token)
    user_creds.access_token = payload["access_token"]
    user_creds.refresh_token = payload["refresh_token"]
    user_creds.expires_at = datetime.fromtimestamp(payload["expires_at"], tz=timezone.utc)
    await db.commit()
    return user_creds.access_token


async def fetch_activities(
    db: AsyncSession,
    app_creds: AppCreds,
    user_creds: models.StravaCredentials,
    after_ts: int | None = None,
    per_page: int = 100,
) -> list[dict[str, Any]]:
    token = await _ensure_fresh_token(db, app_creds, user_creds)
    headers = {"Authorization": f"Bearer {token}"}

    activities: list[dict[str, Any]] = []
    page = 1
    async with httpx.AsyncClient(base_url=_API_BASE, headers=headers, timeout=30) as client:
        while True:
            params: dict[str, Any] = {"per_page": per_page, "page": page}
            if after_ts:
                params["after"] = after_ts
            r = await client.get("/athlete/activities", params=params)
            r.raise_for_status()
            page_data = r.json()
            if not page_data:
                break
            activities.extend(page_data)
            if len(page_data) < per_page:
                break
            page += 1
            if page > 50:
                log.warning("Strava: 50-page safety cap hit (%d activities)", len(activities))
                break

    return activities


def _activity_row_values(act: dict[str, Any]) -> dict[str, Any]:
    start = datetime.fromisoformat(act["start_date"].replace("Z", "+00:00"))
    map_data = act.get("map") or {}
    return {
        "source": "strava",
        "source_id": str(act["id"]),
        "type": (act.get("sport_type") or act.get("type") or "unknown").lower(),
        "name": act.get("name"),
        "start_at": start,
        "duration_s": int(act.get("elapsed_time") or 0),
        "distance_m": act.get("distance"),
        "elevation_gain_m": act.get("total_elevation_gain"),
        "avg_hr": act.get("average_heartrate"),
        "max_hr": act.get("max_heartrate"),
        "avg_power_w": act.get("average_watts"),
        "max_power_w": act.get("max_watts"),
        "kcal": act.get("calories") or act.get("kilojoules"),
        "suffer_score": act.get("suffer_score"),
        "polyline": map_data.get("summary_polyline"),
        "raw": act,
    }


async def upsert_activities(db: AsyncSession, payloads: list[dict[str, Any]]) -> int:
    if not payloads:
        return 0
    rows = [_activity_row_values(a) for a in payloads]
    stmt = insert(models.Activity).values(rows)
    update_cols = {c.name: c for c in stmt.excluded if c.name not in ("source", "source_id")}
    stmt = stmt.on_conflict_do_update(
        index_elements=["source", "source_id"],
        set_=update_cols,
    )
    await db.execute(stmt)
    await db.commit()
    return len(rows)


async def sync_recent(after_ts: int | None = None) -> int:
    """Pull activities since [after_ts] (or since last_sync_at) and upsert."""
    async with SessionLocal() as db:
        app_creds = await get_app_credentials(db)
        if app_creds is None:
            return 0

        user_creds = await get_credentials(db)
        if user_creds is None:
            return 0

        cutoff_ts = after_ts
        if cutoff_ts is None and user_creds.last_sync_at is not None:
            cutoff_ts = int(user_creds.last_sync_at.timestamp())

        activities = await fetch_activities(db, app_creds, user_creds, after_ts=cutoff_ts)
        n = await upsert_activities(db, activities)

        user_creds.last_sync_at = datetime.now(timezone.utc)
        await db.commit()

        if n:
            log.info("Strava: upserted %d activities", n)
        return n
