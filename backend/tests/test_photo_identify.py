"""MEAL-7: identifying pantry items from a photograph.

This is the only surface in the app that sends an image anywhere, so the
tests are weighted toward the three rules that make that acceptable
rather than toward the recognition itself.

* **Nothing is added automatically.** The endpoint returns candidates.
  Vision misidentifies confidently, and a pantry that grows items the
  user did not put there stops being trustworthy — at which point the
  shopping list built on it is worse than useless.
* **The photo is never stored.** Forwarded once, discarded. No column, no
  cache, no log line.
* **Confidence survives to the client.** A guess and a certainty must not
  render identically to someone accepting in bulk.
"""
from __future__ import annotations

import ast
import base64
import re
import inspect
import pathlib

import pytest

from myvitals.integrations import claude as C

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "myvitals"


def _code_only(src: str) -> str:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)


def _endpoint() -> str:
    src = (SRC / "api" / "ai.py").read_text()
    fn = src[src.index("async def meals_identify_endpoint("):]
    return fn[: fn.index("@router.get")]


# ------------------------------------------------ nothing is auto-added


def test_endpoint_never_writes_a_pantry_item():
    """It proposes. The client confirms and calls the ordinary quick-add.

    If this endpoint ever creates a PantryItem directly, a
    misidentification becomes a silent write, and the user finds out when
    the shopping list omits something they never had.
    """
    fn = _code_only(_endpoint())
    assert "PantryItem" not in fn
    assert "db.add(" not in fn


def test_tool_forces_a_confidence_on_every_item():
    """Without it there is nothing to sort the guesses out with."""
    item = C.IDENTIFY_TOOL["input_schema"]["properties"]["items"]["items"]
    assert "confidence" in item["required"]
    assert item["properties"]["confidence"]["enum"] == ["high", "medium", "low"]


def test_prompt_asks_for_low_confidence_freely():
    p = C._identify_system("Blunt")
    low = p.lower()
    assert "low" in low
    assert "confirm" in low or "confirms" in low


def test_prompt_forbids_inventing_a_pantry():
    """A blurry photo must produce an empty list, not a plausible one."""
    p = C._identify_system("Supportive")
    assert "do not invent" in p.lower()


def test_prompt_limits_the_model_to_food():
    """The photo may contain a kitchen, a room, or a person. Only food is
    in scope, and identifying people explicitly is not."""
    p = C._identify_system("Data-only")
    low = p.lower()
    assert "not identify people" in low or "do not identify people" in low


# --------------------------------------------------- the photo is not kept


def test_the_image_is_never_persisted():
    fn = _code_only(_endpoint())
    for sink in ("AiSummary", "_coach_persist", "payload_hash", "_ai_cache_key"):
        assert sink not in fn, f"{sink} would retain a fingerprint of the photo"


def test_no_image_column_exists_anywhere():
    from myvitals.db.models import Base

    for table in Base.metadata.tables.values():
        for col in table.columns:
            assert "image" not in col.name.lower(), (
                f"{table.name}.{col.name} looks like image storage"
            )


def test_the_image_is_not_logged():
    src = _code_only((SRC / "integrations" / "claude.py").read_text())
    fn_start = src.index("async def identify_foods(")
    fn = src[fn_start:fn_start + 2500]
    assert "log." not in fn, "identify_foods must not log; the payload is a photo"


# -------------------------------------------------------- size and type


def test_size_limit_is_below_the_provider_ceiling():
    """Anthropic's own limit is 5 MB. Being under it means an oversized
    upload is refused before it is billed rather than after."""
    assert C.MAX_IMAGE_BYTES < 5_000_000


def test_size_is_checked_on_decoded_bytes_not_the_string():
    """Base64 inflates by a third and can be padded, so measuring the
    string would let a larger image through than intended."""
    fn = _code_only(_endpoint())
    assert "b64decode" in fn
    assert "len(decoded)" in fn


def test_unsupported_media_types_are_refused_before_a_call():
    with pytest.raises(ValueError):
        import asyncio

        class _Cfg:
            enabled = True
            anthropic_api_key = "x"
            model = "m"
            tone = "Blunt"

        asyncio.run(C.identify_foods(None, _Cfg(), "AAAA", "image/tiff"))


def test_allowed_types_match_what_the_provider_accepts():
    assert C.ALLOWED_IMAGE_TYPES == {
        "image/jpeg", "image/png", "image/gif", "image/webp",
    }


def test_a_data_url_prefix_is_tolerated():
    """Both clients build a data: URL at some point; stripping it here
    means a copy-paste of one does not fail confusingly."""
    fn = _code_only(_endpoint())
    assert "data:" in fn


# -------------------------------------------------------- quota + wiring


def test_the_call_is_quota_checked_and_counted():
    fn = _code_only(_endpoint())
    assert "_check_and_bump_quota" in fn
    assert "calls_today" in fn


def test_route_is_mounted():
    from myvitals.main import app

    paths = set()
    for r in app.routes:
        inner = getattr(r, "original_router", None)
        if inner is not None:
            paths |= {getattr(x, "path", "") for x in inner.routes}
    assert "/ai/meals/identify" in paths


def test_identified_names_are_resolved_against_the_catalog():
    """So the client can offer a one-tap add rather than making the user
    search for what the photo already told it."""
    fn = _code_only(_endpoint())
    assert "food_lib.search" in fn
    assert "unmatched" in fn


# ------------------------------------------- provider image translation


def test_openai_compatible_provider_translates_image_blocks():
    """Anthropic and OpenAI disagree on the image block shape. Without
    the mapping, a photo posted to an OpenAI-compatible endpoint either
    errors or — worse — is silently ignored and the model answers about
    nothing."""
    from myvitals.integrations.llm.openai_compat import _map_images

    out = _map_images([{
        "role": "user",
        "content": [
            {"type": "text", "text": "hi"},
            {"type": "image", "source": {
                "type": "base64", "media_type": "image/png", "data": "AAA",
            }},
        ],
    }])
    blocks = out[0]["content"]
    assert blocks[0]["type"] == "text"
    assert blocks[1]["type"] == "image_url"
    assert blocks[1]["image_url"]["url"] == "data:image/png;base64,AAA"


def test_text_only_messages_pass_through_untouched():
    """Every existing call site sends a plain string; none of them may
    change shape."""
    from myvitals.integrations.llm.openai_compat import _map_images

    msgs = [{"role": "user", "content": "plain text"}]
    assert _map_images(msgs) == msgs


# ---------------------------------------------------- client discipline


def test_both_clients_downscale_before_sending():
    """The server limit exists to stop a huge upload being billed; the
    honest way to respect it is not to send one. Re-encoding also drops
    EXIF, including GPS, which matters for an image leaving the device."""
    root = pathlib.Path(__file__).resolve().parents[2]
    web = (root / "frontend" / "src" / "components" / "PhotoPantry.vue").read_text()
    phone = (root / "android" / "app" / "src" / "main" / "kotlin" / "app"
             / "myvitals" / "ui" / "meals" / "PhotoPantry.kt").read_text()
    assert "MAX_EDGE" in web and "toDataURL" in web
    assert "MAX_EDGE" in phone and "inJustDecodeBounds" in phone


def test_bulk_select_never_sweeps_in_low_confidence():
    """The whole reason confidence is reported. A "select all" that
    includes guesses makes the confidence decorative."""
    root = pathlib.Path(__file__).resolve().parents[2]
    web = (root / "frontend" / "src" / "components" / "PhotoPantry.vue").read_text()
    phone = (root / "android" / "app" / "src" / "main" / "kotlin" / "app"
             / "myvitals" / "ui" / "meals" / "PhotoPantry.kt").read_text()
    assert 'it.confidence !== "low"' in web
    assert 'it.confidence != "low"' in phone


def test_both_clients_say_the_photo_leaves_the_device():
    root = pathlib.Path(__file__).resolve().parents[2]
    for f in (
        root / "frontend" / "src" / "components" / "PhotoPantry.vue",
        root / "android" / "app" / "src" / "main" / "kotlin" / "app"
        / "myvitals" / "ui" / "meals" / "PhotoPantry.kt",
    ):
        # Kotlin wraps long user-facing strings across a "+" concat, so
        # the phrase is split in the source while being intact on screen.
        # Join the fragments before matching rather than reflowing the
        # source to suit a test.
        text = re.sub(r'"\s*\+\s*\n?\s*"', "", f.read_text())
        assert "AI provider" in text
        assert "never stored" in text
