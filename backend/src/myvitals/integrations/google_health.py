"""Google Health API v4 — a second, phone-independent route to watch data.

The Android companion app is currently the only path into this system for
every stream it records, which makes the phone a single point of failure for
all of them. Google's Health API serves the same data server-to-server, and
two of its data types are the ones currently dead on this user's watch:
``oxygen-saturation`` and ``daily-sleep-temperature-derivations``. SpO2 in
particular has never had a writer at all — ``vitals_spo2`` is an empty
hypertable whose Health Connect permission is granted and unused.

Checked before any of this was written, because the whole thing is pointless
if the API is gated:

* No allowlist and no approval process. Enable the API, create an OAuth
  client, add yourself as a test user.
* Verification is only required above 100 users, so a single-user
  self-hosted install stays in the unverified tier indefinitely.
* ``oxygen-saturation`` and ``daily-sleep-temperature-derivations`` are both
  documented data types.

What could NOT be checked from here, and is therefore what
:func:`probe_available_types` exists to answer in one click: whether this
particular account's Fitbit-sourced Pixel Watch data actually populates those
types. Nobody should write a mapper against an API they have not seen return
data for.

Deliberately bring-your-own-app, mirroring the Strava integration: the client
id and secret come from the user's own Google Cloud project, so there is no
shared registration to leak and the quota is theirs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import models

log = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://health.googleapis.com/v4/users/me"

# Read-only throughout. This app is a consumer of watch data; nothing here
# should ever be able to write back into the user's Google Health record.
SCOPES = (
    "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
    "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly",
    "https://www.googleapis.com/auth/googlehealth.sleep.readonly",
)

# Refresh this far before actual expiry, so a long sync cannot have the token
# die underneath it mid-run.
_REFRESH_MARGIN = timedelta(minutes=5)
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class GoogleHealthError(RuntimeError):
    """A call failed in a way worth showing the user."""


@dataclass(frozen=True)
class DataTypeSpec:
    """One data type, and where its values land in this app's schema.

    ``value_path`` is the dotted path into a data point's payload. The API
    nests the reading under a key derived from the data type name, so
    ``oxygen-saturation`` yields ``{"oxygenSaturation": {"percentage": 97}}``.
    """
    api_type: str
    value_path: str
    # Which of this app's tables it feeds. Only types with NO competing
    # writer are wired in the first cut — see INGEST_TYPES.
    target: str


# Types this integration currently ingests.
#
# The selection is deliberately narrow, and the reason is double-counting.
# HeartRate, Steps, SleepSession and BodyMetric are all written by the phone
# already; vitals_hrv, vitals_spo2 and vitals_skin_temp key on `time` alone
# with no source column, so a second writer at a different sampling
# granularity would silently overwrite rather than coexist. Google's HRV is a
# DAILY aggregate, which would be actively wrong written into a per-sample
# table.
#
# SpO2 and skin temperature have no competing writer at all — vitals_spo2 has
# never had one — so they carry zero conflict risk and are exactly the two
# streams the firmware bug killed. Everything else waits until the probe
# shows what this account actually serves.
INGEST_TYPES: tuple[DataTypeSpec, ...] = (
    DataTypeSpec("oxygen-saturation", "oxygenSaturation.percentage", "spo2"),
    DataTypeSpec(
        "daily-sleep-temperature-derivations",
        "dailySleepTemperatureDerivations.deltaCelsius",
        "skin_temp",
    ),
)

# Types worth reporting on in the probe even though nothing ingests them yet,
# so the user can see at a glance what their account would make available.
PROBE_TYPES: tuple[str, ...] = (
    "oxygen-saturation",
    "daily-sleep-temperature-derivations",
    "daily-heart-rate-variability",
    "daily-resting-heart-rate",
    "daily-respiratory-rate",
    "daily-vo2-max",
    "heart-rate",
    "steps",
    "sleep",
    "exercise",
    "weight",
    "body-fat",
)


# ---------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------

def authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    """The consent URL to send the user to.

    ``access_type=offline`` plus ``prompt=consent`` because we need a refresh
    token and Google only issues one on the first consent unless explicitly
    asked again — a re-authorisation that silently returns no refresh token
    leaves an integration that works until the first hour elapses.
    """
    return f"{AUTH_URL}?" + urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    })


async def exchange_code(
    db: AsyncSession, code: str, redirect_uri: str,
) -> models.GoogleHealthCredentials:
    cfg = await db.get(models.GoogleHealthConfig, 1)
    if cfg is None or not cfg.client_id or not cfg.client_secret:
        raise GoogleHealthError("Google Health app credentials are not configured")

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(TOKEN_URL, data={
            "code": code,
            "client_id": cfg.client_id,
            "client_secret": cfg.client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })
    if resp.status_code >= 400:
        raise GoogleHealthError(f"token exchange failed: {resp.text[:300]}")
    data = resp.json()

    if not data.get("refresh_token"):
        # Without one the connection dies in an hour and the failure looks
        # like a server problem rather than a consent problem.
        raise GoogleHealthError(
            "Google did not return a refresh token. Revoke this app's access "
            "at myaccount.google.com/permissions and connect again."
        )

    creds = await db.get(models.GoogleHealthCredentials, 1)
    if creds is None:
        creds = models.GoogleHealthCredentials(id=1)
        db.add(creds)
    now = datetime.now(timezone.utc)
    creds.access_token = data["access_token"]
    creds.refresh_token = data["refresh_token"]
    creds.expires_at = now + timedelta(seconds=int(data.get("expires_in", 3600)))
    creds.scope = data.get("scope")
    creds.connected_at = now
    creds.last_error = None
    await db.commit()
    log.info("google health connected; scopes=%s", creds.scope)
    return creds


async def valid_access_token(db: AsyncSession) -> str:
    """A usable access token, refreshing first if it is close to expiry."""
    creds = await db.get(models.GoogleHealthCredentials, 1)
    if creds is None or not creds.refresh_token:
        raise GoogleHealthError("Google Health is not connected")

    now = datetime.now(timezone.utc)
    if creds.access_token and creds.expires_at and creds.expires_at - _REFRESH_MARGIN > now:
        return creds.access_token

    cfg = await db.get(models.GoogleHealthConfig, 1)
    if cfg is None or not cfg.client_id or not cfg.client_secret:
        raise GoogleHealthError("Google Health app credentials are not configured")

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(TOKEN_URL, data={
            "refresh_token": creds.refresh_token,
            "client_id": cfg.client_id,
            "client_secret": cfg.client_secret,
            "grant_type": "refresh_token",
        })
    if resp.status_code >= 400:
        # Record it: a revoked grant otherwise presents as "no new data",
        # which is indistinguishable from a quiet week.
        creds.last_error = f"token refresh failed: {resp.text[:200]}"
        await db.commit()
        raise GoogleHealthError(creds.last_error)

    data = resp.json()
    creds.access_token = data["access_token"]
    creds.expires_at = now + timedelta(seconds=int(data.get("expires_in", 3600)))
    # Google usually omits refresh_token on refresh; keep the existing one.
    if data.get("refresh_token"):
        creds.refresh_token = data["refresh_token"]
    creds.last_error = None
    await db.commit()
    return creds.access_token


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def _dig(payload: dict[str, Any], path: str) -> Any:
    cur: Any = payload
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


async def fetch_data_points(
    token: str, api_type: str, since: date, until: date,
    *, page_size: int = 1000,
) -> list[dict[str, Any]]:
    """All data points of one type in a date range, following pagination.

    The filter field name is the data type with hyphens replaced by
    underscores, which is the API's own convention.
    """
    field = api_type.replace("-", "_")
    params = {
        "pageSize": page_size,
        "filter": (
            f'{field}.interval.start_time >= "{since.isoformat()}T00:00:00Z" '
            f'AND {field}.interval.start_time < "{until.isoformat()}T00:00:00Z"'
        ),
    }
    out: list[dict[str, Any]] = []
    url = f"{API_BASE}/dataTypes/{api_type}/dataPoints"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        while True:
            resp = await client.get(
                url, params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 403:
                raise GoogleHealthError(
                    f"{api_type}: access denied — the granted scopes may not "
                    f"cover it ({resp.text[:160]})"
                )
            if resp.status_code >= 400:
                raise GoogleHealthError(f"{api_type}: {resp.status_code} {resp.text[:200]}")
            body = resp.json()
            out.extend(body.get("dataPoints") or [])
            token_next = body.get("nextPageToken")
            if not token_next:
                return out
            params = {**params, "pageToken": token_next}


async def probe_available_types(
    db: AsyncSession, days: int = 7,
) -> list[dict[str, Any]]:
    """Ask the account what it actually serves, one small call per type.

    This is the honest answer to the one question that could not be settled
    from documentation: whether this user's Fitbit-sourced Pixel Watch data
    reaches the API at all, and for which types. Each entry reports the count
    found and, when a type errors, the reason — a scope that was not granted
    reads very differently from a type the watch simply does not produce.
    """
    token = await valid_access_token(db)
    until = datetime.now(timezone.utc).date() + timedelta(days=1)
    since = until - timedelta(days=days + 1)

    results: list[dict[str, Any]] = []
    for api_type in PROBE_TYPES:
        entry: dict[str, Any] = {"type": api_type, "ingested": any(
            spec.api_type == api_type for spec in INGEST_TYPES
        )}
        try:
            points = await fetch_data_points(token, api_type, since, until, page_size=50)
            entry["points"] = len(points)
            entry["ok"] = True
            if points:
                # One redacted sample so the shape is visible without dumping
                # readings into a log or a screenshot.
                entry["sample_keys"] = sorted(points[0].keys())
        except GoogleHealthError as e:
            entry["ok"] = False
            entry["error"] = str(e)[:200]
        results.append(entry)
    return results


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def _point_time(point: dict[str, Any]) -> datetime | None:
    """The instant a data point describes.

    Instantaneous readings carry an interval; daily aggregates carry a civil
    date instead. A daily value is stamped at local-ish midday rather than
    midnight, because midnight is exactly the boundary the rest of this app
    keeps getting wrong and a value parked there is ambiguous about which day
    it belongs to.
    """
    interval = point.get("interval") or {}
    start = interval.get("startTime")
    if start:
        try:
            return datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        except ValueError:
            return None
    d = point.get("date") or {}
    if d.get("year"):
        try:
            return datetime(
                int(d["year"]), int(d.get("month", 1)), int(d.get("day", 1)),
                12, 0, tzinfo=timezone.utc,
            )
        except (ValueError, TypeError):
            return None
    return None


async def ingest_range(
    db: AsyncSession, since: date, until: date,
) -> dict[str, int]:
    """Pull every wired data type for a date range and upsert it.

    Returns per-type counts of rows written. Types are fetched independently
    and a failure in one is recorded rather than aborting the rest: a scope
    the user did not grant should cost that one stream, not the whole sync.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    token = await valid_access_token(db)
    creds = await db.get(models.GoogleHealthCredentials, 1)
    written: dict[str, int] = {}
    errors: list[str] = []

    for spec in INGEST_TYPES:
        try:
            points = await fetch_data_points(token, spec.api_type, since, until)
        except GoogleHealthError as e:
            errors.append(f"{spec.api_type}: {e}")
            log.warning("google health %s failed: %s", spec.api_type, e)
            continue

        rows: list[dict[str, Any]] = []
        for point in points:
            ts = _point_time(point)
            value = _dig(point, spec.value_path)
            if ts is None or value is None:
                continue
            if spec.target == "spo2":
                rows.append({"time": ts, "percent": float(value)})
            elif spec.target == "skin_temp":
                rows.append({"time": ts, "celsius_delta": float(value)})

        if not rows:
            written[spec.api_type] = 0
            continue

        # De-dupe within the batch: these tables key on `time` alone, so two
        # points sharing an instant would make the statement conflict with
        # itself. Last value wins, matching the FIT ingest's convention.
        by_time = {r["time"]: r for r in rows}
        deduped = list(by_time.values())

        model = models.Spo2 if spec.target == "spo2" else models.SkinTemp
        stmt = pg_insert(model).values(deduped)
        stmt = stmt.on_conflict_do_update(
            index_elements=["time"],
            set_={k: getattr(stmt.excluded, k) for k in deduped[0] if k != "time"},
        )
        await db.execute(stmt)
        written[spec.api_type] = len(deduped)

    if creds is not None:
        creds.last_sync_at = datetime.now(timezone.utc)
        # Partial failure is still failure worth surfacing; a stream that has
        # been erroring for a week must not look like a quiet week.
        creds.last_error = "; ".join(errors)[:500] if errors else None
    await db.commit()
    log.info("google health ingest %s→%s: %s", since, until, written)
    return written
