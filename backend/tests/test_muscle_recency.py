"""A cool-down stretch is not training — OG2-C1.

C1 set out to build openGym's per-muscle fatigue model: intensity-weighted
tonnage accumulated with a 36-hour half-life and a saturating readout. It
was NOT built, and the refusal is the finding rather than an omission. What
shipped instead is the correctness fix the investigation turned up on the
way.

WHY THE MODEL WAS REFUSED. Every constant it needs was measured against this
user's own data and none of them could be sourced:

- The decay constant cannot be derived. Across 286 muscle-to-muscle
  re-training intervals, ZERO arrive above 50% residual at a 36-hour
  half-life, and the maximum residual reachable is 0.397 because the shortest
  gap on any muscle is 2 days. Every muscle would read "ready" at essentially
  every decision point — HEALTH-1's failure with the sign flipped: a signal
  that never fires is ignored exactly as fast as one that always does.
- Nor fitted from performance: of 88 exercises with any weighted set, 49 have
  been performed in exactly ONE session and only 5 in four or more. There is
  no repeated-measures data to fit a curve to.
- The thing the model carries is not there. Session size barely varies — set
  count CV is 0.05 for back, 0.16 chest, 0.19 quadriceps — because the
  generator writes a fixed slot template. And 162 of 165 weighted slots carry
  a single distinct weight, so openGym's (load/1RM)^1.5 intensity term
  collapses to a constant here.
- Two of fourteen muscles have no measurable load at all: abdominals is 97%
  unweighted, lower back 100%.
- The systemic cross the feature was premised on has no signal either.
  Session size against next-day change in recovery_score gives r = -0.082 for
  set count and +0.015 for tonnage over 20 sessions, against a day-to-day
  median absolute change of 15.9 points.
- And `deload_factor` — the "deliberately light session" label the design
  leaned on — is below 1.0 on ZERO of 40 completed workouts.

WHAT SHIPPED. Both muscle readers filtered mobility at the WORKOUT level,
`split_focus NOT IN (yoga, cardio)`, which cannot see a mobility cool-down
appended to a strength day. The generator appends exactly that, and 13 such
slots sit inside `push` / `pull` / `legs` sessions on this database.

That is not cosmetic. `days_since_muscle_trained` feeds the adaptive split
scorer, so a 30-second Cat-Cow reset its muscles' recency to zero and made
the generator believe they had been trained — biasing tomorrow's choice away
from muscles that had only been stretched. The same pose credited against
MEV/MAV made a muscle look closer to its weekly target than the training did.
"""

from __future__ import annotations

import inspect

from myvitals.analytics import strength as algo
from myvitals.analytics.strength import is_mobility


class TestMobilityIsNotTraining:
    def test_a_pose_is_recognised(self):
        mobility = [
            e["id"] for e in algo.CATALOG
            if (e.get("movement_pattern") or "") == "mobility"
        ]
        assert mobility, "the catalog has no mobility entries to test against"
        assert is_mobility(mobility[0]) is True

    def test_a_lift_is_not(self):
        lifts = [
            e["id"] for e in algo.CATALOG
            if (e.get("movement_pattern") or "") not in ("mobility", "")
        ]
        assert is_mobility(lifts[0]) is False

    def test_an_unknown_id_is_not_claimed_either_way(self):
        """An imported Strong/Hevy slug has no catalog entry.

        Treating it as mobility would silently drop real logged work out of
        both readers; the honest default for "I cannot tell" is to leave it
        counted, since it came from a session the user actually did.
        """
        assert is_mobility("import_some_unknown_lift") is False

    def test_the_recency_helper_excludes_it(self):
        """This is the one that changes behaviour.

        `days_since_muscle_trained` feeds the adaptive split scorer, so a
        cool-down pose resetting a muscle's recency to zero biases what the
        generator picks tomorrow.
        """
        src = inspect.getsource(algo.days_since_muscle_trained)
        assert "is_mobility" in src

    def test_the_volume_audit_excludes_it(self):
        """A pose credited against MEV/MAV makes a muscle look closer to its
        weekly target than the training did."""
        src = inspect.getsource(algo.weekly_muscle_volume)
        assert "is_mobility" in src

    def test_both_readers_use_the_same_helper(self):
        """Two copies of "is this a stretch" is how the two readers would
        drift, which is the fault this whole backlog keeps finding."""
        assert "movement_pattern" not in inspect.getsource(
            algo.days_since_muscle_trained)


class TestTheFatigueModelIsDeliberatelyAbsent:
    """Pinned in the house style of `test_no_streak_or_completion_percentage`
    and `test_no_default_fat_target_anywhere_in_the_code`: a decision not to
    ship a number is only durable if something fails when it reappears.
    """

    def test_there_is_no_half_life_constant(self):
        """0 of 286 re-trainings clear 50% residual at 36 hours, and the
        maximum reachable is 0.397. Any half-life here would be asserted, not
        measured — which is precisely what HEALTH-1 forbids."""
        src = inspect.getsource(algo)
        assert "HALF_LIFE" not in src
        assert "half_life" not in src

    def test_there_is_no_per_muscle_fatigue_scalar(self):
        """A 0..1 decaying number carries the same three meanings in its zero
        that `progress_pct` carried before GOAL-STATE — no data, fully
        recovered, and never trained — and invites the client-side interval
        this codebase keeps deleting."""
        src = inspect.getsource(algo)
        assert "fatigue_score" not in src
        assert "def fatigue" not in src

    def test_the_recency_helper_still_reports_days_not_a_verdict(self):
        """It returns days since, which is a fact. Turning it into ready /
        recovering / fatigued would be the refused model wearing a smaller
        name, since the thresholds would still need a half-life nobody can
        source.
        """
        src = inspect.getsource(algo.days_since_muscle_trained)
        assert "-> dict[str, float]" in src
        for verdict in ('"fatigued"', '"recovering"', '"ready"'):
            assert verdict not in src
