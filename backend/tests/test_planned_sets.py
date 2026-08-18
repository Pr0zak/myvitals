"""Per-set prescription and prefill resolution — TD-6.

The prescription was a single flat target on the slot, and each client turned
it into per-set input values with its own rule. They disagreed:
`StrengthToday.vue` seeded every set from the slot target with no rating,
while `StrengthTodayScreen.kt` inherited weight and reps from the most
recently logged set of the same exercise and pre-selected a rating of 4. Same
workout, same screen, two different starting values — on the app's most-used
surface, and invisible to `parity_check.py` because both files exist and both
keep changing.

The cascade is borrowed from SparkyFitness's `resolveAssumedSetValues`, which
is the single most transferable idea in that codebase.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

from myvitals.api.workout.strength import LastSetOut, _planned_sets


def _wex(target_sets=3, reps_low=8, weight=40.0, rest=90):
    return SimpleNamespace(
        target_sets=target_sets, target_reps_low=reps_low, target_reps_high=12,
        target_weight_lb=weight, target_rest_s=rest,
    )


def _set(n, weight=None, reps=None, rating=None, set_type="working", skipped=False):
    return SimpleNamespace(
        set_number=n, actual_weight_lb=weight, actual_reps=reps,
        rating=rating, set_type=set_type, skipped=skipped,
    )


# --------------------------------------------------------------------------
# Shape
# --------------------------------------------------------------------------

def test_one_row_per_prescribed_set():
    rows = _planned_sets(_wex(target_sets=4), [], None, None)
    assert [r.set_number for r in rows] == [1, 2, 3, 4]
    assert all(r.rest_s == 90 for r in rows)
    assert all(r.target_reps == 8 for r in rows)


def test_the_plan_is_derived_never_materialised():
    """Writing placeholder rows would break two things at once.

    `log_set` is idempotent on (workout_exercise_id, set_number) *because*
    sets are created lazily, which the phone's offline replay depends on.
    And the SKIP-1 note already documents why fabricated rows are poisonous:
    `recent_mobility_history` counts a skipped set as a failed one and lowers
    the next hold prescription, and the deload payload folds them into
    `missed_or_skipped_sets`, which the coach reads as fatigue.
    """
    src = inspect.getsource(_planned_sets)
    assert "db.add" not in src
    assert "StrengthSet(" not in src


# --------------------------------------------------------------------------
# The cascade
# --------------------------------------------------------------------------

def test_a_fresh_slot_prefills_from_the_prescription():
    rows = _planned_sets(_wex(), [], None, None)
    assert rows[0].prefill_weight_lb == 40.0
    assert rows[0].prefill_reps == 8


def test_an_edit_on_set_one_carries_forward():
    """The phone's rule, and the correct one: if you found 40 lb too light
    and did 45, set 2 should not offer 40 again."""
    rows = _planned_sets(_wex(), [_set(1, weight=45.0, reps=10)], None, None)
    assert rows[1].prefill_weight_lb == 45.0
    assert rows[1].prefill_reps == 10


def test_last_session_seeds_the_first_set_when_nothing_is_logged_yet():
    last = [LastSetOut(set_number=1, weight_lb=42.5, reps=9)]
    rows = _planned_sets(_wex(), [], last, None)
    assert rows[0].prefill_weight_lb == 42.5
    assert rows[0].prefill_reps == 9


def test_this_session_beats_last_session():
    """Tier order matters: what you just did is better evidence than what you
    did last week."""
    last = [LastSetOut(set_number=2, weight_lb=42.5, reps=9)]
    rows = _planned_sets(_wex(), [_set(1, weight=50.0, reps=6)], last, None)
    assert rows[1].prefill_weight_lb == 50.0


def test_a_warmup_never_seeds_a_working_set():
    """The specific insight worth borrowing from resolveAssumedSetValues.

    Inheriting from a light warm-up would quietly halve the working weight,
    and the user would have to notice and correct it every session.
    """
    rows = _planned_sets(
        _wex(), [_set(1, weight=15.0, reps=12, set_type="warmup")], None, None,
    )
    assert rows[1].prefill_weight_lb == 40.0, "warm-up leaked into the working set"


def test_an_already_logged_set_prefills_from_what_was_actually_done():
    """Editing a logged set must start from the truth, not from the plan."""
    rows = _planned_sets(_wex(), [_set(2, weight=47.5, reps=7, rating=2)], None, None)
    assert rows[1].prefill_weight_lb == 47.5
    assert rows[1].prefill_reps == 7
    assert rows[1].prefill_rating == 2


def test_skipped_sets_do_not_seed_anything():
    """A skipped set records that no work happened; using it as evidence of
    what to do next would be inventing a data point."""
    rows = _planned_sets(
        _wex(), [_set(1, weight=99.0, reps=1, skipped=True)], None, None,
    )
    assert rows[1].prefill_weight_lb == 40.0


# --------------------------------------------------------------------------
# Rating
# --------------------------------------------------------------------------

def test_rating_is_never_pre_selected():
    """The phone pre-selected "Good" to save a tap. The rating is the input
    to next session's weight selection, so defaulting it manufactures
    progression data from a user who tapped through without thinking."""
    rows = _planned_sets(_wex(), [], None, None)
    assert all(r.prefill_rating is None for r in rows)


def test_a_logged_rating_is_returned_for_editing():
    rows = _planned_sets(_wex(), [_set(1, weight=40.0, reps=8, rating=5)], None, None)
    assert rows[0].prefill_rating == 5


# --------------------------------------------------------------------------
# AMRAP
# --------------------------------------------------------------------------

def test_greyskull_marks_only_the_last_set_amrap():
    program = {"scheme": "greyskull", "amrap_last_set": True}
    rows = _planned_sets(_wex(target_sets=3), [], None, program)
    assert [r.is_amrap for r in rows] == [False, False, True]


def test_other_schemes_have_no_amrap_set():
    for program in (
        {"scheme": "linear", "amrap_last_set": False},
        {"scheme": "double", "amrap_last_set": False},
        # A stale config claiming amrap on a non-Greyskull scheme must not
        # produce one — the flag belongs to Greyskull.
        {"scheme": "linear", "amrap_last_set": True},
        None,
    ):
        rows = _planned_sets(_wex(), [], None, program)
        assert not any(r.is_amrap for r in rows), program


# --------------------------------------------------------------------------
# Structural — neither client may derive its own starting values again
# --------------------------------------------------------------------------

def test_neither_client_derives_its_own_prefill():
    """The divergence this task fixed is easy to reintroduce.

    Both surfaces had a local rule for turning one flat slot target into
    per-set inputs, and the rules differed. `parity_check.py` could not see
    it, because both files existed and both kept changing — the gate checks
    that paired files move together, not that they compute the same answer.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    web = (root / "frontend" / "src" / "views" / "workout" / "StrengthToday.vue").read_text()
    phone = (
        root / "android" / "app" / "src" / "main" / "kotlin" / "app" / "myvitals"
        / "ui" / "strength" / "StrengthTodayScreen.kt"
    ).read_text()

    assert "planned_sets" in web, "the web must read the server's planned sets"
    assert "plannedSets" in phone, "the phone must read the server's planned sets"

    # The phone's old rule: find the most recently logged set and inherit
    # from it. That logic belongs on the server now.
    assert "priorLogged" not in phone, (
        "the phone is deriving its own prefill again — the cascade lives in "
        "_planned_sets so both surfaces agree"
    )
    # And it must not silently re-add a default rating.
    assert "rating = 4," not in phone, (
        "a pre-selected rating manufactures the input to next session's "
        "weight selection"
    )


def test_both_surfaces_can_record_a_set_type():
    """SETTYPE-1 shipped a set-type picker on the phone; the web hard-coded
    "working" with no UI, so a warm-up logged there counted as a working set
    in the volume audit and seeded the next session's ghost line."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    web = (root / "frontend" / "src" / "views" / "workout" / "StrengthToday.vue").read_text()
    assert 'class="settype-cell"' in web, "the web still cannot record a warm-up"
