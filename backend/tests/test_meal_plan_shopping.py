"""MEAL-3: the weekly plan and the shopping list it generates.

The property this file protects is that **an item is never silently
dropped or silently reduced**. A shopping list that quietly omits
something sends the user home without it and they find out while
cooking, so every case where the arithmetic cannot be done confidently
has to produce a flagged line rather than a missing one.

Each of the wrong alternatives — assuming a clove weighs 3 g, assuming an
unmeasured jar covers the need — is one line of code and produces a list
that looks tidier and is wrong.
"""
from __future__ import annotations

import ast
import pathlib
from datetime import date

import pytest

from myvitals.analytics import foods as F
from myvitals.analytics import shopping as S

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "myvitals"


def _oil() -> dict:
    return next(r for r in F.catalog() if r["name"] == "Oil, olive, salad or cooking")


# --------------------------------------------------------- aggregation


def test_same_food_across_meals_is_summed_in_grams():
    needs = S.aggregate_needs([
        {"food_id": 1, "label": "Oil", "quantity": 2, "unit": "tbsp",
         "grams": 27.0, "multiplier": 2},
        {"food_id": 1, "label": "Oil", "quantity": 1, "unit": "tbsp",
         "grams": 13.5, "multiplier": 1},
    ])
    assert len(needs) == 1
    assert needs["food:1"].grams == pytest.approx(67.5)


def test_servings_multiplier_scales_the_shopping_need():
    """Planning four servings of a recipe written for two means buying
    twice the ingredients. Ignoring the multiplier would under-buy."""
    one = S.aggregate_needs([
        {"food_id": 1, "label": "Oil", "quantity": 1, "unit": "tbsp",
         "grams": 13.5, "multiplier": 1},
    ])["food:1"].grams
    two = S.aggregate_needs([
        {"food_id": 1, "label": "Oil", "quantity": 1, "unit": "tbsp",
         "grams": 13.5, "multiplier": 2},
    ])["food:1"].grams
    assert two == pytest.approx(one * 2)


def test_unconvertible_lines_keep_their_own_units():
    """"2 clove" and "1 cup" cannot be added. Reducing a clove to grams
    would invent a number; there is no general weight for one of
    something."""
    needs = S.aggregate_needs([
        {"food_id": 2, "label": "Garlic", "quantity": 2, "unit": "clove",
         "grams": None, "multiplier": 3},
    ])
    n = needs["food:2"]
    assert n.grams == 0.0
    assert n.loose_text() == "6 clove"


def test_gram_and_loose_lines_are_reported_side_by_side():
    """A food with both convertible and unconvertible lines must show
    both, not silently discard the half it cannot add up."""
    needs = S.aggregate_needs([
        {"food_id": 3, "label": "Thing", "quantity": 100, "unit": "g",
         "grams": 100.0, "multiplier": 1},
        {"food_id": 3, "label": "Thing", "quantity": 1, "unit": "clove",
         "grams": None, "multiplier": 1},
    ])
    row = S.subtract_pantry(needs["food:3"], [], None)
    assert row["grams"] == 100.0
    assert row["amount_text"] == "1 clove"
    assert row["fully_covered"] is False


def test_hand_typed_lines_merge_by_label_not_by_id():
    needs = S.aggregate_needs([
        {"food_id": None, "label": "Olive oil", "quantity": 1, "unit": "tbsp",
         "grams": None, "multiplier": 1},
        {"food_id": None, "label": "olive OIL", "quantity": 2, "unit": "tbsp",
         "grams": None, "multiplier": 1},
    ])
    assert len(needs) == 1


def test_different_foods_never_merge():
    needs = S.aggregate_needs([
        {"food_id": 1, "label": "Oil", "quantity": 1, "unit": "tbsp",
         "grams": 13.5, "multiplier": 1},
        {"food_id": 2, "label": "Butter", "quantity": 1, "unit": "tbsp",
         "grams": 14.2, "multiplier": 1},
    ])
    assert len(needs) == 2


# ---------------------------------------------------- pantry subtraction


def test_measured_pantry_is_subtracted():
    needs = S.aggregate_needs([
        {"food_id": 1, "label": "Oil", "quantity": 4, "unit": "tbsp",
         "grams": 54.0, "multiplier": 1},
    ])
    row = S.subtract_pantry(needs["food:1"], [{"quantity": 1, "unit": "tbsp"}], _oil())
    assert row["grams"] == pytest.approx(40.5)
    assert row["pantry_covered_g"] == pytest.approx(13.5)
    assert row["pantry_uncertain"] is False


def test_unmeasured_pantry_does_not_reduce_the_need():
    """"We have olive oil" is true, useful, and not a number. Treating it
    as enough is how a list ends up missing the one thing that was short."""
    needs = S.aggregate_needs([
        {"food_id": 1, "label": "Oil", "quantity": 4, "unit": "tbsp",
         "grams": 54.0, "multiplier": 1},
    ])
    row = S.subtract_pantry(needs["food:1"], [{"quantity": None, "unit": None}], _oil())
    assert row["grams"] == pytest.approx(54.0), "need was reduced without evidence"
    assert row["pantry_uncertain"] is True
    assert row["fully_covered"] is False


def test_unconvertible_pantry_unit_is_flagged_not_guessed():
    needs = S.aggregate_needs([
        {"food_id": 1, "label": "Oil", "quantity": 4, "unit": "tbsp",
         "grams": 54.0, "multiplier": 1},
    ])
    row = S.subtract_pantry(needs["food:1"], [{"quantity": 1, "unit": "splash"}], _oil())
    assert row["grams"] == pytest.approx(54.0)
    assert row["pantry_uncertain"] is True


def test_only_a_complete_subtraction_may_drop_an_item():
    """`fully_covered` is the one path that removes a line from the list,
    so it must require complete arithmetic on every axis."""
    needs = S.aggregate_needs([
        {"food_id": 1, "label": "Oil", "quantity": 1, "unit": "tbsp",
         "grams": 13.5, "multiplier": 1},
    ])
    covered = S.subtract_pantry(needs["food:1"], [{"quantity": 1, "unit": "cup"}], _oil())
    assert covered["fully_covered"] is True
    assert covered["grams"] == 0.0


def test_covered_plus_uncertain_is_never_fully_covered():
    """Two pantry rows, one measured and enough, one unmeasured. The
    uncertainty must veto the drop — the measured row might be the one
    that is empty."""
    needs = S.aggregate_needs([
        {"food_id": 1, "label": "Oil", "quantity": 1, "unit": "tbsp",
         "grams": 13.5, "multiplier": 1},
    ])
    row = S.subtract_pantry(
        needs["food:1"],
        [{"quantity": 1, "unit": "cup"}, {"quantity": None, "unit": None}],
        _oil(),
    )
    assert row["fully_covered"] is False


def test_loose_lines_veto_the_drop():
    needs = S.aggregate_needs([
        {"food_id": 1, "label": "Oil", "quantity": 1, "unit": "tbsp",
         "grams": 13.5, "multiplier": 1},
        {"food_id": 1, "label": "Oil", "quantity": 1, "unit": "splash",
         "grams": None, "multiplier": 1},
    ])
    row = S.subtract_pantry(needs["food:1"], [{"quantity": 1, "unit": "cup"}], _oil())
    assert row["fully_covered"] is False
    assert row["amount_text"] == "1 splash"


def test_pantry_never_produces_a_negative_amount():
    needs = S.aggregate_needs([
        {"food_id": 1, "label": "Oil", "quantity": 1, "unit": "tbsp",
         "grams": 13.5, "multiplier": 1},
    ])
    row = S.subtract_pantry(needs["food:1"], [{"quantity": 5, "unit": "cup"}], _oil())
    assert row["grams"] == 0.0


# ------------------------------------------------------------ rendering


def test_humanise_uses_the_foods_own_measures():
    oil = _oil()
    assert S.humanise(432, oil) == "2 cup"
    assert S.humanise(27, oil) == "2 tbsp"


def test_humanise_falls_back_to_mass_not_to_a_wrong_unit():
    assert S.humanise(1500, None) == "1.5 kg"
    assert S.humanise(250, None) == "250 g"


def test_humanise_trims_pointless_decimals():
    assert "2.0" not in S.humanise(432, _oil())


# ------------------------------------------------- Walmart deep links


def test_walmart_url_is_a_search_not_an_add_to_cart():
    """Tier 1 of MEALS_PLAN. The add-to-cart endpoints are deprecated and
    gated to Impact Radius publishers, or need a partner approval that a
    single-user self-hosted install cannot get."""
    url = S.walmart_search_url("Oil, olive, salad or cooking")
    assert url.startswith("https://www.walmart.com/search?q=")
    assert "addToCart" not in url


def test_walmart_url_trims_usda_naming():
    """"Oil, olive, salad or cooking" finds nothing on a retail site."""
    assert S.walmart_search_url("Oil, olive, salad or cooking").endswith("Oil+olive")


def test_walmart_url_escapes_user_text():
    url = S.walmart_search_url("Salt & pepper / mix")
    assert " " not in url
    assert "&q" not in url.split("?q=")[1]


def test_server_never_fetches_walmart():
    """A cart belongs to a logged-in browser session, so only the user's
    own browser can act on it. A server-side fetch would also hit the
    Akamai bot wall this network sits behind."""
    src = (SRC / "analytics" / "shopping.py").read_text()
    for bad in ("httpx", "requests", "aiohttp", "urlopen"):
        assert bad not in src


# ------------------------------------------------------- API + schema


def test_plan_week_starts_on_the_local_day():
    """Deriving the week from a UTC date rolls it over at 7pm on a Sunday
    and shows the wrong seven days all evening."""
    src = (SRC / "api" / "meals.py").read_text()
    fn = src[src.index("async def get_plan("):]
    fn = fn[: fn.index("@router.post")]
    assert "_local_today()" in fn
    assert "datetime.now(timezone.utc).date()" not in fn


def test_day_totals_are_null_not_zero_when_nothing_is_costable():
    src = (SRC / "api" / "meals.py").read_text()
    fn = src[src.index("async def get_plan("):]
    fn = fn[: fn.index("@router.post")]
    assert "if kcals else None" in fn
    assert "if fats else None" in fn


def test_day_totals_multiply_by_planned_servings():
    """Three containers of something is three meals' worth of energy."""
    src = (SRC / "api" / "meals.py").read_text()
    fn = src[src.index("async def get_plan("):]
    fn = fn[: fn.index("@router.post")]
    assert "e.kcal_per_serving * e.servings" in fn


def test_migration_0058_creates_all_three_tables():
    mig = (pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"
           / "0058_meal_plan_shopping.py").read_text()
    for t in ("meal_plan_entries", "shopping_lists", "shopping_list_items"):
        assert f'"{t}"' in mig
    assert 'down_revision: str | None = "0057"' in mig


def test_plan_recipe_fk_sets_null_rather_than_cascading():
    """Deleting a recipe must not silently empty days out of the plan."""
    mig = (pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"
           / "0058_meal_plan_shopping.py").read_text()
    block = mig[mig.index('"meal_plan_entries"'):mig.index('"shopping_lists"')]
    assert 'ondelete="SET NULL"' in block
    assert 'ondelete="CASCADE"' not in block


def test_shopping_item_label_is_snapshotted():
    """A renamed or deleted food must not leave a blank line on a list
    someone is halfway through shopping."""
    from myvitals.db import models

    col = models.ShoppingListItem.__table__.columns["label"]
    assert not col.nullable


def test_all_meal3_routes_are_mounted():
    from myvitals.main import app

    paths = set()
    for r in app.routes:
        inner = getattr(r, "original_router", None)
        if inner is not None:
            paths |= {getattr(x, "path", "") for x in inner.routes}
    for wanted in (
        "/meals/plan", "/meals/plan/{entry_id}", "/meals/shopping-list",
        "/meals/shopping-lists", "/meals/shopping-list/{list_id}",
        "/meals/shopping-list/{list_id}/items/{item_id}",
    ):
        assert wanted in paths, f"{wanted} is not mounted"


def test_shopping_list_is_persisted_not_recomputed():
    """The user ticks items off while standing in a shop. Recomputing the
    list on view would silently undo that."""
    from myvitals.db import models

    assert "checked" in models.ShoppingListItem.__table__.columns


def test_meal3_model_defaults_all_run():
    """Same guard as the models suite: a callable default is a callable
    nobody calls until production does."""
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
