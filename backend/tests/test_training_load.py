"""Weekly training load: the band must be derived, and strength must count.

Two things this guards:

1. Strength sessions contribute load. `daily_training_stress` only ever
   queried the `activities` table, so a week of lifting produced a training
   load of exactly zero and CTL/ATL decayed as though training had stopped —
   while TYPE_INTENSITY had carried a "strength" entry the whole time.
2. The target band is the acute:chronic sweet spot expressed in load units,
   not a number someone picked.
"""
import ast
import inspect
import pathlib

from myvitals.analytics import advanced

SRC = pathlib.Path(advanced.__file__).read_text()


def test_strength_sessions_feed_daily_load():
    """daily_training_stress must consult the strength table, not just activities."""
    fn = inspect.getsource(advanced.daily_training_stress)
    assert "_strength_training_stress" in fn, (
        "daily_training_stress ignores strength workouts, so a lifting-only "
        "week reports zero training load"
    )
    helper = inspect.getsource(advanced._strength_training_stress)
    assert "StrengthWorkout" in helper
    # Only completed sessions, and net of paused time.
    assert '"completed"' in helper, "counts planned/skipped sessions as load"
    assert "total_paused_s" in helper, (
        "counts paused time as training, so a session left open reads as hours"
    )


def test_yoga_is_not_scored_as_strength():
    helper = inspect.getsource(advanced._strength_training_stress)
    assert "yoga" in helper, (
        "yoga days are generated into the same table but are not the same "
        "stimulus; scoring them at strength intensity inflates load"
    )


def test_band_is_the_acute_chronic_ratio():
    """0.8-1.3 x (CTL x 7) — the standard ACWR sweet spot in load units."""
    api = (pathlib.Path(advanced.__file__).parents[1]
           / "api" / "summary.py").read_text()
    tree = ast.parse(api)
    fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
         and n.name == "training_load"),
        None,
    )
    assert fn is not None, "training_load endpoint missing"
    src = ast.get_source_segment(api, fn) or ""
    assert "0.8" in src and "1.3" in src, "band is not the ACWR sweet spot"
    # No chronic load → no target, rather than a fabricated one.
    assert "target_low = target_high = acwr = None" in src, (
        "endpoint should return null bounds when there is no chronic load to "
        "compare against, not guess a target for a first week of training"
    )


def test_week_is_computed_from_source_not_the_summary_column():
    """daily_summary.training_stress_score is only rewritten when a summary is
    recomputed, and staleness watches sleep/HRV — so a change to how load is
    derived never reaches historical days."""
    api = (pathlib.Path(advanced.__file__).parents[1]
           / "api" / "summary.py").read_text()
    tree = ast.parse(api)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "training_load"
    )
    src = ast.get_source_segment(api, fn) or ""
    assert "training_load_by_day" in src, (
        "weekly load reads the stored summary column, so it will report zero "
        "for weeks that predate any change to how load is derived"
    )
