"""MEAL-6: "what can I cook right now", staples, and the honesty rules.

The measure is the ingredient coverage ratio — matched over required —
which is what every app in this category ranks on. Two decisions make it
useful rather than infuriating, and both are tested here:

* Staples are assumed present, or a strict test answers "no" to almost
  every savoury recipe.
* Matching happens on CONCEPT, never on food id. Raw and grilled chicken
  breast are different USDA rows and one thing to have in the house.

The third rule is the one that took a bug to find: a recipe containing a
line the app could not identify must NOT be reported as cookable.
"""
from __future__ import annotations

import pytest

from myvitals.analytics import staples as S
from myvitals.analytics.canmake import (
    match_recipes,
    summarise,
    unlock_ranking,
)


def _r(rid: int, name: str, *concepts: str | None) -> dict:
    return {
        "id": rid, "name": name, "servings": 1,
        "lines": [
            {"concept": c, "label": c or "a splash of something"}
            for c in concepts
        ],
    }


# ---------------------------------------------------------- coverage


def test_full_coverage_is_cookable():
    m = match_recipes([_r(1, "A", "chicken breast", "rice")],
                      {"chicken breast", "rice"}, set())[0]
    assert m.cookable
    assert m.coverage == 1.0
    assert m.missing == []


def test_partial_coverage_lists_what_is_missing():
    m = match_recipes([_r(1, "A", "chicken breast", "rice")],
                      {"chicken breast"}, set())[0]
    assert not m.cookable
    assert m.coverage == pytest.approx(0.5)
    assert m.missing == ["rice"]


def test_staples_count_as_had_and_are_reported_as_such():
    """Assumed, not owned. The distinction has to survive to the UI, or
    the user cannot tell why a recipe claims to be cookable."""
    m = match_recipes([_r(1, "A", "chicken breast", "salt")],
                      {"chicken breast"}, {"salt"})[0]
    assert m.cookable
    assert m.from_staples == ["salt"]


def test_without_staples_almost_nothing_is_cookable():
    """The reason the staples assumption exists at all."""
    recipes = [_r(i, f"R{i}", "chicken breast", "salt") for i in range(5)]
    strict = match_recipes(recipes, {"chicken breast"}, set())
    lenient = match_recipes(recipes, {"chicken breast"}, {"salt"})
    assert sum(m.cookable for m in strict) == 0
    assert sum(m.cookable for m in lenient) == 5


def test_a_repeated_concept_is_one_shopping_decision():
    """Oil in the marinade and oil in the pan is one bottle."""
    m = match_recipes([_r(1, "A", "olive oil", "olive oil", "rice")],
                      {"olive oil", "rice"}, set())[0]
    assert m.required == ["olive oil", "rice"]
    assert m.coverage == 1.0


def test_empty_recipe_is_not_cookable():
    """A recipe with no ingredients is a data problem, not a meal."""
    m = match_recipes([_r(1, "Empty")], set(), set())[0]
    assert not m.cookable
    assert m.coverage == 0.0


# ------------------------------------------- the uncertainty rule


def test_unreadable_line_vetoes_cookable():
    """Found by smoke-testing this module: a recipe whose ingredient the
    app could not identify was reported cookable AND sorted to the top —
    the least certain recipe in the most acted-on position."""
    m = match_recipes([_r(1, "Mystery", None, "chicken breast")],
                      {"chicken breast"}, set())[0]
    assert not m.cookable
    assert m.uncertain
    assert m.unknown == ["a splash of something"]


def test_uncertain_recipes_never_outrank_verified_ones():
    ms = match_recipes(
        [_r(1, "Mystery", None, "chicken breast"),
         _r(2, "Verified", "chicken breast")],
        {"chicken breast"}, set(),
    )
    assert ms[0].name == "Verified"


def test_unknown_lines_are_excluded_from_the_ratio_not_counted_missing():
    """Otherwise a recipe with one unresolvable line is permanently stuck
    below 100% and the user cannot tell why."""
    m = match_recipes([_r(1, "A", None, "rice")], {"rice"}, set())[0]
    assert m.coverage == 1.0
    assert m.missing == []


def test_summary_separates_certain_from_probable():
    ms = match_recipes(
        [_r(1, "Sure", "rice"), _r(2, "Maybe", None, "rice")],
        {"rice"}, set(),
    )
    s = summarise(ms)
    assert s["cookable_now"] == 1
    assert s["probably_cookable"] == 1
    assert s["recipes_with_unknown_lines"] == 1


# ------------------------------------------------- missing-by-one


def test_unlock_ranking_counts_recipes_freed_by_one_purchase():
    """The payoff of the module: knowing you can cook three things is
    mildly useful; knowing one packet of rice makes it seven changes a
    shopping trip."""
    ms = match_recipes(
        [_r(1, "A", "chicken breast", "rice"),
         _r(2, "B", "chicken breast", "rice"),
         _r(3, "C", "chicken breast", "lettuce")],
        {"chicken breast"}, set(),
    )
    top = unlock_ranking(ms)
    assert top[0]["item"] == "rice"
    assert top[0]["unlocks"] == 2


def test_unlock_ignores_recipes_missing_more_than_one():
    """An item that is one of three things still needed unlocks nothing
    on its own, and counting it would overstate the payoff."""
    ms = match_recipes([_r(1, "A", "a", "b", "c")], set(), set())
    assert unlock_ranking(ms) == []


def test_unlock_ignores_recipes_with_unreadable_lines():
    """Buying the one missing item might still not be enough, so it
    cannot be advertised as an unlock."""
    ms = match_recipes([_r(1, "A", None, "rice")], set(), set())
    assert unlock_ranking(ms) == []


# --------------------------------------------------------- staples


def test_butter_is_not_a_staple():
    """Half a stick is 46 g of fat. Assuming it would silently remove
    that from a per-meal total, which is the one number this app's
    medical constraint cares about."""
    assert "butter" not in S.DEFAULT_STAPLES


def test_no_high_fat_item_is_assumed():
    for risky in ("butter", "cream", "cheese", "bacon", "mayonnaise", "coconut oil"):
        assert risky not in S.DEFAULT_STAPLES


def test_user_can_remove_a_default_staple():
    """A wrongly assumed staple is invisible — the item silently never
    reaches a shopping list and you find out in the kitchen."""
    out = S.effective_staples(removed=["olive oil"])
    assert "olive oil" not in out
    assert "salt" in out


def test_removal_beats_addition():
    out = S.effective_staples(added=["olive oil"], removed=["olive oil"])
    assert "olive oil" not in out


def test_staples_are_normalised():
    out = S.effective_staples(added=["  Soy Sauce  "])
    assert "soy sauce" in out


def test_staple_list_stays_short():
    """Every entry silently suppresses a shopping-list line. A long list
    is a long list of things you may arrive home without."""
    assert len(S.DEFAULT_STAPLES) <= 20


# ------------------------------------------------ schema + migration


def test_food_model_has_the_concept_column():
    from myvitals.db import models

    assert "concept" in models.Food.__table__.columns
    assert models.Food.__table__.columns["concept"].nullable


def test_migration_0060_indexes_concept():
    """Pantry matching looks foods up by concept on every shopping-list
    generation and every can-make query."""
    import pathlib

    mig = (pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"
           / "0060_ingredient_concepts.py").read_text()
    assert "ix_foods_concept" in mig
    assert 'down_revision: str | None = "0059"' in mig
