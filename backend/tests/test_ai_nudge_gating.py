"""The AI variety nudge may only suggest exercises the user can actually do.

`build_strength_nudge_payload` received the whole bundled catalog and built
its swap pool from every row matching today's muscles. Equipment was not
consulted — the code comment claimed it was "already represented by what the
generator picked from", but the pool came from the catalog, not from the
generator's filtered candidates. Neither were `exercise_prefs`.

So the coach could propose swapping in a barbell lift for someone who owns
dumbbells, or an exercise the user had explicitly turned off. That reads as
the coach not having read the settings, and it spends a metered AI call to
produce advice that cannot be taken.
"""

from __future__ import annotations

import inspect

from myvitals.analytics import strength as strength_algo
from myvitals.integrations import claude

DUMBBELL_ONLY = {
    "dumbbells": {"type": "fixed_pairs", "pairs_lb": [10, 20, 30, 40]},
    "bench": {"flat": True},
    "barbell": False,
    "cable": False,
    "kettlebell": False,
    "bands": False,
    "pull_up_bar": False,
}


def test_selectable_ids_excludes_equipment_the_user_lacks():
    ids = strength_algo.selectable_catalog_ids(DUMBBELL_ONLY)
    assert ids, "expected some exercises to survive the filter"
    for eid in ids:
        equipment = set(strength_algo.CATALOG_BY_ID[eid].get("equipment") or [])
        assert not (equipment - {"dumbbell", "bench", "bodyweight"}), (
            f"{eid} needs {equipment}, which this equipment set does not include"
        )


def test_selectable_ids_excludes_disabled_exercises():
    ids_all = strength_algo.selectable_catalog_ids(DUMBBELL_ONLY)
    victim = sorted(ids_all)[0]
    ids_less = strength_algo.selectable_catalog_ids(
        DUMBBELL_ONLY, {victim: "disabled"},
    )
    assert victim in ids_all
    assert victim not in ids_less, "a disabled exercise is still selectable"


def test_selectable_ids_excludes_superseded_duplicates():
    """DEDUP-1 rows are the same movement as another entry; offering one as a
    variety swap for the other would be a swap in name only."""
    ids = strength_algo.selectable_catalog_ids(DUMBBELL_ONLY)
    for superseded in strength_algo.SUPERSEDED_EXERCISE_IDS:
        assert superseded not in ids


def test_favourite_and_avoid_prefs_do_not_remove_an_exercise():
    """Only "disabled" is an exclusion. "avoid" biases ordering inside the
    generator and must still be offerable as a swap."""
    ids_plain = strength_algo.selectable_catalog_ids(DUMBBELL_ONLY)
    victim = sorted(ids_plain)[0]
    for pref in ("avoid", "favorite"):
        assert victim in strength_algo.selectable_catalog_ids(
            DUMBBELL_ONLY, {victim: pref},
        ), f"pref={pref} should not exclude"


def test_the_payload_builder_honours_the_gate():
    src = inspect.getsource(claude.build_strength_nudge_payload)
    assert "selectable_ids" in src
    assert "cid not in selectable_ids" in src, (
        "the swap pool must be filtered by the generator's own selection rule"
    )


def test_the_pool_excludes_what_is_already_prescribed_today():
    """Suggesting a swap to something already in today's plan is never a
    variety improvement."""
    src = inspect.getsource(claude.build_strength_nudge_payload)
    assert "in_plan" in src and "cid in in_plan" in src


def test_the_pool_is_ordered_by_least_used_not_by_catalog_order():
    """The old cap took whatever the catalog listed first, biasing every
    suggestion toward the same alphabetical head — working directly against
    the variety the feature exists to provide."""
    src = inspect.getsource(claude.build_strength_nudge_payload)
    assert "candidates.sort" in src
    assert "recent_history.get" in src


def test_the_endpoint_passes_the_gate_through():
    from myvitals.api import ai as ai_api

    src = inspect.getsource(ai_api.strength_nudge_endpoint)
    assert "selectable_catalog_ids" in src
    assert "exercise_prefs" in src


def test_focus_cue_still_gets_the_full_catalog():
    """Deliberate asymmetry: the focus cue only resolves NAMES for exercises
    already in the plan, which may include ones the user has since disabled
    or lost the equipment for. Filtering there would blank them."""
    from myvitals.api import ai as ai_api

    src = inspect.getsource(ai_api.strength_focus_cue_endpoint)
    assert "CATALOG_BY_ID" in src
    assert "selectable_catalog_ids" not in src


# ---------------------------------------------------------------------------
# OG3-C1 — the model's ANSWER is untrusted too, not just its options
# ---------------------------------------------------------------------------
#
# Gating the payload decides what the model may choose from. It does nothing
# about what the model actually returns. `strength_nudge` took `block.input`
# verbatim, JSON-dumped it and cached it in `ai_summaries`, so a bad answer
# persisted until the plan changed — and both clients rendered the raw slug
# through `replace("_", " ")`, which is precisely what made a hallucinated id
# look like a real exercise.

PAYLOAD = {
    # The real shape `build_strength_nudge_payload` returns. The first draft
    # of this fixture used a flat `today_plan` key, which the validator also
    # read — so both sides were wrong together and every test passed while
    # the real card would have rendered empty. Mirroring the builder's actual
    # output is the point of the fixture.
    "today": {"date": "2026-09-17", "split": "push", "exercises": [
        {"exercise_id": "One-Arm_Dumbbell_Row", "name": "One-Arm Dumbbell Row",
         "primary_muscle": "back"},
        {"exercise_id": "Dumbbell_Bench_Press", "name": "Dumbbell Bench Press",
         "primary_muscle": "chest"},
    ]},
    "available_catalog": [
        {"exercise_id": "Incline_Dumbbell_Row", "name": "Incline Dumbbell Row",
         "primary_muscle": "back"},
        {"exercise_id": "Dumbbell_Flyes", "name": "Dumbbell Flyes",
         "primary_muscle": "chest"},
    ],
}

CATALOG = {
    "One-Arm_Dumbbell_Row": {"name": "One-Arm Dumbbell Row", "primary_muscle": "back"},
    "Dumbbell_Bench_Press": {"name": "Dumbbell Bench Press", "primary_muscle": "chest"},
    "Incline_Dumbbell_Row": {"name": "Incline Dumbbell Row", "primary_muscle": "back"},
    "Dumbbell_Flyes": {"name": "Dumbbell Flyes", "primary_muscle": "chest"},
    # In the catalog, offered, but trains something else entirely.
    "Dumbbell_Curl": {"name": "Dumbbell Curl", "primary_muscle": "biceps"},
}


def _validate(swaps):
    return claude.validate_strength_swaps({"swaps": swaps}, PAYLOAD, CATALOG)


class TestAGoodSwapSurvives:
    def test_it_is_kept_and_named(self):
        out = _validate([{
            "target_exercise_id": "One-Arm_Dumbbell_Row",
            "replacement_exercise_id": "Incline_Dumbbell_Row",
            "reason": "not seen in four weeks",
        }])
        assert len(out["swaps"]) == 1
        swap = out["swaps"][0]
        assert swap["target_name"] == "One-Arm Dumbbell Row"
        assert swap["replacement_name"] == "Incline Dumbbell Row"
        assert "notes" not in out, "a clean answer should not be annotated"

    def test_names_are_attached_so_clients_stop_un_slugging_ids(self):
        """The client cannot tell a hallucinated id from a real one.

        Both surfaces rendered `id.replace("_", " ")`, which turns any
        plausible-looking string into a plausible-looking exercise name.
        Sending the catalog's own name removes the guesswork.
        """
        out = _validate([{
            "target_exercise_id": "Dumbbell_Bench_Press",
            "replacement_exercise_id": "Dumbbell_Flyes",
            "reason": "same pattern, fresher stimulus",
        }])
        assert out["swaps"][0]["replacement_name"] == "Dumbbell Flyes"


class TestBadSwapsAreDroppedAndSaidSo:
    def test_a_hallucinated_replacement_is_dropped(self):
        out = _validate([{
            "target_exercise_id": "One-Arm_Dumbbell_Row",
            "replacement_exercise_id": "Cable_Machine_Row_3000",
            "reason": "variety",
        }])
        assert out["swaps"] == []
        assert out["notes"], "a drop must be recorded, not silent"

    def test_a_target_not_in_todays_plan_is_dropped(self):
        out = _validate([{
            "target_exercise_id": "Barbell_Squat",
            "replacement_exercise_id": "Incline_Dumbbell_Row",
            "reason": "variety",
        }])
        assert out["swaps"] == []
        assert out["notes"]

    def test_a_valid_id_for_the_wrong_muscle_is_dropped(self):
        """The failure mode that never announced itself.

        A hallucinated id at least 404s on Accept. A real exercise for a
        different muscle is accepted silently and quietly changes what the
        session trains.

        Note this is reachable precisely BECAUSE the pool filter is coarse:
        `available_catalog` admits anything matching ANY muscle trained
        today, so on a day with both chest and back slots, a back exercise
        is a legitimate pool member and an illegitimate replacement for the
        chest slot. Only the per-slot check catches that.
        """
        out = _validate([{
            "target_exercise_id": "Dumbbell_Bench_Press",     # chest slot
            "replacement_exercise_id": "Incline_Dumbbell_Row",  # back, but offered
            "reason": "variety",
        }])
        assert out["swaps"] == []
        assert any("changes what the session trains" in n for n in out["notes"])

    def test_a_good_swap_survives_beside_a_bad_one(self):
        """Dropping is per-swap. One bad suggestion must not discard a
        good one, or the validator becomes a reason to distrust the card."""
        out = _validate([
            {"target_exercise_id": "One-Arm_Dumbbell_Row",
             "replacement_exercise_id": "Nonexistent_Lift", "reason": "x"},
            {"target_exercise_id": "Dumbbell_Bench_Press",
             "replacement_exercise_id": "Dumbbell_Flyes", "reason": "y"},
        ])
        assert len(out["swaps"]) == 1
        assert out["swaps"][0]["replacement_exercise_id"] == "Dumbbell_Flyes"
        assert out["notes"]


class TestItSurvivesAMalformedAnswer:
    def test_a_non_list_swaps_field_does_not_raise(self):
        out = claude.validate_strength_swaps({"swaps": "none"}, PAYLOAD, CATALOG)
        assert out["swaps"] == []
        assert out["notes"]

    def test_junk_entries_are_skipped(self):
        out = claude.validate_strength_swaps(
            {"swaps": ["not a dict", None]}, PAYLOAD, CATALOG)
        assert out["swaps"] == []

    def test_the_two_swap_cap_is_enforced_here_too(self):
        """`maxItems` is a schema hint the CLI provider does not enforce.

        `claude_cli` injects the schema into the system prompt and parses
        the reply as JSON — there is no schema-constrained decoding — so the
        cap has to hold in code as well.
        """
        out = _validate([
            {"target_exercise_id": "One-Arm_Dumbbell_Row",
             "replacement_exercise_id": "Incline_Dumbbell_Row", "reason": "a"},
            {"target_exercise_id": "Dumbbell_Bench_Press",
             "replacement_exercise_id": "Dumbbell_Flyes", "reason": "b"},
            {"target_exercise_id": "One-Arm_Dumbbell_Row",
             "replacement_exercise_id": "Incline_Dumbbell_Row", "reason": "c"},
        ])
        assert len(out["swaps"]) == 2


def test_the_runner_validates_before_returning():
    """Pinned at the call site, because caching is what makes it matter.

    The caller writes this result into `ai_summaries` keyed by payload
    hash. An unvalidated answer would not just be wrong once — it would be
    wrong every time the same plan was asked about, until the plan changed.
    """
    src = inspect.getsource(claude.strength_nudge)
    assert "validate_strength_swaps" in src
