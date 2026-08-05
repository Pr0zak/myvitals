"""BAR-2 — bodyweight-tagged exercises that secretly need equipment.

free-exercise-db tags anything without a named implement as
`equipment: ['bodyweight']`, including movements whose instructions say
"hang from a pull-up bar". Those slip past the equipment filter and get
prescribed to someone who owns dumbbells and a bench.

The scan below is the real guard: it re-derives the offenders from the
instruction text every run, so a future catalog addition can't quietly
reintroduce the class of bug rather than just the one instance.
"""
import re

import pytest

from myvitals.analytics.strength import (
    CATALOG,
    _BAR_REQUIRED_EXERCISES,
    _LOW_BAR_REQUIRED_EXERCISES,
    filter_catalog_for_equipment,
)

# A dumbbell-and-bench home gym: no bar of any kind, no rack, no partner.
NO_BAR_EQUIP = {
    "dumbbells": {"type": "fixed_pairs", "pairs_lb": [10, 20, 30, 40, 50]},
    "wrist_weights_lb": [],
    "bench": {"flat": True, "incline": True, "decline": False},
    "barbell": False, "squat_rack": False, "pull_up_bar": False,
    "cable_stack": False, "kettlebells_lb": [], "resistance_bands": False,
    "bodyweight": True, "training_partner": False,
}

_HANGS = re.compile(
    r"hang from|hanging from|pull-?up bar|chin-?up bar|dead ?hang", re.I,
)
_NEEDS_FIXED_BAR = re.compile(
    r"under the bar|\brings\b|suspension trainer|smith machine|"
    r"position a bar|bar in a rack|above the bars", re.I,
)


def _bodyweight_tagged():
    for e in CATALOG:
        eq = [x.lower() for x in (e.get("equipment") or [])]
        if eq and eq != ["bodyweight"]:
            continue
        yield e


def test_no_hanging_exercise_survives_without_a_pull_up_bar():
    pool = {e["id"] for e in filter_catalog_for_equipment(CATALOG, NO_BAR_EQUIP)}
    leaked = [
        e["id"] for e in _bodyweight_tagged()
        if _HANGS.search(" ".join(e.get("instructions") or []))
        and e["id"] in pool
    ]
    assert not leaked, (
        "bodyweight-tagged but requires hanging from a bar: "
        f"{leaked} — add to _BAR_REQUIRED_EXERCISES"
    )


def test_no_fixed_bar_exercise_survives_without_a_bar_or_rack():
    pool = {e["id"] for e in filter_catalog_for_equipment(CATALOG, NO_BAR_EQUIP)}
    leaked = [
        e["id"] for e in _bodyweight_tagged()
        if _NEEDS_FIXED_BAR.search(" ".join(e.get("instructions") or []))
        and e["id"] in pool
    ]
    assert not leaked, (
        "bodyweight-tagged but requires a fixed/parallel bar: "
        f"{leaked} — add to _LOW_BAR_REQUIRED_EXERCISES"
    )


@pytest.mark.parametrize("eid", ["Wind_Sprints", "Body_Tricep_Press",
                                 "Dips_-_Triceps_Version"])
def test_the_specific_leaks_found_in_a_real_plan(eid):
    pool = {e["id"] for e in filter_catalog_for_equipment(CATALOG, NO_BAR_EQUIP)}
    assert eid not in pool


def test_gated_ids_all_exist_in_the_catalog():
    ids = {e["id"] for e in CATALOG}
    for eid in _BAR_REQUIRED_EXERCISES | _LOW_BAR_REQUIRED_EXERCISES:
        assert eid in ids, f"{eid} gated but not in catalog — stale entry"


def test_owning_a_bar_brings_them_back():
    # The gates must be conditional, not a permanent delete.
    with_bar = dict(NO_BAR_EQUIP, pull_up_bar=True, barbell=True,
                    squat_rack=True)
    pool = {e["id"] for e in filter_catalog_for_equipment(CATALOG, with_bar)}
    assert "Wind_Sprints" in pool
    assert "Pullups" in pool
