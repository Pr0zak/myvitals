"""Is my data actually arriving? (HEALTH-1)

Two backlog entries asked for this from opposite ends — one wanted
per-STREAM freshness ("is heart rate still flowing?"), the other wanted
per-INTEGRATION status ("is Strava still connected?"). They are the same
question and belong on one screen: when steps stop arriving, the next
thing you want to know is whether the phone stopped syncing or Google
Health stopped answering.

## The design constraint that shapes everything here

Most of these streams are *supposed* to be stale.

On this database right now: body metrics last written 103 days ago,
blood pressure 75 days ago, environment readings never. Those are not
failures — a weigh-in is something you do when you feel like it, and the
Home Assistant sensor feed is optional. A card that paints them red is
wrong three times over, and worse, it trains you to ignore the card
entirely within a week. Then the one time heart rate really does stop,
the red means nothing.

So every stream declares what *normal* looks like for it, and only
streams that should be continuous can be stale.

## The performance constraint

`vitals_heartrate` holds ~23.6M rows across 451 chunks on an 8 GB
container with no memory limit, and the navigation polls this on page
load. Two rules, both learned the hard way:

* Freshness is `MAX(time)` on the indexed time column — measured at
  127-172 ms per hypertable, and TimescaleDB answers it by chunk
  exclusion rather than a scan.
* Never `count(*)` without a time predicate.

The ten MAXes run as ONE statement with scalar subqueries — 510 ms
total against ~1.5 s if issued serially — and the result is cached
briefly, because "how fresh is my data" does not need sub-minute
accuracy.
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

Kind = Literal["continuous", "nightly", "ad_hoc", "optional"]
Status = Literal["ok", "stale", "ad_hoc", "not_configured", "never"]


@dataclass(frozen=True)
class StreamSpec:
    key: str
    label: str
    table: str
    time_col: str
    kind: Kind
    #: Only meaningful for continuous / nightly streams.
    stale_after_h: float = 24.0
    #: What writes it, so the card can point somewhere useful.
    source: str = ""


#: Order is display order — most-continuous first, so the streams that
#: can actually be broken sit at the top where they will be seen.
STREAMS: tuple[StreamSpec, ...] = (
    StreamSpec("heart_rate", "Heart rate", "vitals_heartrate", "time",
               "continuous", 6.0, "Watch via phone"),
    StreamSpec("steps", "Steps", "vitals_steps", "time",
               "continuous", 6.0, "Watch via phone"),
    StreamSpec("hrv", "HRV", "vitals_hrv", "time",
               "nightly", 48.0, "Watch, overnight"),
    StreamSpec("sleep", "Sleep", "sleep_stages", "time",
               "nightly", 48.0, "Watch, overnight"),
    StreamSpec("spo2", "Blood oxygen", "vitals_spo2", "time",
               "nightly", 48.0, "Google Health"),
    StreamSpec("skin_temp", "Skin temperature", "vitals_skin_temp", "time",
               "nightly", 48.0, "Google Health"),
    StreamSpec("activities", "Activities", "activities", "start_at",
               "ad_hoc", source="Strava, Health Connect"),
    StreamSpec("weight", "Body metrics", "body_metrics", "time",
               "ad_hoc", source="Manual, smart scale"),
    StreamSpec("blood_pressure", "Blood pressure", "blood_pressure", "time",
               "ad_hoc", source="Cuff, manual"),
    StreamSpec("environment", "Bedroom environment", "env_readings", "time",
               "optional", 6.0, "Home Assistant"),
)

#: Freshness does not need sub-minute accuracy, and the nav polls this on
#: every page load. One statement per minute is plenty.
_CACHE_TTL_S = 60.0
_cache: tuple[float, list[dict[str, Any]]] | None = None


def _classify(spec: StreamSpec, last: datetime | None, now: datetime) -> tuple[Status, float | None]:
    """Status and age in hours for one stream."""
    if last is None:
        # An optional stream that has never been written is not broken —
        # it is switched off. Home Assistant may simply not be configured.
        return ("not_configured" if spec.kind == "optional" else "never"), None

    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    age_h = (now - last).total_seconds() / 3600.0

    if spec.kind == "ad_hoc":
        # Reports its age and is never red. A weigh-in 103 days ago is a
        # fact about the user, not a fault in the pipeline, and colouring
        # it as a fault is how the whole card gets ignored.
        return "ad_hoc", age_h
    if spec.kind == "optional" and age_h > spec.stale_after_h:
        # Configured once and now quiet. Worth showing, but as "not
        # currently reporting" rather than as a failure.
        return "not_configured", age_h
    return ("ok" if age_h <= spec.stale_after_h else "stale"), age_h


async def stream_health(db: AsyncSession, *, use_cache: bool = True) -> list[dict[str, Any]]:
    """Freshness per data stream.

    One statement, ten scalar subqueries. Assembling this as ten separate
    round trips costs about three times as much for the same answer.
    """
    global _cache
    now_mono = _time.monotonic()
    if use_cache and _cache is not None and now_mono - _cache[0] < _CACHE_TTL_S:
        return _cache[1]

    # Table and column names come from the STREAMS constant above, never
    # from user input, so the interpolation here is not an injection
    # surface. Written as text() because scalar subqueries over ten
    # different models are far clearer this way than as ORM constructs.
    parts = ", ".join(
        f'(SELECT max("{s.time_col}") FROM {s.table}) AS {s.key}'
        for s in STREAMS
    )
    row = (await db.execute(text(f"SELECT {parts}"))).one()  # noqa: S608
    now = datetime.now(timezone.utc)

    out: list[dict[str, Any]] = []
    for spec in STREAMS:
        last = getattr(row, spec.key, None)
        status, age_h = _classify(spec, last, now)
        out.append({
            "key": spec.key,
            "label": spec.label,
            "kind": spec.kind,
            "source": spec.source,
            "last_at": last.isoformat() if last else None,
            "age_hours": round(age_h, 2) if age_h is not None else None,
            "status": status,
            "stale_after_hours": (
                spec.stale_after_h if spec.kind in ("continuous", "nightly") else None
            ),
        })

    _cache = (now_mono, out)
    return out


async def integration_health(db: AsyncSession) -> list[dict[str, Any]]:
    """Status per external integration, from what each already persists.

    No new table: every integration config row already carries
    `last_sync_at`, and the two that can fail in a user-visible way
    (Strava's cookie session, Google Health's OAuth) already carry
    `last_error`. Aggregating those is the whole job — a new
    `integration_health` table would be a second copy of state that could
    disagree with the first.
    """
    from ..db import models

    now = datetime.now(timezone.utc)

    def entry(
        key: str, label: str, row: Any, *,
        configured: bool | None = None,
        error_attr: str = "last_error",
        stale_after_h: float = 48.0,
    ) -> dict[str, Any]:
        is_configured = configured if configured is not None else row is not None
        last = getattr(row, "last_sync_at", None) if row is not None else None
        err = getattr(row, error_attr, None) if row is not None else None
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        age_h = (now - last).total_seconds() / 3600.0 if last else None

        if not is_configured:
            status = "not_configured"
        elif err:
            status = "error"
        elif age_h is None:
            status = "never"
        elif age_h > stale_after_h:
            status = "stale"
        else:
            status = "ok"

        return {
            "key": key,
            "label": label,
            "configured": bool(is_configured),
            "last_sync_at": last.isoformat() if last else None,
            "age_hours": round(age_h, 2) if age_h is not None else None,
            "last_error": err,
            "status": status,
        }

    async def one(model: Any) -> Any:
        return (await db.execute(select(model).limit(1))).scalar_one_or_none()

    gh = await one(models.GoogleHealthConfig)
    cookie = await one(models.StravaCookieCreds)
    c2 = await one(models.Concept2Credentials)

    out = [
        # Google Health polls on a timer, so a day of silence is a fault.
        entry("google_health", "Google Health", gh,
              configured=bool(gh and getattr(gh, "refresh_token", None)),
              stale_after_h=24.0),
        # Strava is cookie-session and manual: the cookie expires and the
        # sync goes quiet. `last_error` is the signal that matters.
        entry("strava", "Strava", cookie,
              configured=bool(cookie and getattr(cookie, "sid_cookie", None)),
              stale_after_h=24 * 14),
        entry("concept2", "Concept2", c2, stale_after_h=24 * 30),
    ]
    return out
