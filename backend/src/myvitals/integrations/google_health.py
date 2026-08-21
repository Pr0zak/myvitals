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

import asyncio
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


def _camel(api_type: str) -> str:
    """`oxygen-saturation` -> `oxygenSaturation`.

    Every data point nests its body under this key alongside `dataSource`,
    and both the reading AND its timestamp live inside it — there is no
    top-level interval or date, which is what the first version of this
    parser assumed.
    """
    head, *rest = api_type.split("-")
    return head + "".join(w.capitalize() for w in rest)


def _body(point: dict[str, Any], api_type: str) -> dict[str, Any]:
    value = point.get(_camel(api_type))
    return value if isinstance(value, dict) else {}


def _spo2_percent(body: dict[str, Any]) -> float | None:
    pct = body.get("percentage")
    return float(pct) if pct is not None else None


def _skin_temp_delta(body: dict[str, Any]) -> float | None:
    """Nightly skin temperature as a DELTA from the user's own baseline.

    Google reports two absolute figures — `nightlyTemperatureCelsius` and
    `baselineTemperatureCelsius` — while `vitals_skin_temp` stores the
    deviation, which is the number that actually means something: 32.8 C at
    the wrist is meaningless on its own, half a degree below your own
    thirty-day baseline is not. Deriving it here keeps the stored column
    honest to its name.
    """
    nightly = body.get("nightlyTemperatureCelsius")
    baseline = body.get("baselineTemperatureCelsius")
    if nightly is None or baseline is None:
        return None
    return round(float(nightly) - float(baseline), 3)


@dataclass(frozen=True)
class DataTypeSpec:
    """One data type, how to read it, and where its values land.

    ``extract`` is a function rather than a dotted path because the payloads
    are not uniformly shaped. SpO2 carries a ready-made percentage; skin
    temperature carries two absolute readings whose difference is the value
    this app stores. A path expression could express the first and not the
    second, and guessing a path that did not exist is exactly how the first
    version of this shipped broken.
    """
    api_type: str
    extract: Any          # (body: dict) -> float | None
    target: str


# Types this integration currently ingests.
#
# The selection is deliberately narrow, and the reason is double-counting.
# HeartRate, Steps, SleepSession and BodyMetric are all written by the phone
# already; vitals_hrv, vitals_spo2 and vitals_skin_temp key on `time` alone
# with no source column, so a second writer at a different sampling
# granularity would silently overwrite rather than coexist.
#
# SpO2 and skin temperature have no competing writer at all — vitals_spo2 has
# never had one — so they carry zero conflict risk and are exactly the two
# streams the Pixel Watch firmware bug killed.
#
# Confirmed present on this account, sourced from a Pixel Watch 3 via
# platform FITBIT, before being wired.
INGEST_TYPES: tuple[DataTypeSpec, ...] = (
    DataTypeSpec("oxygen-saturation", _spo2_percent, "spo2"),
    DataTypeSpec("daily-sleep-temperature-derivations", _skin_temp_delta, "skin_temp"),
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


# Which filter a data type will accept, established empirically against the
# live API — the documentation describes the filter grammar but does not say
# which field each type exposes, and getting it wrong is a flat 400
# (INVALID_DATA_POINT_FILTER_DATA_TYPE_MEMBER) rather than an ignored
# parameter.
#
#   daily-*        filter on `<type>.date` with plain YYYY-MM-DD bounds
#   interval types filter on `<type>.interval.start_time` with RFC-3339
#   everything else  rejects every filter field tried; fetch unfiltered and
#                    bound the window client-side
#
# The last group is the awkward one and the reason `_within` exists. Results
# come back newest-first, so pagination stops as soon as a page runs past the
# start of the window rather than walking the user's whole history.
_INTERVAL_TYPES = frozenset({
    "steps", "distance", "floors", "total-calories", "active-zone-minutes",
    "activity-level", "hydration-log",
})


def _filter_for(api_type: str, since: date, until: date) -> str | None:
    field = api_type.replace("-", "_")
    if api_type.startswith("daily-"):
        return f'{field}.date >= "{since.isoformat()}" AND {field}.date < "{until.isoformat()}"'
    if api_type in _INTERVAL_TYPES:
        return (
            f'{field}.interval.start_time >= "{since.isoformat()}T00:00:00Z" '
            f'AND {field}.interval.start_time < "{until.isoformat()}T00:00:00Z"'
        )
    return None


def _within(point: dict[str, Any], since: date, until: date,
            api_type: str | None = None) -> bool:
    """Is this point inside the window? Used only for unfiltered fetches."""
    ts = _point_time(point, api_type)
    if ts is None:
        return False
    return since <= ts.date() < until


async def _get_with_retry(
    client: httpx.AsyncClient, url: str, params: dict[str, Any], token: str,
) -> httpx.Response:
    """One GET, retrying on 429.

    The API rate-limits, and it does so readily enough that a probe touching
    a dozen types in a row trips it. A 429 surfaced as a hard failure would
    make an available stream look unavailable, which is the one thing the
    probe exists to report accurately.
    """
    delay = 2.0
    for attempt in range(4):
        resp = await client.get(
            url, params=params, headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code != 429:
            return resp
        if attempt == 3:
            return resp
        retry_after = resp.headers.get("Retry-After")
        wait = float(retry_after) if (retry_after or "").isdigit() else delay
        log.info("google health 429; retrying in %.0fs", wait)
        await asyncio.sleep(wait)
        delay *= 2
    return resp


async def fetch_data_points(
    token: str, api_type: str, since: date, until: date,
    *, page_size: int = 1000, max_pages: int = 50,
) -> list[dict[str, Any]]:
    """All data points of one type in a date range, following pagination.

    Applies whatever filter the type accepts and falls back to bounding the
    window in Python for the types that accept none. `max_pages` is a
    backstop for that fallback: without a server-side filter there is nothing
    to stop a paginated walk through years of samples if the ordering
    assumption ever fails.
    """
    server_filter = _filter_for(api_type, since, until)
    params: dict[str, Any] = {"pageSize": page_size}
    if server_filter:
        params["filter"] = server_filter

    out: list[dict[str, Any]] = []
    url = f"{API_BASE}/dataTypes/{api_type}/dataPoints"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for _page in range(max_pages):
            resp = await _get_with_retry(client, url, params, token)
            if resp.status_code == 403:
                raise GoogleHealthError(
                    f"{api_type}: access denied — the granted scopes may not "
                    f"cover it ({resp.text[:160]})"
                )
            if resp.status_code == 429:
                raise GoogleHealthError(
                    f"{api_type}: rate limited by Google after retries — "
                    "try again in a minute"
                )
            if resp.status_code >= 400:
                raise GoogleHealthError(f"{api_type}: {resp.status_code} {resp.text[:200]}")
            body = resp.json()
            page = body.get("dataPoints") or []

            if server_filter:
                out.extend(page)
            else:
                out.extend(p for p in page if _within(p, since, until, api_type))
                # Newest-first ordering: once a whole page predates the
                # window there is nothing older worth walking to.
                if page and all(
                    (t := _point_time(p, api_type)) is not None and t.date() < since
                    for p in page
                ):
                    return out

            next_token = body.get("nextPageToken")
            if not next_token:
                return out
            params = {**params, "pageToken": next_token}
    log.warning("google health %s hit the %d-page cap", api_type, max_pages)
    return out


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
            points = await fetch_data_points(
                token, api_type, since, until, page_size=50, max_pages=2,
            )
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
        # The API rate-limits readily, and a probe walks a dozen types in a
        # row. A short pause costs a few seconds once; a 429 makes an
        # available stream report as unavailable, which is the one thing this
        # function must not get wrong.
        await asyncio.sleep(1.5)
    return results


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def _point_time(point: dict[str, Any], api_type: str | None = None) -> datetime | None:
    """The instant a data point describes.

    The timestamp lives inside the type-specific body, in one of two shapes:
    a sample carries ``sampleTime.physicalTime`` (an RFC-3339 instant), and a
    daily aggregate carries a civil ``date``. A daily value is stamped at
    midday rather than midnight, because midnight is exactly the boundary
    this app keeps getting wrong and a value parked there is ambiguous about
    which day it belongs to.

    ``api_type`` is optional so the probe can call this without knowing the
    type; it falls back to scanning for the one non-``dataSource`` key.
    """
    body: dict[str, Any] = {}
    if api_type:
        body = _body(point, api_type)
    if not body:
        for key, value in point.items():
            if key != "dataSource" and isinstance(value, dict):
                body = value
                break
    if not body:
        return None

    physical = (body.get("sampleTime") or {}).get("physicalTime")
    if physical:
        try:
            return datetime.fromisoformat(str(physical).replace("Z", "+00:00"))
        except ValueError:
            return None

    interval = body.get("interval") or {}
    start = interval.get("startTime")
    if start:
        try:
            return datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        except ValueError:
            return None

    d = body.get("date") or {}
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
            ts = _point_time(point, spec.api_type)
            value = spec.extract(_body(point, spec.api_type))
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
