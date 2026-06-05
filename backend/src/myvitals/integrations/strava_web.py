"""Cookie-session Strava ingestion.

Strava's June 2026 policy puts the OAuth API behind a paid Strava
subscription. This module gives free-tier users a manual sync path:
they paste their `strava_remember_token` cookie (grabbed from
chrome devtools), tap a button, and we pull recent activities via
the same authenticated session their browser uses.

We hit two strava.com surfaces:

  1. `/athlete/training_activities?...&page=N` (Accept: application/json)
     — JSON paginated list of athlete's own activities with id, name,
     type, start_time, distance_raw. Used to discover new activity IDs.

  2. `/activities/{id}/export_original` — returns the *original* upload
     file the activity was created from. For Avinox-recorded rides
     this is a FIT carrying the chest-strap HR stream + GPS + cadence.

The FIT is parsed via the `fitparse` dep (already in pyproject.toml).
Per-second HR samples land in `vitals_heartrate` with source=`strava_fit`;
the Activity row gets avg/max HR computed over the window.

No background scheduler — sync is button-triggered. Cookie staleness
manifests as a 401 on the next call; the user re-pastes from devtools.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
from fitparse import FitFile

from ..db import models

log = logging.getLogger(__name__)

_UA = "myvitals/1.0 (self-hosted; cookie-session)"
_STRAVA = "https://www.strava.com"


# ─── Fernet encryption for the stored password ──────────────────────
#
# SCS-7 — the key lives in the strava_cookie_creds row itself (auto-
# generated on first save). The legacy STRAVA_CREDS_KEY env var still
# wins when set, so existing deployments don't break. New deployments
# never need to touch .env.

def _resolve_key(creds_row_key_b64: str | None) -> str | None:
    """Pick the key to use. Env var wins (back-compat); else DB row's."""
    from ..config import settings as _s
    return _s.strava_creds_key or creds_row_key_b64


def _fernet(key_b64: str | None):
    if not key_b64:
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(key_b64.encode())
    except Exception as e:  # noqa: BLE001
        log.error("Fernet key invalid: %s", e)
        return None


def generate_key_b64() -> str:
    """Auto-mint a fresh Fernet key for a new creds row."""
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()


def encrypt_password(plain: str, key_b64: str) -> str:
    f = _fernet(key_b64)
    if f is None:
        raise RuntimeError("encryption key invalid")
    return f.encrypt(plain.encode()).decode()


def decrypt_password(blob: str, key_b64: str) -> str:
    f = _fernet(key_b64)
    if f is None:
        raise RuntimeError("encryption key invalid")
    return f.decrypt(blob.encode()).decode()


def auto_login_available() -> bool:
    """Always true now — the key is DB-resident and auto-generated
    on first save. Kept for back-compat with the existing UI plumbing."""
    return True


# ─── Playwright-driven auto-login ──────────────────────────────────

@dataclass
class LoginResult:
    ok: bool
    remember_token: str | None = None
    sid_cookie: str | None = None
    athlete_id: int | None = None
    athlete_name: str | None = None
    error: str | None = None


async def auto_login(email: str, password: str) -> LoginResult:
    """Drive a headless Chromium to log into strava.com with the given
    credentials and extract the session cookies. Password lives only on
    the function stack — we don't log it, persist it, or pass it to any
    downstream call.

    Returns ok=False with `error` populated on:
    - Wrong email/password (Strava redirects back to /login)
    - Captcha / Cloudflare challenge (Strava's bot detection kicks in)
    - Network errors / Playwright not installed
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return LoginResult(ok=False, error="playwright not installed on backend")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            try:
                context = await browser.new_context(user_agent=_UA)
                page = await context.new_page()
                await page.goto(f"{_STRAVA}/login", wait_until="domcontentloaded", timeout=30_000)

                # Strava's login form: input[name="email"], input[name="password"], button[type="submit"]
                await page.fill('input[name="email"]', email)
                await page.fill('input[name="password"]', password)

                # Submit and wait for either successful redirect to /dashboard
                # or any other navigation (failed login redirects back to /login
                # with a flash; captcha bounces to a challenge page).
                async with page.expect_navigation(timeout=30_000):
                    await page.click('button[type="submit"]')

                # Allow a beat for client-side redirects + cookie write.
                await page.wait_for_load_state("networkidle", timeout=15_000)

                url = page.url
                if "/login" in url:
                    # Still on /login = wrong creds or captcha.
                    body = (await page.content())[:4000]
                    err = "login failed"
                    if "captcha" in body.lower() or "challenge" in body.lower():
                        err = "captcha — Strava is challenging the login. Try manual cookie paste."
                    elif "incorrect" in body.lower() or "invalid" in body.lower():
                        err = "incorrect email or password"
                    return LoginResult(ok=False, error=err)

                # Extract cookies from the context.
                cookies = await context.cookies(_STRAVA)
                remember = next(
                    (c["value"] for c in cookies if c["name"] == "strava_remember_token"),
                    None,
                )
                sid = next(
                    (c["value"] for c in cookies if c["name"] == "_strava4_session"),
                    None,
                )
                if not remember:
                    return LoginResult(ok=False,
                                       error="no remember_token in response — Strava login flow changed?")

                # Pull identity from the dashboard HTML we already have.
                athlete_id = _extract_athlete_id(await page.content())
                athlete_name = _extract_athlete_name(await page.content())

                return LoginResult(
                    ok=True,
                    remember_token=remember,
                    sid_cookie=sid,
                    athlete_id=athlete_id,
                    athlete_name=athlete_name,
                )
            finally:
                await browser.close()
    except Exception as e:  # noqa: BLE001
        return LoginResult(ok=False, error=f"playwright error: {e}")

# Strava cookies you need from devtools → Application → Cookies → strava.com:
#   - strava_remember_token  (long-lived, months — the important one)
#   - _strava4_session       (short-lived session cookie; optional)
# Both ride in a single Cookie header per HTTP/1.1.


# ─── Cookie validation ──────────────────────────────────────────────

@dataclass
class CookieCheckResult:
    ok: bool
    athlete_id: int | None = None
    athlete_name: str | None = None
    error: str | None = None


async def check_cookie(remember_token: str, sid_cookie: str | None = None) -> CookieCheckResult:
    """Hit the athlete dashboard with the cookie and parse the user's
    identity out of the response. Returns ok=False if the cookie is
    expired / wrong / Strava is shielding behind Cloudflare."""
    headers = _headers(remember_token, sid_cookie)
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            r = await client.get(f"{_STRAVA}/athlete/training", headers=headers)
        if r.status_code == 302 or "Sign In" in r.text[:2000]:
            return CookieCheckResult(ok=False, error="cookie expired or invalid (redirected to login)")
        if r.status_code != 200:
            return CookieCheckResult(ok=False, error=f"unexpected HTTP {r.status_code}")
        # Parse the athlete id + name from inline <meta> tags Strava ships.
        # Robust enough across UI redesigns to not need a full HTML parser.
        athlete_id = _extract_athlete_id(r.text)
        athlete_name = _extract_athlete_name(r.text)
        return CookieCheckResult(ok=True, athlete_id=athlete_id, athlete_name=athlete_name)
    except httpx.RequestError as e:
        return CookieCheckResult(ok=False, error=f"request error: {e}")


def _extract_athlete_id(html: str) -> int | None:
    import re
    # Strava embeds <meta name="logged-in-athlete-id" content="...">
    m = re.search(r'logged-in-athlete-id"\s+content="(\d+)"', html)
    if m:
        return int(m.group(1))
    return None


def _extract_athlete_name(html: str) -> str | None:
    import re
    m = re.search(r'logged-in-athlete-name"\s+content="([^"]+)"', html)
    if m:
        return m.group(1)
    return None


# ─── Activity list discovery ───────────────────────────────────────

@dataclass
class ActivityStub:
    id: int
    name: str | None
    type: str | None
    start_at: datetime
    distance_m: float | None
    duration_s: int | None


async def list_recent_activities(
    remember_token: str,
    sid_cookie: str | None,
    since: datetime | None = None,
    max_pages: int = 20,
) -> list[ActivityStub]:
    """Page through /athlete/training_activities (JSON) newest-first and
    return stubs newer than `since`. Stops at the first page that contains
    only too-old activities or when max_pages is reached."""
    headers = _headers(remember_token, sid_cookie, json_accept=True)
    out: list[ActivityStub] = []
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        for page in range(1, max_pages + 1):
            r = await client.get(
                f"{_STRAVA}/athlete/training_activities",
                params={"page": page, "per_page": 50},
                headers=headers,
            )
            if r.status_code != 200:
                log.warning("training_activities page=%d returned %d", page, r.status_code)
                break
            try:
                payload = r.json()
            except Exception:
                log.warning("training_activities page=%d not JSON (cookie expired?)", page)
                break
            rows = payload.get("models") or payload if isinstance(payload, list) else []
            if not rows:
                break
            keep_paging = False
            for row in rows:
                stub = _row_to_stub(row)
                if stub is None:
                    continue
                if since is not None and stub.start_at <= since:
                    continue  # too old, skip but keep scanning page
                out.append(stub)
                keep_paging = True  # found at least one new activity → next page might have more
            if since is not None and not keep_paging:
                break
            if since is None and len(out) >= 50:
                break  # bulk path bounds by since_days, not raw count
    return out


def _row_to_stub(row: dict[str, Any]) -> ActivityStub | None:
    try:
        aid = int(row["id"])
        start = row.get("start_time") or row.get("start_date_local") or row.get("start_date")
        if start is None:
            return None
        if isinstance(start, str):
            # Strava returns ISO; tolerate trailing Z and missing offset.
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        else:
            return None
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        return ActivityStub(
            id=aid,
            name=row.get("name"),
            type=row.get("type") or row.get("activity_type"),
            start_at=start_dt,
            distance_m=row.get("distance_raw") or row.get("distance"),
            duration_s=row.get("elapsed_time_raw") or row.get("moving_time_raw"),
        )
    except (KeyError, ValueError, TypeError) as e:
        log.debug("training_activities row skipped: %s", e)
        return None


# ─── Original file download ─────────────────────────────────────────

async def download_activity_original(
    remember_token: str,
    sid_cookie: str | None,
    activity_id: int,
) -> bytes:
    """GET /activities/{id}/export_original → raw bytes.

    Returns whatever Avinox / the original recording device uploaded.
    Avinox uploads FIT. The caller decides how to parse based on the
    Content-Disposition header (or just probes the first bytes).
    Raises httpx.HTTPStatusError on non-2xx.
    """
    headers = _headers(remember_token, sid_cookie)
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        r = await client.get(
            f"{_STRAVA}/activities/{activity_id}/export_original",
            headers=headers,
        )
        r.raise_for_status()
        return r.content


# ─── FIT parsing ────────────────────────────────────────────────────

@dataclass
class ParsedFit:
    """Subset of FIT data we care about for an Activity row + HR stream."""
    start_at: datetime | None = None
    duration_s: int | None = None
    type_hint: str | None = None  # e.g. "cycling", "running" from FIT session.sport
    distance_m: float | None = None
    avg_hr: float | None = None
    max_hr: float | None = None
    polyline: str | None = None
    hr_samples: list[tuple[datetime, float]] = field(default_factory=list)


def parse_fit_bytes(blob: bytes) -> ParsedFit:
    """Pull session metadata + per-record HR / GPS from a FIT file.

    `record` messages have per-second HR + lat/lng + speed for the
    duration of the ride. `session` has rolled-up averages and totals.
    We prefer session values for avg/max HR + distance + duration so
    they match what Avinox / Strava show, falling back to record-stream
    aggregates if session is missing them.
    """
    result = ParsedFit()
    try:
        import io
        fit = FitFile(io.BytesIO(blob))
        fit.parse()
    except Exception as e:  # noqa: BLE001
        log.warning("FIT parse failed: %s", e)
        return result

    # Session message — one per ride, carries the totals.
    for sess in fit.get_messages("session"):
        d: dict[str, Any] = {f.name: f.value for f in sess if f.value is not None}
        result.start_at = _ensure_utc(d.get("start_time"))
        result.duration_s = _safe_int(d.get("total_elapsed_time") or d.get("total_timer_time"))
        result.distance_m = _safe_float(d.get("total_distance"))
        result.avg_hr = _safe_float(d.get("avg_heart_rate"))
        result.max_hr = _safe_float(d.get("max_heart_rate"))
        sport = d.get("sport")
        if sport:
            result.type_hint = str(sport).lower()
        break

    # Record messages — per-second telemetry. Pull HR + GPS.
    hr_samples: list[tuple[datetime, float]] = []
    gps_points: list[tuple[float, float]] = []
    for rec in fit.get_messages("record"):
        ts: datetime | None = None
        bpm: float | None = None
        lat: float | None = None
        lon: float | None = None
        for f in rec:
            if f.value is None:
                continue
            if f.name == "timestamp":
                ts = _ensure_utc(f.value)
            elif f.name == "heart_rate":
                bpm = float(f.value)
            elif f.name == "position_lat":
                lat = _semicircles_to_deg(f.value)
            elif f.name == "position_long":
                lon = _semicircles_to_deg(f.value)
        if ts is not None and bpm is not None and bpm > 30:
            hr_samples.append((ts, bpm))
        if lat is not None and lon is not None:
            gps_points.append((lat, lon))

    result.hr_samples = hr_samples
    if result.avg_hr is None and hr_samples:
        result.avg_hr = sum(b for _, b in hr_samples) / len(hr_samples)
    if result.max_hr is None and hr_samples:
        result.max_hr = max(b for _, b in hr_samples)
    if gps_points:
        result.polyline = _encode_polyline(gps_points)

    return result


def _ensure_utc(ts: Any) -> datetime | None:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
    return None


def _safe_int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _safe_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _semicircles_to_deg(sc: int) -> float:
    """FIT GPS is stored in semicircles. 2^31 semicircles = 180°."""
    return sc * (180.0 / (2 ** 31))


def _encode_polyline(points: list[tuple[float, float]]) -> str:
    """Google encoded polyline format (precision=5). Same shape Strava
    uses for `polyline` on Activity rows."""
    try:
        import polyline  # already a project dep
        return polyline.encode(points, precision=5)
    except Exception:  # noqa: BLE001
        return ""


# ─── Header builder ─────────────────────────────────────────────────

def _headers(
    remember_token: str,
    sid_cookie: str | None,
    json_accept: bool = False,
) -> dict[str, str]:
    cookies = [f"strava_remember_token={remember_token}"]
    if sid_cookie:
        cookies.append(f"_strava4_session={sid_cookie}")
    h = {
        "Cookie": "; ".join(cookies),
        "User-Agent": _UA,
        "Accept-Language": "en-US,en;q=0.9",
    }
    if json_accept:
        h["Accept"] = "application/json"
        h["X-Requested-With"] = "XMLHttpRequest"
    return h


# ─── DB ingest ──────────────────────────────────────────────────────

async def get_cookie_creds(db) -> models.StravaCookieCreds | None:
    """Read singleton row. Returns None when cookie hasn't been set."""
    from sqlalchemy import select
    result = await db.execute(
        select(models.StravaCookieCreds).where(models.StravaCookieCreds.id == 1)
    )
    return result.scalar_one_or_none()


async def upsert_activity_from_fit(
    db,
    stub: ActivityStub,
    parsed: ParsedFit,
) -> bool:
    """Upsert an Activity row from the FIT-parsed data and bulk-insert
    the per-second HR samples (source='strava_fit'). Returns True if
    the activity row was new or updated."""
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    start_at = parsed.start_at or stub.start_at
    duration_s = parsed.duration_s or stub.duration_s or 0
    distance_m = parsed.distance_m or stub.distance_m

    values = {
        "source": "strava",
        "source_id": str(stub.id),
        "type": (parsed.type_hint or stub.type or "ride").lower(),
        "name": stub.name,
        "start_at": start_at,
        "duration_s": duration_s,
        "distance_m": distance_m,
        "avg_hr": parsed.avg_hr,
        "max_hr": parsed.max_hr,
        "polyline": parsed.polyline or None,
    }
    stmt = pg_insert(models.Activity).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["source", "source_id"],
        set_={
            "type": values["type"],
            "name": values["name"],
            "start_at": values["start_at"],
            "duration_s": values["duration_s"],
            "distance_m": values["distance_m"],
            "avg_hr": values["avg_hr"],
            "max_hr": values["max_hr"],
            "polyline": values["polyline"],
        },
    )
    await db.execute(stmt)

    # HR samples — chest-strap is canonical for the ride window. The
    # vitals_heartrate PK is `time` alone, so we delete watch samples
    # in the window first to make room for the FIT stream. Cycling
    # HR from the wrist is unreliable (bouncing handlebars, optical
    # lag), so chest-strap winning is the right policy.
    if parsed.hr_samples:
        from sqlalchemy import delete
        first_ts = parsed.hr_samples[0][0]
        last_ts = parsed.hr_samples[-1][0]
        await db.execute(
            delete(models.HeartRate)
            .where(models.HeartRate.time >= first_ts)
            .where(models.HeartRate.time <= last_ts)
        )
        hr_values = [
            {"time": ts, "bpm": bpm, "source": "strava_fit"}
            for ts, bpm in parsed.hr_samples
        ]
        # On second sync of the same activity we just removed the
        # prior strava_fit rows in the delete above; insert is safe.
        await db.execute(pg_insert(models.HeartRate).values(hr_values))

    return True
