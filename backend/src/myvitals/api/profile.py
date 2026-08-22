"""User profile + derived metrics (age-adjusted max HR, HR zones, BMI)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..analytics import cardio, tiles
from ..auth import require_any
from ..db import models
from ..db.session import get_session

router = APIRouter(prefix="/profile", dependencies=[Depends(require_any)])


class ProfileIn(BaseModel):
    birth_date: date | None = None
    sex: str | None = None  # "male" | "female" | "other"
    height_cm: float | None = None
    weight_goal_kg: float | None = None
    fasting_target_hours_per_week: float | None = None
    resting_hr_baseline: float | None = None
    max_hr: float | None = None
    activity_level: str | None = None  # "sedentary"|"light"|"moderate"|"active"|"athlete"
    extra: dict[str, Any] | None = None
    home_latitude: float | None = None
    home_longitude: float | None = None


def _age_years(birth: date | None) -> int | None:
    if not birth:
        return None
    today = date.today()
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def _hr_zones(max_hr: float) -> list[dict[str, Any]]:
    """The 5-zone split, derived from the shared bounds in analytics/cardio.

    This used to be a second hand-written table, and it disagreed with the
    one the zone analytics use: it started Z1 at 50% of max where cardio.py
    starts it at 0%, so the profile screen and every zone chart in the app
    were describing different zones under the same names.
    """
    return [
        {
            "zone": i + 1,
            "label": spec["label"],
            "low": spec["lo_bpm"],
            "high": spec["hi_bpm"] if spec["hi_bpm"] is not None else round(max_hr),
        }
        for i, spec in enumerate(cardio.zone_bounds(max_hr))
    ]


async def _auto_rhr_baseline(db: AsyncSession) -> float | None:
    """Recent rolling average of daily_summary.resting_hr — best objective
    estimate of the user's current resting HR baseline. Used when the
    profile doesn't override with a manual value.

    Walks back from the most recent day with RHR data (instead of always
    today minus 30) so a brief gap in syncing doesn't drop the count to 0
    or pull in stale readings from years ago when historical imports
    happened to land in the window."""
    latest = (await db.execute(
        select(func.max(models.DailySummary.date))
        .where(models.DailySummary.resting_hr.is_not(None))
    )).scalar()
    if latest is None:
        return None
    cutoff = latest - timedelta(days=14)
    val = (await db.execute(
        select(func.avg(models.DailySummary.resting_hr))
        .where(models.DailySummary.date >= cutoff)
        .where(models.DailySummary.date <= latest)
        .where(models.DailySummary.resting_hr.is_not(None))
    )).scalar()
    return float(val) if val is not None else None


async def _profile_dict(
    db: AsyncSession, p: models.UserProfile | None,
) -> dict[str, Any]:
    auto_rhr = await _auto_rhr_baseline(db)
    if p is None:
        return {
            "id": 1, "birth_date": None, "sex": None, "height_cm": None,
            "weight_goal_kg": None, "resting_hr_baseline": None, "max_hr": None,
            "activity_level": None, "extra": None,
            "home_latitude": None, "home_longitude": None,
            "updated_at": None,
            "derived": {"resting_hr_baseline_auto": auto_rhr},
        }
    age = _age_years(p.birth_date)
    derived: dict[str, Any] = {"age": age, "resting_hr_baseline_auto": auto_rhr}
    if age is not None:
        # Tanaka 2001: max HR ≈ 208 - 0.7 × age (more accurate than 220-age).
        derived["max_hr_estimated"] = round(208 - 0.7 * age)
    # An explicitly measured maximum always wins over the age estimate, and
    # the zones follow whichever one is actually in use -- otherwise the
    # profile screen shows boundaries that no chart in the app agrees with.
    effective = p.max_hr or derived.get("max_hr_estimated")
    if effective:
        derived["max_hr_effective"] = round(effective)
        derived["max_hr_source"] = "profile" if p.max_hr else "estimated"
        derived["hr_zones"] = _hr_zones(float(effective))
    if p.height_cm and p.weight_goal_kg:
        h_m = p.height_cm / 100
        derived["bmi_at_goal"] = round(p.weight_goal_kg / (h_m * h_m), 1)
    return {
        "id": p.id,
        "birth_date": p.birth_date.isoformat() if p.birth_date else None,
        "sex": p.sex,
        "height_cm": p.height_cm,
        "weight_goal_kg": p.weight_goal_kg,
        "sleep_target_h": p.sleep_target_h,
        "fasting_target_hours_per_week": p.fasting_target_hours_per_week,
        "resting_hr_baseline": p.resting_hr_baseline,
        "max_hr": p.max_hr,
        "activity_level": p.activity_level,
        "extra": p.extra,
        "home_latitude": p.home_latitude,
        "home_longitude": p.home_longitude,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        "derived": derived,
    }


@router.get("")
async def get_profile(db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    p = await db.get(models.UserProfile, 1)
    return await _profile_dict(db, p)


@router.put("")
async def put_profile(
    body: ProfileIn,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if body.sex is not None and body.sex not in {"male", "female", "other"}:
        raise HTTPException(status_code=400, detail="sex must be male|female|other")
    p = await db.get(models.UserProfile, 1)
    now = datetime.now(timezone.utc)
    if p is None:
        p = models.UserProfile(id=1, updated_at=now)
        db.add(p)
    p.birth_date = body.birth_date
    p.sex = body.sex
    p.height_cm = body.height_cm
    # Detect goal-relevant changes before applying so we can propagate
    # to any active AiGoal of the matching kind (GOALS-1 bidirectional
    # sync — see api/ai.py:_profile_target_for_kind).
    sync_pairs: list[tuple[str, float | None]] = []
    if body.weight_goal_kg != p.weight_goal_kg:
        sync_pairs.append(("weight", body.weight_goal_kg))
    new_sleep = (body.extra or {}).get("sleep_target_h") if body.extra else None
    if new_sleep != p.sleep_target_h:
        sync_pairs.append(("sleep", new_sleep))
    new_steps = (body.extra or {}).get("steps_goal") if body.extra else None
    cur_steps = (p.extra or {}).get("steps_goal") if p.extra else None
    if new_steps != cur_steps:
        sync_pairs.append(("steps", float(new_steps) if new_steps is not None else None))
    if body.fasting_target_hours_per_week != p.fasting_target_hours_per_week:
        sync_pairs.append(("fast_streak", body.fasting_target_hours_per_week))

    p.weight_goal_kg = body.weight_goal_kg
    p.fasting_target_hours_per_week = body.fasting_target_hours_per_week
    p.resting_hr_baseline = body.resting_hr_baseline
    p.max_hr = body.max_hr
    p.activity_level = body.activity_level
    # Preserve keys the caller does not model.
    #
    # This used to be `p.extra = body.extra` — a wholesale replace. The
    # phone's ProfileExtra models six keys, so toggling the workout
    # reminder there silently deleted every other key in `extra`,
    # including the `display` block (units / time format / theme) and
    # `fasting_prefs`. The phone's saveReminderPrefs already re-copies
    # `steps_goal`, `sleep_goal_h`, `vitals_order` and `vitals_hidden` by
    # hand precisely because of this, which is a workaround for a server
    # bug rather than a fix.
    #
    # Merging here means a client can send only what it knows about, and
    # is what makes the scoped preference endpoints (/tile-prefs,
    # /display-prefs) safe to coexist with this one.
    #
    # The protocol this implies, stated out loud because it is the part a
    # client can get wrong: an ABSENT key means "leave it alone", and an
    # explicit NULL means "clear it".
    #
    # Settings.vue used to clear a goal with `delete extra.steps_goal`,
    # which under a merge would mean "keep" and would silently stop the
    # clear from working. It now sends an explicit null instead. Nulls are
    # therefore written through rather than skipped — and every reader
    # already uses `.get(...)`, so a stored null and an absent key are
    # indistinguishable downstream.
    if body.extra is not None:
        merged = dict(p.extra or {})
        merged.update(body.extra)
        p.extra = merged
    p.home_latitude = body.home_latitude
    p.home_longitude = body.home_longitude
    if new_sleep is not None:
        try:
            p.sleep_target_h = float(new_sleep)
        except (TypeError, ValueError):
            pass
    p.updated_at = now

    # Propagate to active goals of matching kind.
    for kind, value in sync_pairs:
        rows = (await db.execute(
            select(models.AiGoal)
            .where(models.AiGoal.kind == kind)
            .where(models.AiGoal.ended_at.is_(None))
        )).scalars().all()
        for g in rows:
            g.target_value = value

    await db.commit()
    await db.refresh(p)
    return await _profile_dict(db, p)


class TilePrefsIn(BaseModel):
    """Which Key-metrics tiles show, and in what order.

    Deliberately a separate endpoint from ``PUT /profile`` rather than
    another field on it. ``put_profile`` assigns ``p.extra = body.extra``
    wholesale, so any client that PUTs a profile without carrying the tile
    keys forward erases them — and the phone's Settings screen does
    exactly that for every field it does not know about. A scoped write
    that touches only these two keys cannot lose a preference it has never
    heard of.
    """

    order: list[str]
    hidden: list[str] = []


def _tile_prefs_payload(order: list[str], hidden: list[str]) -> dict[str, Any]:
    reconciled_order, reconciled_hidden = tiles.reconcile_tile_prefs(order, hidden)
    return {
        "order": reconciled_order,
        "hidden": reconciled_hidden,
        # The editor renders from this rather than keeping its own copy of
        # the label strings — one of the four client-side maps this
        # endpoint exists to retire.
        "available": [
            {
                "key": k,
                "label": tiles.TILE_LABELS[k],
                "group": tiles.TILE_GROUPS.get(k, "Other"),
                "hidden": k in reconciled_hidden,
            }
            for k in reconciled_order
        ],
        "group_order": tiles.GROUP_ORDER,
    }


# ── DISP-1: display preferences ──────────────────────────────────────
#
# Units, time format and theme were localStorage-only on the web, and the
# phone had no preference at all — it hardcoded `/ 1609.34` in twelve
# places across eight files (with two different values for the same
# constant, 1609.34 and 1609.344). Clearing browser data reset the web;
# nothing could change the phone.
#
# These live in `user_profile.extra` rather than getting columns: `extra`
# is free-form JSON, so adding a preference later needs no migration.
DISPLAY_DEFAULTS: dict[str, str] = {
    "units": "imperial",
    "time_format": "auto",
    "theme": "neon",
}

DISPLAY_ALLOWED: dict[str, set[str]] = {
    "units": {"metric", "imperial"},
    "time_format": {"auto", "12h", "24h"},
    # "refined" was retired in v0.7.366 but may still be in a client's
    # localStorage; it is accepted here and folded to "neon" so an old
    # value round-trips instead of 400ing on every save.
    "theme": {"dark", "light", "auto", "neon", "refined"},
}


class DisplayPrefsIn(BaseModel):
    units: str | None = None
    time_format: str | None = None
    theme: str | None = None


def _display_payload(extra: dict[str, Any]) -> dict[str, Any]:
    stored = (extra.get("display") or {}) if isinstance(extra, dict) else {}
    out = dict(DISPLAY_DEFAULTS)
    for k, allowed in DISPLAY_ALLOWED.items():
        v = stored.get(k)
        if isinstance(v, str) and v in allowed:
            out[k] = "neon" if (k == "theme" and v == "refined") else v
    return out


@router.get("/display-prefs")
async def get_display_prefs(
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Units / time format / theme, with defaults filled in.

    Always returns every key, so a client never has to know the default
    for a preference it has not seen before.
    """
    p = await db.get(models.UserProfile, 1)
    return _display_payload((p.extra if p and p.extra else {}) or {})


@router.put("/display-prefs")
async def put_display_prefs(
    body: DisplayPrefsIn,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Scoped, partial write — same reasoning as /tile-prefs.

    ``PUT /profile`` replaces ``extra`` wholesale, so routing display
    preferences through it would let any client that does not carry them
    forward erase them. Omitted fields here keep their stored value rather
    than reverting to the default, so a client that only knows about
    ``units`` cannot clobber a ``theme`` set from the other surface.
    """
    incoming = {
        k: v for k, v in
        (("units", body.units), ("time_format", body.time_format), ("theme", body.theme))
        if v is not None
    }
    for k, v in incoming.items():
        if v not in DISPLAY_ALLOWED[k]:
            raise HTTPException(
                status_code=400,
                detail=f"{k} must be one of {sorted(DISPLAY_ALLOWED[k])}",
            )

    p = await db.get(models.UserProfile, 1)
    now = datetime.now(timezone.utc)
    if p is None:
        p = models.UserProfile(id=1, updated_at=now)
        db.add(p)

    # Copy-then-reassign: SQLAlchemy does not track in-place mutation of a
    # JSON column, so mutating p.extra directly would commit nothing.
    extra = dict(p.extra or {})
    display = dict(extra.get("display") or {})
    display.update(incoming)
    extra["display"] = display
    p.extra = extra
    p.updated_at = now
    await db.commit()
    return _display_payload(extra)


@router.get("/tile-prefs")
async def get_tile_prefs(db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Current tile order and visibility, reconciled against today's tiles.

    Always returns the full current key set, so a client can render the
    editor without knowing which metrics exist.
    """
    p = await db.get(models.UserProfile, 1)
    extra = (p.extra if p and p.extra else {}) or {}
    return _tile_prefs_payload(
        list(extra.get("vitals_order") or []),
        list(extra.get("vitals_hidden") or []),
    )


@router.put("/tile-prefs")
async def put_tile_prefs(
    body: TilePrefsIn,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Scoped write — merges into ``extra`` rather than replacing it."""
    order, hidden = tiles.reconcile_tile_prefs(body.order, body.hidden)

    # Refuse an all-hidden layout. The Key metrics section renders only
    # when it has something to show, so hiding everything makes the
    # section vanish along with the Edit button that leads back here —
    # the user would have no route to undo it.
    if len(hidden) >= len(order):
        raise HTTPException(
            status_code=400,
            detail="At least one metric must stay visible.",
        )

    p = await db.get(models.UserProfile, 1)
    now = datetime.now(timezone.utc)
    if p is None:
        p = models.UserProfile(id=1, updated_at=now)
        db.add(p)

    # Copy-then-reassign: SQLAlchemy does not track in-place mutation of a
    # JSON column, so mutating p.extra directly would commit nothing.
    extra = dict(p.extra or {})
    extra["vitals_order"] = order
    extra["vitals_hidden"] = hidden
    p.extra = extra
    p.updated_at = now
    await db.commit()
    return _tile_prefs_payload(order, hidden)


class GeocodeIn(BaseModel):
    query: str


@router.post("/geocode")
async def geocode_home(body: GeocodeIn) -> dict[str, Any]:
    """Resolve a freeform address / Google Maps URL / lat,lng pair to
    coordinates. Used by the Settings 'Home location' field so the user
    can paste anything and get back a lat/lng to save.

    Order of attempts: short-URL redirect → @lat,lng pattern → bare
    lat,lng → Nominatim. Nominatim is rate-limited (1 req/sec per their
    fair-use policy) and requires a User-Agent — fine for the
    handful-of-times-a-year a home setting changes.
    """
    import re
    import httpx
    q = (body.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="empty query")

    # Expand a Google Maps short URL (maps.app.goo.gl/...) by following
    # its redirect to the long form, where coords are embedded.
    if "maps.app.goo.gl" in q or "goo.gl/maps" in q:
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
                r = await c.head(q)
                q = str(r.url)
        except Exception:  # noqa: BLE001 — short URL is best-effort
            pass

    # Google Maps long URL with @lat,lng
    m = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", q)
    if m:
        return {
            "latitude": float(m.group(1)),
            "longitude": float(m.group(2)),
            "source": "google_maps_url",
        }

    # q=lat,lng or ?q=lat,lng style
    m = re.search(r"[?&]q=(-?\d+\.\d+),(-?\d+\.\d+)", q)
    if m:
        return {
            "latitude": float(m.group(1)),
            "longitude": float(m.group(2)),
            "source": "google_maps_url",
        }

    # Bare "lat,lng" pair
    m = re.match(r"^\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)\s*$", q)
    if m:
        return {
            "latitude": float(m.group(1)),
            "longitude": float(m.group(2)),
            "source": "pair",
        }

    # Fall back to Nominatim address geocoding
    try:
        async with httpx.AsyncClient(timeout=15.0,
            headers={"User-Agent": "myvitals/1.0 (self-hosted; admin@local)"}) as c:
            r = await c.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": q, "format": "json", "limit": 1},
            )
            r.raise_for_status()
            results = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"geocode upstream failed: {e}")
    if not results:
        raise HTTPException(status_code=404, detail="No match for that address.")
    return {
        "latitude": float(results[0]["lat"]),
        "longitude": float(results[0]["lon"]),
        "display_name": results[0].get("display_name"),
        "source": "nominatim",
    }
