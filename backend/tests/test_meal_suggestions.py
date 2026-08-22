"""MEAL-4: AI meal suggestions.

Two properties matter more than the prose the model produces.

**The fat check is enforced in code, not only in the prompt.** A prompt
rule is a request, not a guarantee, and the one number this user's
cholecystectomy makes matter is exactly the one a model is most likely to
be breezy about. Every suggestion is re-judged after the tool call by the
same deterministic function the recipe pages use.

**The payload stays bounded.** The cache key is per-byte, so a payload
that grows with the pantry is how the bill climbs — and how a cache stops
hitting at all.
"""
from __future__ import annotations

import ast
import inspect
import json
import pathlib

import pytest

from myvitals.analytics import nutrition as N
from myvitals.integrations import claude as C

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "myvitals"


def _code_only(src: str) -> str:
    """Source with comments and docstrings removed.

    Assertions that match a module's own explanatory prose have produced
    four false failures in this project already — including one that
    matched the very comment explaining why the thing it forbade was
    absent. Strip both properly via the AST.
    """
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)


# ------------------------------------------------------- tool contract


def test_tool_forces_a_per_serving_fat_estimate():
    """Without `est_fat_g` there is nothing to re-check, and the whole
    safeguard becomes decorative."""
    props = C.MEAL_SUGGEST_TOOL["input_schema"]["properties"]
    item = props["suggestions"]["items"]
    assert "est_fat_g" in item["properties"]
    assert "est_fat_g" in item["required"]


def test_tool_requires_a_reason_tied_to_today():
    item = C.MEAL_SUGGEST_TOOL["input_schema"]["properties"]["suggestions"]["items"]
    assert "why" in item["required"]


def test_tool_separates_pantry_items_from_things_to_buy():
    """"Do not quietly assume staples" only works if there is a field for
    the things the user does not have."""
    props = C.MEAL_SUGGEST_TOOL["input_schema"]["properties"]["suggestions"]["items"]["properties"]
    assert "uses_from_pantry" in props
    assert "also_needs" in props


def test_tool_can_attribute_a_suggestion_to_a_saved_recipe():
    """The app never reproduces published recipe text. Adapting one of
    the user's OWN recipes is fine and should be named as such."""
    props = C.MEAL_SUGGEST_TOOL["input_schema"]["properties"]["suggestions"]["items"]["properties"]
    assert "based_on_saved_recipe" in props


# ------------------------------------------------------ system prompt


def test_prompt_states_the_medical_constraint_and_its_mechanism():
    p = C._meal_suggest_system("Supportive")
    assert "gall bladder" in p.lower()
    assert "one sitting" in p.lower() or "ONE sitting" in p


def test_prompt_forbids_inventing_a_fat_target():
    """Same rule as the rest of MEAL-2: with no target set, the model
    must not supply one or call a meal safe."""
    p = C._meal_suggest_system("Blunt")
    low = p.lower()
    assert "do not invent one" in low or "not invent" in low
    assert "safe" in low


def test_prompt_forbids_reproducing_published_recipes():
    p = C._meal_suggest_system("Data-only")
    low = p.lower()
    assert "never reproduce" in low
    assert "published" in low


def test_prompt_is_tone_parameterised():
    """Every other system prompt builder takes the tone setting; one that
    ignores it silently drops a user preference."""
    assert "Blunt" in C._meal_suggest_system("Blunt")
    assert "Supportive" in C._meal_suggest_system("Supportive")


# ---------------------------------------- the application-layer check


def test_safeguard_reruns_the_deterministic_fat_check():
    """The model's own opinion of a meal's fat is discarded and replaced
    by `assess_meal_fat`, so this card cannot disagree with the recipe
    page about the same number."""
    src = _code_only(inspect.getsource(C.meal_suggestions))
    assert "assess_meal_fat" in src
    assert 's["fat_assessment"]' in src or "s['fat_assessment']" in src


def test_safeguard_flags_rather_than_removes():
    """Silently dropping an over-target suggestion leaves the user
    wondering why the obvious meal was not offered — and hides that the
    model ignored the constraint."""
    src = _code_only(inspect.getsource(C.meal_suggestions))
    for removal in (".remove(", "del tool_input", "suggestions.pop("):
        assert removal not in src


def test_over_target_suggestion_is_marked_high():
    """The behaviour the safeguard exists for, exercised directly."""
    v = N.assess_meal_fat(45.0, target_g=20.0, history_fat_g=[])
    assert v["verdict"] in {"high", "very_high"}
    assert v["basis"] == "target"


def test_no_target_means_no_verdict_not_a_pass():
    """With no target and no history the check must refuse, exactly as it
    does everywhere else — never quietly approve."""
    v = N.assess_meal_fat(45.0, target_g=None, history_fat_g=[])
    assert v["verdict"] == "unknown"
    assert v["basis"] == "none"


def test_safeguard_survives_a_non_numeric_estimate():
    """Tool input is model-generated. A string where a number belongs
    must not 500 the endpoint."""
    src = _code_only(inspect.getsource(C.meal_suggestions))
    assert "TypeError" in src and "ValueError" in src


def test_missing_tool_call_has_a_safe_fallback():
    src = _code_only(inspect.getsource(C.meal_suggestions))
    assert '"suggestions": []' in src or "'suggestions': []" in src


# ------------------------------------------------------------ payload


def test_payload_caps_the_pantry():
    """The cache key is per-byte. A payload that grows without bound is
    how the bill climbs and how the cache stops hitting."""
    src = _code_only(inspect.getsource(C.build_meal_suggestion_payload))
    assert "[:60]" in src
    assert "limit(40)" in src


def test_payload_sends_names_not_nutrition_tables():
    """Bounded means aggregates, not raw rows — adding a surface must not
    mean sending more data. The model gets pantry names and recipe names;
    every number it needs was computed server-side."""
    src = _code_only(inspect.getsource(C.build_meal_suggestion_payload))
    for leak in ("RecipeIngredient", "NUTRIENT_COLUMNS", "vitamin_"):
        assert leak not in src


def test_payload_carries_the_fat_target_and_its_absence():
    src = _code_only(inspect.getsource(C.build_meal_suggestion_payload))
    assert "fat_per_meal_target_g" in src
    assert "fat_target_source" in src


def test_payload_carries_todays_context():
    """The differentiator: a generic app cannot know any of these."""
    src = _code_only(inspect.getsource(C.build_meal_suggestion_payload))
    for signal in (
        "_planned_strength_today", "_fasting_status",
        "_active_weight_goal_ctx", "recent_dailies",
    ):
        assert signal in src


def test_payload_sorts_pantry_by_expiry():
    """Suggesting what is about to go off is most of the value here."""
    src = _code_only(inspect.getsource(C.build_meal_suggestion_payload))
    assert "days_to_expiry" in src
    assert "sort" in src


def test_payload_uses_the_local_day():
    src = _code_only(inspect.getsource(C.build_meal_suggestion_payload))
    assert "_local_today()" in src
    assert "datetime.now(timezone.utc).date()" not in src


# ------------------------------------------------------------- wiring


def test_routes_are_mounted():
    from myvitals.main import app

    paths = set()
    for r in app.routes:
        inner = getattr(r, "original_router", None)
        if inner is not None:
            paths |= {getattr(x, "path", "") for x in inner.routes}
    assert "/ai/meals/suggest" in paths
    assert "/ai/meals/suggest/latest" in paths


def test_endpoint_is_quota_checked_and_cached():
    """Every AI surface in this codebase does both. One that skips the
    cache re-bills for an unchanged pantry; one that skips the quota lets
    a client run away with the bill."""
    src = (SRC / "api" / "ai.py").read_text()
    fn = src[src.index("async def meals_suggest_endpoint("):]
    fn = fn[: fn.index("@router.get")]
    assert "_check_and_bump_quota" in fn
    assert "_ai_cache_key" in fn
    assert "_coach_cached" in fn
    assert "_coach_persist" in fn


def test_latest_endpoint_does_not_bill():
    src = (SRC / "api" / "ai.py").read_text()
    fn = src[src.index("async def meals_suggest_latest("):]
    fn = fn[: fn.index("@router.post") if "@router.post" in fn[10:] else len(fn)]
    assert "meal_suggestions(" not in fn
    assert "_check_and_bump_quota" not in fn


def test_range_kind_is_consistent_between_write_and_read():
    """A mismatch here means the card is written under one key and read
    under another, so every load looks like a cache miss and re-bills."""
    src = (SRC / "api" / "ai.py").read_text()
    write = src[src.index("async def meals_suggest_endpoint("):]
    write = write[: write.index("@router.get")]
    read = src[src.index("async def meals_suggest_latest("):][:1200]
    assert '"meal_suggest"' in write
    assert '"meal_suggest"' in read


def test_tool_choice_forces_structured_output():
    """Cards, not prose — the clients render fields."""
    src = _code_only(inspect.getsource(C.meal_suggestions))
    assert "tool_choice" in src
    assert "give_meal_suggestions" in src
