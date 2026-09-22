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

**Health Connect dedupe runs from both sides, and still only ever deletes a
Health Connect row.**

``reconcile_promotions`` closes the half that was missing: a provider sync
that supersedes an already-promoted session now takes the duplicate back
itself, instead of waiting for a later Health Connect batch to happen to
contain that session again (for one recorded days ago, never).

Choosing the survivor genuinely on content — sometimes deleting the provider
row — was considered and rejected, and the reason is structural rather than
a preference:

* **Deleting a promotion is terminal; deleting a provider row is a loop.**
  ``promote_health_connect_workouts`` checks for a clash BEFORE it writes, so
  once a provider row exists the promotion is never recreated and the
  decision is settled for good. No provider sync has an equivalent check —
  ``strava_web`` and ``concept2`` call ``upsert_activity`` unconditionally —
  so a deleted Strava row is rebuilt by the next cookie sync, reconciled
  away again, and rebuilt again, re-downloading the FIT and re-cutting the
  heart-rate window every time. Making that safe needs a tombstone table,
  which is a new schema concept whose own failure mode (a tombstone that
  outlives its reason silently suppressing a real activity) is worse than
  the duplicate it prevents.
* **A provider row's identity cannot be carried.** ``source_id`` IS the
  Strava activity id, and ``raw`` is that provider's payload in that
  provider's schema. There is no way to move either onto a Health Connect
  row, so "carry everything, then delete" is not actually available in that
  direction. ``strength_workouts.completed_by_activity_source(_id)`` also
  points at an activity by that pair with no foreign key behind it.

So the scope stays. What changes is that the CARRY is complete rather than
gap-filling (``CARRYABLE_COLUMNS``), and that the GPS track is chosen on
measured coverage rather than on which provider wrote it
(``track_is_materially_better``) — because SA-P3 falsified the premise the
old rule rested on, that a provider row is strictly the richer one.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, delete, func, or_, select
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
    # SA-P3. Why there is no polyline, when the provider could say. Listed
    # here so the skip-None rule governs it like every other provider
    # column: a pass that has nothing to say about the route must not
    # erase what an earlier pass learned.
    "route_state",
)

# Columns the user owns. Listed so the rule is documented in code rather than
# implied by their absence from the allowlist above.
USER_OWNED_COLUMNS: tuple[str, ...] = ("notes", "tags", "trail_id")

# Columns a retiring duplicate may hand to the row that survives it.
#
# `_retire_promotion` DELETES a row, so anything that row alone holds is
# gone unless it moves first. Until SA-P3 the carry was a special case for
# the two columns that had been noticed (the user's own, then the route),
# which is the wrong shape: the question is not "which fields did we
# remember to think about" but "which fields can be lost". Derived from
# `PROVIDER_COLUMNS` so a column added there has to be considered here too.
#
# Four are deliberately excluded, and not because they are unimportant:
#
# * `type`, `start_at`, `duration_s` -- the survivor's OWN account of the
#   event. A second recorder disagreeing about when a walk started is not a
#   gap in the survivor's row, and splicing one recorder's duration onto
#   another's start produces an interval neither of them observed.
# * `name` -- Health Connect promotions never set it, on purpose: it comes
#   from whichever app wrote the record and is exactly the field that
#   carries a location (`test_hc_promotion.TestPrivacy`). Carrying it here
#   would reintroduce that by the back door.
# * `raw` -- the provider's own payload, in the provider's own schema.
#   Merging two providers' blobs into one column makes it unreadable by
#   whoever parses it, and the survivor's next sync overwrites the column
#   wholesale anyway, so a carried value would silently disappear.
#
# `polyline` IS in the set, but it does not use the plain gap-fill rule --
# see `track_is_materially_better`.
_NOT_CARRYABLE: frozenset[str] = frozenset({
    "type", "name", "start_at", "duration_s", "raw",
})
CARRYABLE_COLUMNS: tuple[str, ...] = tuple(
    c for c in PROVIDER_COLUMNS if c not in _NOT_CARRYABLE
)

#: How much more of a route one track has to describe before it displaces
#: another.
#:
#: Sourced from the overlapping pairs in this database that carry a track on
#: BOTH sides -- the only direct evidence available for what two recordings
#: of one event look like. There are four. Their span ratios (larger over
#: smaller) are 1.00, 1.08, 3.51 and 11.83; their path ratios are 1.22,
#: 1.90, 3.07 and 3.68. Both distributions are bimodal with an empty band in
#: the middle, and the two pairs above the band are the ones where the
#: loser is visibly a fragment: a 149 m bounding box for a walk both rows
#: agree was 1,965.9 m, and a 1,096 m box for a 20,940 m ride. The two below
#: it describe the same ground at different sampling rates. 2.0 sits inside
#: both empty bands.
#:
#: It is close to the top of the path band (1.90), and that costs nothing:
#: the pair at 1.90 is the one where both tracks cover an identical 771 m
#: box, so swapping or not swapping there changes which sampling of the
#: same route is kept and loses no part of it.
TRACK_MARGIN = 2.0


def track_is_materially_better(
    candidate: str | None, incumbent: str | None,
) -> bool:
    """Does `candidate` describe materially more of the route than `incumbent`?

    The premise the dedupe was built on -- "providers with GPS are strictly
    richer" -- was true until SA-P3 and is now false: a Health Connect row
    can carry a route, and on 2026-09-19 it carried a 5,598-point track
    while the Strava row that beat it carried none at all. So a track has to
    be compared on its content.

    **Not by point count.** It is the available and obvious number and it is
    the wrong one. Every provider track here is decimated before storage --
    `fit_tracks._MAX_POLYLINE_POINTS` caps a FIT decode at 500 points, and
    the retired OAuth path stored Strava's server-thinned
    `map.summary_polyline` -- where a Health Connect route is the raw sample
    stream. Measured on production: Strava's median track is 334 points and
    the single Health Connect route is 5,598. Point count would hand Health
    Connect every contested decision seventeen times over, for a reason that
    is entirely about the encoder. Worse, it points the wrong way on real
    data: of the four overlapping pairs in this table where both rows carry
    a track, the denser side has more points in all four and is the poorer
    description of the route in three -- including 1,760 points confined to
    a 149 m box for a walk of 1,965.9 m.

    So: coverage, measured two ways by `geo.track_extent`, both invariant to
    sampling rate.

    * **Span** -- the bounding-box diagonal. This is what collapses when a
      track is truncated or is a stationary fragment, and it is immune to
      the jitter that inflates a 1 Hz stream's length.
    * **Path** -- the traversed length, as a second opinion for the case
      span is blind to: half the laps of a circuit reach the same ground.
      Only consulted when the spans are comparable, so a jittery fragment
      cannot win on length alone.

    Gap-filling is the same question with a trivial answer: any track beats
    none.

    Equal coverage keeps the INCUMBENT, which is what makes the outcome
    stable. It is also why nothing is lost by keeping a decimated track over
    a raw one: this app renders tracks through `geo.simplify_encoded`, whose
    own sourced constants say 400 points and ~11 m of detail are enough for
    every map it draws, and `fit_tracks` says 500 is "plenty" for the detail
    view. Two tracks that reach the same ground are the same track to every
    consumer here.
    """
    if not candidate:
        return False
    if not incumbent:
        return True

    from ..analytics.geo import track_extent

    cand_span, cand_path = track_extent(candidate)
    inc_span, inc_path = track_extent(incumbent)
    if cand_span <= 0.0 and cand_path <= 0.0:
        # Undecodable, empty, or a single point. Never displaces a track
        # that measures as something.
        return False
    if cand_span >= inc_span * TRACK_MARGIN:
        return True
    # Comparable ground covered -- now the length is allowed to speak. The
    # span floor is what stops a track that wanders inside a small box from
    # beating one that actually goes somewhere.
    return (
        cand_span * TRACK_MARGIN >= inc_span
        and cand_path >= inc_path * TRACK_MARGIN
    )


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

#: Mapped labels that say only "some exercise happened".
#:
#: Health Connect's `other` is the bucket a writer uses when it has not
#: classified the session, and `HC_TYPE_MAP` renders it as the feed's generic
#: `workout`. Two recordings of one ride can disagree here while agreeing on
#: everything else, which is how the 2026-09-13 duplicate got through: the
#: Fitbit app wrote the same ride twice, 4.2 s apart, once as `other` and once
#: as `biking`, so the type-equality test saw `workout` against `cycling` and
#: let both into the feed.
#:
#: Membership is deliberately narrow. A label that names an activity — even a
#: vague one like `hiking` — is a claim about what was done and must keep the
#: protection that two different types overlapping are two different sessions.
GENERIC_TYPES: frozenset[str] = frozenset({"workout"})


async def _retire_promotion(
    db: AsyncSession,
    source_id: str,
    reason: str,
    *,
    winner: models.Activity | None = None,
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
    * Any of `USER_OWNED_COLUMNS` set on the row is a decision this function
      did not make, and losing it silently is worse than showing one
      duplicate.

    `winner` is the row this one is a duplicate of, and it turns that second
    rule from a veto into a transfer. The two rows describe ONE event, so
    which of them holds the user's trail link is an implementation detail
    they never chose — on 2026-09-13 the user linked the ride to a trail and
    happened to link the copy the dedupe rule discards, which under a plain
    veto would have kept the duplicate on screen permanently. The value moves
    to the survivor and the row goes.

    The veto still stands where a transfer would destroy something: no winner
    to carry to, or a winner that already holds a DIFFERENT value in that
    column. Two different trails on two rows is a genuine conflict between
    two of the user's own decisions, and this is not the code to resolve it.

    Every other column the row holds is carried too, not just the ones
    someone noticed — `CARRYABLE_COLUMNS`, gap-filled. A function that
    deletes a row has to answer "what can be lost here", and answering it
    one field at a time is how the GPS track came to be at risk for a
    release.

    The track (SA-P3) is the one column where a value can displace another
    value rather than only fill a hole, because two tracks of one event are
    two descriptions of the same route and one of them can be strictly more
    of it. Which one is decided by `track_is_materially_better`, on measured
    coverage — not by which provider wrote it, and not by point count.

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

    carried = {
        col: getattr(stale, col, None)
        for col in USER_OWNED_COLUMNS
        if getattr(stale, col, None)
    }
    if carried:
        if winner is None:
            log.info(
                "activity_sink: keeping HC promotion %s (%s) — it carries "
                "user-owned data and there is no surviving row to move it to",
                source_id, reason,
            )
            return False
        conflicts = [
            col for col, val in carried.items()
            if getattr(winner, col, None) and getattr(winner, col, None) != val
        ]
        if conflicts:
            log.info(
                "activity_sink: keeping HC promotion %s (%s) — %s would "
                "overwrite the surviving row's own value",
                source_id, reason, ", ".join(sorted(conflicts)),
            )
            return False
        for col, val in carried.items():
            setattr(winner, col, val)
        log.info(
            "activity_sink: carried %s from HC promotion %s to %s/%s",
            ", ".join(sorted(carried)), source_id,
            winner.source, winner.source_id,
        )

    # Everything else this row holds that the survivor does not.
    #
    # This used to be two hand-picked columns -- the user's own, then the
    # route when SA-P3 made one possible -- which is the wrong shape for a
    # function that deletes a row. The question is not "which fields did
    # someone remember" but "which fields can be lost", so the carry is
    # driven off `CARRYABLE_COLUMNS` and a new provider column has to be
    # classified there rather than quietly falling through the gap.
    #
    # Plain gap-fill: a value beats no value. Two values are two recorders'
    # own measurements of one event, and a row assembled from both is a row
    # neither of them observed, so the survivor's own account stands
    # unaltered. `polyline` is the one exception and is handled below --
    # there a second value can be strictly MORE of the same route rather
    # than a competing opinion about it.
    if winner is not None:
        filled = []
        for col in CARRYABLE_COLUMNS:
            if col == "polyline":
                continue
            val = getattr(stale, col, None)
            if val is None or getattr(winner, col, None) is not None:
                continue
            setattr(winner, col, val)
            filled.append(col)
        if filled:
            log.info(
                "activity_sink: filled %s on %s/%s from HC promotion %s",
                ", ".join(sorted(filled)), winner.source, winner.source_id,
                source_id,
            )

    # SA-P3 — the track is not user-owned, and until routes existed there
    # was never one on a promoted row, so it was never at risk here. Now
    # there can be, and this function DELETES the row.
    #
    # The 2026-09-19 walk is the case, and it is the case that falsified the
    # rule above it. Health Connect published the walk with a 5,598-point
    # route; Strava published the same walk with NO polyline at all. The
    # dedupe called Strava the richer provider on principle, kept it, and
    # only came out right because the carry moved the track across. The rule
    # picked the wrong winner and a transfer undid it -- which works exactly
    # once, in the case where the winner happens to hold nothing.
    #
    # So the carry is no longer gap-filling. It asks which track describes
    # more of the route (`track_is_materially_better`), and a Strava or
    # Garmin recording keeps its own unless the Health Connect one is
    # materially more of the same ride. `polyline_simple` is a cached
    # simplification of the OLD value and has to go with it -- same
    # reasoning as `upsert_activity`.
    #
    # The same day is also the intra-Health-Connect case, which the coverage
    # rule handles by the same comparison: TWO Health Connect writers
    # published that walk, `com.fitbit.FitbitMobile` at 8217 s and
    # `nl.appyhapps.healthsync` at 8213 s, four seconds apart, both answering
    # CONSENT_REQUIRED to the probe. Nothing says the one the dedupe keeps is
    # the one whose route Health Connect released, and losing the only copy
    # of a track the user had just granted access to would look exactly like
    # the grant not working.
    if winner is not None and track_is_materially_better(
        stale.polyline, winner.polyline,
    ):
        winner.polyline = stale.polyline
        winner.polyline_simple = None
        log.info(
            "activity_sink: carried the route from HC promotion %s to %s/%s "
            "before retiring it",
            source_id, winner.source, winner.source_id,
        )

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
    others: list[tuple[datetime, datetime, str]],
) -> datetime | None:
    """The start of a session this one is a second recording of.

    Pure so the rule can be tested directly; the database half of the same
    question is the identical predicate expressed in SQL.

    **The intervals must overlap.** Not a ± window around the start, because
    each recorder stamps its own start instant — the pair that prompted this
    began 4.4 s apart and ended 0.6 s apart.

    Given an overlap, which of the two is the duplicate is decided by type:

    * **Same type — the earlier one wins.** That asymmetry is load-bearing
      rather than a tidy-up: a symmetric test would have each of a pair block
      the other, so both would be dropped and the duplicate could never be
      resolved. Earliest wins is also stable across runs, which is what stops
      the feed reordering itself between syncs.
    * **A named type beats a generic one, in either direction.** A session
      labelled `other` says only that exercise happened; one labelled `biking`
      over the same minutes is the same event, described better. Start order
      is the wrong tiebreak here — on 2026-09-13 the uninformative recording
      came first, so earliest-wins alone would have kept "workout" and
      discarded "cycling". Still antisymmetric: a named session is never
      claimed by a generic one, so every cluster keeps a winner.
    * **Two different named types never match.** A strength session logged
      during a long walk overlaps legitimately, and merging those loses real
      work. This is the case `GENERIC_TYPES` is kept narrow to protect.

    The cost of the generic rule is a genuinely unclassified session that
    overlaps a named one — a stretching block logged as `other` during a walk
    recorded by another app — which is absorbed into the walk. That is the
    same trade the module already makes elsewhere: an unlabelled recording
    cannot be told apart from an unlabelled duplicate, and the duplicate is
    overwhelmingly the commoner case on this data.
    """
    generic = activity_type in GENERIC_TYPES
    best: datetime | None = None
    for k_start, k_end, k_type in others:
        if not (k_start < end and start < k_end):
            continue
        if k_type == activity_type:
            # Same label: only a strictly earlier recording may claim this
            # one, so the first of a pair can never be claimed itself.
            if k_start >= start:
                continue
        elif not (generic and k_type not in GENERIC_TYPES):
            # Either this session is the named one (it wins, whatever the
            # order), or both are named but disagree (two real sessions).
            continue
        if best is None or k_start < best:
            best = k_start
    return best


def _hc_activity_values(
    w: models.Workout,
    hc_type: str,
    start: datetime,
    source_id: str,
    distance_by_start: dict[str, float] | None,
    polyline_by_start: dict[str, str] | None = None,
    route_state_by_start: dict[str, str] | None = None,
) -> dict[str, Any]:
    """The row `promote_health_connect_workouts` hands to `upsert_activity`.

    Pulled out as a pure function so the distance wiring can be tested
    without a database: `models.Workout` and `models.Activity` are plain
    ORM classes and can be built directly, the way the rest of this test
    suite already builds fake rows for `_retire_promotion`.

    `distance_by_start` is looked up by `source_id`, not defaulted to 0.0
    when the key is absent -- an indoor session genuinely has no distance,
    and `.get()` already returns None for that case. None is exactly what
    `upsert_activity` needs: it inserts it as a real NULL on a brand-new
    row, and its skip-None rule means an UPDATE never uses it to blank out
    a distance a richer provider (or an earlier call to this same function,
    with batch data this one lacks) already stored.

    `polyline_by_start` (SA-P3) is the same side-channel, carrying a Google
    encoded polyline at precision 5 -- byte-identical in shape to what
    Strava stores in this column, so the existing Leaflet renderers on both
    clients need no change. It obeys the same None rule for the same
    reason, which matters more here than for distance: a Health Connect
    route is a watch track, and it must never be written over a row a
    richer provider already filled.

    `route_state_by_start` records WHY there is no polyline, when Health
    Connect was asked and could answer -- "consent_required" or "none".
    Absent means nobody asked, and that is a third state, not a synonym
    for "none"; see the 0068 migration.
    """
    return {
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
        "distance_m": (distance_by_start or {}).get(source_id),
        "polyline": (polyline_by_start or {}).get(source_id),
        "route_state": (route_state_by_start or {}).get(source_id),
        # `name` deliberately omitted. `workouts.title` comes from
        # whichever app wrote the HC record, and the feed already
        # renders the type; a borrowed title adds nothing and can
        # carry a location.
    }


async def promote_health_connect_workouts(
    db: AsyncSession,
    since: datetime | None = None,
    distance_by_start: dict[str, float] | None = None,
    polyline_by_start: dict[str, str] | None = None,
    route_state_by_start: dict[str, str] | None = None,
) -> dict[str, int]:
    """Copy Health Connect exercise sessions into the activities feed.

    Skips any session that OVERLAPS an activity from a different provider.
    Overlap rather than start-time proximity, because the same ride gets a
    different start instant from each recorder — Strava starts on the
    first GPS fix, the watch on the button press — and a fixed ± window
    either misses real duplicates or merges genuinely separate sessions.

    **The provider row is the one that survives — but not because it is the
    richer one.** Three successive versions of this paragraph claimed it
    was, and measurement has now falsified all three. The first said Health
    Connect's session record carries no distance at all: true of the
    *session* record, but Health Connect also exposes a `DistanceRecord`
    aggregate over the session's own window, which `HealthConnectGateway`
    now reads (SA-P1). The second said it has "no equivalent" for a
    polyline: it does — `ExerciseRouteResult` carries one, and the probe
    that shipped with SA-P1 came back `CONSENT_REQUIRED`, meaning a route
    existed and was being withheld (SA-P3). The third, that a provider
    track is full-fidelity where Health Connect's is whatever the writing
    app published, is backwards: every provider track here is decimated
    before storage at `fit_tracks._MAX_POLYLINE_POINTS`, and on 2026-09-19
    the Health Connect row held a 5,598-point route while the Strava row
    that beat it held none at all.

    What actually makes the provider row the right survivor is that the
    delete has to be safe and has to stay decided — see the module
    docstring. The CONTENT question is answered separately, by carrying
    everything the retired row holds onto the survivor
    (`CARRYABLE_COLUMNS`) and by choosing the GPS track on measured
    coverage (`track_is_materially_better`). So this still fills gaps and
    never overwrites; it no longer assumes which side the gap is on.

    ``distance_by_start`` is an optional ``{start.isoformat(): meters}`` map
    for the distance Health Connect reported for each session, keyed the
    same way ``source_id`` is below. It comes from the caller because the
    `workouts` table itself has no `distance_m` column — only `activities`
    does, and that is deliberate: this function fills a gap in an existing
    field rather than growing the raw ingest schema. A caller with no batch
    context (the post-Strava-sync rescan in `strava.py`) passes nothing, and
    `upsert_activity`'s None-skip rule means that never erases a distance an
    earlier promotion already wrote — it only ever fails to *add* one.

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

    So a session is also skipped when another session in the scan overlaps it
    and beats it — see `is_duplicate_recording` for which of an overlapping
    pair that is. Between two recordings carrying the same label the earlier
    one wins, which is arbitrary between near-identical rows but is
    deterministic, and determinism is what makes re-running produce the same
    feed.

    Matching on type as well as interval is deliberate. Two different
    activities can legitimately overlap — a strength session logged during a
    long walk — and merging those would lose real work. Two sessions of the
    SAME type covering the same minutes are one event seen twice.

    The exception, and the 2026-09-13 report: Health Connect's `other` is not
    a type, it is the absence of one. The Fitbit app wrote one ride twice,
    4.2 s apart, as `other` and as `biking`, and the type test let both into
    the feed as "workout" and "cycling". A named recording now beats a
    generic one regardless of which started first, so the surviving row is
    the one that says what the session actually was.

    Idempotent — re-running promotes nothing new. Safe to call on every
    ingest and to re-run over history.
    """
    stmt = select(models.Workout).order_by(models.Workout.time)
    if since is not None:
        stmt = stmt.where(models.Workout.time >= since)
    sessions = (await db.execute(stmt)).scalars().all()

    promoted = already_present = skipped_overlap = skipped_untimed = 0
    skipped_duplicate = removed_duplicate = removed_superseded = 0

    # Resolve every session's interval and label up front, because the
    # duplicate test has to be able to look FORWARD as well as back.
    #
    # A list of what the scan has kept so far is enough while the winner is
    # always the earlier row, and it is not enough now that a named
    # recording beats a generic one whatever the order. On 2026-09-13 the
    # generic row came first, so a backward-looking pass promoted it, then
    # promoted the named row too — and the ingest path scans only the
    # window of the batch it just received, so nothing would have revisited
    # the pair. Asking against the whole scan makes the outcome independent
    # of the order rows are visited in, which is what lets one pass settle
    # it. A session never matches itself: `workouts` is keyed on `time`, so
    # no two candidates share a start.
    prepared: list[tuple[models.Workout, datetime, datetime, str]] = []
    for w in sessions:
        if not w.duration_s or w.duration_s <= 0:
            # A zero-length session has no interval to compare and nothing
            # useful to show.
            skipped_untimed += 1
            continue
        start = w.time
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        prepared.append((
            w,
            start,
            start + timedelta(seconds=int(w.duration_s)),
            HC_TYPE_MAP.get(
                (w.type or "").lower(), (w.type or "workout").lower(),
            ),
        ))
    scan_window: list[tuple[datetime, datetime, str]] = [
        (start, end, hc_type) for _, start, end, hc_type in prepared
    ]

    for w, start, end, hc_type in prepared:
        # Any activity from ANOTHER source whose interval overlaps this
        # one. `duration_s` may be null on older rows, so coalesce to 0 —
        # a zero-length existing row then only matches an exact start,
        # which is the conservative reading.
        clash = (await db.execute(
            # The whole row, not just its id: it is the survivor, so any
            # trail link or note on the row being retired has to move onto it.
            select(models.Activity)
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
        )).scalars().first()

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
            if await _retire_promotion(
                db, source_id, "superseded by a richer provider",
                winner=clash,
            ):
                removed_superseded += 1
            continue

        # A second Health Connect recording of a session already taken in
        # this scan. Overlapping minutes, and either the same type or a
        # better-labelled one — see `is_duplicate_recording`.
        twin = is_duplicate_recording(start, end, hc_type, scan_window)
        twin_row: models.Activity | None = None
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
            # Same-label twins are claimed only by a strictly earlier row.
            beaten_by = and_(
                models.Activity.type == hc_type,
                models.Activity.start_at < start,
            )
            if hc_type in GENERIC_TYPES:
                # ...and a generic one is claimed by any named recording of
                # the same minutes, whichever arrived first. Without this
                # second arm the SQL half disagrees with
                # `is_duplicate_recording`, and the table is the half that
                # decides once the scan window has moved past the pair.
                beaten_by = or_(
                    beaten_by,
                    models.Activity.type.notin_(tuple(GENERIC_TYPES)),
                )
            twin_row = (await db.execute(
                select(models.Activity)
                .where(models.Activity.source == HC_SOURCE)
                # Never this session's own row. The same-label arm excludes
                # it by start order, but the generic arm has no ordering: a
                # session already promoted as `cycling` whose Health Connect
                # record later flips to `other` would otherwise match itself
                # and be deleted.
                .where(models.Activity.source_id != source_id)
                # The two halves of the overlap. Both unconditional: the
                # ordering above is the winner rule, not the overlap test,
                # and conflating them is what the generic arm needs undone.
                .where(models.Activity.start_at < end)
                .where(
                    func.extract("epoch", start - models.Activity.start_at)
                    < func.coalesce(models.Activity.duration_s, 0)
                )
                .where(beaten_by)
                .limit(1)
            )).scalars().first()
            if twin_row is not None:
                twin = twin_row.start_at
        if twin is not None:
            skipped_duplicate += 1
            if twin_row is None:
                # The winner came from this scan's in-memory list, which
                # holds start instants rather than rows. It is in the table
                # under `HC_SOURCE` at that instant, and the retire path
                # needs the row itself to move any trail link onto it.
                twin_row = (await db.execute(
                    select(models.Activity)
                    .where(models.Activity.source == HC_SOURCE)
                    .where(models.Activity.start_at == twin)
                    .limit(1)
                )).scalars().first()
            # Self-heal a duplicate promoted before this rule existed.
            if await _retire_promotion(
                db, source_id, f"duplicate {hc_type} of {twin.isoformat()}",
                winner=twin_row,
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

        values = _hc_activity_values(
            w, hc_type, start, source_id, distance_by_start,
            polyline_by_start, route_state_by_start,
        )
        await upsert_activity(
            db,
            values,
            # Until SA-P3 these never had GPS, so there was never a trail to
            # match and this was unconditionally False. Now a promoted
            # session may carry a route, and `_auto_link_trail` is exactly
            # the thing that should run when it does. Still False without
            # one: that path reads `act.polyline` and would do nothing but
            # cost a query on every indoor session.
            link_trail=values.get("polyline") is not None,
            # The recursion guard. This function IS the promotion scan;
            # letting the row it just wrote reconcile against promotions
            # would have it retire itself.
            reconcile=False,
        )
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


async def reconcile_promotions(
    db: AsyncSession, act: models.Activity,
) -> int:
    """Retire any Health Connect promotion this provider row supersedes.

    The other half of `promote_health_connect_workouts`'s overlap rule, read
    from the provider side.

    Until this existed the rule only ever ran in one direction. Both calls to
    `_retire_promotion` sat inside the promotion scan, which walks the Health
    Connect sessions in the batch being ingested — so a Strava, Garmin or
    Concept2 sync that superseded an already-promoted row triggered nothing
    at all. The clash was noticed only if a later Health Connect batch
    happened to carry that same session again, and for a session recorded
    days ago it never does. The 2026-09-19 walk sat duplicated in the feed
    until a human ran the maintenance endpoint by hand.

    **The predicate is the promotion's own, with the roles swapped.**
    Promotion asks "is there an activity from another source whose interval
    overlaps this session"; this asks "is there a Health Connect promotion
    whose interval overlaps this row". Identical inequality, and that is not
    tidiness — it is what makes the two halves incapable of disagreeing.
    There is no state in which this retires a row the scan would re-promote,
    or leaves one the scan would have skipped, so the feed's contents stop
    depending on which provider happened to sync first.

    Note it retires EVERY overlapping promotion, not the first: promotion
    tests each session independently and would have skipped all of them, so
    stopping at one would leave the rest behind. The three 20-minute
    `workout` sessions on 2026-08-23 are the shape that needs it.

    Returns how many rows it took back. Never deletes a provider row — see
    the module docstring for why that scope is deliberate.
    """
    if act.source == HC_SOURCE:
        # Belt to `upsert_activity`'s braces. A promotion reconciling
        # against promotions would delete the row it just wrote.
        return 0

    start = act.start_at
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    end = start + timedelta(seconds=int(act.duration_s or 0))

    # Just the keys, not the rows. `_retire_promotion` re-reads the row it
    # is about to delete anyway, and holding ORM instances across a delete
    # that expunges them from the session is a way to make the second
    # iteration of this loop raise on a row the first one removed.
    stale_ids = (await db.execute(
        select(models.Activity.source_id)
        .where(models.Activity.source == HC_SOURCE)
        .where(models.Activity.start_at < end)
        # `hc.start + hc.duration > this.start`, as a seconds difference
        # rather than a constructed INTERVAL — the same expression the
        # promotion scan uses, for the same SQLAlchemy reason.
        .where(
            func.extract("epoch", start - models.Activity.start_at)
            < func.coalesce(models.Activity.duration_s, 0)
        )
    )).scalars().all()

    removed = 0
    for stale_id in stale_ids:
        if await _retire_promotion(
            db, stale_id,
            f"superseded by {act.source} {act.source_id}",
            winner=act,
        ):
            removed += 1
    return removed


async def upsert_activity(
    db: AsyncSession,
    values: dict[str, Any],
    *,
    link_trail: bool = True,
    complete_cardio_day: bool = True,
    reconcile: bool = True,
) -> models.Activity | None:
    """Insert or update one activity, then run the ingest side-effects.

    ``values`` must carry ``source`` and ``source_id``; everything else is
    optional, and any provider column whose value is None is left alone on
    an update rather than overwriting what is already stored.

    ``reconcile`` runs `reconcile_promotions` when this call INSERTS a row
    from a provider — the Health Connect dedupe, read from the side that
    previously never triggered it. Three things bound it:

    * **It cannot recurse.** The Health Connect promotion is itself a caller
      of this function, and it passes ``reconcile=False``.
      `reconcile_promotions` also returns immediately for `HC_SOURCE`, so
      neither the flag nor the guard is load-bearing alone.
    * **It does not fire on an ordinary update.** Gated on the row being
      new. A re-sync changes no row's existence, so there is nothing for the
      overlap rule to notice that it did not notice the first time; firing
      on every Strava poll would re-ask a settled question forever.
    * **It cannot make a bulk import quadratic.** It is one indexed lookup
      per newly inserted row, against the handful of rows carrying
      `HC_SOURCE` — not a scan, and nothing per existing row. The historical
      importers do not reach it at all: `api/imports._upsert_activities_chunk`
      is deliberately the one Activity writer outside this sink, precisely
      so a three-year backfill does not fire per-row side-effects. Those
      imports are still reconciled, from the promotion side, by the
      full-history sweep behind `POST /activities/promote-health-connect`.

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
        # A sync must not replace a stored track with materially less of the
        # same route. This is the founding rule of the module ("a poorer
        # sync can no longer erase a richer one") applied to the case it
        # originally only covered for None: a FIT that parses to five points
        # is not an absent track, so skip-None lets it through, and it would
        # overwrite a complete one. There is such a row in production — a
        # Strava ride stored as a 5-point, 25 m track.
        #
        # It matters most for a track this module CARRIED here from a row it
        # then deleted. That copy is the only one left, and without this the
        # next provider sync could quietly drop it.
        if track_is_materially_better(existing.polyline, new_polyline):
            log.info(
                "activity_sink: keeping the stored track on %s/%s — the "
                "incoming one describes materially less of the route",
                source, source_id,
            )
            update_set.pop("polyline", None)
            new_polyline = None
        else:
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

    # Before the two side-effects below, because a carry can hand this row
    # the user's trail link (which must then stop `_auto_link_trail`
    # guessing over it) or a GPS track (which is exactly what should make it
    # run).
    if reconcile and existing is None and source != HC_SOURCE:
        try:
            await reconcile_promotions(db, act)
        except Exception:  # noqa: BLE001
            # Same rule as the other side-effects: the row is the valuable
            # part. A failure here leaves the duplicate on screen, which is
            # exactly the state that existed before this ran, and the
            # maintenance sweep still clears it.
            log.warning("HC reconciliation failed for %s/%s",
                        act.source, act.source_id, exc_info=True)

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
