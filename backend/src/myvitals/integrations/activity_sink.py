"""The one place an Activity row is written.

Every provider that ingests a workout -- the live Strava cookie sync, the
retired Strava OAuth path, Concept2 -- had its own upsert, and the
side-effects that are supposed to follow an ingest were attached to some of
them and not others. Three defects came out of that:

**Cardio-day auto-completion was dead.** ``maybe_complete_cardio_day`` was
called from ``integrations/strava.py`` (the retired OAuth path, whose poll was
disabled in v0.7.275) and from Concept2 -- but not from
``strava_web.upsert_activity_from_fit``, which is the only Strava path that
actually runs. So a planned cardio day never closed itself out from a ride,
even though the feature had shipped and the helper was correct.

**Trail linking only happened on demand.** ``_link_activity_to_trail`` had
exactly one caller, inside ``POST /trails/link-activities``, so every newly
synced ride sat unlinked until the user remembered to press a button.

**A re-sync could destroy good data.** The FIT upsert's
``on_conflict_do_update`` wrote ``avg_hr``, ``max_hr`` and ``polyline``
unconditionally. ``parse_fit_bytes`` returns an empty ``ParsedFit`` and logs a
warning rather than raising, so re-syncing an activity whose FIT file failed
to parse silently nulled the heart rate and GPS track already stored against
it.

The sink fixes all three by being the only writer. Two rules keep it safe:

* **Skip None, but only for provider-derived columns.** A provider that has
  nothing to say about a field must not erase what an earlier, richer sync
  stored. That reasoning does not extend to user-owned columns -- ``notes``,
  ``tags`` and ``trail_id`` belong to the user, where clearing a value is a
  deliberate act and None legitimately means "remove this". Those are never
  touched here at all.
* **Auto-link a trail only when there is none.** A user who deliberately
  unlinked an activity must not have the proximity heuristic put it back on
  the next sync.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import models

log = logging.getLogger(__name__)

# Columns a provider is allowed to write. Deliberately an allowlist rather
# than "everything except the user's": a new column added to the model
# should have to be considered here rather than silently becoming
# provider-writable.
PROVIDER_COLUMNS: tuple[str, ...] = (
    "type", "name", "start_at", "duration_s", "distance_m",
    "elevation_gain_m", "avg_hr", "max_hr", "avg_power_w", "max_power_w",
    "kcal", "suffer_score", "polyline", "raw",
    "hr_recovery_60s", "hr_recovery_120s",
)

# Columns the user owns. Listed so the rule is documented in code rather than
# implied by their absence from the allowlist above.
USER_OWNED_COLUMNS: tuple[str, ...] = ("notes", "tags", "trail_id")


# ── HC-1: Health Connect exercise sessions → the activities feed ─────
#
# `ExerciseSessionRecord` has always been read from Health Connect and
# written to the `workouts` table, which nothing user-facing reads. The
# Activities feed is built from `activities`, so a session the watch
# recorded but Strava never saw was invisible.
#
# On this database that was 11 of the 22 sessions since June — including a
# 2h23m ride on 2026-06-19 and a 1h30m ride the following day. Rides that
# reach Strava were covered; walks and any ride not uploaded were not.

#: Health Connect's exercise type → the label the Activities feed uses.
#:
#: The `activities.type` vocabulary is provider-specific and inconsistent
#: (`walk` and `walking` both exist, alongside
#: `walking,_2.5_mph,_leisurely_pace_(myfitnesspal)`), which is a
#: pre-existing taxonomy problem this mapping does not try to solve. It
#: only picks the spelling already dominant in the table, so promoted rows
#: get the same icon and match the same filter chips as everything else.
HC_TYPE_MAP: dict[str, str] = {
    "biking": "cycling",
    "walking": "walking",
    "running": "running",
    "hiking": "hiking",
    "swimming": "swimming",
    "rowing": "indoor_rowing",
    "strength_training": "strength_training",
    "other": "workout",
}

#: A promoted session claims this source so it is distinguishable in the
#: feed and can be re-promoted idempotently.
HC_SOURCE = "healthconnect"


async def _retire_promotion(
    db: AsyncSession, source_id: str, reason: str,
) -> bool:
    """Remove a promoted Health Connect row that should no longer be there.

    Promotion decides once, at the moment it runs, and both of its skip rules
    can become true LATER — a second Health Connect recording arrives, or a
    richer provider finally syncs. Skipping a session it has already promoted
    changes nothing on screen, so the scan has to be able to take a row back.

    Deliberately conservative, and returns False rather than deleting when it
    cannot be sure:

    * Scoped to `HC_SOURCE` and one `source_id`, so it can never reach a
      Strava or Concept2 row carrying GPS and power data this function could
      not reconstruct.
    * Vetoed by any of `USER_OWNED_COLUMNS`. A row the user has annotated or
      linked to a trail records a decision this function did not make, and
      losing that silently is worse than showing one duplicate. Such a row
      stays and is reported.

    Same discipline as MEAL-3's shopping list, where only a demonstrably
    complete cancellation may drop a line.
    """
    stale = (await db.execute(
        select(models.Activity)
        .where(models.Activity.source == HC_SOURCE)
        .where(models.Activity.source_id == source_id)
        .limit(1)
    )).scalar_one_or_none()
    if stale is None:
        return False
    if any(getattr(stale, col, None) for col in USER_OWNED_COLUMNS):
        log.info(
            "activity_sink: keeping HC promotion %s (%s) — it carries "
            "user-owned data", source_id, reason,
        )
        return False
    await db.execute(
        delete(models.Activity)
        .where(models.Activity.source == HC_SOURCE)
        .where(models.Activity.source_id == source_id)
    )
    log.info("activity_sink: retired HC promotion %s (%s)", source_id, reason)
    return True


def is_duplicate_recording(
    start: datetime,
    end: datetime,
    activity_type: str,
    kept: list[tuple[datetime, datetime, str]],
) -> datetime | None:
    """The start of an earlier session this one is a second recording of.

    Pure so the rule can be tested directly; the database half of the same
    question is the identical predicate expressed in SQL.

    Two conditions, both required:

    * **The intervals overlap.** Not a ± window around the start, because
      each recorder stamps its own start instant — the pair that prompted
      this began 4.4 s apart and ended 0.6 s apart.
    * **The type matches.** A strength session logged during a long walk
      overlaps legitimately, and merging those loses real work.

    Only a strictly EARLIER session can claim a later one, and that
    asymmetry is load-bearing rather than a tidy-up: a symmetric test would
    have each of a pair block the other, so both would be dropped and the
    duplicate could never be resolved. Earliest wins is also stable across
    runs, which is what stops the feed reordering itself between syncs.
    """
    best: datetime | None = None
    for k_start, k_end, k_type in kept:
        if k_type != activity_type:
            continue
        if k_start >= start:
            continue
        if k_start < end and start < k_end:
            if best is None or k_start < best:
                best = k_start
    return best


async def promote_health_connect_workouts(
    db: AsyncSession, since: datetime | None = None,
) -> dict[str, int]:
    """Copy Health Connect exercise sessions into the activities feed.

    Skips any session that OVERLAPS an activity from a different provider.
    Overlap rather than start-time proximity, because the same ride gets a
    different start instant from each recorder — Strava starts on the
    first GPS fix, the watch on the button press — and a fixed ± window
    either misses real duplicates or merges genuinely separate sessions.

    Providers with GPS are strictly richer: they carry distance, elevation
    and a polyline that Health Connect's session record does not. So when
    both have a session, the existing one wins and this does nothing. This
    fills gaps; it never overwrites.

    That skip is also applied RETROSPECTIVELY, because promotion decides once
    and the richer provider usually arrives second. Strava here is synced by
    hand from a cookie session, so a ride reaches Health Connect within the
    hour and Strava days later — the ride on 2026-08-30 promoted from Health
    Connect immediately and Strava landed two days after, at which point the
    feed held both. Skipping a session already promoted changes nothing on
    screen, so a scan that finds a clash now retires the row it created.

    That same reasoning applies WITHIN Health Connect, which the first cut
    missed: the cross-provider clash query excludes `HC_SOURCE`, so two HC
    sessions describing one ride each promoted independently. A ride on
    2026-08-30 arrived twice from `com.fitbit.FitbitMobile`, starting 4.4 s
    apart and ending 0.6 s apart, and appeared twice in the feed. Because
    `source_id` is the start instant, the two never collided on the primary
    key. This is the same shape as the multi-source step over-count that
    `pick_canonical_steps_source` exists to solve — several Health Connect
    writers publishing one underlying event.

    So a session is also skipped when it overlaps an EARLIER session of the
    same type already kept in this scan. Earliest start wins, which is
    arbitrary between near-identical rows but is deterministic, and
    determinism is what makes re-running produce the same feed. Sessions are
    read oldest-first for exactly that reason.

    Matching on type as well as interval is deliberate. Two different
    activities can legitimately overlap — a strength session logged during a
    long walk — and merging those would lose real work. Two sessions of the
    SAME type covering the same minutes are one event seen twice.

    Idempotent — re-running promotes nothing new. Safe to call on every
    ingest and to re-run over history.
    """
    stmt = select(models.Workout).order_by(models.Workout.time)
    if since is not None:
        stmt = stmt.where(models.Workout.time >= since)
    sessions = (await db.execute(stmt)).scalars().all()

    promoted = already_present = skipped_overlap = skipped_untimed = 0
    skipped_duplicate = removed_duplicate = removed_superseded = 0
    # (start, end, type) for every session kept in this scan, so a later
    # session can be recognised as a second recording of one already taken.
    kept: list[tuple[datetime, datetime, str]] = []

    for w in sessions:
        if not w.duration_s or w.duration_s <= 0:
            # A zero-length session has no interval to compare and nothing
            # useful to show.
            skipped_untimed += 1
            continue

        start = w.time
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        end = start + timedelta(seconds=int(w.duration_s))

        # Any activity from ANOTHER source whose interval overlaps this
        # one. `duration_s` may be null on older rows, so coalesce to 0 —
        # a zero-length existing row then only matches an exact start,
        # which is the conservative reading.
        clash = (await db.execute(
            select(models.Activity.source_id)
            .where(models.Activity.source != HC_SOURCE)
            .where(models.Activity.start_at < end)
            # `existing.start + existing.duration > hc_start`, expressed as
            # a seconds difference rather than by constructing an INTERVAL.
            # SQLAlchemy's generic `func` takes no keyword arguments, so
            # `make_interval(secs=…)` does not compile; EXTRACT(EPOCH …) is
            # the portable form and reads as the same inequality.
            .where(
                func.extract("epoch", start - models.Activity.start_at)
                < func.coalesce(models.Activity.duration_s, 0)
            )
            .limit(1)
        )).scalar_one_or_none()

        hc_type = HC_TYPE_MAP.get(
            (w.type or "").lower(), (w.type or "workout").lower(),
        )
        source_id = start.isoformat()

        if clash is not None:
            skipped_overlap += 1
            # The richer provider may have arrived AFTER this session was
            # promoted, which is the normal case here rather than an edge
            # one: Strava is synced manually from a cookie session, so a
            # ride reaches Health Connect within the hour and Strava days
            # later. Skipping a row already in the feed changes nothing on
            # screen, so take it back — the provider that clashed carries
            # the distance and the GPS track this row never had.
            if await _retire_promotion(db, source_id, "superseded by a richer provider"):
                removed_superseded += 1
            continue

        # A second Health Connect recording of a session already taken in
        # this scan. Same type, overlapping minutes.
        twin = is_duplicate_recording(start, end, hc_type, kept)
        # The in-memory list only covers the scan window, and `since` is the
        # earliest workout in an ingest batch — so a batch carrying only the
        # LATER of the pair would start its scan past the winner and promote
        # the loser again. Ask the table too.
        #
        # Strictly earlier, never merely overlapping, and that asymmetry is
        # the whole point: a mutual test would have each row block the other
        # once both exist, so both would be skipped and the duplicate would
        # become permanent. An earliest-wins test can never block the winner,
        # because nothing precedes it.
        if twin is None:
            twin = (await db.execute(
                select(models.Activity.start_at)
                .where(models.Activity.source == HC_SOURCE)
                .where(models.Activity.type == hc_type)
                .where(models.Activity.start_at < start)
                .where(models.Activity.start_at < end)
                .where(
                    func.extract("epoch", start - models.Activity.start_at)
                    < func.coalesce(models.Activity.duration_s, 0)
                )
                .limit(1)
            )).scalar_one_or_none()
        if twin is not None:
            skipped_duplicate += 1
            # Self-heal a duplicate promoted before this rule existed.
            if await _retire_promotion(
                db, source_id, f"duplicate {hc_type} of {twin.isoformat()}",
            ):
                removed_duplicate += 1
            continue

        # Distinguish a new promotion from a re-promotion. The upsert
        # below is idempotent either way, but a run that created nothing
        # must not report that it promoted twelve sessions — this endpoint
        # exists to say what it did, so the count has to be true.
        exists = (await db.execute(
            select(models.Activity.source_id)
            .where(models.Activity.source == HC_SOURCE)
            .where(models.Activity.source_id == source_id)
            .limit(1)
        )).scalar_one_or_none()

        await upsert_activity(
            db,
            {
                "source": HC_SOURCE,
                # The workouts PK is `time`, so the ISO instant is a stable
                # natural key: re-promoting the same session updates its
                # row rather than creating a second one.
                "source_id": source_id,
                "type": hc_type,
                "start_at": start,
                "duration_s": int(w.duration_s),
                "avg_hr": w.avg_hr,
                "max_hr": w.max_hr,
                "kcal": w.kcal,
                # `name` deliberately omitted. `workouts.title` comes from
                # whichever app wrote the HC record, and the feed already
                # renders the type; a borrowed title adds nothing and can
                # carry a location.
            },
            # No GPS on these, so there is no trail to match.
            link_trail=False,
        )
        kept.append((start, end, hc_type))
        if exists is None:
            promoted += 1
        else:
            already_present += 1

    return {
        "promoted": promoted,
        "already_present": already_present,
        "skipped_overlap": skipped_overlap,
        "skipped_duplicate": skipped_duplicate,
        "removed_duplicate": removed_duplicate,
        "removed_superseded": removed_superseded,
        "skipped_untimed": skipped_untimed,
        "considered": len(sessions),
    }


async def upsert_activity(
    db: AsyncSession,
    values: dict[str, Any],
    *,
    link_trail: bool = True,
    complete_cardio_day: bool = True,
) -> models.Activity | None:
    """Insert or update one activity, then run the ingest side-effects.

    ``values`` must carry ``source`` and ``source_id``; everything else is
    optional, and any provider column whose value is None is left alone on
    an update rather than overwriting what is already stored.

    Returns the persisted row. Does not commit -- the caller owns the
    transaction, because most callers are ingesting a batch.
    """
    source = values.get("source")
    source_id = values.get("source_id")
    if not source or not source_id:
        raise ValueError("upsert_activity requires source and source_id")

    insert_values = {
        k: v for k, v in values.items()
        if k in PROVIDER_COLUMNS or k in ("source", "source_id")
    }
    # A brand-new row still needs the NOT NULL columns to have something.
    insert_values.setdefault("type", "workout")
    insert_values.setdefault("duration_s", 0)

    update_set = {
        k: v for k, v in insert_values.items()
        if k in PROVIDER_COLUMNS and v is not None
    }

    # polyline_simple is derived from polyline. When a sync brings a new
    # track the cached simplification is stale, so drop it and let the map
    # endpoint recompute lazily. Only when the polyline actually changed --
    # clearing it on every sync would make the map recompute forever.
    existing = (await db.execute(
        select(models.Activity)
        .where(models.Activity.source == source)
        .where(models.Activity.source_id == source_id)
    )).scalar_one_or_none()
    new_polyline = update_set.get("polyline")
    if new_polyline is not None and existing is not None and existing.polyline != new_polyline:
        update_set["polyline_simple"] = None

    stmt = pg_insert(models.Activity).values(**insert_values)
    if update_set:
        stmt = stmt.on_conflict_do_update(
            index_elements=["source", "source_id"], set_=update_set,
        )
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=["source", "source_id"])
    await db.execute(stmt)

    act = (await db.execute(
        select(models.Activity)
        .where(models.Activity.source == source)
        .where(models.Activity.source_id == source_id)
    )).scalar_one_or_none()
    if act is None:
        return None

    if complete_cardio_day:
        from .cardio_completion import maybe_complete_cardio_day
        try:
            await maybe_complete_cardio_day(
                db,
                source=act.source,
                source_id=act.source_id,
                activity_type=act.type,
                start_at=act.start_at,
                duration_s=act.duration_s,
            )
        except Exception:  # noqa: BLE001
            # A side-effect must never cost us the ingest itself. The row is
            # the valuable part; a missed cardio-day flip is recoverable by
            # the next sync or by hand.
            log.warning("cardio-day completion failed for %s/%s",
                        act.source, act.source_id, exc_info=True)

    if link_trail and act.trail_id is None and act.polyline:
        try:
            await _auto_link_trail(db, act)
        except Exception:  # noqa: BLE001
            log.warning("trail auto-link failed for %s/%s",
                        act.source, act.source_id, exc_info=True)

    return act


async def _auto_link_trail(db: AsyncSession, act: models.Activity) -> None:
    """Attach the nearest trail, if the ride started within range of one.

    Guarded on ``trail_id is None`` by the caller: the proximity heuristic is
    a starting guess, and a user who has deliberately unlinked an activity
    should not have it silently relinked on the next sync.
    """
    from ..api.trails import _link_activity_to_trail

    trails = (await db.execute(
        select(models.Trail)
        .where(models.Trail.latitude.is_not(None))
        .where(models.Trail.longitude.is_not(None))
    )).scalars().all()
    if not trails:
        return
    await _link_activity_to_trail(db, act, list(trails))
