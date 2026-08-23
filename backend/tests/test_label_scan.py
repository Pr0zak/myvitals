"""MEAL-8: reading a nutrition-facts panel from a photo.

Roughly half this user's diet is packaged, and the only nutrition source
for a packaged item is the label on it. Typing thirteen numbers off a
panel is the friction that stops a food ever being added.

Distinct from `identify_foods`, which names WHAT is in a picture. This
reads NUMBERS off a structured document, so the rules differ — and the
one that matters most is that a field absent from the label stays absent
rather than becoming zero.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from myvitals.integrations import claude as C

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "myvitals"


def _endpoint() -> str:
    src = (SRC / "api" / "ai.py").read_text()
    fn = src[src.index("async def meals_read_label_endpoint("):]
    return fn[: fn.index("@router.get")]


def _code_only(src: str) -> str:
    tree = ast.parse(src.strip())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)


# ------------------------------------------- absent is not zero


def test_no_nutrient_is_required_by_the_schema():
    """A label that omits fibre is not a food with no fibre. Requiring a
    field would force the model to invent one."""
    schema = C.LABEL_TOOL["input_schema"]
    assert schema["required"] == ["basis"]


def test_the_prompt_forbids_estimating_a_missing_value():
    p = C._label_system("Blunt")
    low = p.lower()
    assert "do not infer" in low or "not infer" in low
    assert "omit" in low


def test_unreadable_fields_are_reported_rather_than_guessed():
    """A value that IS on the label but cannot be read is a different
    case from one that is absent, and the user can act on it — retake the
    photo."""
    assert "unreadable" in C.LABEL_TOOL["input_schema"]["properties"]
    assert "unreadable" in C._label_system("Blunt").lower()


# ----------------------------------------------- the conversion


def test_conversion_happens_server_side_not_in_the_model():
    """Asking a model to both read numbers and do arithmetic on them is
    two chances to be wrong where one will do."""
    fn = _code_only(_endpoint())
    assert "100.0 / serving" in fn


def test_a_per_serving_label_without_a_serving_size_refuses():
    """Assuming 100 g would silently inflate or deflate every figure on
    the card, with nothing to show it happened."""
    fn = _code_only(_endpoint())
    assert "convertible = False" in fn
    assert "reason" in fn


def test_per_100g_labels_are_not_rescaled():
    # ast.unparse normalises string quoting, so match on the shape.
    fn = _code_only(_endpoint())
    assert "per_100g" in fn
    assert "factor = 1.0" in fn


def test_the_basis_is_asked_for_explicitly():
    """US panels are per serving, UK/EU usually print both. Guessing
    which column was read is a 100x-scale error waiting to happen."""
    basis = C.LABEL_TOOL["input_schema"]["properties"]["basis"]
    assert basis["enum"] == ["per_serving", "per_100g", "unknown"]


def test_salt_is_not_silently_converted_to_sodium():
    """Salt is ~2.5x sodium by weight. A model doing that conversion
    unprompted is a wrong number with no audit trail."""
    p = C._label_system("Blunt")
    assert "do NOT do" in p or "do not do" in p.lower()
    assert "2.5" in p


# ------------------------------------------------- nothing is saved


def test_the_endpoint_creates_no_food():
    """It returns fields to confirm; the ordinary POST /meals/foods
    creates the row. A transcription error written straight into the
    catalog is a wrong number nobody knows to look for."""
    fn = _code_only(_endpoint())
    assert "models.Food(" not in fn
    assert "db.add(" not in fn


def test_what_was_read_is_returned_alongside_the_conversion():
    """So a user can check the transcription against the packet in hand,
    rather than only seeing post-arithmetic numbers."""
    fn = _code_only(_endpoint())
    assert "as_read" in fn


def test_the_image_is_not_persisted():
    fn = _code_only(_endpoint())
    for sink in ("AiSummary", "_coach_persist", "payload_hash"):
        assert sink not in fn


# ------------------------------------------------------- plumbing


def test_route_is_mounted():
    from myvitals.main import app

    paths = set()
    for r in app.routes:
        inner = getattr(r, "original_router", None)
        if inner is not None:
            paths |= {getattr(x, "path", "") for x in inner.routes}
    assert "/ai/meals/read-label" in paths


def test_quota_checked_and_size_bounded():
    fn = _code_only(_endpoint())
    assert "_check_and_bump_quota" in fn
    assert "MAX_IMAGE_BYTES" in fn
    assert "b64decode" in fn


def test_the_reader_uses_the_provider_aware_credentials_check():
    """It must work under claude_cli, which has no API key by design."""
    src = inspect.getsource(C.read_nutrition_label)
    assert "_credentials_missing(cfg)" in src
    assert "not cfg.anthropic_api_key" not in src


def test_both_surfaces_offer_the_scan():
    root = pathlib.Path(__file__).resolve().parents[2]
    web = (root / "frontend" / "src" / "views" / "meals" / "Foods.vue").read_text()
    phone = (root / "android" / "app" / "src" / "main" / "kotlin" / "app"
             / "myvitals" / "ui" / "meals" / "MealsScreen.kt").read_text()
    assert "Scan a label" in web
    assert "readLabel" in web
    assert "Scan a nutrition label" in phone
    assert "mealsReadLabel" in phone
