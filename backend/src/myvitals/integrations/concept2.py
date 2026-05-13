"""Concept2 Logbook → activities pipeline.

Pulls rowing (and ski-/bike-erg, if logged) sessions from
log.concept2.com via the user's stored personal token. Each result
becomes a row in the `activities` table with `source='concept2'`
and the Concept2 result id as `source_id`, slotting into the same
machinery (Activities feed, HR chart overlay) Strava already uses.

Each upserted activity also (a) writes per-interval HR samples into
`vitals_heartrate` so the HR-during-workout + HR-zone charts have
data for the row window, and (b) triggers cardio-day auto-complete
on a matching planned `strength_workouts` row for that local date.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import models
from .cardio_completion import maybe_complete_cardio_day

LOGBOOK_BASE = "https://log.concept2.com"
PER_PAGE = 250  # Concept2 max
HEADERS_ACCEPT = {"Accept": "application/vnd.c2logbook.v1+json"}

log = logging.getLogger(__name__)


async def list_results(
    token: str,
    *,
    from_date: datetime | None = None,
    page: int = 1,
    type_filter: str | None = None,
) -> dict[str, Any]:
    """Single page of /api/users/me/results. Caller handles pagination."""
    params: dict[str, Any] = {"page": page, "per_page": PER_PAGE}
    if from_date is not None:
        params["from"] = from_date.date().isoformat()
    if type_filter is not None:
        params["type"] = type_filter
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            f"{LOGBOOK_BASE}/api/users/me/results",
            headers={"Authorization": f"Bearer {token}", **HEADERS_ACCEPT},
            params=params,
        )
    r.raise_for_status()
    return r.json()


def _coerce_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        # Concept2 returns ISO with timezone offset, e.g. 2024-08-12T07:14:23+00:00
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def map_result(result: dict[str, Any]) -> dict[str, Any] | None:
    """Translate one Concept2 result row to Activity-table kwargs.
    Returns None when essential fields are missing (no time / no date)."""
    rid = result.get("id")
    if rid is None:
        return None
    start_at = _coerce_dt(result.get("date"))
    time_tenths = result.get("time")
    if start_at is None or time_tenths is None:
        return None

    hr = result.get("heart_rate") or {}
    # Concept2's root-level heart_rate.{min,max,recovery} are often 0 even
    # when the intervals each carry valid per-interval HR (their UI shows
    # those fine). Roll up across intervals so the activity row has true
    # max — falls back to the root value if intervals are empty.
    intervals = (result.get("workout") or {}).get("intervals") or []
    interval_max = max(
        (
            (iv.get("heart_rate") or {}).get("max") or 0
            for iv in intervals
            if isinstance(iv, dict)
        ),
        default=0,
    )
    interval_avg_vals = [
        (iv.get("heart_rate") or {}).get("average")
        for iv in intervals
        if isinstance(iv, dict)
        and (iv.get("heart_rate") or {}).get("average")
    ]
    distance_m = result.get("distance")
    duration_s = int(time_tenths) // 10

    # Concept2 reports power as "watt_minutes" — total work over the
    # session. Average watts ≈ watt_minutes / minutes.
    avg_power: float | None = None
    wm = result.get("watt_minutes")
    if wm and duration_s > 0:
        avg_power = float(wm) * 60.0 / duration_s

    # Type comes back lowercase: rower / skierg / bikeerg / dyno / etc.
    typ = (result.get("type") or "rower").lower()

    workout = result.get("workout") or {}
    # Try the user-set name inside workout, then workout.type, then the
    # root-level workout_type field (where Concept2 actually puts the
    # template name like "VariableInterval" / "JustRow_Time"). If all
    # three are empty, synthesize from duration + distance so the UI
    # never shows "(untitled)".
    explicit = (
        (workout.get("name") or workout.get("type") or result.get("workout_type") or "")
        .strip()
    )
    if explicit:
        if duration_s and distance_m:
            mm, ss = divmod(duration_s, 60)
            name: str | None = f"{explicit} · {mm}:{ss:02d} / {int(distance_m)}m"
        else:
            name = explicit
    elif duration_s and distance_m:
        mm, ss = divmod(duration_s, 60)
        name = f"Row · {mm}:{ss:02d} / {int(distance_m)}m"
    else:
        name = None

    # Compose a one-line note with the things a rower actually wants
    # to glance at (drag, stroke rate, 500m split).
    parts: list[str] = []
    if (sr := result.get("stroke_rate")):
        parts.append(f"{sr} spm")
    if (df := result.get("drag_factor")):
        parts.append(f"DF {df}")
    if distance_m and duration_s:
        # 500m split = (duration / distance) * 500 (in seconds)
        split_s = duration_s * 500 / distance_m
        m, s = divmod(split_s, 60)
        parts.append(f"{int(m)}:{s:04.1f} /500m")
    notes = " · ".join(parts) if parts else None

    return {
        "source": "concept2",
        "source_id": str(rid),
        "type": typ,
        "name": name,
        "start_at": start_at,
        "duration_s": duration_s,
        "distance_m": float(distance_m) if distance_m else None,
        "avg_hr": (
            float(hr.get("average")) if hr.get("average")
            else (float(sum(interval_avg_vals) / len(interval_avg_vals))
                  if interval_avg_vals else None)
        ),
        "max_hr": (
            float(hr.get("max")) if hr.get("max")
            else (float(interval_max) if interval_max else None)
        ),
        "avg_power_w": avg_power,
        "kcal": float(result.get("calories")) if result.get("calories") else None,
        "notes": notes,
        "raw": result,
    }


async def write_interval_hr(
    db: AsyncSession,
    raw: dict[str, Any],
    start_at: datetime,
) -> int:
    """Emit per-interval HR samples to vitals_heartrate so the HR chart
    has coverage for the workout window.

    Three samples per interval (start=min, mid=average, end=ending) — a
    typical 5-interval row produces ~15 rows. vitals_heartrate's PK is
    (time) only, so collisions with HC writes are resolved with
    ON CONFLICT DO NOTHING (HC wins). Source tagged 'concept2' for
    downstream per-source dedupe.
    """
    intervals = (raw.get("workout") or {}).get("intervals") or []
    if not intervals:
        return 0
    rows: list[dict[str, Any]] = []
    t = start_at
    for iv in intervals:
        if not isinstance(iv, dict):
            continue
        hr = iv.get("heart_rate") or {}
        dur_s = (iv.get("time") or 0) / 10
        if dur_s <= 0:
            continue
        for offset_s, bpm in (
            (0.0,         hr.get("min")),
            (dur_s / 2,   hr.get("average")),
            (dur_s,       hr.get("ending")),
        ):
            if bpm and bpm > 0:
                rows.append({
                    "time": t + timedelta(seconds=offset_s),
                    "bpm": float(bpm),
                    "source": "concept2",
                })
        t = t + timedelta(seconds=dur_s + (iv.get("rest_time") or 0) / 10)
    if not rows:
        return 0
    stmt = (
        pg_insert(models.HeartRate)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["time"])
    )
    await db.execute(stmt)
    return len(rows)


async def sync_results(
    db: AsyncSession,
    *,
    cred: models.Concept2Credentials,
    type_filter: str | None = "rower",
    incremental: bool = True,
) -> int:
    """Pull all results since `cred.last_sync_at` (or all-time on first
    run / when `incremental=False`) and upsert into Activity. Returns
    the number of rows written."""
    from_date = cred.last_sync_at if incremental else None
    page = 1
    upserted = 0
    while True:
        body = await list_results(
            cred.access_token,
            from_date=from_date,
            page=page,
            type_filter=type_filter,
        )
        items = body.get("data") or []
        if not items:
            break

        for raw in items:
            mapped = map_result(raw)
            if mapped is None:
                continue
            existing = await db.get(
                models.Activity, (mapped["source"], mapped["source_id"]),
            )
            if existing is None:
                db.add(models.Activity(**mapped))
            else:
                for k, v in mapped.items():
                    if k in ("source", "source_id"):
                        continue
                    setattr(existing, k, v)
            upserted += 1
            await write_interval_hr(db, raw, mapped["start_at"])
            await maybe_complete_cardio_day(
                db,
                source=mapped["source"],
                source_id=mapped["source_id"],
                activity_type=mapped["type"],
                start_at=mapped["start_at"],
                duration_s=mapped["duration_s"],
            )

        meta = body.get("meta") or {}
        pagination = meta.get("pagination") or {}
        # Concept2 ignores per_page > 50. Drive the loop off
        # current_page / total_pages — the link object the API ships isn't
        # always shaped consistently across calls.
        current = pagination.get("current_page") or page
        total_pages = pagination.get("total_pages") or 1
        if current >= total_pages:
            break
        page = current + 1

    cred.last_sync_at = datetime.now(timezone.utc)
    await db.commit()
    log.info("Concept2 sync done: %d results upserted (page=%d)", upserted, page)
    return upserted
