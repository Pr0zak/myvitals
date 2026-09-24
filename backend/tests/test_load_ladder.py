"""UI-F4 — the logger's +/- stepper walks a ladder of loadable weights.

The ladder is a window onto the SAME load set the micro-loader rounder snaps
prescriptions onto, so these tests pin it against `round_weight` /
`valid_dumbbell_loads` rather than against hand-written expectations alone.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from myvitals.analytics.strength import (
    LOAD_LADDER_STEPS, load_ladder, round_weight, valid_dumbbell_loads,
)
from myvitals.api.workout.strength import _CATALOG, _load_ladder_for

PAIRS_5S = [5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0]
WRISTS = [1.0, 1.5, 2.0, 3.0]


@pytest.mark.parametrize("pairs,wrist", [
    (PAIRS_5S, WRISTS), (PAIRS_5S, []), ([10.0, 20.0, 30.0], [2.5]),
])
@pytest.mark.parametrize("raw", [4.0, 12.3, 27.0, 31.0, 44.9, 70.0])
def test_monotonic_bounded_and_contains_the_rounded_target(pairs, wrist, raw):
    target = round_weight(raw, pairs, wrist)
    ladder = load_ladder(target, pairs, wrist)
    assert ladder
    assert all(a < b for a, b in zip(ladder, ladder[1:]))
    assert target in ladder
    i = ladder.index(target)
    assert i <= LOAD_LADDER_STEPS
    assert len(ladder) - 1 - i <= LOAD_LADDER_STEPS


def test_every_rung_is_loadable_with_the_owned_gear():
    valid = set(valid_dumbbell_loads(PAIRS_5S, WRISTS))
    assert set(load_ladder(30.0, PAIRS_5S, WRISTS)) <= valid


def test_no_micro_loaders_steps_by_whole_pairs():
    # The fixed 2.5 lb step would offer 32.5 — the rack cannot make it.
    assert load_ladder(30.0, PAIRS_5S, []) == PAIRS_5S
    assert 32.5 not in load_ladder(30.0, PAIRS_5S, [])


def test_micro_loaders_fill_the_gaps_between_pairs():
    ladder = load_ladder(30.0, PAIRS_5S, WRISTS)
    i = ladder.index(30.0)
    # Half-pound rungs, each one real: 25 + (1+1.5+3) = 30.5 above,
    # 25 + (1+1.5+2) = 29.5 below. A fixed 2.5 lb step would skip both.
    assert ladder[i + 1] == 30.5
    assert ladder[i - 1] == 29.5


def test_sparse_pairs_are_respected():
    # Only a 10 and a 20 pair + one 2.5 micro: 10, 12.5, 20, 22.5.
    assert load_ladder(12.5, [10.0, 20.0], [2.5]) == [10.0, 12.5, 20.0, 22.5]


def test_window_is_bounded_on_a_dense_rack():
    ladder = load_ladder(30.0, PAIRS_5S, WRISTS)
    assert len(ladder) == 2 * LOAD_LADDER_STEPS + 1


def test_unloadable_stored_target_is_not_inserted():
    # A target made with gear since sold: the ladder lists only real loads.
    ladder = load_ladder(32.5, PAIRS_5S, [])
    assert 32.5 not in ladder
    assert 30.0 in ladder and 35.0 in ladder


def test_null_without_a_weight_or_without_dumbbells():
    assert load_ladder(None, PAIRS_5S, WRISTS) is None
    assert load_ladder(30.0, [], WRISTS) is None


def _wex(exercise_id, weight):
    return SimpleNamespace(exercise_id=exercise_id, target_weight_lb=weight)


def _first(pred):
    return next(e for e in _CATALOG if pred(e))


def test_slot_ladder_null_for_bodyweight_and_timed():
    bw = _first(lambda e: "dumbbell" not in e["equipment"] and not e.get("is_timed"))
    assert _load_ladder_for(_wex(bw["id"], None), bw, PAIRS_5S, WRISTS) is None
    # Even a stray weight on a bodyweight slot gets no stepper.
    assert _load_ladder_for(_wex(bw["id"], 20.0), bw, PAIRS_5S, WRISTS) is None
    timed = {"id": "x", "equipment": ["dumbbell"], "is_timed": True}
    assert _load_ladder_for(_wex("x", 20.0), timed, PAIRS_5S, WRISTS) is None
    assert _load_ladder_for(_wex("nope", 20.0), None, PAIRS_5S, WRISTS) is None


def test_slot_ladder_for_a_dumbbell_lift():
    db = _first(lambda e: "dumbbell" in e["equipment"] and not e.get("is_timed"))
    ladder = _load_ladder_for(_wex(db["id"], 30.0), db, PAIRS_5S, WRISTS)
    assert ladder == load_ladder(30.0, PAIRS_5S, WRISTS)
