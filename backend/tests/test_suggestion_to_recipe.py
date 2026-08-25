"""Saving an AI meal suggestion as a real recipe.

The recipe book could not fill itself. Suggestions were the only feature
generating meal ideas, and a planned suggestion goes into the plan as a
NOTE rather than a recipe — deliberately, because the model's
`est_fat_g` is an estimate and a recipe carrying invented nutrition is
worse than no recipe at all. The consequence, visible in production: 0
recipes, 0 recipe ingredients, 0 plan entries, against 37 pantry items.
Three screens were permanently empty because of it.

The way out is the prep planner's, not an exception to the rule. The
model proposes ingredients as SEARCH TERMS with amounts, the server
resolves them against the catalog, and nutrition is computed from the
resolved rows. What the model estimates never reaches the recipe.
"""
from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "myvitals"
MEALS = (SRC / "api" / "meals.py").read_text()
CLAUDE = (SRC / "integrations" / "claude.py").read_text()


def _fn_src(name: str) -> str:
    tree = ast.parse(MEALS)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            for sub in ast.walk(node):
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef,
                                    ast.ClassDef, ast.Module)):
                    if (sub.body and isinstance(sub.body[0], ast.Expr)
                            and isinstance(sub.body[0].value, ast.Constant)
                            and isinstance(sub.body[0].value.value, str)):
                        sub.body.pop(0)
            return ast.unparse(node)
    raise AssertionError(f"{name} not found")


def test_the_endpoint_exists() -> None:
    assert '@router.post("/recipes/from-suggestion"' in MEALS


def test_ingredients_are_resolved_through_the_catalog() -> None:
    """The same ranked search the pickers use. A recipe whose chicken is a
    different row from the food log's chicken is two foods, not one."""
    src = _fn_src("save_suggestion_as_recipe")
    assert "_resolve_food_term(db, term)" in src


def test_the_models_own_nutrition_estimates_never_reach_the_recipe() -> None:
    """`est_fat_g` and `est_kcal` are for the CARD, shown before anything
    is saved. Carrying them onto the recipe would leave the app showing
    two different fat numbers for one meal, and the catalog is the one
    that is right."""
    src = _fn_src("save_suggestion_as_recipe")
    for banned in ("est_fat_g", "est_kcal", "fat_g=", "kcal="):
        assert banned not in src, f"{banned} leaked into the saved recipe"


def test_an_unresolved_ingredient_is_kept_not_dropped() -> None:
    """A silently shorter ingredient list hides the gap AND makes the fat
    total look better than it is — wrong in the dangerous direction for
    the one constraint this app exists to respect."""
    src = _fn_src("save_suggestion_as_recipe")
    assert "term if food is None" in src, \
        "an unmatched ingredient must survive as a hand-typed line"
    assert "unresolved.append(term)" in src
    # And it must still be APPENDED — a `continue` here would drop it.
    assert src.count("lines.append(") == 1


def test_unresolved_ingredients_are_named_to_the_user() -> None:
    """The user is the only one who can say what "smoked paprika" should
    have matched, so the note has to say which lines failed."""
    src = _fn_src("save_suggestion_as_recipe")
    assert "did not match a catalog food" in src, \
        "the note does not say that any line failed to resolve"
    assert "join(unresolved)" in src, "the failed lines are not named"


def test_the_saved_recipe_admits_where_it_came_from() -> None:
    """A recipe the user wrote and one a model proposed deserve different
    confidence, and flattening them loses that."""
    src = _fn_src("save_suggestion_as_recipe")
    assert "ai-suggested" in src
    assert "Saved from an AI suggestion" in src


def test_the_tool_schema_asks_for_ingredients_but_not_their_nutrition() -> None:
    """Same split as PREP_PLAN_TOOL: the model names a food and an amount,
    the server computes every gram. An ingredient-level nutrition field
    would reintroduce exactly the estimate this endpoint exists to avoid.
    """
    start = CLAUDE.index("MEAL_SUGGEST_TOOL")
    block = CLAUDE[start:CLAUDE.index("def ", start)]
    ing = block[block.index('"ingredients"'):]
    ing = ing[:ing.index('"servings"')]
    assert '"food_search"' in ing and '"quantity"' in ing and '"unit"' in ing
    for banned in ("fat", "kcal", "calorie", "protein", "carb"):
        assert banned not in ing.lower(), \
            f"the ingredient schema asks the model for {banned}"


def test_the_prompt_warns_against_multi_food_ingredients() -> None:
    """MEAL-9 learned this the hard way: "roasted broccoli and bell
    pepper" resolved to broccoli and the peppers vanished from every
    total, and none of the unresolved machinery fires because a food DID
    match."""
    assert "broccoli" in CLAUDE and "peppers vanish" in CLAUDE


def test_a_word_where_a_number_was_asked_for_does_not_lose_the_recipe() -> None:
    """From a live run, verbatim:

        {"food_search": "Salt, table", "quantity": "pinch", "unit": "tsp"}

    "A pinch" is a perfectly sensible thing to write down, and a strict
    float field rejects it with a 422 that loses the WHOLE recipe over a
    pinch of salt — every other ingredient with it. The amount is carried
    through as text instead.
    """
    from myvitals.api.meals import SuggestedIngredientIn
    i = SuggestedIngredientIn(food_search="Salt, table", quantity="pinch", unit="tsp")
    assert i.numeric_quantity is None
    assert i.quantity_word == "pinch"


def test_numeric_quantities_still_parse_including_numeric_strings() -> None:
    from myvitals.api.meals import SuggestedIngredientIn
    for raw, want in ((2, 2.0), (0.5, 0.5), ("1.5", 1.5)):
        i = SuggestedIngredientIn(food_search="x", quantity=raw, unit="g")
        assert i.numeric_quantity == want
        assert i.quantity_word is None


def test_an_unmeasurable_amount_is_never_given_an_invented_number() -> None:
    """Inventing a gram figure for "a pinch" would put a fabricated weight
    into a fat total. The line is kept, uncosted, and named in the notes."""
    src = _fn_src("save_suggestion_as_recipe")
    assert "unmeasured.append" in src
    assert "not measurable and so are not costed" in src
    # The unit is dropped along with the number: "tsp" with no quantity
    # would let a later edit multiply by a phantom amount.
    assert "if ing.unit and qty is not None" in src
