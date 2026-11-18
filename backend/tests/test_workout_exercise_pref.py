"""The workout shows each exercise's standing preference.

Before this, the workout screens let you SET favourite / avoid / disable from
an exercise's menu but never showed which one was in force; only the catalog
did. `WorkoutExerciseOut.pref` carries it, read from user_equipment at
serialization time.
"""
from __future__ import annotations

import pathlib

from myvitals.api.workout import strength as api
from myvitals.db import models

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _wex(exercise_id: str) -> models.StrengthWorkoutExercise:
    return models.StrengthWorkoutExercise(
        id=1, workout_id=1, exercise_id=exercise_id, order_index=0,
        superset_id=None, target_sets=3, target_reps_low=8, target_reps_high=12,
        target_weight_lb=None, target_rest_s=90, notes=None, skipped=False,
    )


EX = next(iter(api._CATALOG_BY_ID))


def test_favourite_comes_from_the_equipment_prefs():
    out = api._wex_to_out(_wex(EX), [], equipment={"exercise_prefs": {EX: "favorite"}})
    assert out.pref == "favorite"


def test_explicit_prefs_win_and_neutral_is_null():
    assert api._wex_to_out(_wex(EX), [], prefs={EX: "avoid"}).pref == "avoid"
    assert api._wex_to_out(_wex(EX), [], prefs={}).pref is None
    assert api._wex_to_out(_wex(EX), []).pref is None


def test_an_unknown_value_is_not_passed_through():
    assert api._wex_to_out(_wex(EX), [], prefs={EX: "neutral"}).pref is None
    assert api._wex_to_out(_wex(EX), [], prefs={EX: "bogus"}).pref is None


def test_the_swap_response_carries_it_too():
    import inspect
    src = inspect.getsource(api.swap_exercise)
    assert 'prefs=equip.get("exercise_prefs")' in src


def test_both_clients_render_it():
    web = (ROOT / "frontend/src/views/workout/StrengthToday.vue").read_text()
    assert ':pref="c.wex.pref"' in web and ':pref="heroWex.pref"' in web
    kt = ROOT / "android/app/src/main/kotlin/app/myvitals"
    assert "val pref: String? = null" in (kt / "sync/Models.kt").read_text()
    assert "PrefMark(wex.pref" in (kt / "ui/strength/NowHero.kt").read_text()
    assert "ExercisePrefMenu(wex.pref" in (kt / "ui/strength/StrengthTodayScreen.kt").read_text()
