"""Decode Garmin FIT files into encoded polylines for the activities table.

A FIT file's `record` messages contain per-second trackpoints with
``position_lat`` / ``position_long`` in Garmin's "semicircles" unit
(degrees * 2^31 / 180). We convert those to decimal degrees, downsample
to a few hundred points to keep the polyline string compact, and encode
with Google's Encoded Polyline Algorithm — same format Strava emits, so
the existing Leaflet decoder handles it without changes.
"""
from __future__ import annotations

import io
import logging
import re
from typing import Any

import polyline as polyline_lib
from fitparse import FitFile

log = logging.getLogger(__name__)

_SEMICIRCLE_TO_DEG = 180.0 / (1 << 31)
_FILENAME_ID_RE = re.compile(r"_(\d+)\.fit$", re.IGNORECASE)
# Cap the polyline at this many points — 500 is plenty for thumbnail rendering
# and keeps the string under ~3 KB even on long rides.
_MAX_POLYLINE_POINTS = 500


def extract_activity_id(filename: str) -> str | None:
    """Pull the numeric activity id out of a Garmin FIT filename.

    Garmin's filename pattern is `<athlete>_<activity_id>.fit`. The id is
    the same value that appears as `activityId` in summarizedActivities.
    """
    m = _FILENAME_ID_RE.search(filename)
    return m.group(1) if m else None


def parse_fit_track(data: bytes) -> dict[str, Any]:
    """Return {polyline, n_points, hr_avg, hr_max, start_time} for a FIT blob.

    start_time is a UTC datetime taken from the session message — needed to
    match the FIT to a row in the activities table since Garmin's FIT
    filenames use uploadId, not activityId. Returns polyline=None when the
    file has no GPS records (indoor sessions, strength training, etc.).
    """
    try:
        ff = FitFile(io.BytesIO(data))
        ff.parse()
    except Exception as e:
        log.warning("FIT parse error: %s", e)
        return {"polyline": None, "n_points": 0, "hr_avg": None, "hr_max": None, "start_time": None}

    # Session message holds the canonical start_time + sport.
    start_time = None
    for s in ff.get_messages("session"):
        for fld in s:
            if fld.name == "start_time":
                start_time = fld.value
                break
        if start_time is not None:
            break

    points: list[tuple[float, float]] = []
    hr_values: list[int] = []                       # for hr_avg / hr_max summary
    hr_samples: list[tuple[Any, int]] = []          # (timestamp, bpm) per record
    for rec in ff.get_messages("record"):
        d: dict[str, Any] = {x.name: x.value for x in rec}
        ts = d.get("timestamp")
        # Fallback start_time from first record if session was missing.
        if start_time is None and ts is not None:
            start_time = ts
        lat_raw = d.get("position_lat")
        lon_raw = d.get("position_long")
        if lat_raw is not None and lon_raw is not None:
            points.append((lat_raw * _SEMICIRCLE_TO_DEG, lon_raw * _SEMICIRCLE_TO_DEG))
        hr = d.get("heart_rate")
        if isinstance(hr, (int, float)) and hr > 0:
            hr_values.append(int(hr))
            if ts is not None:
                hr_samples.append((ts, int(hr)))

    if not points:
        encoded: str | None = None
    else:
        if len(points) > _MAX_POLYLINE_POINTS:
            step = max(1, len(points) // _MAX_POLYLINE_POINTS)
            points = points[::step]
        encoded = polyline_lib.encode(points)

    hr_avg = (sum(hr_values) / len(hr_values)) if hr_values else None
    hr_max = max(hr_values) if hr_values else None

    return {
        "polyline": encoded,
        "n_points": len(points),
        "hr_avg": hr_avg,
        "hr_max": hr_max,
        "hr_samples": hr_samples,  # list[(datetime, int_bpm)]
        "start_time": start_time,  # naive datetime in UTC per FIT spec
    }
