"""Shared cardio-day auto-completion.

Called from every integration that upserts an Activity (concept2,
strava, …). If the activity is cardio-shaped and lands on a date that
has a planned/in-progress cardio StrengthWorkout, flip the workout to
'completed' and stash which activity did it.

Caller passes the same flat fields the integrations already have on
hand (source/source_id/type/start_at/duration_s) so this module doesn't
need to know about each integration's row shape.
"""
from __future__ import annotations

import logging
from datetime import date as _date
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select

from ..config import settings
from ..db import models

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

_CARDIO_SUBSTRINGS = (
    "row",          # rower, rowing, indoorrowing
    "ride",         # ride, virtualride, ebikeride, gravelride, mountainbikeride
    "run",          # run, virtualrun, trailrun
    "erg",          # bikeerg, skierg
    "bike",         # standalone biking labels
    "cycl",         # cycling
    "hike",
    "swim",
    "elliptical",
    "stair",
    "treadmill",
)

MIN_CARDIO_DURATION_S = 300  # 5 min — avoid auto-completing on a tiny warmup row


def is_cardio_type(activity_type: str | None) -> bool:
    if not activity_type:
        return False
    t = activity_type.lower()
    return any(s in t for s in _CARDIO_SUBSTRINGS)


def _local_date(dt: datetime) -> _date:
    try:
        from zoneinfo import ZoneInfo
        local = ZoneInfo(settings.tz) if settings.tz != "UTC" else timezone.utc
    except Exception:  # noqa: BLE001
        local = timezone.utc
    return dt.astimezone(local).date()


async def maybe_complete_cardio_day(
    db: "AsyncSession",
    *,
    source: str,
    source_id: str,
    activity_type: str | None,
    start_at: datetime,
    duration_s: int,
) -> bool:
    """If today's planned cardio StrengthWorkout matches this activity,
    mark it completed. Returns True iff a row was flipped."""
    if not is_cardio_type(activity_type):
        return False
    if duration_s < MIN_CARDIO_DURATION_S:
        return False

    local_d = _local_date(start_at)
    q = (
        select(models.StrengthWorkout)
        .where(models.StrengthWorkout.date == local_d)
        .where(models.StrengthWorkout.split_focus == "cardio")
        .where(models.StrengthWorkout.status.in_(("planned", "in_progress")))
        .order_by(models.StrengthWorkout.id.desc())
        .limit(1)
    )
    workout = (await db.execute(q)).scalar_one_or_none()
    if workout is None:
        return False

    workout.status = "completed"
    # Set BOTH started_at and completed_at to the activity's real window.
    # The UI computes duration as (completed_at - started_at); leaving
    # started_at as the StrengthWorkout's noon-default generated_at would
    # surface a 7h+ phantom duration in the activity calendar.
    workout.started_at = start_at
    workout.completed_at = start_at + timedelta(seconds=duration_s)
    workout.completed_by_activity_source = source
    workout.completed_by_activity_source_id = source_id
    log.info(
        "Auto-completed cardio workout id=%s for date=%s from %s:%s (type=%s, dur=%ss)",
        workout.id, local_d, source, source_id, activity_type, duration_s,
    )
    return True
