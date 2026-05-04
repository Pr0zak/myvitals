"""Streaming parsers for Fitbit (Google Takeout) and Garmin Connect ZIP exports.

Both parsers are **generators** that yield ``(stream_name, [samples])``
tuples while walking the ZIP. The HTTP endpoint flushes each yielded chunk
to Postgres immediately, so memory stays bounded around the size of one
expanded ZIP entry (typically <50 MB even on multi-GB takeouts).

Stream names map 1:1 to backend tables:

  heartrate, hrv, steps, sleep_stages, body_metrics, skin_temp, activities

A single entry can yield more than once (large files are pre-chunked at
``MAX_BATCH``). Missing or malformed files are skipped with a warning.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import zipfile
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

# Postgres' 32k bind-param limit gives us roughly 4000 wide rows per insert.
# Yielding in batches of this size keeps the importer's transient memory low
# and matches the chunk size the bulk-upsert helper uses internally.
MAX_BATCH = 4000

# Fitbit timestamps: "MM/DD/YY HH:MM:SS" (no tz — local). We treat them as UTC
# since Fitbit doesn't preserve tz in the export anyway.
_FITBIT_TS = "%m/%d/%y %H:%M:%S"
_LB_TO_KG = 0.45359237


def _parse_fitbit_ts(s: str) -> datetime | None:
    try:
        return datetime.strptime(s, _FITBIT_TS).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _parse_iso_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _emit(stream: str, batch: list[dict[str, Any]]) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """Helper: yield batch in MAX_BATCH-sized chunks, then return."""
    if not batch:
        return
    for i in range(0, len(batch), MAX_BATCH):
        yield (stream, batch[i : i + MAX_BATCH])


# --- Fitbit (Google Takeout / fitbit.com export) ---------------------

def parse_fitbit_zip(
    zf: zipfile.ZipFile, weight_unit: str = "kg",
) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """Walk a Fitbit export ZIP, yielding (stream_name, [samples]) batches.

    weight_unit ("kg" | "lb") is what the user said their Fitbit profile is
    set to. We can't tell from the export alone.
    """
    files_seen: dict[str, int] = {}

    for name in zf.namelist():
        low = name.lower()

        # Heart rate intraday: heart_rate-YYYY-MM-DD.json
        if "heart_rate-" in low and low.endswith(".json"):
            files_seen["heartrate"] = files_seen.get("heartrate", 0) + 1
            yield from _parse_fitbit_hr(zf, name)

        elif re.search(r"(^|/)steps-\d{4}-\d{2}-\d{2}\.json$", low):
            files_seen["steps"] = files_seen.get("steps", 0) + 1
            yield from _parse_fitbit_steps(zf, name)

        elif re.search(r"(^|/)sleep-\d{4}-\d{2}-\d{2}\.json$", low):
            files_seen["sleep_stages"] = files_seen.get("sleep_stages", 0) + 1
            yield from _parse_fitbit_sleep(zf, name)

        elif "heart rate variability details" in low and low.endswith(".csv"):
            files_seen["hrv"] = files_seen.get("hrv", 0) + 1
            yield from _parse_fitbit_hrv(zf, name)

        elif re.search(r"(^|/)weight-\d{4}-\d{2}", low) and low.endswith(".json"):
            files_seen["body_metrics"] = files_seen.get("body_metrics", 0) + 1
            yield from _parse_fitbit_weight(zf, name, weight_unit)

        elif "wrist temperature" in low and low.endswith(".csv"):
            files_seen["skin_temp"] = files_seen.get("skin_temp", 0) + 1
            yield from _parse_fitbit_wrist_temp(zf, name)

        elif re.search(r"(^|/)exercise(-\d+)?\.json$", low):
            files_seen["activities"] = files_seen.get("activities", 0) + 1
            yield from _parse_fitbit_exercise(zf, name)

    log.info("fitbit zip walk done: files_seen=%s", files_seen)


def _safe_load_json(zf: zipfile.ZipFile, name: str) -> Any | None:
    try:
        with zf.open(name) as fp:
            return json.load(fp)
    except Exception as e:
        log.warning("parse %s failed: %s", name, e)
        return None


def _safe_load_csv(zf: zipfile.ZipFile, name: str) -> Iterator[dict[str, str]]:
    try:
        with zf.open(name) as fp:
            text = fp.read().decode("utf-8", errors="replace")
    except Exception as e:
        log.warning("read %s failed: %s", name, e)
        return
    yield from csv.DictReader(io.StringIO(text))


def _parse_fitbit_hr(zf, name) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    data = _safe_load_json(zf, name)
    if not data:
        return
    batch: list[dict[str, Any]] = []
    for row in data:
        ts = _parse_fitbit_ts(row.get("dateTime", ""))
        val = row.get("value") or {}
        bpm = val.get("bpm") if isinstance(val, dict) else None
        if ts and bpm is not None:
            batch.append({"time": ts, "bpm": float(bpm), "source": "fitbit"})
            if len(batch) >= MAX_BATCH:
                yield ("heartrate", batch)
                batch = []
    yield from _emit("heartrate", batch)


def _parse_fitbit_steps(zf, name) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    data = _safe_load_json(zf, name)
    if not data:
        return
    batch: list[dict[str, Any]] = []
    for row in data:
        ts = _parse_fitbit_ts(row.get("dateTime", ""))
        v = row.get("value")
        try:
            count = int(v)
        except (TypeError, ValueError):
            continue
        if ts and count > 0:
            batch.append({"time": ts, "count": count})
            if len(batch) >= MAX_BATCH:
                yield ("steps", batch)
                batch = []
    yield from _emit("steps", batch)


def _parse_fitbit_sleep(zf, name) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    data = _safe_load_json(zf, name)
    if not data:
        return
    batch: list[dict[str, Any]] = []
    for sess in data:
        levels = (sess.get("levels") or {}).get("data") or []
        for lv in levels:
            ts = _parse_iso_ts(lv.get("dateTime"))
            stage = (lv.get("level") or "").lower()
            secs = lv.get("seconds")
            if ts and stage and isinstance(secs, (int, float)) and secs > 0:
                batch.append({"time": ts, "stage": stage, "duration_s": int(secs)})
                if len(batch) >= MAX_BATCH:
                    yield ("sleep_stages", batch)
                    batch = []
    yield from _emit("sleep_stages", batch)


def _parse_fitbit_hrv(zf, name) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    batch: list[dict[str, Any]] = []
    for row in _safe_load_csv(zf, name):
        ts = _parse_iso_ts(row.get("timestamp") or row.get("Timestamp"))
        rmssd = row.get("rmssd") or row.get("RMSSD") or row.get("rMSSD")
        if ts and rmssd:
            try:
                batch.append({"time": ts, "rmssd_ms": float(rmssd)})
            except ValueError:
                continue
            if len(batch) >= MAX_BATCH:
                yield ("hrv", batch)
                batch = []
    yield from _emit("hrv", batch)


def _parse_fitbit_weight(zf, name, weight_unit) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    data = _safe_load_json(zf, name)
    if not data:
        return
    batch: list[dict[str, Any]] = []
    for row in data:
        d = row.get("date")
        t = row.get("time") or "00:00:00"
        ts: datetime | None = None
        if d:
            try:
                ts = datetime.strptime(f"{d} {t}", "%m/%d/%y %H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                try:
                    ts = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                except ValueError:
                    ts = None
        if ts is None:
            continue
        weight = row.get("weight")
        if weight is None:
            continue
        weight_kg = float(weight) * _LB_TO_KG if weight_unit == "lb" else float(weight)
        batch.append({
            "time": ts,
            "weight_kg": weight_kg,
            "body_fat_pct": row.get("fat"),
            "bmi": row.get("bmi"),
            "lean_mass_kg": None,
            "source": "fitbit",
        })
        if len(batch) >= MAX_BATCH:
            yield ("body_metrics", batch)
            batch = []
    yield from _emit("body_metrics", batch)


def _parse_fitbit_wrist_temp(zf, name) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    batch: list[dict[str, Any]] = []
    for row in _safe_load_csv(zf, name):
        ts = _parse_iso_ts(row.get("recorded_time") or row.get("timestamp") or row.get("date"))
        delta = (row.get("temperature") or row.get("nightly_temperature")
                 or row.get("Temperature") or row.get("temp_diff"))
        if ts and delta:
            try:
                batch.append({"time": ts, "celsius_delta": float(delta)})
            except ValueError:
                continue
            if len(batch) >= MAX_BATCH:
                yield ("skin_temp", batch)
                batch = []
    yield from _emit("skin_temp", batch)


def _parse_fitbit_exercise(zf, name) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    data = _safe_load_json(zf, name)
    if not data:
        return
    batch: list[dict[str, Any]] = []
    for ex in data:
        start = _parse_iso_ts(ex.get("startTime"))
        if not start:
            continue
        dur_ms = ex.get("duration") or 0
        dur_s = int(dur_ms / 1000) if dur_ms else 0
        dist_km = ex.get("distance")
        dist_m = float(dist_km) * 1000 if isinstance(dist_km, (int, float)) else None
        log_id = ex.get("logId") or ex.get("logID")
        if log_id is None:
            continue
        act_type = (ex.get("activityName") or ex.get("activityTypeId") or "unknown")
        batch.append({
            "source": "fitbit",
            "source_id": str(log_id),
            "type": str(act_type).lower().replace(" ", "_"),
            "name": ex.get("activityName"),
            "start_at": start,
            "duration_s": dur_s,
            "distance_m": dist_m,
            "elevation_gain_m": ex.get("elevationGain"),
            "avg_hr": ex.get("averageHeartRate"),
            "max_hr": ex.get("maxHeartRate"),
            "kcal": ex.get("calories"),
            "raw": ex,
        })
        if len(batch) >= MAX_BATCH:
            yield ("activities", batch)
            batch = []
    yield from _emit("activities", batch)


# --- Garmin Connect data export ---------------------------------------

def parse_garmin_zip(zf: zipfile.ZipFile) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """Walk a Garmin export ZIP, yielding (stream_name, [samples]) batches."""
    files_seen: dict[str, int] = {}

    for name in zf.namelist():
        low = name.lower()

        if "summarizedactivities" in low and low.endswith(".json"):
            files_seen["activities"] = files_seen.get("activities", 0) + 1
            yield from _parse_garmin_activities(zf, name)

        elif "sleep" in low and low.endswith(".json") and "wellness" in low:
            files_seen["sleep_stages"] = files_seen.get("sleep_stages", 0) + 1
            yield from _parse_garmin_sleep(zf, name)

        elif ("heartrate" in low or "heart_rate" in low or "/hr_" in low) and low.endswith(".json"):
            files_seen["heartrate"] = files_seen.get("heartrate", 0) + 1
            yield from _parse_garmin_hr(zf, name)

        elif ("biometric" in low or "weight" in low or "bodycomposition" in low) \
                and low.endswith(".json"):
            files_seen["body_metrics"] = files_seen.get("body_metrics", 0) + 1
            yield from _parse_garmin_weight(zf, name)

        elif "wellness" in low and low.endswith(".json") and "daily" in low:
            files_seen["steps"] = files_seen.get("steps", 0) + 1
            yield from _parse_garmin_steps(zf, name)

    log.info("garmin zip walk done: files_seen=%s", files_seen)


def _parse_garmin_activities(zf, name) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    payload = _safe_load_json(zf, name)
    if payload is None:
        return
    arr: list[dict[str, Any]] = []
    if isinstance(payload, list):
        for chunk in payload:
            if isinstance(chunk, dict):
                arr.extend(chunk.get("summarizedActivitiesExport") or [])
            elif isinstance(chunk, list):
                arr.extend(chunk)
    elif isinstance(payload, dict):
        arr = payload.get("summarizedActivitiesExport") or []
    batch: list[dict[str, Any]] = []
    for ex in arr:
        start = _parse_iso_ts(ex.get("startTimeGmt") or ex.get("startTimeLocal"))
        if not start and isinstance(ex.get("beginTimestamp"), (int, float)):
            start = datetime.fromtimestamp(ex["beginTimestamp"] / 1000, tz=timezone.utc)
        aid = ex.get("activityId")
        if not start or aid is None:
            continue
        batch.append({
            "source": "garmin",
            "source_id": str(aid),
            "type": str(ex.get("activityType") or "unknown").lower(),
            "name": ex.get("name"),
            "start_at": start,
            "duration_s": int(ex.get("duration") or ex.get("elapsedDuration") or 0),
            "distance_m": ex.get("distance"),
            "elevation_gain_m": ex.get("elevationGain"),
            "avg_hr": ex.get("avgHr") or ex.get("averageHR"),
            "max_hr": ex.get("maxHr") or ex.get("maxHR"),
            "avg_power_w": ex.get("avgPower"),
            "max_power_w": ex.get("maxPower"),
            "kcal": ex.get("calories"),
            "raw": ex,
        })
        if len(batch) >= MAX_BATCH:
            yield ("activities", batch)
            batch = []
    yield from _emit("activities", batch)


def _parse_garmin_sleep(zf, name) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    payload = _safe_load_json(zf, name)
    if payload is None:
        return
    sessions = payload if isinstance(payload, list) else [payload]
    batch: list[dict[str, Any]] = []
    for sess in sessions:
        if not isinstance(sess, dict):
            continue
        levels = sess.get("sleepLevels") or sess.get("sleepStages") or []
        for lv in levels:
            ts = _parse_iso_ts(lv.get("startGMT") or lv.get("start"))
            end = _parse_iso_ts(lv.get("endGMT") or lv.get("end"))
            stage = str(lv.get("activityLevel") or lv.get("level") or "").lower()
            if not ts:
                continue
            secs = int((end - ts).total_seconds()) if end else int(lv.get("durationInSeconds") or 0)
            if secs > 0 and stage:
                batch.append({"time": ts, "stage": stage, "duration_s": secs})
                if len(batch) >= MAX_BATCH:
                    yield ("sleep_stages", batch)
                    batch = []
    yield from _emit("sleep_stages", batch)


def _parse_garmin_hr(zf, name) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    payload = _safe_load_json(zf, name)
    if payload is None:
        return
    sessions = payload if isinstance(payload, list) else [payload]
    batch: list[dict[str, Any]] = []
    for sess in sessions:
        if not isinstance(sess, dict):
            continue
        values = sess.get("heartRateValues") or sess.get("samples") or []
        for v in values:
            if isinstance(v, list) and len(v) == 2:
                ts_ms, bpm = v
                if isinstance(ts_ms, (int, float)) and isinstance(bpm, (int, float)) and bpm > 0:
                    batch.append({
                        "time": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc),
                        "bpm": float(bpm), "source": "garmin",
                    })
            elif isinstance(v, dict):
                ts = _parse_iso_ts(v.get("timestamp") or v.get("time"))
                bpm = v.get("bpm") or v.get("value")
                if ts and isinstance(bpm, (int, float)) and bpm > 0:
                    batch.append({"time": ts, "bpm": float(bpm), "source": "garmin"})
            if len(batch) >= MAX_BATCH:
                yield ("heartrate", batch)
                batch = []
    yield from _emit("heartrate", batch)


def _parse_garmin_weight(zf, name) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    payload = _safe_load_json(zf, name)
    if payload is None:
        return
    entries = payload if isinstance(payload, list) else [payload]
    batch: list[dict[str, Any]] = []
    for ent in entries:
        if not isinstance(ent, dict):
            continue
        rows = ent.get("dateWeightList") or ent.get("weights") or [ent]
        for r in rows:
            if not isinstance(r, dict):
                continue
            ts = _parse_iso_ts(
                r.get("calendarDate") or r.get("timestampGmt")
                or r.get("date") or r.get("samplePk")
            )
            w_grams = r.get("weight") if isinstance(r.get("weight"), (int, float)) and r.get("weight", 0) > 1000 else None
            w_kg = (w_grams / 1000.0) if w_grams else (r.get("weight_kg") or r.get("bodyWeight"))
            if ts and w_kg:
                batch.append({
                    "time": ts,
                    "weight_kg": float(w_kg),
                    "body_fat_pct": r.get("bodyFat") or r.get("body_fat"),
                    "bmi": r.get("bmi"),
                    "lean_mass_kg": (
                        (r.get("muscleMass") / 1000.0)
                        if isinstance(r.get("muscleMass"), (int, float))
                        and r.get("muscleMass", 0) > 100
                        else r.get("muscleMass")
                    ),
                    "source": "garmin",
                })
                if len(batch) >= MAX_BATCH:
                    yield ("body_metrics", batch)
                    batch = []
    yield from _emit("body_metrics", batch)


def _parse_garmin_steps(zf, name) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    payload = _safe_load_json(zf, name)
    if payload is None:
        return
    entries = payload if isinstance(payload, list) else [payload]
    batch: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        cal = entry.get("calendarDate")
        steps = entry.get("totalSteps") or entry.get("steps")
        if cal and isinstance(steps, (int, float)) and steps > 0:
            ts = _parse_iso_ts(f"{cal}T00:00:00")
            if ts:
                batch.append({"time": ts, "count": int(steps)})
                if len(batch) >= MAX_BATCH:
                    yield ("steps", batch)
                    batch = []
    yield from _emit("steps", batch)
