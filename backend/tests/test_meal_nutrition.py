"""MEAL-2: per-meal fat awareness, and the refusal that protects it.

The single most important property in this file is that the app never
invents a fat threshold. Tolerance after a cholecystectomy varies widely
between people and commonly improves over months, so a made-up gram limit
could be wrong in either direction — and wrong-and-permissive is the
dangerous direction. A "we cannot judge this" answer is correct; a
confident-looking guess is not.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from myvitals.analytics import foods as F
from myvitals.analytics import nutrition as N

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "myvitals"


# ------------------------------------------------- the refusal contract


def test_refuses_without_a_target_or_enough_history():
    r = N.assess_meal_fat(31.0)
    assert r["verdict"] == "unknown"
    assert r["basis"] == "none"
    assert "does not guess" in r["reason"]


def test_refusal_says_how_much_history_is_missing():
    """A refusal that does not say what would fix it is just a dead end."""
    r = N.assess_meal_fat(31.0, history_fat_g=[10.0, 12.0])
    assert r["verdict"] == "unknown"
    assert r["comparison_meals"] == 2
    assert str(N.MIN_HISTORY) in r["reason"]


def test_no_default_fat_target_anywhere_in_the_code():
    """The absence of a default is the safety property. If a number ever
    appears as a fallback here, the app has started making a medical
    claim it has no basis for."""
    from myvitals.api import meals

    assert meals._DIET_DEFAULTS["fat_per_meal_target_g"] is None
    settings = {**meals._DIET_DEFAULTS}
    r = N.assess_meal_fat(
        99.0, target_g=settings["fat_per_meal_target_g"], history_fat_g=[],
    )
    assert r["verdict"] == "unknown"


def test_unknown_fat_is_not_treated_as_zero():
    """A recipe whose fat could not be costed must not read as fat-free,
    which would be the most dangerous possible failure here."""
    r = N.assess_meal_fat(None, target_g=20.0)
    assert r["verdict"] == "unknown"
    assert "could not be worked out" in r["reason"]


# ------------------------------------------------------ the three bases


def test_user_target_wins_and_is_named_as_the_basis():
    r = N.assess_meal_fat(25.0, target_g=20.0)
    assert r["basis"] == "target"
    assert r["verdict"] in {"high", "very_high"}
    assert "20 g per-meal target" in r["reason"]


def test_target_beats_history_when_both_are_present():
    """A clinician's number is authoritative; the user's own cooking
    habits must not override it."""
    r = N.assess_meal_fat(
        25.0, target_g=20.0, history_fat_g=[40.0] * 10,
    )
    assert r["basis"] == "target"
    assert r["verdict"] != "ok"


def test_history_basis_needs_no_medical_claim():
    r = N.assess_meal_fat(31.0, history_fat_g=[10, 12, 14, 9, 11, 13, 15])
    assert r["basis"] == "history"
    assert r["verdict"] == "very_high"
    assert r["comparison_meals"] == 7
    assert "median" in r["reason"]


def test_ordinary_meal_reads_ok_against_history():
    r = N.assess_meal_fat(11.0, history_fat_g=[10, 12, 14, 9, 11, 13])
    assert r["verdict"] == "ok"


def test_approaching_sits_between_ok_and_high():
    r = N.assess_meal_fat(17.0, target_g=20.0)
    assert r["verdict"] == "approaching"


def test_all_zero_history_refuses_rather_than_dividing_by_it():
    r = N.assess_meal_fat(10.0, history_fat_g=[0.0] * 8)
    assert r["verdict"] == "unknown"
    assert "nothing to compare" in r["reason"]


def test_zero_target_is_not_treated_as_a_target():
    """`0` and "unset" are different, and `if target_g:` would conflate
    them. A zero target falls through to the history path."""
    r = N.assess_meal_fat(10.0, target_g=0.0, history_fat_g=[])
    assert r["basis"] == "none"


# --------------------------------------------------------- energy split


def test_energy_split_uses_atwater_factors():
    s = N.energy_split({"protein_g": 30, "carbs_g": 40, "fat_g": 20, "kcal": 460})
    assert s["kcal_from_macros"] == 460.0
    assert s["percent"]["fat"] == pytest.approx(39.1, abs=0.1)
    assert not s["incomplete"]


def test_energy_split_reports_incomplete_rather_than_guessing():
    """A missing macro must not render as 0%, which would understate the
    share of the macros that ARE known."""
    s = N.energy_split({"protein_g": 30, "carbs_g": 40, "fat_g": None})
    assert s["percent"]["fat"] is None
    assert s["incomplete"] is True


def test_energy_split_of_nothing_does_not_divide_by_zero():
    s = N.energy_split({})
    assert s["kcal_from_macros"] is None
    assert set(s["percent"].values()) == {None}


def test_stated_and_derived_calories_are_both_reported():
    """A gap between them means the macros are incomplete. Showing only
    one hides that."""
    s = N.energy_split({"protein_g": 10, "carbs_g": 10, "fat_g": 10, "kcal": 500})
    assert s["kcal_stated"] == 500
    assert s["kcal_from_macros"] == 170.0


# ------------------------------------------------- fat-soluble vitamins


def test_fat_soluble_columns_exist_in_the_catalog():
    """These are carried for a medical reason: absorbing them depends on
    absorbing fat, which is the thing a cholecystectomy changes."""
    assert set(N.__dict__ and F.FAT_SOLUBLE_COLUMNS) == {
        "vitamin_a_ug", "vitamin_d_ug", "vitamin_e_mg", "vitamin_k_ug",
    }
    for col in F.FAT_SOLUBLE_COLUMNS:
        assert col in F.NUTRIENT_COLUMNS


def test_catalog_actually_carries_vitamin_data():
    rows = F.catalog()
    with_a = sum(1 for r in rows if r.get("vitamin_a_ug") is not None)
    assert with_a > len(rows) * 0.4, "vitamin A barely present; extractor regressed"


def test_fat_soluble_summary_distinguishes_absent_from_zero():
    s = N.fat_soluble_summary({"vitamin_a_ug": 12.0, "vitamin_d_ug": None})
    assert s["present"] == {"vitamin_a_ug": 12.0}
    assert "vitamin_d_ug" in s["missing"]
    assert s["no_data"] is False


def test_fat_soluble_no_data_is_its_own_state():
    """"We know nothing about this meal's vitamins" and "this meal has
    none" are different claims and must not render identically."""
    s = N.fat_soluble_summary({})
    assert s["no_data"] is True
    assert s["present"] == {}


def test_no_rda_thresholds_are_asserted():
    """Awareness only. The moment a percentage-of-RDA appears here, the
    app is making a nutritional claim it has no basis for."""
    src = (SRC / "analytics" / "nutrition.py").read_text()
    tree = ast.parse(src)
    # Strip docstrings via the AST rather than by eyeballing line
    # prefixes. A line-prefix filter leaves the BODY of a multi-line
    # docstring in place, so this assertion kept matching the very
    # comment that explains why no RDA is asserted — the same
    # self-matching failure that bit three tests earlier in this project.
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    code = ast.unparse(tree)
    for word in ("RDA", "recommended_daily", "daily_value", "dv_percent"):
        assert word not in code


# ------------------------------------------------------ model + schema


def test_migration_0057_adds_all_four_vitamins():
    mig = (pathlib.Path(__file__).resolve().parents[1]
           / "alembic" / "versions" / "0057_fat_soluble_vitamins.py").read_text()
    for col in ("vitamin_a_ug", "vitamin_d_ug", "vitamin_e_mg", "vitamin_k_ug"):
        assert col in mig
    assert 'down_revision: str | None = "0056"' in mig


def test_food_model_has_every_nutrient_column():
    """The bundled JSON, the seeder and the table must agree, or the seed
    silently writes nulls for the new columns."""
    from myvitals.db import models

    cols = set(models.Food.__table__.columns.keys())
    missing = [c for c in F.NUTRIENT_COLUMNS if c not in cols]
    assert missing == [], f"model is missing nutrient columns: {missing}"


def test_food_out_schema_exposes_every_nutrient():
    """`_food_out` splats NUTRIENT_COLUMNS into FoodOut. A column the
    schema does not declare makes that call raise at runtime."""
    from myvitals.api.meals import FoodOut

    fields = set(FoodOut.model_fields)
    missing = [c for c in F.NUTRIENT_COLUMNS if c not in fields]
    assert missing == [], f"FoodOut is missing: {missing}"


def test_seeder_chunk_still_fits_after_adding_columns():
    """Four more columns per row eats into the asyncpg bind-parameter
    headroom. This is the check that catches it before production does."""
    from myvitals.db.seed_foods import CHUNK, _COLUMNS

    assert CHUNK * (len(_COLUMNS) + 1) < 32_767


# ----------------------------------------------------- API wiring


def test_diet_profile_routes_are_mounted():
    from myvitals.main import app

    paths = set()
    for r in app.routes:
        inner = getattr(r, "original_router", None)
        if inner is not None:
            paths |= {getattr(x, "path", "") for x in inner.routes}
    assert "/meals/diet-profile" in paths
    assert "/meals/nutrition/assess" in paths


def test_diet_profile_is_a_scoped_merge_not_a_wholesale_write():
    """`PUT /profile` assigns `extra` wholesale. Writing diet settings the
    same way would erase the tile and display prefs sharing that column —
    the exact bug the scoped-endpoint rule in CLAUDE.md exists to stop."""
    src = (SRC / "api" / "meals.py").read_text()
    fn = src[src.index("async def put_diet_profile("):]
    fn = fn[: fn.index("@router.get")]
    assert "dict(p.extra or {})" in fn, "must copy-then-reassign the JSON column"
    assert "p.extra = extra" in fn
    assert "exclude_unset=True" in fn


def test_fat_history_does_not_hydrate_recipes():
    """`_fat_history` calling `_hydrate_recipe` would recurse — hydration
    asks for the history, the history hydrates — and would make listing N
    recipes cost N^2 hydrations."""
    src = (SRC / "api" / "meals.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_fat_history":
            called = {
                n.func.id for n in ast.walk(node)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            }
            assert "_hydrate_recipe" not in called
            return
    raise AssertionError("_fat_history not found")


def test_assessment_judges_a_serving_not_the_whole_batch():
    """A batch of six portions must not be flagged as an enormous fat
    load when each plate is ordinary. That is the whole per-meal point."""
    src = (SRC / "api" / "meals.py").read_text()
    fn = src[src.index("async def _hydrate_recipe("):]
    fn = fn[: fn.index("async def _replace_ingredients")]
    assert 'per_srv.get("fat_g")' in fn
    assert 'totals.get("fat_g")' not in fn


# --------------------------------------------- the seeder staleness guard


def test_seed_guard_is_not_row_count_only():
    """A row-count-only guard is what let v0.16.0 deploy with every new
    vitamin column NULL in production.

    Adding four columns did not change the number of rows, so the seeder
    decided it was already up to date, skipped, and the tables looked
    perfectly healthy while the data was missing. The guard has to notice
    that a column the bundled catalog supplies is empty in the database.
    """
    src = (SRC / "db" / "seed_foods.py").read_text()
    tree = ast.parse(src)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_needs_reseed"
    )
    body = ast.unparse(fn)
    assert "NUTRIENT_COLUMNS" in body, "guard must inspect the nutrient columns"
    assert "func.count(" in body


def test_seed_guard_only_blames_columns_the_catalog_supplies():
    """A column the bundled file has no data for cannot be evidence that
    the database is stale — otherwise the seeder would re-run forever."""
    src = (SRC / "db" / "seed_foods.py").read_text()
    fn = src[src.index("async def _needs_reseed("):]
    fn = fn[: fn.index("async def seed_foods(")]
    assert "supplied" in fn
    assert "if not supplied" in fn


def test_seeder_writes_the_vitamin_columns():
    """The seeder splats NUTRIENT_COLUMNS, so the new columns are only
    written if they are in that tuple AND in the seeder's column list."""
    from myvitals.db.seed_foods import _COLUMNS

    for col in F.FAT_SOLUBLE_COLUMNS:
        assert col in _COLUMNS, f"seeder does not write {col}"
