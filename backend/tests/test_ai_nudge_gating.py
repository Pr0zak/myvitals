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
