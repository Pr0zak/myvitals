"""Ad-hoc exercise slots — TD-10.

Work performed off-plan was unrecordable. Enumerating every route in
``api/workout/strength.py`` before this change turns up
``POST /workout-exercises/{id}/swap`` (strictly 1:1, refusing once a set is
logged), ``DELETE /workouts/{id}`` and ``DELETE /sets/{id}`` -- and nothing
that adds an exercise to a session. ``POST /workouts`` exists but
``createStrengthWorkout`` in the web client has zero call sites and the
phone's Retrofit interface never declared it, so the generator was the only
way a session came into being.

Three extra sets of curls done in the moment therefore had nowhere to go,
which meant they were absent from tonnage, ``weekly_muscle_volume``,
``/records``, ``recent_frequency_by_exercise`` rotation pressure and every AI
payload. The work happened and the app never knew.
"""

from __future__ import annotations

import inspect

from fastapi.routing import APIRoute

from myvitals.api.workout import strength


def _paths() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for route in strength.router.routes:
        if isinstance(route, APIRoute):
            out.setdefault(route.path, set()).update(route.methods)
    return out


def test_the_add_and_delete_routes_exist():
    paths = _paths()
    assert "POST" in paths.get("/workout/strength/workouts/{workout_id}/exercises", set())
    assert "DELETE" in paths.get("/workout/strength/workout-exercises/{wex_id}", set())


def test_add_returns_the_whole_workout():
    """Matching the SKIP-1 PATCH convention.

    Returning just the new slot would leave the caller to re-derive the
    progress counters and the session summary, which is exactly the
    client-side re-derivation the counters were introduced to remove.
    """
    route = next(
        r for r in strength.router.routes
        if isinstance(r, APIRoute)
        and r.path == "/workout/strength/workouts/{workout_id}/exercises"
    )
    assert route.response_model is strength.WorkoutOut


def test_delete_returns_the_whole_workout():
    route = next(
        r for r in strength.router.routes
        if isinstance(r, APIRoute)
        and r.path == "/workout/strength/workout-exercises/{wex_id}"
        and "DELETE" in r.methods
    )
    assert route.response_model is strength.WorkoutOut


def test_the_prescription_is_server_computed_from_the_shared_chain():
    """The weight must come from history via the generator's own helpers.

    A client-guessed weight would violate the architecture rule and then
    disagree with the server on the next reload. Reusing prescribe_slot also
    means an added plank prescribes seconds rather than reps, without a
    second copy of the is_timed logic.
    """
    src = inspect.getsource(strength.add_exercise)
    assert "last_target_weight_for_exercise" in src
    # OG2-A2: the rating/weight decision moved behind `weight_from_history`,
    # which calls `progress_from_rating` when a rating exists and holds at
    # the logged weight when one does not. Asserting the shared entry point
    # rather than the inner helper is the stronger check — a site that
    # reached past it to `progress_from_rating` would have reintroduced the
    # three-way branch this consolidated.
    # OG2-B2 moved the branch behind `next_prescription`, which also owns
    # the starting-table fallback — so this site no longer names either.
    assert "next_prescription" in src
    assert "round_weight" in src
    assert "prescribe_slot" in src


def test_ad_hoc_slots_are_flagged_on_the_wire():
    """The distinction the AI reviewer and explain_workout both consume."""
    assert "added_ad_hoc" in strength.WorkoutExerciseOut.model_fields
    assert strength.WorkoutExerciseOut.model_fields["added_ad_hoc"].default is False


def test_add_marks_the_slot_and_never_joins_a_superset():
    """A superset pairing in SPLIT_SLOTS is deliberate; an appended accessory
    has no partner, and inventing one would misrepresent how it was done."""
    src = inspect.getsource(strength.add_exercise)
    assert "added_ad_hoc=True" in src
    assert "superset_id=None" in src


def test_delete_refuses_when_real_sets_exist():
    """Same contract as swap. The actuals are a record of work that was
    performed; deleting the slot would silently erase it. Skipping is the
    right move for "I'm not doing the rest of this"."""
    src = inspect.getsource(strength.delete_exercise)
    assert "status_code=409" in src
    assert "actual_reps.is_not(None)" in src


def test_add_refuses_on_a_closed_session():
    """Appending to a finished workout would rewrite what was performed
    rather than record it."""
    src = inspect.getsource(strength.add_exercise)
    assert '"completed"' in src and "409" in src


def test_the_ai_reviewer_is_told_about_ad_hoc_slots():
    """Reading a self-added accessory as a deviation from the plan would be
    exactly backwards -- it is extra work the user chose to do."""
    from myvitals.integrations import claude

    payload_src = inspect.getsource(claude.build_strength_review_payload)
    assert '"added_ad_hoc"' in payload_src
    assert "added_ad_hoc: true" in claude._strength_review_system("supportive")


def test_explain_does_not_take_credit_for_user_choices():
    """A rules-based explanation that claims to have reasoned its way to an
    exercise the user picked is a small dishonesty that undermines the whole
    rationale."""
    src = inspect.getsource(strength.explain_workout)
    assert "added_ad_hoc" in src
    assert "planned exercises" in src
