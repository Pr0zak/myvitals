"""Two of four sets is not a session — OG2-B1.

`target_sets` was written on seven construction sites in
`analytics/strength.py` and read back by no progression reader. So logging 2
of 4 prescribed sets and rating them Easy produced the same weight jump as
logging all 4 — a +20% advance off half the work.

The truncation biases both of the reducer's inputs in the same direction. The
sets a user abandons are the late ones, and the late ones are the hard ones,
so a short session's average rating and average reps both read easier than
the session actually was. It advances precisely when the advance is least
earned.

`enough` closes it, and the ASYMMETRY is the design decision: it gates the
ADVANCE and never the deload. Two sets rated Easy out of four are not
evidence the prescription was met. Two sets rated Failed are still real
evidence to cut — refusing to act on them would leave a weight the user could
not lift standing because they stopped early, which is the wrong way round.

A stall count was specified and is deliberately NOT shipped. An adversarial
review measured the streak across all 143 exercises with history: the maximum
is 1, and zero exercises reach 2 or 3 — so it could only ever return 0 or 1,
and nothing consumed it. Shipping a function with no caller and a promise
attached is the liability this file argues against everywhere else. It is
recorded in TODO.md against the coach payload, which is where it would have
a consumer: `build_deload_payload` sends four coarse 14-day numbers and its
`missed_or_skipped_sets` counts rows with null reps, of which production has
zero because an unlogged set has no row — so a partial session is invisible
to the deload check today, and that is the gap a count would close.

Had it shipped it would not have been acted on either. Three deloads already
exist — the rating policy's cut at `avg_rating <= FAIL_THRESHOLD`, the
recovery factor (0.85 x 0.90, then generate_plan's own 0.90 on an easy day,
so 0.6885 is reachable today), and PROG-1's fail streak — and a fourth
multiplier is the compounding this codebase refuses elsewhere.

Measured before building: of 292 completed slots in this database, 5 are
partial and 277 complete, so the gate is a correct fix with a small blast
radius. openGym's `fallback` for pre-prescription history is deliberately NOT
ported — `target_sets` is NOT NULL in migration 0021 and has zero nulls
across 1,430 rows, so myvitals has no era the hazard applies to.
"""

from __future__ import annotations

import inspect
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]

from myvitals.analytics.strength import (
    EASY_THRESHOLD,
    FAIL_THRESHOLD,
    SetFacts,
    double_progression,
    read_session,
    weight_from_history,
)


def _set(reps=8, rating=5, weight=25.0, set_type="working", skipped=False):
    return SetFacts(
        skipped=skipped, actual_reps=reps, set_type=set_type,
        actual_weight_lb=weight, rating=rating,
    )


class TestEnough:
    def test_a_full_session_is_enough(self):
        r = read_session(target_sets=4, slot_declined=False,
                         sets=[_set() for _ in range(4)])
        assert r.performed_sets == 4
        assert r.enough is True

    def test_two_of_four_is_not(self):
        """The reported case."""
        r = read_session(target_sets=4, slot_declined=False,
                         sets=[_set() for _ in range(2)])
        assert r.performed_sets == 2
        assert r.enough is False

    def test_more_than_prescribed_still_counts_as_enough(self):
        """An extra set is not a shortfall. `>=`, not `==`."""
        r = read_session(target_sets=3, slot_declined=False,
                         sets=[_set() for _ in range(5)])
        assert r.enough is True

    def test_warmups_and_drops_do_not_count_toward_it(self):
        """The same rule OG2-A1 named: real work, but not evidence about the
        load to prescribe. Counting them would let three warm-ups satisfy a
        3-set prescription."""
        r = read_session(target_sets=3, slot_declined=False, sets=[
            _set(set_type="warmup"), _set(set_type="drop"), _set(),
        ])
        assert r.performed_sets == 1
        assert r.enough is False

    def test_a_skipped_set_does_not_count(self):
        r = read_session(target_sets=2, slot_declined=False,
                         sets=[_set(), _set(skipped=True)])
        assert r.performed_sets == 1
        assert r.enough is False

    def test_a_set_with_no_reps_was_never_performed(self):
        r = read_session(target_sets=2, slot_declined=False,
                         sets=[_set(), _set(reps=None)])
        assert r.performed_sets == 1

    def test_a_declined_slot_is_a_decision_not_a_short_session(self):
        """SKIP-1: declining is an explicit choice and carries no sets to
        judge. Reading it as a shortfall would make every deliberate skip
        look like a failure to complete."""
        r = read_session(target_sets=3, slot_declined=True, sets=[])
        assert r.enough is False
        assert r.has_history is False


class TestTheGateIsAsymmetric:
    """The whole design decision, in four assertions."""

    def test_a_short_easy_session_does_not_advance(self):
        held, why = weight_from_history(
            25.0, EASY_THRESHOLD + 0.5, is_compound=False, enough=False)
        assert held == 25.0
        assert why == "held_incomplete"

    def test_the_same_session_completed_does_advance(self):
        up, why = weight_from_history(
            25.0, EASY_THRESHOLD + 0.5, is_compound=False, enough=True)
        assert up > 25.0
        assert why == "rated"

    def test_a_short_failed_session_still_cuts(self):
        """The asymmetry. Refusing to act on two Failed sets would leave a
        weight the user could not lift standing because they stopped early."""
        cut, why = weight_from_history(
            25.0, FAIL_THRESHOLD - 0.5, is_compound=False, enough=False)
        assert cut < 25.0
        assert why == "rated"

    def test_a_short_middling_session_holds_either_way(self):
        """The rating policy already holds in the middle band, so the gate
        changes nothing there and must not invent a reason."""
        a, why_a = weight_from_history(25.0, 3.0, is_compound=False, enough=False)
        b, why_b = weight_from_history(25.0, 3.0, is_compound=False, enough=True)
        assert a == b == 25.0
        assert why_a == why_b == "rated"

    def test_the_default_preserves_existing_behaviour(self):
        """Every caller that is not edited keeps its answer."""
        sig = inspect.signature(weight_from_history)
        assert sig.parameters["enough"].default is True


class TestDoubleProgressionRespectsIt:
    ARGS = dict(
        base_reps_lo=8, base_reps_hi=12, last_weight_lb=25.0,
        is_compound=False, goal="hypertrophy",
        pairs_lb=[5, 10, 15, 20, 25, 30], wrist_weights_lb=[],
    )

    def test_a_short_session_at_the_top_of_the_range_does_not_add_weight(self):
        w, lo, hi, _ = double_progression(
            last_avg_rating=5.0, last_avg_reps=12.0,
            session_complete=False, **self.ARGS)
        assert w == 25.0

    def test_the_same_session_completed_does(self):
        w, lo, hi, _ = double_progression(
            last_avg_rating=5.0, last_avg_reps=12.0,
            session_complete=True, **self.ARGS)
        assert w is not None and w > 25.0

    def test_a_short_session_does_not_add_a_rep_either(self):
        """Branch 3 advances too. Adding a rep off half the prescribed sets
        is the same unearned progression in a different unit."""
        w, lo, hi, _ = double_progression(
            last_avg_rating=4.0, last_avg_reps=9.0,
            session_complete=False, **self.ARGS)
        assert lo == 8

    def test_a_short_failed_session_still_cuts(self):
        """The failure branch sits ABOVE the gate, deliberately."""
        w, _lo, _hi, _ = double_progression(
            last_avg_rating=1.0, last_avg_reps=8.0,
            session_complete=False, **self.ARGS)
        assert w is not None and w < 25.0

    def test_the_gate_is_below_the_failure_branch(self):
        src = inspect.getsource(double_progression)
        assert src.index("last_avg_rating <= FAIL_THRESHOLD") < src.index(
            "if not session_complete:")


class TestTheHistoricalPrescriptionIsWhatCounts:
    def test_the_reducer_takes_target_sets_as_an_argument(self):
        """It must come from the slot being JUDGED, not from today's plan.

        FAST-18 modulates the count before it is persisted — fewer sets at 18
        and 24 hours fasted — so comparing last session against today's
        prescription would let a fasted day retroactively declare a complete
        session incomplete.
        """
        sig = inspect.signature(read_session)
        assert "target_sets" in sig.parameters
        assert sig.parameters["target_sets"].kind is inspect.Parameter.KEYWORD_ONLY

    def test_no_fallback_parameter_was_ported(self):
        """openGym needed one because its workouts only began recording a
        prescription in v1.2.2, and judging older entries against nothing
        would greet a long-standing user with a spurious deload. myvitals has
        no such era: `target_sets` is NOT NULL in migration 0021 and has zero
        nulls across 1,430 rows.
        """
        sig = inspect.signature(read_session)
        assert "fallback" not in sig.parameters


class TestTheLookbackIsBounded:
    """A regression the first cut of B1 introduced, caught by review.

    Moving from "the newest completed slot" to "the newest slot that carries
    qualifying sets" is correct — one declined slot used to discard all
    history — but without a bound it reaches arbitrarily far back. Several
    exercises in this database have no logged sets since May, and prescribing
    September's weight off a four-month-old session states a confidence the
    data does not support. Beyond the bound the caller falls through to
    `starting_weight_lb`, which is at least honest about being a default.
    """

    def test_a_bound_exists(self):
        from myvitals.analytics.strength import PROGRESSION_LOOKBACK_DAYS
        assert PROGRESSION_LOOKBACK_DAYS == 180

    def test_the_query_applies_it(self):
        from myvitals.analytics import strength as algo
        src = inspect.getsource(algo.read_recent_sessions)
        assert "PROGRESSION_LOOKBACK_DAYS" in src
        assert "StrengthWorkout.date >= cutoff" in src

    def test_the_number_is_not_invented(self):
        """It matches the prefill ghost's existing 180-day window, so this is
        the codebase's own number rather than a new one — the same discipline
        HEALTH-1 applied in measuring its thresholds instead of guessing."""
        from myvitals.analytics.strength import PROGRESSION_LOOKBACK_DAYS
        ghost = (
            REPO / "backend" / "src" / "myvitals" / "api" / "workout" / "strength.py"
        ).read_text()
        assert f"{PROGRESSION_LOOKBACK_DAYS}" in ghost
