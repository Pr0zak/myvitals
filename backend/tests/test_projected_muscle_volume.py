"""The muscle map, before the session rather than after it — OG2-C2.

`weekly_muscle_volume` counts LOGGED sets, so the silhouette could only ever
describe training already done. It reports a gap you have already trained
around — which is the limitation openGym's routine editor names in a comment
on the same feature: it shows the diagram while you are still building the
session, "so a gap shows up while you're building it rather than after a
month of training around it".

`project_muscle_volume` adds today's plan to this week's audit, so the same
diagram answers "what will this session leave me at" — a question that can
still be acted on by swapping a slot.

Four decisions inside it:

**The credit rule is identical to the audit's** — primary at 1.0, each
catalog secondary at 0.5. The projected figure is rendered in the same row as
the audited one, and two numbers computed under different rules cannot both
be right.

**`volume_status` is extracted rather than duplicated.** A projection that
called 9 sets "in range" where the audit called it "under" would be two
answers to one question, and the classifier was previously inline.

**Each slot's own `target_sets`, not an assumed session size.** The finisher
picker nearby approximates at three sets per slot with the comment "close
enough" — fine for ranking which gap is widest, wrong for a number a user
reads.

**A declined slot contributes nothing.** SKIP-1 records that declining is a
decision, and projecting work the user has ruled out would show them a week
they are not going to have.

It is computed on read rather than stored, which also means the projection
settles toward the audited figure as sets are logged during the session.
"""

from __future__ import annotations

import inspect

from myvitals.analytics import strength as algo
from myvitals.analytics.strength import (
    ExerciseInPlan,
    project_muscle_volume,
    volume_status,
)
from myvitals.api.workout import strength as api

CURRENT = {
    "chest": {"sets": 4, "mev": 10, "mav": 20, "status": "under"},
    "triceps": {"sets": 2, "mev": 8, "mav": 16, "status": "under"},
    "calves": {"sets": 0, "mev": 8, "mav": 16, "status": "untrained"},
}


def _slot(ex_id: str, sets: int = 4) -> ExerciseInPlan:
    return ExerciseInPlan(
        exercise_id=ex_id, order_index=0, superset_id=None, target_sets=sets,
        target_reps_low=8, target_reps_high=12, target_weight_lb=25.0,
        target_rest_s=90,
    )


def _bench() -> str:
    for e in algo.CATALOG:
        if e.get("primary_muscle") == "chest" and e.get("secondary_muscles"):
            return e["id"]
    raise AssertionError("no chest exercise with secondaries in the catalog")


class TestTheProjection:
    def test_a_planned_slot_credits_its_primary_in_full(self):
        out = project_muscle_volume(CURRENT, [_slot(_bench(), sets=4)])
        assert out["chest"]["sets_planned"] == 4.0
        assert out["chest"]["sets_projected"] == 8.0

    def test_a_secondary_is_credited_at_half(self):
        """The audit's rule exactly. MEV/MAV bands are calibrated to it —
        traps, forearms and lower back had their targets halved precisely
        because they mostly receive secondary stimulus."""
        ex = algo.CATALOG_BY_ID[_bench()]
        sec = [algo.taxonomy.credits_volume(m) for m in ex["secondary_muscles"]]
        out = project_muscle_volume(CURRENT, [_slot(_bench(), sets=4)])
        for m in sec:
            if m in CURRENT:
                assert out[m]["sets_planned"] == 2.0

    def test_an_untouched_muscle_is_unchanged(self):
        out = project_muscle_volume(CURRENT, [_slot(_bench())])
        assert out["calves"]["sets_planned"] == 0.0
        assert out["calves"]["sets_projected"] == 0.0
        assert out["calves"]["status_projected"] == "untrained"

    def test_it_uses_the_slots_own_set_count(self):
        """Not an assumed session size. The finisher picker approximates at
        three per slot and says "close enough" — acceptable for ranking a
        gap, not for a number a user reads."""
        four = project_muscle_volume(CURRENT, [_slot(_bench(), sets=4)])
        two = project_muscle_volume(CURRENT, [_slot(_bench(), sets=2)])
        assert four["chest"]["sets_planned"] == 4.0
        assert two["chest"]["sets_planned"] == 2.0

    def test_mobility_is_not_projected_as_training(self):
        """OG2-C1's rule, applied here by the same helper. A cool-down pose
        appended to a strength day is not training the muscle it stretches."""
        poses = [e["id"] for e in algo.CATALOG
                 if (e.get("movement_pattern") or "") == "mobility"]
        assert poses
        out = project_muscle_volume(CURRENT, [_slot(poses[0], sets=2)])
        assert all(v["sets_planned"] == 0.0 for v in out.values())

    def test_an_unknown_exercise_projects_nothing(self):
        """An imported slug has no catalog entry, so there is nothing to
        attribute. Guessing would put sets on a muscle from no evidence."""
        out = project_muscle_volume(CURRENT, [_slot("import_unknown_lift")])
        assert all(v["sets_planned"] == 0.0 for v in out.values())

    def test_the_audit_figure_is_preserved_alongside(self):
        """Both numbers travel, so a client can say "4 now, 8 after today"
        rather than replacing one with the other."""
        out = project_muscle_volume(CURRENT, [_slot(_bench())])
        assert out["chest"]["sets"] == 4
        assert out["chest"]["sets_projected"] == 8.0


class TestOneClassifier:
    def test_the_status_rule_is_shared(self):
        """It was inline in the audit. Two copies would let the projection
        call 9 sets "in range" where the audit called it "under"."""
        assert "volume_status(" in inspect.getsource(algo.weekly_muscle_volume)
        assert "volume_status(" in inspect.getsource(project_muscle_volume)

    def test_the_bands_behave_as_documented(self):
        assert volume_status(0, 10, 20) == "untrained"
        assert volume_status(4, 10, 20) == "under"
        assert volume_status(10, 10, 20) == "in_range"
        assert volume_status(21, 10, 20) == "over"


class TestItReachesTheClients:
    def test_the_workout_carries_it(self):
        assert "projected_muscle_volume" in api.WorkoutOut.model_fields

    def test_it_is_computed_on_read_not_stored(self):
        """So it settles toward the audited figure as sets are logged, and so
        there is exactly one place that computes it."""
        assert "project_muscle_volume" in inspect.getsource(api._hydrate_workout)
        assert "projected_muscle_volume" not in inspect.getsource(algo.persist_plan)

    def test_a_declined_slot_is_excluded(self):
        """SKIP-1: declining is a decision, and projecting work the user has
        ruled out would show a week they are not going to have."""
        src = inspect.getsource(api._hydrate_workout)
        block = src[src.index("project_muscle_volume"):]
        assert "if not e.skipped" in block[:900]
