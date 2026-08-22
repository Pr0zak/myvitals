"""MEAL-5: the food log.

Intermittent logging is the design assumption here, not a failure mode.
That single decision drives everything this file checks:

* A half-logged day is worse than an unlogged one — it reads as "you
  barely ate" rather than "you barely logged", and any average built on
  it is wrong in the direction that looks like success. So completeness
  is DECLARED by the user, never inferred, and partial days are excluded
  from every derived number.
* Gaps are shown as gaps. No interpolation, no zero-filling.
* Nothing nags. No streak, no completion percentage, no notification for
  an unlogged meal — a tracker that turns red when you stop is a tracker
  you stop opening.
"""
from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "myvitals"
MEALS = (SRC / "api" / "meals.py").read_text()


def _code_only(src: str) -> str:
    """Source with comments and docstrings removed, via the AST."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)


def _fn(name: str, end: str = "@router") -> str:
    """Source of one endpoint, comments and docstrings stripped.

    Stripped via the AST rather than by line prefix: a prefix filter
    leaves the BODY of a multi-line docstring behind, which has already
    caused four self-matching false failures in this project.
    """
    start = MEALS.index(f"async def {name}(")
    body = MEALS[start:]
    cut = body.find(end, 10)
    src = body[:cut] if cut > 0 else body
    tree = ast.parse(src.strip())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)


# ------------------------------------------- completeness is declared


def test_complete_defaults_to_false():
    """The app cannot tell "I stopped logging" from "I stopped eating".
    Defaulting to complete would silently corrupt every average."""
    from myvitals.db import models

    col = models.FoodLogDay.__table__.columns["complete"]
    assert col.default.arg is False
    assert str(col.server_default.arg).lower() == "false"


def test_completeness_is_never_inferred_from_entry_count():
    """A day with three entries is not evidence of a complete day. If
    this ever starts guessing, the refusal below becomes meaningless."""
    src = _fn("mark_log_day")
    assert "entry_count" not in src
    assert "len(rows)" not in src


def test_stats_counts_only_complete_days():
    src = _fn("log_stats")
    assert "d.complete" in src
    assert "if d.complete" in src


def test_stats_refuses_below_the_threshold():
    from myvitals.api.meals import MIN_COMPLETE_DAYS

    src = _fn("log_stats")
    assert "MIN_COMPLETE_DAYS" in src
    assert "out.reason" in src
    assert MIN_COMPLETE_DAYS >= 5


def test_refusal_leaves_the_averages_null():
    """A number the caller has to know is untrustworthy is worse than no
    number. The refusal returns before either average is assigned."""
    src = _fn("log_stats")
    reason_at = src.index("out.reason")
    assert src.index("out.avg_kcal") > reason_at
    assert src.index("out.avg_fat_g") > reason_at


def test_partial_days_are_counted_and_reported():
    """The exclusion has to be visible, or it looks like data loss."""
    src = _fn("log_stats")
    assert "partial_days" in src
    from myvitals.api.meals import LogStatsOut

    assert "partial_days" in LogStatsOut.model_fields
    assert "days_needed" in LogStatsOut.model_fields


def test_per_meal_fat_is_reported_even_when_days_are_too_few():
    """A single meal is the unit of interest for this condition, so one
    complete meal is meaningful in a way one complete day is not. The
    median must be computed before the refusal returns."""
    src = _fn("log_stats")
    assert src.index("median_meal_fat_g") < src.index("out.reason")


# ------------------------------------------------ gaps stay gaps


def test_unlogged_days_are_returned_not_omitted():
    """A gap is shown as a gap. Omitting empty days would let a client
    draw a line straight through them."""
    src = _fn("_log_days", end="@router.get")
    assert "while cursor <= end" in src
    assert "cursor += timedelta(days=1)" in src


def test_empty_day_totals_are_null_not_zero():
    """`_sum_nutrition` nulls a nutrient no line supplied, so an empty
    day has null totals rather than a confident zero."""
    from myvitals.api.meals import _sum_nutrition

    assert set(_sum_nutrition([]).values()) == {None}


def test_no_interpolation_or_zero_filling():
    src = _fn("_log_days", end="@router.get")
    for bad in ("interpolat", "ffill", "or 0.0", "or 0)"):
        assert bad not in src


# ------------------------------------------------------ nothing nags


def test_no_streak_or_completion_percentage_anywhere():
    """A tracker that turns red the moment you stop is a tracker you stop
    opening. Intermittent use has to stay a first-class state."""
    # Comments and docstrings must be stripped before matching. The
    # section's own header comment says "there is deliberately no
    # streak", and a raw substring search matches that and fails — the
    # fifth self-matching assertion in this project.
    from myvitals.api import meals as meals_mod

    code = _code_only(pathlib.Path(meals_mod.__file__).read_text())
    lowered = code.lower()
    for nag in ("streak", "completion_pct", "adherence", "missed_day"):
        assert nag not in lowered, f"{nag!r} reintroduces nagging"


def test_log_section_sends_no_notifications():
    for bad in ("Notifier", "push_notification", "send_notification"):
        assert bad not in MEALS


# ----------------------------------------------- costing and honesty


def test_entry_source_is_reported():
    """A figure looked up from the catalog and one typed off a menu are
    both useful and must not be presented identically."""
    from myvitals.api.meals import LogEntryOut

    assert "source" in LogEntryOut.model_fields


def test_manual_nutrition_is_stored_separately_from_computed():
    from myvitals.db import models

    cols = set(models.FoodLogEntry.__table__.columns.keys())
    assert {"manual_kcal", "manual_fat_g"} <= cols


def test_uncostable_entry_is_reported_not_zeroed():
    from myvitals.api.meals import _entry_nutrition
    from myvitals.db import models

    e = models.FoodLogEntry(day=None, slot="dinner", label="something")
    nut, source, reason = _entry_nutrition(e, None, None)
    assert reason is not None
    assert source == "none"
    assert set(nut.values()) == {None}


def test_manual_entry_costs_from_the_typed_figures():
    from myvitals.api.meals import _entry_nutrition
    from myvitals.db import models

    e = models.FoodLogEntry(
        day=None, slot="lunch", label="burrito", manual_kcal=700, manual_fat_g=28,
    )
    nut, source, reason = _entry_nutrition(e, None, None)
    assert source == "manual"
    assert reason is None
    assert nut["fat_g"] == 28
    # Nutrients the user did not type stay unknown, not zero.
    assert nut["protein_g"] is None


def test_recipe_entry_scales_by_servings():
    from myvitals.api.meals import _entry_nutrition
    from myvitals.db import models

    e = models.FoodLogEntry(day=None, slot="dinner", recipe_id=1, servings=2)
    nut, source, _ = _entry_nutrition(e, None, {"kcal": 300.0, "fat_g": None})
    assert source == "recipe"
    assert nut["kcal"] == 600.0
    assert nut["fat_g"] is None


def test_fat_is_assessed_per_MEAL_not_per_day():
    """The whole point of the condition this tracks: what matters is how
    much fat lands in one sitting."""
    src = _fn("_log_days", end="@router.get")
    assert "assess_meal_fat" in src
    # `ast.unparse` normalises string quotes, so match on the call shape
    # rather than on the exact quoting of the source.
    assert "slot_totals.get(" in src
    assert "fat_g" in src


# --------------------------------------------------------- structure


def test_log_uses_the_local_day():
    for name in ("get_log", "log_stats"):
        src = _fn(name)
        assert "_local_today()" in src
        assert "datetime.now(timezone.utc).date()" not in src


def test_migration_0059_creates_both_tables():
    mig = (pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"
           / "0059_food_log.py").read_text()
    assert '"food_log_entries"' in mig
    assert '"food_log_days"' in mig
    assert 'down_revision: str | None = "0058"' in mig


def test_log_foreign_keys_set_null():
    """Deleting a recipe must not erase the history of having eaten it."""
    mig = (pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"
           / "0059_food_log.py").read_text()
    assert mig.count('ondelete="SET NULL"') == 2
    assert "CASCADE" not in mig


def test_log_routes_are_mounted():
    from myvitals.main import app

    paths = set()
    for r in app.routes:
        inner = getattr(r, "original_router", None)
        if inner is not None:
            paths |= {getattr(x, "path", "") for x in inner.routes}
    for wanted in ("/meals/log", "/meals/log/{entry_id}",
                   "/meals/log/day/{day}", "/meals/log/stats"):
        assert wanted in paths, f"{wanted} is not mounted"


def test_model_defaults_still_all_run():
    from myvitals.db.models import Base

    failures = []
    for table in Base.metadata.tables.values():
        for col in table.columns:
            d = col.default
            if d is None or not getattr(d, "is_callable", False):
                continue
            try:
                d.arg(None)
            except Exception as e:  # noqa: BLE001
                failures.append(f"{table.name}.{col.name}: {e}")
    assert failures == []
