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

import json
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

class CookieExpired(Exception):
    """Raised when the Strava cookie session is confirmed dead (401 /
    login-redirect) and could NOT be self-healed via auto-login. The
    sync runner catches this and persists it as a user-facing
    `last_error` instead of silently reporting a clean 0-activity run —
    which is what let a dead cookie masquerade as 'up to date' for
    weeks (the ride never came in, but the UI stayed green)."""


@dataclass
class CookieCheckResult:
    ok: bool
    athlete_id: int | None = None
    athlete_name: str | None = None
    error: str | None = None


def parse_cookie_blob(blob: str | None) -> tuple[str | None, str | None]:
    """Extract (strava_remember_token, _strava4_session) from a pasted
    cookie export in any common format, so the user can paste ONE blob
    from a cookie-export extension (Cookie-Editor / EditThisCookie) instead
    of hunting each value in DevTools and matching it to the right field.

    Handles:
      - JSON array/object (Cookie-Editor, EditThisCookie): [{"name":…,"value":…}]
      - Netscape cookies.txt: tab-separated, name in col 6, value col 7
      - Header/`document.cookie` string: "name=value; name2=value2"

    Returns (None, None) for anything it can't recognise; the caller keeps
    whatever it does find. HttpOnly values are fine — the extension reads
    them via the browser cookie API, unlike a document.cookie bookmarklet."""
    if not blob or not blob.strip():
        return None, None
    text = blob.strip()
    remember: str | None = None
    sid: str | None = None

    def _take(name: str, val: str | None) -> None:
        nonlocal remember, sid
        if not val:
            return
        if name == "strava_remember_token":
            remember = val
        elif name == "_strava4_session":
            sid = val

    # 1) JSON export.
    if text[:1] in "[{":
        try:
            data = json.loads(text)
            items = data if isinstance(data, list) else (
                data.get("cookies", []) if isinstance(data, dict) else [])
            for c in items:
                if isinstance(c, dict):
                    _take(str(c.get("name") or c.get("Name") or ""),
                          c.get("value") or c.get("Value"))
            if remember or sid:
                return remember, sid
        except (ValueError, TypeError):
            pass  # fall through to the text formats

    # 2) Netscape cookies.txt (has tabs).
    if "\t" in text:
        for line in text.splitlines():
            parts = line.split("\t")
            if len(parts) >= 7 and not line.startswith("#"):
                _take(parts[5].strip(), parts[6].strip())
        if remember or sid:
            return remember, sid

    # 3) Header / document.cookie string.
    for pair in text.replace("\n", ";").split(";"):
        if "=" in pair:
            name, _, val = pair.strip().partition("=")
            _take(name.strip(), val.strip())
    return remember, sid


async def check_cookie(
    remember_token: str | None,
    sid_cookie: str | None = None,
) -> CookieCheckResult:
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
    remember_token: str | None,
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
            # NB: the response is a dict {"models": [...], "page", ...};
            # a bare list is tolerated for robustness. The old one-liner
            # `payload.get("models") or payload if isinstance(payload, list)
            # else []` parsed as `(... ) if isinstance(payload, list) else []`
            # — always [] for the dict Strava actually returns, so the
            # cookie sync never imported anything (fixed v0.7.284).
            if isinstance(payload, dict):
                rows = payload.get("models") or []
            elif isinstance(payload, list):
                rows = payload
            else:
                rows = []
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
            # training_activities rows carry the canonical Strava type in
            # `sport_type` (e.g. "EBikeRide") — `type`/`activity_type` are
            # null there. Lowercased it matches the OAuth-era convention
            # ("ebikeride") that cardio analytics / icons / map colors key on.
            type=row.get("type") or row.get("activity_type") or row.get("sport_type"),
            start_at=start_dt,
            distance_m=row.get("distance_raw") or row.get("distance"),
            duration_s=row.get("elapsed_time_raw") or row.get("moving_time_raw"),
        )
    except (KeyError, ValueError, TypeError) as e:
        log.debug("training_activities row skipped: %s", e)
        return None


# ─── Original file download ─────────────────────────────────────────

async def download_activity_original(
    remember_token: str | None,
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
            # Records written before GPS lock carry 0 semicircles →
            # (0.0, 0.0) "Null Island". One bad leading point becomes
            # the start marker and stretches the route map across the
            # Atlantic. Drop those + anything out of range.
            if (lat, lon) != (0.0, 0.0) and abs(lat) <= 90 and abs(lon) <= 180:
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
    remember_token: str | None,
    sid_cookie: str | None,
    json_accept: bool = False,
) -> dict[str, str]:
    # SCS-8: either cookie alone is enough. OTC accounts don't get
    # strava_remember_token, so we accept _strava4_session-only.
    cookies: list[str] = []
    if remember_token:
        cookies.append(f"strava_remember_token={remember_token}")
    if sid_cookie:
        cookies.append(f"_strava4_session={sid_cookie}")
    if not cookies:
        raise ValueError("at least one of remember_token / sid_cookie required")
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
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    start_at = parsed.start_at or stub.start_at
    duration_s = parsed.duration_s or stub.duration_s or 0
    distance_m = parsed.distance_m or stub.distance_m

    values = {
        "source": "strava",
        "source_id": str(stub.id),
        # Strava's own type wins over the FIT sport hint — FIT says
        # "e_biking" where every downstream consumer expects "ebikeride".
        "type": (stub.type or parsed.type_hint or "ride").lower(),
        "name": stub.name,
        "start_at": start_at,
        "duration_s": duration_s,
        "distance_m": distance_m,
        "avg_hr": parsed.avg_hr,
        "max_hr": parsed.max_hr,
        "polyline": parsed.polyline or None,
    }
    # TD-5 — one sink for every Activity write.
    #
    # This used to be a hand-rolled on_conflict_do_update that wrote avg_hr,
    # max_hr and polyline unconditionally. parse_fit_bytes returns an empty
    # ParsedFit and logs a warning rather than raising, so re-syncing an
    # activity whose FIT file failed to parse silently nulled the heart rate
    # and GPS already stored against it. The sink skips None on
    # provider-derived columns, so a poorer sync can no longer erase a
    # richer one.
    #
    # It also carries the two ingest side-effects this path never had:
    # cardio-day auto-completion (which was wired only to the retired OAuth
    # sync, so it had been dead for every ride the user actually syncs) and
    # trail auto-linking (previously only reachable from the manual
    # /trails/link-activities button).
    from .activity_sink import upsert_activity

    await upsert_activity(db, values)

    # HR samples — chest-strap is canonical for the ride window. The
    # vitals_heartrate PK is `time` alone, so we delete watch samples
    # in the window first to make room for the FIT stream. Cycling
    # HR from the wrist is unreliable (bouncing handlebars, optical
    # lag), so chest-strap winning is the right policy.
    if parsed.hr_samples:
        from sqlalchemy import delete

        # FIT records can repeat a timestamp (pause/resume, >1 record
        # per second) and the PK is `time` alone — de-dupe keeping the
        # last sample per ts or the batch insert conflicts with itself.
        by_ts = {ts: bpm for ts, bpm in parsed.hr_samples}
        hr_values = [
            {"time": ts, "bpm": bpm, "source": "strava_fit"}
            for ts, bpm in sorted(by_ts.items())
        ]
        first_ts = hr_values[0]["time"]
        last_ts = hr_values[-1]["time"]
        span_s = (last_ts - first_ts).total_seconds()

        # Only clear the window when the FIT stream is dense enough to
        # actually replace what is being removed.
        #
        # The delete takes out EVERY heart-rate row in the ride window
        # regardless of source, so that the chest strap wins over the
        # wrist — a defensible policy for cycling, where optical HR is
        # unreliable on bouncing handlebars. But a truncated or sparse
        # FIT (a dropped strap, a corrupt download) can span two hours
        # with a handful of samples, and the delete would then destroy
        # two hours of good watch data to install five points.
        #
        # Requiring at least one sample every 30 seconds on average
        # keeps the intended behaviour for a real ride while refusing
        # the trade when there is nothing to trade with.
        dense_enough = span_s <= 0 or (len(hr_values) / span_s) >= (1 / 30)
        if dense_enough:
            await db.execute(
                delete(models.HeartRate)
                .where(models.HeartRate.time >= first_ts)
                .where(models.HeartRate.time <= last_ts)
            )
        else:
            log.warning(
                "FIT HR stream too sparse to replace watch data "
                "(%d samples over %.0f min); inserting alongside instead",
                len(hr_values), span_s / 60,
            )

        # Chunked. asyncpg refuses more than 32,767 bind parameters and
        # these rows bind three each, so a single statement caps at
        # ~10,900 samples — about three hours at 1 Hz. The longest ride
        # in this database is already 2h22m, so a longer one would have
        # failed the whole import with an asyncpg error rather than
        # dropping a few points.
        chunk_size = 10_000
        for i in range(0, len(hr_values), chunk_size):
            chunk = hr_values[i:i + chunk_size]
            ins = pg_insert(models.HeartRate).values(chunk)
            await db.execute(ins.on_conflict_do_update(
                index_elements=["time"],
                set_={"bpm": ins.excluded.bpm, "source": ins.excluded.source},
            ))

    return True
