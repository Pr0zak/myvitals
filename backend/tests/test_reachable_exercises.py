"""Can this kit even train that muscle? (OG3-B2)

The weekly audit answers "did you train this muscle enough". It cannot
answer the question standing behind it. A muscle you own one exercise for
and a muscle you simply skipped this week render identically as "under",
and only one of those is something the user can act on.

This file also records a CORRECTION to the teardown entry that asked for the
feature. That entry counted `primary_muscle` only and reported "five of
fourteen muscles have a pool smaller than their own MEV". Counted against
what MEV actually credits — prime movers at 1.0 and catalog-tagged
secondaries at 0.5, per the audit's own rule — the real figure on this
user's equipment is ONE: lats, with 9 reachable exercises against an MEV of
10. The prime-mover pools are genuinely thin for several more (lower back 1,
lats 2, calves 4, traps 4), which is why both numbers are reported, but the
flag has to use the same arithmetic as the thing it is annotating or it
fires on muscles that are in fact trainable.
"""

from __future__ import annotations

from myvitals.analytics import strength as strength_algo
from myvitals.analytics.taxonomy import MUSCLE_VOLUME_TARGETS

#: The real shape of this user's home gym: fixed dumbbell pairs, a bench,
#: nothing else. Deliberately not a fixture with everything switched on —
#: the whole point of the count is what happens when kit is absent.
HOME_GYM = {
    "dumbbells": {"type": "fixed_pairs",
                  "pairs_lb": [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]},
    "bench": {"flat": True, "incline": True},
    "barbell": False,
    "cable": False,
    "kettlebell": False,
    "bands": False,
    "pull_up_bar": False,
    "wrist_weights_lb": [],
}


class TestItCountsTheGeneratorsOwnPool:
    def test_every_audited_muscle_gets_a_row(self):
        """Absent is not zero-by-omission: every muscle reports a count."""
        reach = strength_algo.reachable_exercises_by_muscle(HOME_GYM, {})
        assert set(reach) == set(MUSCLE_VOLUME_TARGETS)
        for muscle, row in reach.items():
            assert row["primary"] >= 0 and row["any"] >= 0
            assert row["any"] >= row["primary"], (
                f"{muscle}: `any` must include the prime-mover exercises"
            )

    def test_equipment_actually_constrains_the_count(self):
        """A barbell-and-cable gym reaches strictly more than this one.

        If it did not, the count would be measuring the catalog rather than
        the kit, which is the whole failure the feature exists to fix.
        """
        rich = dict(HOME_GYM, barbell=True, cable=True, pull_up_bar=True)
        lean = strength_algo.reachable_exercises_by_muscle(HOME_GYM, {})
        full = strength_algo.reachable_exercises_by_muscle(rich, {})
        assert sum(r["any"] for r in full.values()) > \
            sum(r["any"] for r in lean.values())

    def test_a_disabled_exercise_leaves_the_pool(self):
        """`exercise_prefs` is honoured, because the generator honours it.

        An exercise the user turned off is not one their kit can reach, and
        counting it would overstate the pool in exactly the case where the
        user has deliberately narrowed it.
        """
        base = strength_algo.reachable_exercises_by_muscle(HOME_GYM, {})
        # Deliberately NOT `next(iter(...))` over a set: iteration order
        # varies with the hash seed, and an arbitrary pick can land on a
        # mobility row, which the count excludes — so the test passed or
        # failed depending on the run. Pick a named, counted exercise.
        some_id = "Dumbbell_Bench_Press"
        assert some_id in strength_algo.selectable_catalog_ids(HOME_GYM, {})
        off = strength_algo.reachable_exercises_by_muscle(
            HOME_GYM, {some_id: "disabled"})
        assert sum(r["any"] for r in off.values()) < \
            sum(r["any"] for r in base.values())

    def test_mobility_is_excluded(self):
        """Same reason OG2-C1 excluded it from volume.

        A cool-down pose is not a route to MEV, so counting one as a way to
        train a muscle would make a thin pool look adequate.
        """
        import inspect
        src = inspect.getsource(strength_algo.reachable_exercises_by_muscle)
        assert "is_mobility" in src


class TestTheFlagUsesTheAuditsOwnArithmetic:
    def test_lats_is_the_muscle_this_kit_cannot_reach_to_mev(self):
        """The measured fact, pinned so a catalog change surfaces it.

        This is an assertion about THIS user's equipment and the bundled
        catalog together. If it starts failing, one of the two moved — which
        is worth knowing either way, since the audit card's honesty depends
        on it.
        """
        reach = strength_algo.reachable_exercises_by_muscle(HOME_GYM, {})
        below = {
            m for m, r in reach.items()
            if r["any"] < MUSCLE_VOLUME_TARGETS[m][0]
        }
        assert below == {"lats"}, (
            f"expected only lats below MEV on this kit, got {sorted(below)}"
        )

    def test_counting_prime_movers_only_would_overfire(self):
        """Why the flag does not use `primary`.

        Against prime movers alone this kit looks unable to reach five
        muscles. The audit credits secondaries at 0.5, so those muscles DO
        accumulate volume and the flag would be wrong — an alarm that fires
        on healthy data is the HEALTH-1 failure, and it is the reason the
        teardown entry's own figure is corrected here rather than adopted.
        """
        reach = strength_algo.reachable_exercises_by_muscle(HOME_GYM, {})
        by_primary = {
            m for m, r in reach.items()
            if r["primary"] < MUSCLE_VOLUME_TARGETS[m][0]
        }
        by_any = {
            m for m, r in reach.items()
            if r["any"] < MUSCLE_VOLUME_TARGETS[m][0]
        }
        assert len(by_primary) > len(by_any)
