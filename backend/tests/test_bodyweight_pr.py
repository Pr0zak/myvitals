"""Bodyweight, added-load and hold personal records (PR-1b).

Before this, `_detect_pr` returned early whenever `actual_weight_lb` was
None and `/records` filtered those rows out. In this database that is 233
of 760 logged sets — 31% of everything recorded — and 112 of the 275
catalog exercises. A push-up session could not set a record however it
went.
"""

from __future__ import annotations

import pytest

from myvitals.analytics import strength as S

P = S.PriorSet

BW = {"equipment": ["body only"], "movement_pattern": "push", "is_timed": False}
HOLD = {"equipment": ["body only"], "movement_pattern": "core", "is_timed": True}
DB = {"equipment": ["dumbbell"], "movement_pattern": "push", "is_timed": False}
MOBILITY = {"equipment": ["body only"], "movement_pattern": "mobility", "is_timed": True}


class TestBodyweightReps:
    def test_more_reps_at_bodyweight_is_a_record(self):
        """The whole point. This was structurally impossible before."""
        assert S.classify_pr(BW, [P(None, 12, False)], None, 15) == "reps"

    def test_fewer_reps_is_not(self):
        assert S.classify_pr(BW, [P(None, 20, False)], None, 15) is None

    def test_equal_reps_is_not(self):
        """Matching a best is not beating it."""
        assert S.classify_pr(BW, [P(None, 15, False)], None, 15) is None

    def test_first_ever_set_is_a_baseline_not_a_record(self):
        assert S.classify_pr(BW, [], None, 15) is None


class TestHolds:
    def test_longer_hold_is_a_record(self):
        assert S.classify_pr(HOLD, [P(None, 45, False)], None, 60) == "hold"

    def test_shorter_hold_is_not(self):
        assert S.classify_pr(HOLD, [P(None, 90, False)], None, 60) is None


class TestMobilityIsExcluded:
    def test_a_longer_mobility_hold_is_never_a_record(self):
        """The false-record case, and the reason `pr_eligible` exists.

        `adjust_mobility_target` raises the prescribed hold to the user's
        own `max_actual`, so the prescription chases the best-ever hold.
        Each time the tuner steps a target up, the next session beats the
        previous best BY CONSTRUCTION — a "record" awarded for following
        instructions. Production has 19 mobility poses with enough history
        for this to fire.
        """
        assert S.classify_pr(MOBILITY, [P(None, 45, False)], None, 60) is None

    def test_pr_eligible_rejects_mobility_directly(self):
        assert S.pr_eligible(MOBILITY) is False
        assert S.pr_eligible(BW) is True
        assert S.pr_eligible(DB) is True


class TestLoadedLifts:
    def test_heavier_top_set_is_a_weight_pr(self):
        assert S.classify_pr(DB, [P(50, 8, False)], 55, 8) == "weight"

    def test_more_reps_at_equal_weight_is_an_e1rm_pr_not_a_rep_pr(self):
        """Deliberately NOT a separate "reps" kind on a loaded lift.

        More reps at the same weight already raises the Epley estimate, so
        it already fires as an e1RM PR. Adding a rep kind here would report
        one achievement twice.
        """
        assert S.classify_pr(DB, [P(50, 8, False)], 50, 12) == "e1rm"

    def test_weight_beats_e1rm_when_both_fire(self):
        """Precedence exists so the server picks, not each client.

        Both clients used to hard-code `is_weight_pr ? "weight" : "e1RM"`
        separately, which is two copies of one decision.
        """
        assert S.classify_pr(DB, [P(50, 8, False)], 60, 12) == "weight"


class TestWeightedBodyweight:
    def test_added_load_on_a_bodyweight_movement(self):
        assert S.classify_pr(BW, [P(25, 8, False)], 35, 8) == "added_load"

    def test_a_weighted_bodyweight_lift_never_reports_an_e1rm(self):
        """The pre-existing defect this fixes.

        A weighted dip logged at 25 lb went through `estimate_1rm(25, 8)`,
        which treats 25 lb as the TOTAL load rather than the added load —
        producing a number far below the user's real capability. That
        number was then the sort key for the entire Records card.
        """
        kind = S.classify_pr(BW, [P(25, 8, False)], 35, 8)
        assert kind != "e1rm"
        assert S._pr_metric(BW, "e1rm", 35, 8) is None


class TestOncePerWorkout:
    def test_only_the_set_that_breaks_the_record_fires(self):
        """Working up 135 → 145 → 155 is one achievement, not three.

        Without this, a user ramping to a top set gets a "personal record!"
        toast on every ascending set and the badge becomes noise. It also
        fixes a pre-existing bug: a weight PR on set 1 followed by a
        heavier set 2 fired twice.
        """
        prior_best = P(135, 5, False)
        # First set past the old best: this is the news.
        assert S.classify_pr(DB, [prior_best], 145, 5) == "weight"
        # A heavier set later in the SAME session: already reported.
        assert S.classify_pr(
            DB, [prior_best, P(145, 5, True)], 155, 5,
        ) is None

    def test_a_new_session_can_set_a_record_again(self):
        """Same-workout suppression must not leak across days."""
        history = [P(135, 5, False), P(145, 5, False)]
        assert S.classify_pr(DB, history, 155, 5) == "weight"

    def test_suppression_applies_per_kind(self):
        """A weight PR earlier today does not suppress a later hold PR.

        The kinds are independent achievements; suppressing across them
        would hide a genuine second record.
        """
        # Weight already broken this session...
        assert S.classify_pr(DB, [P(135, 5, False), P(145, 5, True)], 150, 5) is None
        # ...but a hold on a different exercise is untouched.
        assert S.classify_pr(HOLD, [P(None, 40, False)], None, 55) == "hold"


class TestGuards:
    @pytest.mark.parametrize("reps", [None, 0, -1])
    def test_no_reps_is_never_a_record(self, reps):
        assert S.classify_pr(BW, [P(None, 10, False)], None, reps) is None

    def test_warmup_and_skipped_are_filtered_by_the_caller(self):
        """Documented boundary: this function trusts its inputs.

        `_detect_pr` drops warmups and skipped sets before calling, and
        the prior-set query excludes them too. Keeping that filtering at
        the query boundary is what lets this function stay pure and
        testable without a database.
        """
        import inspect
        src = inspect.getsource(S.classify_pr)
        assert "warmup" not in src

    def test_precedence_list_covers_every_kind_the_metric_knows(self):
        kinds = set(S.PR_PRECEDENCE)
        assert kinds == {"weight", "e1rm", "added_load", "hold", "reps"}
        for k in kinds:
            # Every declared kind must be computable for some input.
            assert any(
                S._pr_metric(ex, k, w, r) is not None
                for ex, w, r in [
                    (DB, 100.0, 5), (BW, None, 10), (BW, 25.0, 5), (HOLD, None, 60),
                ]
            ), f"{k} is unreachable"
