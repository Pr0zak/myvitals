"""Avinox e-bike integration — ride ingestion, sync, and telemetry storage.

Avinox e-bike rides (from the Avinox server) replace Strava as the primary
ride source. They carry rich e-bike telemetry not available from Strava:
motor assistance power, rider power, pedaling cadence, battery consumption,
odometer, assist levels, drive unit temperature, and per-second GPS tracks.

When an Avinox ride is ingested:
1. It is upserted through `activity_sink.upsert_activity` with source='avinox'.
2. If an overlapping Strava activity exists for the same ride, user-owned
   metadata (notes, tags, trail links) are carried across and the old Strava
   duplicate is retired.
3. Health Connect promotions are reconciled away (reconcile=True in the sink).
4. Heart rate series samples are stored in `vitals_heartrate` with source='avinox'.
5. Cardio-day auto-completion and trail auto-linking run via the sink.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import polyline as _polyline_lib
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import models
from . import activity_sink

log = logging.getLogger(__name__)


def _ensure_utc(dt: Any) -> datetime | None:
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            parsed = datetime.fromisoformat(dt.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    if isinstance(dt, datetime):
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    if isinstance(dt, (int, float)):
        return datetime.fromtimestamp(dt, timezone.utc)
    return None


async def get_or_create_config(db: AsyncSession) -> models.AvinoxConfig:
    cfg = await db.get(models.AvinoxConfig, 1)
    if cfg is None:
        cfg = models.AvinoxConfig(
            id=1,
            server_url=settings.avinox_url or "http://avinox.lan:8000",
            query_token=settings.avinox_token or "",
            webhook_secret=secrets.token_urlsafe(32),
            auto_sync_enabled=True,
        )
        db.add(cfg)
        await db.flush()
    elif not cfg.webhook_secret:
        cfg.webhook_secret = secrets.token_urlsafe(32)
        await db.flush()
    return cfg


def map_avinox_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract Activity-table kwargs from an Avinox ride payload."""
    ride_id = payload.get("ride_id") or payload.get("id")
    if ride_id is None:
        raise ValueError("Avinox payload missing ride_id")

    source_id = str(ride_id)
    start_at = _ensure_utc(payload.get("start"))
    if start_at is None:
        raise ValueError("Avinox payload missing start timestamp")

    duration_s = int(payload.get("duration_s") or 0)
    distance_km = payload.get("distance_km")
    distance_m = float(distance_km) * 1000.0 if distance_km is not None else None

    # Calculate kcal from rider energy (1 kJ ~ 0.239006 kcal)
    rider_energy_kj = payload.get("rider_energy_kj")
    kcal = round(float(rider_energy_kj) * 0.239006, 1) if rider_energy_kj is not None else None

    # Generate or extract polyline
    poly = payload.get("polyline")
    if not poly and payload.get("track"):
        try:
            pts = [(float(p[0]), float(p[1])) for p in payload["track"] if len(p) >= 2]
            if pts:
                poly = _polyline_lib.encode(pts, precision=5)
        except Exception as e:
            log.warning("failed to encode Avinox polyline: %s", e)
            poly = None

    assist_secs = payload.get("assist_seconds")
    if isinstance(assist_secs, str):
        import json
        try:
            assist_secs = json.loads(assist_secs)
        except Exception:
            assist_secs = None

    values: dict[str, Any] = {
        "source": "avinox",
        "source_id": source_id,
        "type": "ebikeride",
        "name": f"Avinox Ride #{source_id}",
        "start_at": start_at,
        "duration_s": duration_s,
        "moving_time_s": payload.get("moving_time_s") or duration_s,
        "distance_m": distance_m,
        "elevation_gain_m": payload.get("ascent_m"),
        "elevation_loss_m": payload.get("descent_m"),
        "avg_hr": payload.get("avg_heart_rate"),
        "max_hr": payload.get("max_heart_rate"),
        "avg_power_w": payload.get("avg_rider_power_w"),
        "max_power_w": payload.get("max_rider_power_w"),
        "avg_motor_power_w": payload.get("avg_motor_power_w"),
        "max_motor_power_w": payload.get("max_motor_power_w"),
        "avg_cadence": payload.get("avg_cadence"),
        "battery_start": payload.get("battery_start"),
        "battery_end": payload.get("battery_end"),
        "odometer_end_km": payload.get("odometer_end_km"),
        "assist_seconds": assist_secs,
        "kcal": kcal,
        "polyline": poly,
        "raw": payload,
    }
    return values


async def ingest_ride_payload(
    db: AsyncSession, payload: dict[str, Any]
) -> dict[str, Any]:
    """Ingest one Avinox ride payload into activities and heart rate."""
    values = map_avinox_payload(payload)
    start_at: datetime = values["start_at"]
    source_id: str = values["source_id"]

    # Deduplicate against existing Strava activity for the same ride.
    # If the user previously imported this ride via Strava, migrate user-owned
    # fields (notes, tags, trail_id, recorded_type) and retire the Strava duplicate.
    strava_match = (await db.execute(
        select(models.Activity)
        .where(models.Activity.source == "strava")
        .where(models.Activity.start_at >= start_at - timedelta(seconds=120))
        .where(models.Activity.start_at <= start_at + timedelta(seconds=120))
    )).scalar_one_or_none()

    if strava_match is not None:
        for col in activity_sink.USER_OWNED_COLUMNS:
            v = getattr(strava_match, col, None)
            if v is not None:
                values[col] = v
        await db.delete(strava_match)
        log.info(
            "avinox_ingest: superseded Strava activity %s with Avinox %s",
            strava_match.source_id, source_id,
        )

    # Upsert through the canonical sink (auto-linking trails, completing cardio days,
    # and retiring any overlapping Health Connect promotions).
    act = await activity_sink.upsert_activity(
        db,
        values,
        link_trail=True,
        complete_cardio_day=True,
        reconcile=True,
    )

    # Ingest heart rate stream if provided
    hr_samples_raw = payload.get("hr_samples")
    if hr_samples_raw and isinstance(hr_samples_raw, list):
        parsed_hr: list[tuple[datetime, float]] = []
        for item in hr_samples_raw:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                t = _ensure_utc(item[0])
                bpm = float(item[1])
                if t is not None and bpm > 30:
                    parsed_hr.append((t, bpm))

        if parsed_hr:
            by_ts = {ts: bpm for ts, bpm in parsed_hr}
            hr_values = [
                {"time": ts, "bpm": bpm, "source": "avinox"}
                for ts, bpm in sorted(by_ts.items())
            ]
            first_ts = hr_values[0]["time"]
            last_ts = hr_values[-1]["time"]
            span_s = (last_ts - first_ts).total_seconds()
            dense_enough = span_s <= 0 or (len(hr_values) / span_s) >= (1 / 30)

            if dense_enough:
                await db.execute(
                    delete(models.HeartRate)
                    .where(models.HeartRate.time >= first_ts)
                    .where(models.HeartRate.time <= last_ts)
                )

            chunk_size = 10_000
            for i in range(0, len(hr_values), chunk_size):
                chunk = hr_values[i : i + chunk_size]
                ins = pg_insert(models.HeartRate).values(chunk)
                await db.execute(
                    ins.on_conflict_do_update(
                        index_elements=["time"],
                        set_={"bpm": ins.excluded.bpm, "source": ins.excluded.source},
                    )
                )

    # Update AvinoxConfig
    cfg = await get_or_create_config(db)
    cfg.last_push_at = datetime.now(timezone.utc)
    cfg.last_error = None

    return {
        "status": "ok",
        "source": "avinox",
        "source_id": source_id,
        "name": act.name if act else values.get("name"),
    }


async def sync_from_avinox(
    db: AsyncSession,
    *,
    full: bool = False,
    server_url: str | None = None,
    query_token: str | None = None,
) -> dict[str, Any]:
    """Pull rides from Avinox server on demand."""
    cfg = await get_or_create_config(db)
    base_url = (server_url or cfg.server_url or "http://avinox.lan:8000").rstrip("/")
    token = query_token or cfg.query_token or ""

    headers: dict[str, str] = {"Accept": "application/json"}
    if token:
        headers["X-Query-Token"] = token
        headers["Authorization"] = f"Bearer {token}"

    scanned = 0
    upserted = 0
    now = datetime.now(timezone.utc)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # 1. Fetch rides list
            r = await client.get(f"{base_url}/api/rides", params={"limit": 500}, headers=headers)
            r.raise_for_status()
            data = r.json()
            rides_list = data.get("rides") or []
            scanned = len(rides_list)

            for summary in rides_list:
                ride_id = summary.get("ride_id") or summary.get("id")
                pk = summary.get("id")
                if not ride_id or not pk:
                    continue

                if not full:
                    # Check if already present
                    exists = (await db.execute(
                        select(models.Activity.source_id)
                        .where(models.Activity.source == "avinox")
                        .where(models.Activity.source_id == str(ride_id))
                        .limit(1)
                    )).scalar_one_or_none()
                    if exists is not None:
                        continue

                # Fetch full ride detail with series and track
                detail_resp = await client.get(f"{base_url}/api/rides/{pk}", headers=headers)
                if detail_resp.status_code != 200:
                    log.warning("failed to fetch avinox ride %s: HTTP %s", pk, detail_resp.status_code)
                    continue
                detail = detail_resp.json()
                await ingest_ride_payload(db, detail)
                upserted += 1

        cfg.last_sync_at = now
        cfg.last_error = None
        await db.commit()
    except Exception as e:
        cfg.last_error = str(e)
        await db.commit()
        raise

    return {
        "scanned": scanned,
        "upserted": upserted,
        "last_sync_at": now.isoformat(),
    }
