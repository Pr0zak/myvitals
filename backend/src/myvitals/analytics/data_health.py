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
    # 24 h, not 6 h. Measured over 30 days on this database, the longest
    # real gap between heart-rate samples is 16.4 hours — the watch comes
    # off to charge, and it is not worn every night. A 6 h threshold
    # therefore fires "stale" on perfectly healthy data most weeks, which
    # is precisely the cry-wolf failure the module docstring above warns
    # about: once the card has been wrong three times it gets ignored,
    # and then the one time heart rate really does stop, nobody looks.
    StreamSpec("heart_rate", "Heart rate", "vitals_heartrate", "time",
               "continuous", 24.0, "Watch via phone"),
    StreamSpec("steps", "Steps", "vitals_steps", "time",
               "continuous", 24.0, "Watch via phone"),
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

#: Steps are written by SEVEN sources on this database and `source` is
#: part of the primary key, so they coexist rather than overwrite. Three
#: are currently live; four stopped between May and August.
#:
#: That makes a whole-table `MAX(time)` the wrong question. It stays
#: green as long as ANY writer is active, so the watch feed could die
#: while the phone's built-in pedometer kept the badge fresh — and the
#: watch feed is the one every summary and analytic actually uses, via
#: `pick_canonical_steps_source`. The card would be reassuring about a
#: stream that had stopped, which is the exact failure it exists to
#: catch.
#:
#: `_is_watch_source` is imported rather than re-listed: the keyword list
#: has been extended twice already (for the Fitbit rename and the Google
#: Health rebrand) and a second copy here would silently drift.
_MULTI_SOURCE_STREAMS: frozenset[str] = frozenset({"steps"})


async def _canonical_steps_last(db: AsyncSession) -> datetime | None:
    """Newest step sample from the source the rest of the app trusts.

    Cheap: one grouped MAX over an indexed column, no time predicate
    needed because there is one row per source.
    """
    from .jobs import _is_watch_source

    rows = (await db.execute(text(
        'SELECT source, max("time") AS newest FROM vitals_steps '
        "WHERE source <> 'unknown' GROUP BY source"
    ))).all()
    if not rows:
        return None
    watch = [r for r in rows if r.source and _is_watch_source(r.source)]
    if watch:
        return max(r.newest for r in watch if r.newest is not None)
    # No watch writer at all — fall back to the freshest of whatever is
    # there, which matches what the summaries would do.
    candidates = [r.newest for r in rows if r.newest is not None]
    return max(candidates) if candidates else None

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

    # One extra statement, only for the streams where a whole-table MAX
    # answers the wrong question. See _MULTI_SOURCE_STREAMS.
    canonical: dict[str, datetime | None] = {}
    if "steps" in _MULTI_SOURCE_STREAMS:
        canonical["steps"] = await _canonical_steps_last(db)

    out: list[dict[str, Any]] = []
    for spec in STREAMS:
        last = canonical.get(spec.key) if spec.key in canonical else getattr(row, spec.key, None)
        status, age_h = _classify(spec, last, now)
        out.append({
            "key": spec.key,
            "label": spec.label,
            "kind": spec.kind,
            "source": spec.source,
            # True when this row is judged on one writer among several,
            # so the client can say which rather than implying the table
            # as a whole is being reported.
            "canonical_source_only": spec.key in _MULTI_SOURCE_STREAMS,
            "last_at": last.isoformat() if last else None,
            "age_hours": round(age_h, 2) if age_h is not None else None,
            "status": status,
            "stale_after_hours": (
                spec.stale_after_h if spec.kind in ("continuous", "nightly") else None
            ),
        })

    _cache = (now_mono, out)
    return out


#: Where to look for what an integration has actually IMPORTED, as
#: opposed to whether its poll ran.
#:
#: This is the gap the card had. A poll that succeeds and brings back
#: nothing is indistinguishable, from `last_sync_at` alone, from a poll
#: that succeeds when there genuinely was nothing to bring — and the
#: first of those is precisely how Strava fails here. The cookie expires,
#: the request 401s, the sync completes, and zero rides arrive; CLAUDE.md
#: records that going unnoticed until a reconnect banner was added.
#:
#: Live proof that it is still a gap: Concept2 reports `status: ok` with
#: no error, polling every thirty minutes, and its newest imported
#: session is from three months ago.
#:
#: These numbers get REPORTED, never turned into a red status. A three
#: month gap in erg sessions is a perfectly ordinary thing for a person
#: to do, so inferring breakage from it would generate exactly the false
#: alarm this module is otherwise careful to avoid. Showing "polled 18
#: minutes ago, last imported 102 days ago" side by side lets the user
#: draw a conclusion the app cannot safely draw for them.
_ITEM_PROBES: dict[str, tuple[str, str, str | None]] = {
    # key -> (table, time column, optional SQL predicate)
    "strava": ("activities", "start_at", "source = 'strava'"),
    "concept2": ("activities", "start_at", "source = 'concept2'"),
    # Google Health feeds daily aggregates rather than the activity feed.
    "google_health": ("google_health_daily", "date", None),
}


async def _last_items(db: AsyncSession) -> dict[str, datetime | None]:
    """Newest row each integration has produced, in one statement.

    Same shape as the streams query: table and column names come from the
    constant above, never from user input, so the interpolation is not an
    injection surface. `activities` holds ~2k rows, so the predicate scan
    is immaterial next to the round trip it saves.
    """
    parts = []
    for key, (table, col, pred) in _ITEM_PROBES.items():
        where = f" WHERE {pred}" if pred else ""
        parts.append(f'(SELECT max("{col}") FROM {table}{where}) AS {key}')
    row = (await db.execute(text("SELECT " + ", ".join(parts)))).one()  # noqa: S608
    return {key: getattr(row, key, None) for key in _ITEM_PROBES}


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
    last_items = await _last_items(db)

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

        # What it last actually brought back, beside when it last ran.
        # Deliberately NOT folded into `status` — see _ITEM_PROBES.
        item = last_items.get(key)
        if item is not None and not isinstance(item, datetime):
            # `google_health_daily.date` is a plain calendar date.
            item = datetime(item.year, item.month, item.day, tzinfo=timezone.utc)
        if item is not None and item.tzinfo is None:
            item = item.replace(tzinfo=timezone.utc)
        item_age_h = (now - item).total_seconds() / 3600.0 if item else None

        return {
            "key": key,
            "label": label,
            "configured": bool(is_configured),
            "last_sync_at": last.isoformat() if last else None,
            "age_hours": round(age_h, 2) if age_h is not None else None,
            "last_error": err,
            "status": status,
            # Null, never a zero age, when the integration has produced
            # nothing at all — "imported nothing ever" and "imported
            # nothing lately" are different facts.
            "last_item_at": item.isoformat() if item else None,
            "item_age_hours": round(item_age_h, 2) if item_age_h is not None else None,
            # True when the poll is healthy but nothing has arrived in a
            # long time. A HINT for the client to render as a neutral
            # note, not a fault: the user may simply not have ridden.
            "importing_nothing": bool(
                status == "ok" and item_age_h is not None
                and age_h is not None and item_age_h > 24 * 30
            ),
        }

    async def one(model: Any) -> Any:
        return (await db.execute(select(model).limit(1))).scalar_one_or_none()

    # The OAuth tokens live in a SEPARATE table from the config — the
    # config holds the client id/secret, the credentials hold the refresh
    # token. Testing `refresh_token` on the config row silently reported a
    # working, actively-polling integration as "not connected", which is
    # the one thing this card must never get wrong: it would send you off
    # to re-authorise something that is fine.
    gh_creds = await one(models.GoogleHealthCredentials)
    cookie = await one(models.StravaCookieCreds)
    c2 = await one(models.Concept2Credentials)

    out = [
        # Google Health polls on a timer, so a day of silence is a fault.
        #
        # Everything this needs is on the CREDENTIALS row — refresh_token,
        # last_sync_at and last_error all live there. The config row holds
        # only the client id and secret, so passing it here produced
        # `configured=True, status=never` on an integration that had synced
        # minutes earlier.
        entry("google_health", "Google Health", gh_creds,
              configured=bool(gh_creds and gh_creds.refresh_token),
              stale_after_h=24.0),
        # Strava is cookie-session and manual: the cookie expires and the
        # sync goes quiet. `last_error` is the signal that matters.
        entry("strava", "Strava", cookie,
              configured=bool(cookie and getattr(cookie, "sid_cookie", None)),
              stale_after_h=24 * 14),
        entry("concept2", "Concept2", c2, stale_after_h=24 * 30),
    ]
    return out
