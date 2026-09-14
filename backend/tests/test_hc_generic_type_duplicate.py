"""One ride, two Health Connect recordings, two DIFFERENT types — OG2-A14.

Reported from live use on 2026-09-14: "yesterday's cycling was duped. I see a
cycling and a workout that are both the same."

The rows, both `source=healthconnect`, both promoted from `workouts` written
by `com.fitbit.FitbitMobile`::

    2026-09-13T19:12:11+00:00    other  -> workout   2945 s   trail_id=4
    2026-09-13T19:12:15.2+00:00  biking -> cycling   2939 s   trail_id=NULL

4.2 s apart, overlapping for their whole length: one ride, recorded twice.
This is the same shape as the 2026-08-30 pair that `is_duplicate_recording`
was written for, and it got through anyway, because that rule required the
mapped type to MATCH and these two disagree. Over all history the Fitbit app
had written eight such twin pairs and the first seven were `biking`/`biking`;
2026-09-13 is the first where one side landed in Health Connect's `other`
bucket.

Two decisions carry the fix, and both are worth stating because the obvious
version of each is wrong.

**A named type beats a generic one, and start order does not enter into it.**
The rest of the module resolves duplicates by earliest-wins, and earliest-wins
here would have kept `workout` and discarded `cycling` — a strictly worse
label for the same ride, on the row the user can see. `other` is not a kind of
exercise, it is the absence of a claim about which kind, so it loses to any
recording that does make one. The ordering rule still governs everything else,
including two generic recordings of one event.

**The user's trail link moves to the survivor rather than vetoing the
delete.** `_retire_promotion` refused to remove any row carrying a
user-owned column, and the user had manually linked the ride to trail 4 —
on the copy this rule discards. Under a plain veto the duplicate would have
survived every future scan, permanently, with the reason logged where nobody
would read it. The two rows are one event, so which of them holds the link is
an implementation detail the user never chose.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

import pytest

from myvitals.db import models
from myvitals.integrations import activity_sink
from myvitals.integrations.activity_sink import (
    GENERIC_TYPES,
    HC_TYPE_MAP,
    is_duplicate_recording,
)


def _at(hhmmss: str, seconds: float, kind: str) -> tuple[datetime, datetime, str]:
    """A (start, end, type) triple from a wall-clock time and a duration."""
    h, m, s = hhmmss.split(":")
    start = datetime(
        2026, 9, 13, int(h), int(m), int(float(s)),
        int(round((float(s) % 1) * 1_000_000)), tzinfo=timezone.utc,
    )
    return start, start + timedelta(seconds=seconds), kind


def _survivors(
    sessions: list[tuple[datetime, datetime, str]],
) -> list[tuple[datetime, datetime, str]]:
    """Which of an overlapping set the promoter keeps, in one pass.

    Mirrors `promote_health_connect_workouts`: every session is tested
    against the WHOLE scan, not against a list that grows as the loop goes.
    A progressive list cannot see a winner that starts later, which is the
    order the reported pair arrived in — so a scan built that way promoted
    both rows and left the duplicate for some later full-history run.
    """
    return [
        s for s in sessions
        if is_duplicate_recording(s[0], s[1], s[2], sessions) is None
    ]


#: The two production rows, exactly.
GENERIC = _at("19:12:11", 2945, "workout")
NAMED = _at("19:12:15.2", 2939, "cycling")


class TestTheReportedPair:
    def test_the_generic_recording_is_the_duplicate(self):
        """Even though it started first."""
        start, end, kind = GENERIC
        assert is_duplicate_recording(start, end, kind, [NAMED]) == NAMED[0]

    def test_the_named_recording_is_never_claimed(self):
        """The antisymmetry that stops both rows being dropped.

        If this ever returns a match the pair deadlocks: each row is a
        duplicate of the other, both are skipped, and nothing can resolve it.
        """
        start, end, kind = NAMED
        assert is_duplicate_recording(start, end, kind, [GENERIC]) is None

    def test_the_pair_resolves_to_exactly_one_survivor(self):
        """Walk the scan the way the promoter does."""
        assert _survivors([GENERIC, NAMED]) == [NAMED], (
            "the survivor must be the one labelled cycling"
        )

    def test_health_connects_other_bucket_is_what_produced_this(self):
        """Pins the mapping the whole case rests on."""
        assert HC_TYPE_MAP["other"] in GENERIC_TYPES
        assert HC_TYPE_MAP["biking"] == "cycling"
        assert HC_TYPE_MAP["biking"] not in GENERIC_TYPES


class TestTheGenericSetStaysNarrow:
    def test_only_the_unclassified_bucket_is_generic(self):
        """Widening this is how the protection below gets traded away.

        Every named type is a claim about what was done. The moment one of
        them joins this set, two genuinely different overlapping sessions
        start merging into one.
        """
        assert GENERIC_TYPES == frozenset({"workout"})

    def test_no_named_health_connect_type_is_generic(self):
        named = set(HC_TYPE_MAP.values()) - {HC_TYPE_MAP["other"]}
        assert named.isdisjoint(GENERIC_TYPES)


class TestWhatMustStillNotBeMerged:
    def test_two_different_named_types_may_overlap(self):
        """A strength session logged during a long walk is real work.

        The reason `GENERIC_TYPES` is one element and not a general
        "close enough" rule.
        """
        walk_start, walk_end, _ = _at("09:00:00", 7200, "walking")
        lift_start, lift_end, _ = _at("09:30:00", 1800, "strength_training")
        assert is_duplicate_recording(
            lift_start, lift_end, "strength_training",
            [(walk_start, walk_end, "walking")],
        ) is None

    def test_two_generic_sessions_still_resolve_by_earliest_wins(self):
        """The new rule is additive; it does not replace the ordering one."""
        first_start, first_end, kind = _at("09:00:00", 3600, "workout")
        second_start, second_end, _ = _at("09:00:04", 3600, "workout")
        assert is_duplicate_recording(
            second_start, second_end, kind,
            [(first_start, first_end, kind)],
        ) == first_start
        assert is_duplicate_recording(
            first_start, first_end, kind,
            [(second_start, second_end, kind)],
        ) is None

    def test_a_generic_session_that_does_not_overlap_survives(self):
        """Overlap is still required. A generic session is not open season."""
        ride_start, ride_end, _ = _at("09:00:00", 3600, "cycling")
        later_start, later_end, kind = _at("11:00:00", 1800, "workout")
        assert is_duplicate_recording(
            later_start, later_end, kind, [(ride_start, ride_end, "cycling")],
        ) is None

    def test_a_generic_session_does_not_match_itself(self):
        """Re-promotion stays a no-op rather than becoming a self-block."""
        start, end, kind = GENERIC
        assert is_duplicate_recording(start, end, kind, [GENERIC]) is None


class TestClustersStillConverge:
    def test_a_named_winner_is_reported_over_an_earlier_generic_one(self):
        """Three recordings, one ride, and one survivor.

        A generic row deferring to a generic row that itself defers to a
        named row would leave two survivors. Named beats generic outright,
        so every generic row in a cluster points at the same named winner.
        """
        early_generic = _at("09:00:00", 3600, "workout")
        named = _at("09:00:05", 3600, "cycling")
        late_generic = _at("09:00:09", 3600, "workout")
        assert _survivors([early_generic, named, late_generic]) == [named]

    def test_two_named_types_and_a_generic_keep_both_named_rows(self):
        """The generic row is absorbed; the two real sessions are not."""
        walk = _at("09:00:00", 7200, "walking")
        lift = _at("09:30:00", 1800, "strength_training")
        vague = _at("09:31:00", 1800, "workout")
        assert _survivors([walk, lift, vague]) == [walk, lift]


class TestTheDatabaseHalfMirrorsThePredicate:
    """`is_duplicate_recording` decides inside the scan window; the SQL
    decides outside it. They have to agree, and nothing but a test says so —
    the two are written in different languages a hundred lines apart.
    """

    def _source(self) -> str:
        return inspect.getsource(
            activity_sink.promote_health_connect_workouts
        )

    def test_the_sql_has_a_generic_arm(self):
        src = self._source()
        assert "GENERIC_TYPES" in src
        assert "notin_" in src, (
            "the generic arm is what lets a LATER named row claim an "
            "already-promoted generic one"
        )

    def test_the_ordering_rule_survives_for_same_type_matches(self):
        assert "Activity.start_at < start" in self._source()

    def test_the_overlap_test_is_not_conditional(self):
        """The bug in miniature: the old query folded the winner rule into
        the overlap by requiring `start_at < start` for every candidate. The
        generic arm needs both halves of the overlap and no ordering.
        """
        src = self._source()
        twin = src[src.index("beaten_by = and_("):]
        twin = twin[:twin.index("scalars().first()")]
        assert "Activity.start_at < end" in twin
        assert 'func.extract("epoch", start - models.Activity.start_at)' in twin

    def test_the_predicate_is_asked_against_the_whole_scan(self):
        """Not against a list that grows as the loop advances.

        This is the difference between resolving the pair in one pass and
        leaving it on screen. The generic row is visited first, so a
        backward-looking list is empty when it is judged; the named row that
        beats it has not been reached yet. The ingest path scans only the
        window of the batch it just received, so nothing would revisit the
        pair afterwards either.
        """
        src = self._source()
        assert "is_duplicate_recording(start, end, hc_type, scan_window)" in src
        assert "scan_window: list[tuple[datetime, datetime, str]] = [" in src
        assert "scan_window.append" not in src, (
            "a scan window that is appended to during the loop is the "
            "backward-looking version this replaced"
        )

    def test_a_session_cannot_match_its_own_promoted_row(self):
        """Without this the generic arm can delete the row it is promoting.

        The same-label arm excludes self by start order. The generic arm has
        no ordering, so a session already in the feed as `cycling` whose
        Health Connect record later flips to `other` would find itself,
        report itself as its own twin, and be retired.
        """
        src = self._source()
        assert "Activity.source_id != source_id" in src


# ── the retire path: a duplicate the user has touched ────────────────

class _Result:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class _Session:
    """Just enough AsyncSession for `_retire_promotion`.

    A real database is not what is interesting here — the decision about
    whose data wins is, and it is pure branching over two rows.
    """

    def __init__(self, stale: models.Activity | None) -> None:
        self.stale = stale
        self.deleted = False

    async def execute(self, stmt: object) -> _Result:
        if getattr(stmt, "is_delete", False):
            self.deleted = True
            return _Result(None)
        return _Result(self.stale)


def _row(source: str, source_id: str, **kw: object) -> models.Activity:
    return models.Activity(
        source=source, source_id=source_id, type=kw.pop("type", "cycling"),
        start_at=GENERIC[0], duration_s=2945, **kw,
    )


@pytest.mark.asyncio
class TestTheUsersTrailLinkMovesToTheSurvivor:
    async def test_the_link_is_carried_and_the_duplicate_goes(self):
        """The production case. Trail 4 was on the row being discarded."""
        loser = _row("healthconnect", "loser", type="workout", trail_id=4)
        winner = _row("healthconnect", "winner", type="cycling")
        db = _Session(loser)

        assert await activity_sink._retire_promotion(
            db, "loser", "duplicate", winner=winner,
        ) is True
        assert db.deleted is True
        assert winner.trail_id == 4

    async def test_notes_and_tags_move_too(self):
        """`USER_OWNED_COLUMNS` is the declaration; all of it is carried."""
        loser = _row(
            "healthconnect", "loser", type="workout",
            trail_id=4, notes="felt strong", tags=["commute"],
        )
        winner = _row("healthconnect", "winner")
        db = _Session(loser)

        assert await activity_sink._retire_promotion(
            db, "loser", "duplicate", winner=winner,
        ) is True
        assert (winner.trail_id, winner.notes, winner.tags) == (
            4, "felt strong", ["commute"],
        )

    async def test_a_conflicting_value_still_vetoes_the_delete(self):
        """Two trails on two rows is a conflict between two of the user's
        own decisions, and this is not the code to resolve it. The duplicate
        stays and is reported, which is the original discipline.
        """
        loser = _row("healthconnect", "loser", type="workout", trail_id=4)
        winner = _row("healthconnect", "winner", trail_id=9)
        db = _Session(loser)

        assert await activity_sink._retire_promotion(
            db, "loser", "duplicate", winner=winner,
        ) is False
        assert db.deleted is False
        assert winner.trail_id == 9

    async def test_the_same_value_on_both_rows_is_not_a_conflict(self):
        """The user linked both copies to the same trail. Nothing is lost."""
        loser = _row("healthconnect", "loser", type="workout", trail_id=4)
        winner = _row("healthconnect", "winner", trail_id=4)
        db = _Session(loser)

        assert await activity_sink._retire_promotion(
            db, "loser", "duplicate", winner=winner,
        ) is True
        assert db.deleted is True

    async def test_no_winner_means_the_old_veto(self):
        """Nothing to carry the value to, so the row is not deletable."""
        loser = _row("healthconnect", "loser", type="workout", trail_id=4)
        db = _Session(loser)

        assert await activity_sink._retire_promotion(
            db, "loser", "duplicate", winner=None,
        ) is False
        assert db.deleted is False

    async def test_an_untouched_duplicate_needs_no_winner(self):
        """The common path is unchanged: nothing user-owned, just delete."""
        loser = _row("healthconnect", "loser", type="workout")
        db = _Session(loser)

        assert await activity_sink._retire_promotion(
            db, "loser", "duplicate", winner=None,
        ) is True
        assert db.deleted is True

    async def test_a_row_that_is_already_gone_reports_false(self):
        db = _Session(None)
        assert await activity_sink._retire_promotion(
            db, "loser", "duplicate", winner=_row("healthconnect", "winner"),
        ) is False
        assert db.deleted is False


class TestTheRicherProviderPathCarriesItToo:
    """Strava is synced by hand here, so it lands days after Health Connect.

    When it does, the cross-provider clash retires the promoted row — and
    that row is the one the user has been looking at and may have annotated
    in the meantime. Passing the clashing row as the winner is what stops
    the trail link being the reason the duplicate cannot be cleaned up.
    """

    def test_the_clash_query_selects_the_row_not_just_its_id(self):
        src = inspect.getsource(
            activity_sink.promote_health_connect_workouts
        )
        clash = src[src.index("clash = ("):src.index("source_id = start.isoformat()")]
        assert "select(models.Activity)" in clash
        assert "select(models.Activity.source_id)" not in clash

    def test_the_clash_branch_passes_a_winner(self):
        src = inspect.getsource(
            activity_sink.promote_health_connect_workouts
        )
        branch = src[src.index("if clash is not None:"):]
        branch = branch[:branch.index("continue")]
        assert "winner=clash" in branch

    def test_the_duplicate_branch_passes_a_winner(self):
        src = inspect.getsource(
            activity_sink.promote_health_connect_workouts
        )
        branch = src[src.index("if twin is not None:"):]
        branch = branch[:branch.index("continue")]
        assert "winner=twin_row" in branch
