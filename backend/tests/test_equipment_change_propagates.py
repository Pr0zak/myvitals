"""Selling the bench should reach the plan — OG2-A6.

`PUT /equipment` auto-regenerates today's plan when a training preference
changes, and its comment said equipment was deliberately excluded:

    Equipment-only changes (e.g. flipping a cardio_rower flag) do NOT
    trigger a strength regen since the strength plan is unaffected.

That claim is not true. `filter_catalog_for_equipment` keeps only exercises
whose every required tag is owned, so the plan is built FROM the equipment.
Untick the bench and today's plan went on prescribing bench work: nothing
regenerated, nothing warned, no row was marked, and the user finds out at the
rack.

Two halves, because one fix cannot cover both cases.

**An untouched plan regenerates.** The trigger asks the question directly —
did this edit change WHICH EXERCISES ARE POSSIBLE — by comparing the filtered
catalog before and after. A named-field list was the obvious alternative and
is the worse one: `EquipmentPayload` is a JSON column precisely so it can grow
without a migration, so a second list would need hand-updating every time it
does, and the field someone forgets fails silently. Comparing the catalogs
cannot drift, and it is exact, because it is the same function the generator
selects from.

**A plan already in progress is FLAGGED, not rewritten.** Regenerating under
someone mid-session would delete work they are looking at. `equipment_missing`
says the slot cannot be done and leaves the decision to them — openGym's rule
for the same case, and the same reasoning as the shopping list flagging an
uncostable line rather than dropping it.
"""

from __future__ import annotations

import inspect
import pathlib

from myvitals.analytics import strength as algo
from myvitals.analytics.strength import CATALOG_BY_ID, can_do_exercise
from myvitals.api.workout import strength as api

REPO = pathlib.Path(__file__).resolve().parents[2]
WEB = REPO / "frontend" / "src" / "views" / "workout" / "StrengthToday.vue"
PHONE = (
    REPO / "android" / "app" / "src" / "main" / "kotlin" / "app" / "myvitals"
    / "ui" / "strength" / "StrengthTodayScreen.kt"
)


def _bench_press() -> dict:
    """A catalog exercise that genuinely requires a bench and dumbbells."""
    for ex in CATALOG_BY_ID.values():
        eq = ex.get("equipment") or []
        if "bench" in eq and "dumbbell" in eq:
            return ex
    raise AssertionError("no bench+dumbbell exercise in the catalog")


FULL_GYM = {
    "dumbbells": {"type": "fixed_pairs", "pairs_lb": [10, 20, 30]},
    "bench": {"flat": True, "incline": True, "decline": False},
    "pull_up_bar": True,
    "bodyweight": True,
}
NO_BENCH = {**FULL_GYM, "bench": {"flat": False, "incline": False, "decline": False}}


class TestThePredicateAnswersForOneExercise:
    def test_a_bench_lift_is_possible_with_a_bench(self):
        assert can_do_exercise(_bench_press(), FULL_GYM) is True

    def test_the_same_lift_is_impossible_without_one(self):
        """The reported case. Before extraction nothing could ask this about
        an exercise already in a plan — only about candidates for a new one."""
        assert can_do_exercise(_bench_press(), NO_BENCH) is False

    def test_the_filter_and_the_predicate_cannot_disagree(self):
        """The filter must BE the predicate, not a second copy of it.

        Two implementations of "can I do this" is how the plan and the
        warning would end up contradicting each other.
        """
        src = inspect.getsource(algo.filter_catalog_for_equipment)
        assert "can_do_exercise" in src

    def test_extraction_did_not_change_who_is_filtered_out(self):
        """Behaviour-preserving, checked over the whole catalog."""
        kept = {e["id"] for e in algo.filter_catalog_for_equipment(
            algo.CATALOG, NO_BENCH)}
        for ex_id, ex in CATALOG_BY_ID.items():
            if ex_id in algo.SUPERSEDED_EXERCISE_IDS:
                continue
            assert (ex_id in kept) == can_do_exercise(ex, NO_BENCH)


class TestAnUntouchedPlanRegenerates:
    def test_the_trigger_compares_filtered_catalogs(self):
        src = inspect.getsource(api.put_equipment)
        assert "equipment_changed" in src
        assert "filter_catalog_for_equipment" in src

    def test_the_trigger_actually_gates_the_regeneration(self):
        """Computing the flag and not branching on it is a silent no-op.

        Written after the first version of this file passed while the guard
        had been reverted to `if training_changed:` — the flag was still
        computed, so every assertion about it still held. A test that cannot
        fail is worse than no test, because it reports coverage it does not
        have.
        """
        src = inspect.getsource(api.put_equipment)
        assert "if training_changed or equipment_changed:" in src, (
            "the equipment flag is computed but does not gate the regen"
        )

    def test_it_is_not_a_second_hand_maintained_field_list(self):
        """`EquipmentPayload` is JSON so it can grow without a migration.

        A named-field list would need updating every time it does, and the
        field someone forgets fails silently — which is exactly how the
        training-prefs list came to exclude equipment in the first place.
        """
        src = inspect.getsource(api.put_equipment)
        watched = src[src.index("watched_fields"):src.index("training_changed")]
        for kit in ("bench", "dumbbells", "pull_up_bar", "barbell", "kettlebells_lb"):
            assert kit not in watched, (
                f"{kit} was added to watched_fields — compare the catalogs instead"
            )

    def test_the_regen_still_refuses_to_clobber_logged_work(self):
        """The safety condition is unchanged and is what makes the other
        half necessary: a plan with logged sets is never rewritten."""
        src = inspect.getsource(api.put_equipment)
        assert 'existing.status == "planned"' in src
        assert "logged_count == 0" in src


class TestAPlanInProgressIsFlaggedNotRewritten:
    def test_the_field_exists_and_defaults_to_false(self):
        assert api.WorkoutExerciseOut.model_fields["equipment_missing"].default is False

    def test_it_is_derived_from_the_shared_predicate(self):
        src = inspect.getsource(api._wex_to_out)
        assert "can_do_exercise" in src

    def test_an_exercise_the_catalog_does_not_know_is_not_flagged(self):
        """Unjudgeable is not undoable.

        An imported or superseded id has no equipment tags to check, and
        painting it as missing kit would be a confident claim from no
        evidence — the same distinction `/log/stats` draws in refusing rather
        than averaging what it cannot see.
        """
        src = inspect.getsource(api._wex_to_out)
        assert "meta is not None" in src

    def test_the_slot_is_never_removed(self):
        """Flagged, not deleted.

        Silently dropping work from a session the user is looking at is the
        failure this avoids, and it is the same rule the shopping list
        follows for a line it cannot cost.
        """
        src = inspect.getsource(api._wex_to_out)
        assert "delete" not in src.lower()


class TestBothSurfacesSayIt:
    def test_the_web_renders_the_marker(self):
        src = WEB.read_text()
        assert "equipment_missing" in src

    def test_the_phone_renders_the_marker(self):
        src = PHONE.read_text()
        assert "equipmentMissing" in src

    def test_the_phone_model_defaults_the_field(self):
        """An older server that omits the key must read as fine.

        Moshi throws on a null for a non-nullable field, and this ships to a
        phone that updates on its own schedule.
        """
        models = (
            REPO / "android" / "app" / "src" / "main" / "kotlin" / "app"
            / "myvitals" / "sync" / "Models.kt"
        ).read_text()
        assert 'val equipmentMissing: Boolean = false' in models

    def test_the_marker_is_amber_not_rose(self):
        """GOAL-STATE: rose belongs to the crisis surfaces.

        A slot you cannot do today is worth noticing and is not a crisis.
        """
        assert "pal.caution" in PHONE.read_text()
        assert ".kit-tag" in WEB.read_text()
