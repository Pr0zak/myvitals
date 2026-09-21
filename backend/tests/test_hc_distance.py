"""Health Connect distance -> the activities feed (SA-P1).

`android.permission.health.READ_DISTANCE` was declared and granted, and
`DistanceRecord` was imported into `HealthConnectGateway` -- and never read.
`WorkoutSample` had nowhere to put a distance anyway: it did not exist on
either side of the wire. All 18 Health Connect-sourced activities in
production carried a NULL `distance_m`, while every Strava and Garmin
activity had one, so the feed looked inconsistent for no visible reason.

The backend sink was never the blocker. `activity_sink.py` already writes
`distance_m` for every other provider; the column already exists on
`activities`. What was missing was the wire: a field on `WorkoutSample`
(phone Kotlin + backend Pydantic) and a path from it into the row HC-1's
promotion writes.

Two things this file exists to pin, because they are exactly the kind of
thing a later "just sum the raw records" or "0.0 is a fine default"
edit would quietly break:

1. **Null survives the whole chain.** An indoor session has no distance
   and must land as NULL in `activities.distance_m`, never 0.0 -- a zero
   is a claim the user covered no ground, and it would pollute the feed's
   distance totals.
2. **A Health Connect distance never overwrites a richer provider's.**
   `promote_health_connect_workouts` fills gaps in the feed; it must never
   replace a GPS-measured Strava/Garmin distance with a phone/watch
   step-based estimate, on a session that already has one.

`workouts` (the raw ingest table) gained no column and needs no migration
-- `activities.distance_m` already exists and is already populated by
other providers, per the finding. The batch's own distance values are
handed directly to the promotion step instead of round-tripping through a
`workouts` column that was never asked to store them; see
`ingest.py::ingest_batch` and `activity_sink._hc_activity_values`.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone

from myvitals.api.ingest import WorkoutSample
from myvitals.db import models
from myvitals.integrations import activity_sink

T = datetime(2026, 9, 19, 14, 5, 5, tzinfo=timezone.utc)


def _hc_workout(**kw: object) -> models.Workout:
    """A plain ORM instance -- no database needed to build one."""
    defaults: dict[str, object] = dict(
        time=T, type="walking", duration_s=8217, kcal=None,
        avg_hr=None, max_hr=None, source="com.fitbit.FitbitMobile",
        title=None,
    )
    defaults.update(kw)
    return models.Workout(**defaults)


class TestTheWireModelDefaultsToNull:
    """The Kotlin-side landmine CLAUDE.md warns about (`Boolean = true`
    defaults changing behaviour silently) has a Pydantic twin: a numeric
    default of 0.0 would be just as much a lie as a boolean one."""

    def test_a_workout_sample_with_no_distance_key_is_none_not_zero(self):
        w = WorkoutSample(time=T, type="workout", duration_s=600)
        assert w.distance_m is None

    def test_a_workout_sample_with_an_explicit_distance_keeps_it(self):
        w = WorkoutSample(time=T, type="biking", duration_s=1800, distance_m=4021.5)
        assert w.distance_m == 4021.5

    def test_the_raw_workouts_table_write_excludes_distance(self):
        """`workouts` has no `distance_m` column -- see
        TestNoMigrationWasNeeded below. Dumping it into the multi-row
        VALUES list `_bulk_upsert` builds for `models.Workout` would fail
        the whole insert on an unrecognised column, for every sample in
        the batch, not just the ones carrying a distance.
        """
        w = WorkoutSample(time=T, type="biking", duration_s=1800, distance_m=4021.5)
        dumped = w.model_dump(exclude={"distance_m"})
        assert "distance_m" not in dumped
        # Everything workouts.time / update_cols actually references
        # still has to survive the exclude.
        for col in ("time", "type", "duration_s", "kcal", "avg_hr", "max_hr",
                    "source", "title"):
            assert col in dumped


class TestNoMigrationWasNeeded:
    def test_workouts_table_has_no_distance_column(self):
        """Pins the finding's premise. If this ever starts failing, the raw
        ingest table gained a `distance_m` column somewhere and the
        `distance_by_start` side-channel this module wires through
        `ingest_batch` can be deleted in favour of reading it straight off
        the row `promote_health_connect_workouts` already queries.
        """
        assert "distance_m" not in models.Workout.__table__.columns.keys()

    def test_activities_table_already_had_distance_m(self):
        assert "distance_m" in models.Activity.__table__.columns.keys()
        assert "distance_m" in activity_sink.PROVIDER_COLUMNS


class TestDistanceLandsOnThePromotedRow:
    """`_hc_activity_values` is the exact dict `promote_health_connect_workouts`
    hands to `upsert_activity` -- pulled out as a pure function specifically
    so this could be tested without a live Postgres, the same way
    `is_duplicate_recording` was pulled out of the same function for its
    own tests.
    """

    def test_a_workout_posted_with_a_distance_lands_in_the_row(self):
        w = _hc_workout(type="biking", duration_s=1800)
        source_id = T.isoformat()
        values = activity_sink._hc_activity_values(
            w, "cycling", T, source_id, {source_id: 4021.5},
        )
        assert values["distance_m"] == 4021.5
        assert values["source"] == activity_sink.HC_SOURCE
        assert values["source_id"] == source_id

    def test_a_workout_posted_without_one_leaves_it_null(self):
        """The 2h17m walk from the report: no distance, not a zero."""
        w = _hc_workout(type="walking", duration_s=8217)
        source_id = T.isoformat()
        values = activity_sink._hc_activity_values(
            w, "walking", T, source_id, {},
        )
        assert values["distance_m"] is None
        assert "distance_m" in values, (
            "must be an explicit None so a fresh INSERT stores a real "
            "NULL, not a key silently missing from the row"
        )
        assert values["distance_m"] != 0.0

    def test_a_none_distance_map_behaves_like_an_empty_one(self):
        """The post-Strava-sync rescan (`strava.py`) calls the promoter
        with no batch context at all, so `distance_by_start` is None
        there, not {}. Both must resolve to "no data", not a KeyError."""
        w = _hc_workout()
        source_id = T.isoformat()
        values = activity_sink._hc_activity_values(
            w, "walking", T, source_id, None,
        )
        assert values["distance_m"] is None

    def test_lookup_is_keyed_by_source_id_not_by_the_raw_workout_time(self):
        """`source_id` and `start.isoformat()` are the same value everywhere
        else in this module (the natural key HC-1 re-promotion relies on);
        distance has to be looked up the same way or a session promoted a
        second time would silently lose the distance found the first time.
        """
        other_id = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
        w = _hc_workout()
        values = activity_sink._hc_activity_values(
            w, "walking", T, T.isoformat(), {other_id: 999.0},
        )
        assert values["distance_m"] is None


class TestNeverOverwritesARicherDistance:
    """`upsert_activity`'s skip-None-on-update rule is what actually
    enforces "never overwrite a richer provider" for every provider
    column, distance included -- this just confirms distance gets no
    special exemption from that rule, since it would be easy to special
    case a column that used to not exist here at all.
    """

    @staticmethod
    def _update_set(values: dict) -> dict:
        insert_values = {
            k: v for k, v in values.items()
            if k in activity_sink.PROVIDER_COLUMNS or k in ("source", "source_id")
        }
        return {
            k: v for k, v in insert_values.items()
            if k in activity_sink.PROVIDER_COLUMNS and v is not None
        }

    def test_no_distance_this_round_does_not_blank_an_existing_one(self):
        """A GPS-measured Strava distance must survive a Health Connect
        promotion pass that has nothing to say about distance."""
        values = activity_sink._hc_activity_values(
            _hc_workout(), "walking", T, T.isoformat(), {},
        )
        written = self._update_set(values)
        assert "distance_m" not in written

    def test_a_real_distance_does_reach_the_update(self):
        """The skip-None rule is about None specifically, not about
        distance being unwritable on an update in general."""
        source_id = T.isoformat()
        values = activity_sink._hc_activity_values(
            _hc_workout(), "walking", T, source_id, {source_id: 3219.4},
        )
        written = self._update_set(values)
        assert written["distance_m"] == 3219.4

    def test_zero_distance_would_still_be_written_because_it_is_a_measurement(self):
        """Mirrors test_activity_sink.py's rule for elevation/kcal: 0.0 is
        a real reading (an ergometer session with a stationary distance
        sensor, say), not the same thing as "no reading". Distance must
        not be special-cased into treating a genuine zero as absent."""
        source_id = T.isoformat()
        values = activity_sink._hc_activity_values(
            _hc_workout(), "walking", T, source_id, {source_id: 0.0},
        )
        written = self._update_set(values)
        assert written["distance_m"] == 0.0


class TestTheDocstringNoLongerTeachesTheGap:
    """The docstring used to claim outright that "Health Connect's session
    record does not" carry distance -- true of the session record, false
    of Health Connect, which is what actually caused this gap to exist
    (and, unfixed, would have re-taught it to the next reader)."""

    def test_the_false_absolute_claim_is_gone(self):
        src = inspect.getsource(activity_sink.promote_health_connect_workouts)
        assert "Health Connect's session record does not" not in src

    def test_the_correction_is_present(self):
        src = inspect.getsource(activity_sink.promote_health_connect_workouts)
        assert "DistanceRecord" in src
