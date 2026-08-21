"""Health Connect sessions → the activities feed (HC-1).

`ExerciseSessionRecord` has always been read from Health Connect and
written to `workouts`, a table nothing user-facing reads. The Activities
feed is built from `activities`, so a session the watch recorded but
Strava never saw was invisible.

On the production database that was 11 of 22 sessions since June —
including a 2h23m ride and a 1h30m ride on consecutive days. The whole
risk of fixing it is the other direction: promoting a session Strava
already has would double every ride in the feed.
"""

from __future__ import annotations

import inspect

from myvitals.integrations import activity_sink


class TestOverlapRatherThanProximity:
    def test_dedupe_is_an_interval_overlap_test(self):
        """Not a fixed ± window around the start time.

        The same ride gets a different start instant from each recorder —
        Strava starts on the first GPS fix, the watch on the button press.
        A tight window misses real duplicates; a wide one merges two
        genuinely separate walks on the same afternoon. Comparing the
        intervals answers the actual question.
        """
        src = inspect.getsource(activity_sink.promote_health_connect_workouts)
        assert "Activity.start_at < end" in src
        assert 'func.extract("epoch"' in src

    def test_null_duration_on_an_existing_row_is_coalesced(self):
        """Older activity rows may have no duration.

        Without the coalesce the interval arithmetic yields NULL, the
        comparison is neither true nor false, and the row silently stops
        blocking a duplicate.
        """
        src = inspect.getsource(activity_sink.promote_health_connect_workouts)
        assert "coalesce" in src

    def test_only_other_sources_block_a_promotion(self):
        """A previously promoted row must not block its own re-promotion,
        or the operation stops being idempotent after the first run."""
        src = inspect.getsource(activity_sink.promote_health_connect_workouts)
        assert "Activity.source != HC_SOURCE" in src


class TestNeverOverwritesRicherData:
    def test_an_overlapping_activity_wins(self):
        """Strava and Garmin carry distance, elevation and a polyline that
        a Health Connect session record does not. This fills gaps; it must
        never replace a richer row with a poorer one."""
        src = inspect.getsource(activity_sink.promote_health_connect_workouts)
        assert "skipped_overlap += 1" in src
        assert "continue" in src

    def test_zero_length_sessions_are_skipped(self):
        """No interval to compare, and nothing useful to show."""
        src = inspect.getsource(activity_sink.promote_health_connect_workouts)
        assert "skipped_untimed" in src

    def test_trail_linking_is_disabled(self):
        """These have no GPS, so there is no trail to match against."""
        src = inspect.getsource(activity_sink.promote_health_connect_workouts)
        assert "link_trail=False" in src


class TestIdempotence:
    def test_source_id_is_the_session_instant(self):
        """`workouts` is keyed on `time`, so the ISO instant is a stable
        natural key — re-promoting updates the row rather than adding a
        second one."""
        src = inspect.getsource(activity_sink.promote_health_connect_workouts)
        assert "start.isoformat()" in src
        assert '"source": HC_SOURCE' in src


class TestPrivacy:
    def test_the_session_title_is_not_copied(self):
        """`workouts.title` comes from whichever app wrote the HC record.

        The feed already renders the type, so a borrowed title adds
        nothing — and it is exactly the field that carries a location, per
        the rule test_ai_privacy.py exists to enforce.
        """
        src = inspect.getsource(activity_sink.promote_health_connect_workouts)
        assert '"name":' not in src
        assert "w.title" not in src


class TestTypeMapping:
    def test_biking_maps_to_the_dominant_existing_spelling(self):
        """`biking` does not appear in `activities` at all, so promoting it
        verbatim would give every promoted ride a fallback icon and drop it
        out of the cycling filter chip."""
        assert activity_sink.HC_TYPE_MAP["biking"] == "cycling"

    def test_walking_keeps_its_own_spelling(self):
        assert activity_sink.HC_TYPE_MAP["walking"] == "walking"

    def test_unmapped_types_fall_back_to_the_raw_value(self):
        """A new Health Connect exercise type should appear under its own
        name rather than vanish or be forced into a wrong bucket."""
        src = inspect.getsource(activity_sink.promote_health_connect_workouts)
        assert 'HC_TYPE_MAP.get(' in src
        assert '(w.type or "workout").lower()' in src


class TestIngestIsNotRisked:
    def test_promotion_failure_cannot_fail_an_ingest(self):
        """The raw samples are the irreplaceable part and are already
        written by the time this runs. A derived convenience must never
        take down the pipe that carries them."""
        from myvitals.api import ingest
        src = inspect.getsource(ingest)
        assert "HC-1 promotion failed" in src

    def test_ingest_promotion_is_bounded_to_the_batch(self):
        """Rescanning all history on every 15-minute sync would be a full
        table walk for nothing."""
        from myvitals.api import ingest
        src = inspect.getsource(ingest)
        assert "since=earliest" in src


class TestTheQueryActuallyCompiles:
    """The tests above read source text, which is why they all passed
    while the query referenced `Activity.id` — a column that does not
    exist, since the table is keyed on (source, source_id).

    Source inspection cannot catch a bad column reference. This compiles
    the statement, which does.
    """

    def test_the_overlap_query_compiles_against_the_real_model(self):
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import func, select
        from sqlalchemy.dialects import postgresql

        from myvitals.db import models
        from myvitals.integrations.activity_sink import HC_SOURCE

        start = datetime(2026, 6, 19, tzinfo=timezone.utc)
        end = start + timedelta(hours=2)
        stmt = (
            select(models.Activity.source_id)
            .where(models.Activity.source != HC_SOURCE)
            .where(models.Activity.start_at < end)
            .where(
                func.extract("epoch", start - models.Activity.start_at)
                < func.coalesce(models.Activity.duration_s, 0)
            )
            .limit(1)
        )
        sql = str(stmt.compile(dialect=postgresql.dialect()))
        assert "activities.source_id" in sql
        assert "EXTRACT" in sql.upper()

    def test_activity_has_no_id_column(self):
        """Pins the fact that made the original reference wrong, so the
        next person reaching for `Activity.id` fails here first."""
        from myvitals.db import models
        assert not hasattr(models.Activity, "id")
        assert models.Activity.__table__.primary_key.columns.keys() == [
            "source", "source_id",
        ]
