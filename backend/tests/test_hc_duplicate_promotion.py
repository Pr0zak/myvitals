"""One ride, two Health Connect recordings, two rows in the feed — OG2-A10.

Reported from live use: today's ride appeared twice in the Activities feed.
Both rows came from the same writer, `com.fitbit.FitbitMobile`, starting
4.4 s apart (13:54:05.6 and 13:54:10) and ending 0.6 s apart. One ride,
recorded twice.

`promote_health_connect_workouts` deduped against other providers and only
against other providers::

    .where(models.Activity.source != HC_SOURCE)

That exclusion is correct for what it was written for — a row must not block
its own re-promotion, or the function stops being idempotent after the first
run — but it left Health Connect entirely undeduped against itself. And
because `source_id` is the session's start instant, two recordings 4.4 s
apart are two different primary keys, so nothing collided.

The docstring already contained the reasoning that fixes it: "the same ride
gets a different start instant from each recorder". That was applied across
providers and never within one. It is also the same shape as the multi-source
step over-count `pick_canonical_steps_source` exists to solve — several
Health Connect writers publishing one underlying event.

Two properties carry the fix, and both are easy to regress:

**Earliest start wins, asymmetrically.** A mutual "does anything overlap me"
test would have each row block the other once both exist, so both would be
skipped and the duplicate would become permanent. Only a strictly earlier row
blocks, which can never block the winner because nothing precedes it.

**Type must match.** A strength session logged during a long walk overlaps
legitimately, and merging those loses real work.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
from datetime import datetime, timedelta, timezone

from myvitals.integrations import activity_sink
from myvitals.integrations.activity_sink import is_duplicate_recording

SRC = pathlib.Path(activity_sink.__file__)


def _promoter_source() -> str:
    return inspect.getsource(activity_sink.promote_health_connect_workouts)


def _at(hhmmss: str, seconds: float) -> tuple[datetime, datetime, str]:
    """A (start, end, type) triple from a wall-clock time and a duration."""
    h, m, s = hhmmss.split(":")
    start = datetime(
        2026, 8, 30, int(h), int(m), int(float(s)),
        int((float(s) % 1) * 1_000_000), tzinfo=timezone.utc,
    )
    return start, start + timedelta(seconds=seconds), "cycling"


class TestTheReportedPair:
    """The exact rows from the production database on 2026-08-30."""

    FIRST = _at("13:54:05.6", 4619)
    SECOND = _at("13:54:10", 4614)

    def test_the_later_recording_is_recognised_as_a_duplicate(self):
        start, end, kind = self.SECOND
        assert is_duplicate_recording(
            start, end, kind, [self.FIRST],
        ) == self.FIRST[0]

    def test_the_earlier_recording_is_never_blocked(self):
        """The winner must survive even when the loser is already stored.

        This is the case that makes the rule self-healing rather than
        deadlocked: run the scan with both rows present and the earlier one
        still promotes.
        """
        start, end, kind = self.FIRST
        assert is_duplicate_recording(start, end, kind, [self.SECOND]) is None

    def test_the_pair_resolves_to_exactly_one_survivor(self):
        """Walk the scan the way the promoter does and count what is kept."""
        kept: list[tuple[datetime, datetime, str]] = []
        for start, end, kind in sorted([self.SECOND, self.FIRST]):
            if is_duplicate_recording(start, end, kind, kept) is None:
                kept.append((start, end, kind))
        assert len(kept) == 1
        assert kept[0][0] == self.FIRST[0]


class TestWhatMustNotBeMerged:
    def test_two_different_types_may_overlap(self):
        """A strength session logged during a long walk is real work."""
        walk_start, walk_end, _ = _at("09:00:00", 7200)
        lift_start, lift_end, _ = _at("09:30:00", 1800)
        assert is_duplicate_recording(
            lift_start, lift_end, "strength_training",
            [(walk_start, walk_end, "walking")],
        ) is None

    def test_back_to_back_sessions_of_one_type_both_survive(self):
        """Two rides on one afternoon are two rides.

        The boundary is touching, not overlapping: the second starts exactly
        when the first ends. A ± window around the start would have merged
        these, which is why the check is an interval test.
        """
        first_start, first_end, kind = _at("09:00:00", 3600)
        second_start, second_end, _ = _at("10:00:00", 3600)
        assert is_duplicate_recording(
            second_start, second_end, kind, [(first_start, first_end, kind)],
        ) is None

    def test_an_overlap_of_one_second_still_counts(self):
        """No minimum-overlap threshold, deliberately.

        Any invented threshold is a number with no evidence behind it, and
        the type match already carries the discrimination.
        """
        first_start, first_end, kind = _at("09:00:00", 3600)
        second_start, second_end, _ = _at("09:59:59", 3600)
        assert is_duplicate_recording(
            second_start, second_end, kind, [(first_start, first_end, kind)],
        ) == first_start


class TestStability:
    def test_an_empty_history_never_reports_a_duplicate(self):
        start, end, kind = _at("09:00:00", 3600)
        assert is_duplicate_recording(start, end, kind, []) is None

    def test_a_session_does_not_match_itself(self):
        """Re-promotion has to stay a no-op, not become a self-block."""
        start, end, kind = _at("09:00:00", 3600)
        assert is_duplicate_recording(
            start, end, kind, [(start, end, kind)],
        ) is None

    def test_the_earliest_of_several_is_reported(self):
        """Three recorders, one ride: everything defers to the same winner.

        Reporting whichever happened to be scanned first would make the
        surviving row depend on scan order, and the feed would reshuffle
        between syncs.
        """
        a_start, a_end, kind = _at("09:00:00", 3600)
        b_start, b_end, _ = _at("09:00:05", 3600)
        c_start, c_end, _ = _at("09:00:09", 3600)
        assert is_duplicate_recording(
            c_start, c_end, kind,
            [(b_start, b_end, kind), (a_start, a_end, kind)],
        ) == a_start


class TestHealthConnectDedupesAgainstItself:
    def test_a_same_type_overlap_within_health_connect_is_skipped(self):
        """The reported bug. Without this the feed shows one ride twice."""
        src = _promoter_source()
        assert "skipped_duplicate" in src
        assert "Activity.source == HC_SOURCE" in src, (
            "the duplicate check must look at HC rows — the cross-provider "
            "clash query excludes them, which is how this shipped"
        )

    def test_the_cross_provider_rule_is_untouched(self):
        """A promoted row must still not block its own re-promotion.

        The new rule is additive. If this assertion ever has to be deleted,
        idempotency has been traded away for the dedupe and the function will
        promote nothing on its second run.
        """
        assert "Activity.source != HC_SOURCE" in _promoter_source()

    def test_type_is_part_of_the_match(self):
        """Overlap alone would merge a strength session logged mid-walk."""
        src = _promoter_source()
        assert "Activity.type == hc_type" in src
        assert "is_duplicate_recording(" in src


class TestTheWinnerIsDeterministic:
    def test_only_a_strictly_earlier_row_blocks(self):
        """The asymmetry is the fix, not an optimisation.

        `start_at < start` means the earliest row is never blocked, because
        nothing precedes it. Relax this to a plain overlap and two existing
        rows block each other, both are skipped, and the duplicate can never
        be cleaned up.
        """
        assert "Activity.start_at < start" in _promoter_source()

    def test_sessions_are_scanned_oldest_first(self):
        """Earliest-wins is only well-defined in a known order."""
        assert "order_by(models.Workout.time)" in _promoter_source()

    def test_the_scan_window_is_not_trusted_alone(self):
        """`since` is the earliest workout in an ingest batch.

        A batch carrying only the LATER of a pair starts its scan past the
        winner, so an in-memory list of what this run kept cannot see it. The
        table has to be asked as well.
        """
        src = _promoter_source()
        assert "kept" in src
        assert src.count("HC_SOURCE") >= 3, (
            "expected both the in-memory check and a database check"
        )


class TestSelfHealingIsConservative:
    """The retire path, shared by both skip rules.

    Promotion decides once, and BOTH of its skip rules can become true after
    the fact: a second Health Connect recording arrives, or a richer provider
    finally syncs. Skipping a session already promoted changes nothing on
    screen, so the scan has to be able to take a row back.
    """

    def test_a_stale_row_is_removed(self):
        src = _promoter_source()
        assert "removed_duplicate" in src
        assert "removed_superseded" in src
        assert "_retire_promotion" in src

    def test_user_owned_columns_veto_the_delete(self):
        """`notes`, `tags` and `trail_id` belong to the user.

        A duplicate the user has annotated or linked to a trail records a
        decision this function did not make. It is left in place and reported
        rather than deleted — the same discipline as MEAL-3, where only a
        demonstrably complete cancellation may drop a line.
        """
        src = inspect.getsource(activity_sink._retire_promotion)
        assert "USER_OWNED_COLUMNS" in src
        assert "return False" in src

    def test_the_veto_reads_the_declared_list_rather_than_naming_columns(self):
        """Pinned against the module's own declaration.

        Spelling the three columns out by hand means a fourth user-owned
        column added later is silently deletable. Reading the tuple the
        module already declares makes that impossible.
        """
        src = inspect.getsource(activity_sink._retire_promotion)
        assert "for col in USER_OWNED_COLUMNS" in src
        assert activity_sink.USER_OWNED_COLUMNS == ("notes", "tags", "trail_id")

    def test_the_delete_is_scoped_to_health_connect(self):
        """A DELETE in an ingest path is worth reading twice.

        It must never be able to reach a Strava or Concept2 row, which carry
        GPS and power data this function could not reconstruct.
        """
        tree = ast.parse(SRC.read_text())
        deletes = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "delete"
        ]
        assert len(deletes) == 1, (
            f"expected exactly one delete() in the sink, found {len(deletes)}"
        )
        src = inspect.getsource(activity_sink._retire_promotion)
        head = src[src.index("delete(models.Activity)"):]
        assert "Activity.source == HC_SOURCE" in head
        assert "Activity.source_id == source_id" in head

    def test_retiring_reports_whether_it_acted(self):
        """The caller increments a counter off the return value.

        Returning None and letting the caller assume success is how a
        vetoed row would get counted as removed, which would report a
        cleanup that did not happen.
        """
        src = inspect.getsource(activity_sink._retire_promotion)
        assert "-> bool" in src
        assert "return True" in src


class TestARicherProviderArrivingLate:
    """The reported second failure, one day after the first.

    Health Connect had already promoted the ride when Strava synced two days
    later, so the cross-provider skip — which only ever ran at promotion
    time — had nothing left to prevent. The feed ended up holding three rows
    for one ride: two Health Connect recordings and the Strava one.
    """

    def test_the_clash_branch_retires_the_row_it_promoted(self):
        src = _promoter_source()
        clash = src[src.index("if clash is not None:"):]
        clash = clash[:clash.index("continue")]
        assert "_retire_promotion" in clash
        assert "removed_superseded += 1" in clash

    def test_the_type_is_resolved_before_the_clash_branch(self):
        """`source_id` is needed to retire, and it is derived from the start.

        Ordering regression risk: the clash branch used to `continue` before
        `source_id` existed, so moving the retire call in without hoisting
        that would raise NameError on the one path that matters.
        """
        src = _promoter_source()
        assert src.index("source_id = start.isoformat()") < src.index("if clash is not None:")

    def test_superseded_and_duplicate_are_counted_separately(self):
        """Two different faults, and only one of them is Health Connect's.

        A ride superseded by a late Strava sync is the system working as
        designed; two Health Connect recordings of one ride is a fault in the
        source data. Folding them into one counter would hide the second.
        """
        src = _promoter_source()
        assert '"removed_superseded": removed_superseded' in src
        assert '"removed_duplicate": removed_duplicate' in src


class TestTheCountsStayHonest:
    def test_both_new_outcomes_are_reported(self):
        """This function's return value is what the endpoint reports.

        A run that silently dropped a row while reporting only "promoted: 0"
        would be indistinguishable from a run that did nothing.
        """
        src = _promoter_source()
        assert '"skipped_duplicate": skipped_duplicate' in src
        assert '"removed_duplicate": removed_duplicate' in src

    def test_a_duplicate_is_not_counted_as_an_overlap(self):
        """`skipped_overlap` means "a richer provider already has this".

        Folding duplicates into it would hide a Health Connect fault behind a
        counter that reads as normal operation.
        """
        src = _promoter_source()
        assert "skipped_duplicate += 1" in src
        i_dup = src.index("skipped_duplicate += 1")
        i_ovl = src.index("skipped_overlap += 1")
        assert i_ovl < i_dup, "the cross-provider check should run first"
