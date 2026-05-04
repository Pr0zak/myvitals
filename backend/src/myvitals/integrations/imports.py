"""Parsers for Fitbit (Google Takeout) and Garmin Connect data exports.

Both providers ship account-data archives as ZIP. We don't try to be a
1:1 mirror of every field — the goal is to get historical heart rate,
sleep, steps and activity summaries into the existing tables so older
data shows up in the dashboard.

The parsers walk the zip entry list, match filenames against known
patterns, and accumulate samples. Missing sections are skipped with a
warning so a partial export still imports what it can.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import zipfile
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


# --- Fitbit (Google Takeout / fitbit.com export) ---------------------

# Fitbit timestamps: "MM/DD/YY HH:MM:SS" (no tz — local). We treat them as UTC
# since Fitbit doesn't preserve tz in the export anyway.
_FITBIT_TS = "%m/%d/%y %H:%M:%S"


def _parse_fitbit_ts(s: str) -> datetime | None:
    try:
        return datetime.strptime(s, _FITBIT_TS).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _parse_iso_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # Trailing Z and missing tz both happen in real exports
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


_LB_TO_KG = 0.45359237


def parse_fitbit_zip(
    zf: zipfile.ZipFile, weight_unit: str = "kg",
) -> dict[str, list[dict[str, Any]]]:
    """Walk a Fitbit export ZIP and return per-stream samples.

    Output dict keys: heartrate, steps, sleep_stages, hrv, activities,
    body_metrics, skin_temp. Each value is a list of dicts ready to feed
    into _bulk_upsert.

    weight_unit ("kg" | "lb") tells us how to interpret the raw `weight`
    field — Fitbit exports it in whatever unit the user's profile is set to,
    and the export itself doesn't say.
    """
    out: dict[str, list[dict[str, Any]]] = {
        "heartrate": [],
        "steps": [],
        "sleep_stages": [],
        "hrv": [],
        "activities": [],
        "body_metrics": [],
        "skin_temp": [],
    }

    files_seen = {k: 0 for k in out}

    for name in zf.namelist():
        low = name.lower()
        # Heart rate intraday: heart_rate-YYYY-MM-DD.json
        if "heart_rate-" in low and low.endswith(".json"):
            files_seen["heartrate"] += 1
            try:
                data = json.loads(zf.read(name))
            except Exception as e:
                log.warning("fitbit hr parse %s: %s", name, e)
                continue
            for row in data:
                ts = _parse_fitbit_ts(row.get("dateTime", ""))
                val = row.get("value") or {}
                bpm = val.get("bpm") if isinstance(val, dict) else None
                if ts and bpm is not None:
                    out["heartrate"].append({"time": ts, "bpm": float(bpm), "source": "fitbit"})

        # Steps intraday: steps-YYYY-MM-DD.json
        elif re.search(r"(^|/)steps-\d{4}-\d{2}-\d{2}\.json$", low):
            files_seen["steps"] += 1
            try:
                data = json.loads(zf.read(name))
            except Exception as e:
                log.warning("fitbit steps parse %s: %s", name, e)
                continue
            for row in data:
                ts = _parse_fitbit_ts(row.get("dateTime", ""))
                v = row.get("value")
                try:
                    count = int(v)
                except (TypeError, ValueError):
                    continue
                if ts and count > 0:
                    out["steps"].append({"time": ts, "count": count})

        # Sleep: sleep-YYYY-MM-DD.json — array of session objects
        elif re.search(r"(^|/)sleep-\d{4}-\d{2}-\d{2}\.json$", low):
            files_seen["sleep_stages"] += 1
            try:
                data = json.loads(zf.read(name))
            except Exception as e:
                log.warning("fitbit sleep parse %s: %s", name, e)
                continue
            for sess in data:
                levels = (sess.get("levels") or {}).get("data") or []
                for lv in levels:
                    ts = _parse_iso_ts(lv.get("dateTime"))
                    stage = (lv.get("level") or "").lower()
                    secs = lv.get("seconds")
                    if ts and stage and isinstance(secs, (int, float)) and secs > 0:
                        out["sleep_stages"].append({
                            "time": ts, "stage": stage, "duration_s": int(secs),
                        })

        # HRV: "Heart Rate Variability Details - YYYY-MM-DD.csv"
        elif "heart rate variability details" in low and low.endswith(".csv"):
            files_seen["hrv"] += 1
            try:
                text = zf.read(name).decode("utf-8", errors="replace")
            except Exception as e:
                log.warning("fitbit hrv read %s: %s", name, e)
                continue
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                ts = _parse_iso_ts(row.get("timestamp") or row.get("Timestamp"))
                # Fitbit uses "rmssd" or "RMSSD" depending on era
                rmssd = row.get("rmssd") or row.get("RMSSD") or row.get("rMSSD")
                if ts and rmssd:
                    try:
                        out["hrv"].append({"time": ts, "rmssd_ms": float(rmssd)})
                    except ValueError:
                        pass

        # Weight: weight-YYYY-MM-DD.json (or weight-YYYY-MM.json)
        elif re.search(r"(^|/)weight-\d{4}-\d{2}", low) and low.endswith(".json"):
            files_seen["body_metrics"] += 1
            try:
                data = json.loads(zf.read(name))
            except Exception as e:
                log.warning("fitbit weight parse %s: %s", name, e)
                continue
            for row in data:
                # Fitbit weight files use date + time (LOCAL) as separate fields
                d = row.get("date")
                t = row.get("time") or "00:00:00"
                ts = None
                if d and t:
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
                # Convert lb → kg if the user told us their Fitbit profile was imperial.
                weight_kg = float(weight) * _LB_TO_KG if weight_unit == "lb" else float(weight)
                out["body_metrics"].append({
                    "time": ts,
                    "weight_kg": weight_kg,
                    "body_fat_pct": row.get("fat"),
                    "bmi": row.get("bmi"),
                    "lean_mass_kg": None,
                    "source": "fitbit",
                })

        # Wrist temperature: "Wrist Temperature - YYYY-MM-DD.csv"
        elif "wrist temperature" in low and low.endswith(".csv"):
            files_seen["skin_temp"] += 1
            try:
                text = zf.read(name).decode("utf-8", errors="replace")
            except Exception as e:
                log.warning("fitbit temp read %s: %s", name, e)
                continue
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                ts = _parse_iso_ts(row.get("recorded_time") or row.get("timestamp") or row.get("date"))
                delta = (row.get("temperature") or row.get("nightly_temperature")
                         or row.get("Temperature") or row.get("temp_diff"))
                if ts and delta:
                    try:
                        out["skin_temp"].append({"time": ts, "celsius_delta": float(delta)})
                    except ValueError:
                        pass

        # Activities: exercise-N.json (or exercise.json)
        elif re.search(r"(^|/)exercise(-\d+)?\.json$", low):
            files_seen["activities"] += 1
            try:
                data = json.loads(zf.read(name))
            except Exception as e:
                log.warning("fitbit exercise parse %s: %s", name, e)
                continue
            for ex in data:
                start = _parse_iso_ts(ex.get("startTime"))
                if not start:
                    continue
                # duration is in milliseconds in the export
                dur_ms = ex.get("duration") or 0
                dur_s = int(dur_ms / 1000) if dur_ms else 0
                # Fitbit distances are in km in the JSON export
                dist_km = ex.get("distance")
                dist_m = float(dist_km) * 1000 if isinstance(dist_km, (int, float)) else None
                log_id = ex.get("logId") or ex.get("logID")
                if log_id is None:
                    continue
                act_type = (ex.get("activityName") or ex.get("activityTypeId") or "unknown")
                out["activities"].append({
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

    log.info("fitbit zip: files_seen=%s samples=%s",
             files_seen, {k: len(v) for k, v in out.items()})
    return out


# --- Garmin Connect data export ---------------------------------------

def parse_garmin_zip(zf: zipfile.ZipFile) -> dict[str, list[dict[str, Any]]]:
    """Walk a Garmin export ZIP and return per-stream samples.

    Garmin's format has shifted across years; this tries the common patterns
    for activities + sleep + intraday HR + steps. Anything we don't recognise
    is silently skipped.
    """
    out: dict[str, list[dict[str, Any]]] = {
        "heartrate": [],
        "steps": [],
        "sleep_stages": [],
        "activities": [],
        "body_metrics": [],
    }
    files_seen = {k: 0 for k in out}

    for name in zf.namelist():
        low = name.lower()

        # Activity summaries: *summarizedActivities*.json
        if "summarizedactivities" in low and low.endswith(".json"):
            files_seen["activities"] += 1
            try:
                payload = json.loads(zf.read(name))
            except Exception as e:
                log.warning("garmin activities parse %s: %s", name, e)
                continue
            # Format is usually [{"summarizedActivitiesExport": [ {...}, ... ]}]
            arr: list[dict[str, Any]] = []
            if isinstance(payload, list):
                for chunk in payload:
                    if isinstance(chunk, dict):
                        arr.extend(chunk.get("summarizedActivitiesExport") or [])
                    elif isinstance(chunk, list):
                        arr.extend(chunk)
            elif isinstance(payload, dict):
                arr = payload.get("summarizedActivitiesExport") or []
            for ex in arr:
                start = _parse_iso_ts(ex.get("startTimeGmt") or ex.get("startTimeLocal"))
                if not start and isinstance(ex.get("beginTimestamp"), (int, float)):
                    start = datetime.fromtimestamp(ex["beginTimestamp"] / 1000, tz=timezone.utc)
                aid = ex.get("activityId")
                if not start or aid is None:
                    continue
                out["activities"].append({
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

        # Sleep data: */sleepData/*.json or *sleep*.json under wellness
        elif "sleep" in low and low.endswith(".json") and "wellness" in low:
            files_seen["sleep_stages"] += 1
            try:
                payload = json.loads(zf.read(name))
            except Exception as e:
                log.warning("garmin sleep parse %s: %s", name, e)
                continue
            sessions = payload if isinstance(payload, list) else [payload]
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
                    if end:
                        secs = int((end - ts).total_seconds())
                    else:
                        secs = int(lv.get("durationInSeconds") or 0)
                    if secs > 0 and stage:
                        out["sleep_stages"].append({
                            "time": ts, "stage": stage, "duration_s": secs,
                        })

        # Intraday HR: HR_*.json under HeartRateBpm or wellness
        elif ("heartrate" in low or "heart_rate" in low or "/hr_" in low) and low.endswith(".json"):
            files_seen["heartrate"] += 1
            try:
                payload = json.loads(zf.read(name))
            except Exception as e:
                log.warning("garmin hr parse %s: %s", name, e)
                continue
            sessions = payload if isinstance(payload, list) else [payload]
            for sess in sessions:
                if not isinstance(sess, dict):
                    continue
                # Garmin commonly: heartRateValues = [[epoch_ms, bpm], ...]
                values = sess.get("heartRateValues") or sess.get("samples") or []
                for v in values:
                    if isinstance(v, list) and len(v) == 2:
                        ts_ms, bpm = v
                        if isinstance(ts_ms, (int, float)) and isinstance(bpm, (int, float)) and bpm > 0:
                            out["heartrate"].append({
                                "time": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc),
                                "bpm": float(bpm),
                                "source": "garmin",
                            })
                    elif isinstance(v, dict):
                        ts = _parse_iso_ts(v.get("timestamp") or v.get("time"))
                        bpm = v.get("bpm") or v.get("value")
                        if ts and isinstance(bpm, (int, float)) and bpm > 0:
                            out["heartrate"].append({
                                "time": ts, "bpm": float(bpm), "source": "garmin",
                            })

        # Weight: userBioMetrics or weight files under wellness
        elif ("biometric" in low or "weight" in low or "bodycomposition" in low) \
                and low.endswith(".json"):
            files_seen["body_metrics"] += 1
            try:
                payload = json.loads(zf.read(name))
            except Exception as e:
                log.warning("garmin weight parse %s: %s", name, e)
                continue
            entries = payload if isinstance(payload, list) else [payload]
            for ent in entries:
                if not isinstance(ent, dict):
                    continue
                # Two common shapes: top-level fields, or {"dateWeightList":[...]}
                rows = ent.get("dateWeightList") or ent.get("weights") or [ent]
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    ts = _parse_iso_ts(
                        r.get("calendarDate") or r.get("timestampGmt")
                        or r.get("date") or r.get("samplePk")
                    )
                    # Garmin weight is in grams when the field is `weight`,
                    # in kg when it's `weightInGrams`/`weight_kg`/`bodyWeight`.
                    w_grams = r.get("weight") if isinstance(r.get("weight"), (int, float)) and r.get("weight", 0) > 1000 else None
                    w_kg = (w_grams / 1000.0) if w_grams else (
                        r.get("weight_kg") or r.get("bodyWeight")
                    )
                    if ts and w_kg:
                        out["body_metrics"].append({
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

        # Steps daily: wellness daily files often have totalSteps + calendarDate
        elif "wellness" in low and low.endswith(".json") and "daily" in low:
            files_seen["steps"] += 1
            try:
                payload = json.loads(zf.read(name))
            except Exception as e:
                log.warning("garmin steps parse %s: %s", name, e)
                continue
            entries = payload if isinstance(payload, list) else [payload]
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                cal = entry.get("calendarDate")
                steps = entry.get("totalSteps") or entry.get("steps")
                if cal and isinstance(steps, (int, float)) and steps > 0:
                    ts = _parse_iso_ts(f"{cal}T00:00:00")
                    if ts:
                        out["steps"].append({"time": ts, "count": int(steps)})

    log.info("garmin zip: files_seen=%s samples=%s",
             files_seen, {k: len(v) for k, v in out.items()})
    return out
