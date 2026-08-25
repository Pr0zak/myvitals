"""MEAL-BARCODE — scanning a packaged food.

Phase 7 of the meals plan, deliberately deferred until the typing
friction was measurable rather than predicted. It became measurable: the
bundled catalog is USDA, which carries generic foods and no brands, so
every packaged entry began by typing a product name into a catalog that
does not contain it — and roughly half this diet is packaged.

Open Food Facts is crowd-sourced, and that is the fact the whole design
turns on. A live probe of Lay's Classic Potato Chips came back with an
ingredients list for CHEESE. So a product from there is a CANDIDATE, is
never merged into the bundled catalog, and always says where it came
from.
"""
from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "myvitals"
MEALS = (SRC / "api" / "meals.py").read_text()
OFF = (SRC / "integrations" / "openfoodfacts.py").read_text()


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
    assert '@router.get("/foods/barcode/{code}"' in MEALS


def test_a_scan_saves_nothing() -> None:
    """Same rule as the photo features. A catalog that grows entries the
    user did not put there stops being trustworthy, and the shopping list,
    the pantry match and every fat total built on it go with it."""
    src = _fn_src("lookup_barcode")
    assert "db.add" not in src, "the lookup must not write a food"
    assert "commit" not in src, "a lookup must not commit"


def test_this_catalog_is_consulted_before_the_network() -> None:
    """A barcode scanned twice returns the food the user already
    corrected, not a fresh copy of whatever OFF currently says. It also
    means a known product costs no network call at all."""
    src = _fn_src("lookup_barcode")
    local = src.index("models.Food.barcode == digits")
    remote = src.index("openfoodfacts.lookup")
    assert local < remote, "the network is consulted before the local catalog"


def test_not_found_and_could_not_look_up_are_different_answers() -> None:
    """The user can act on one — try again, or use the label scanner —
    and not on the other. Collapsing them into a single failure hides
    which situation they are in."""
    src = _fn_src("lookup_barcode")
    assert "HTTPException(404" in src
    assert "HTTPException(502" in src


def test_the_origin_is_always_reported() -> None:
    """A crowd-sourced figure and one already in this catalog deserve
    different confidence, and rendering them identically loses that."""
    src = _fn_src("lookup_barcode")
    assert "origin='local'" in src
    assert "origin='openfoodfacts'" in src


def test_salt_is_never_converted_to_sodium() -> None:
    """OFF publishes both, and they differ by a factor of about 2.5. The
    label scanner refuses this conversion for the same reason: silent
    arithmetic turns a readable number into a wrong one."""
    assert '"sodium_100g"' in OFF
    assert '"salt_100g"' not in OFF, "salt must not be read as sodium"


def test_a_product_from_open_food_facts_is_not_marked_usda() -> None:
    """`db/seed_foods.py` only upserts rows whose source is "usda", so a
    catalog rebuild cannot overwrite these — but only while they carry a
    different source."""
    assert '"source": "openfoodfacts"' in OFF
    seed = (SRC / "db" / "seed_foods.py").read_text()
    assert "usda" in seed


def test_absent_nutrients_stay_null() -> None:
    """A product whose fibre was never entered by a contributor is not a
    food with no fibre. The null-is-not-zero rule runs the whole way
    through the meals feature and does not stop at the network edge."""
    assert "def _num" in OFF
    assert "return None" in OFF
    assert "or 0" not in OFF, "a missing nutrient must not default to zero"


def test_the_request_asks_for_only_the_fields_used() -> None:
    """The whole product document carries images, tags and translations —
    megabytes for one lookup of eight numbers."""
    assert "_FIELDS" in OFF and "fields" in OFF
    assert "ingredients_text" in OFF


def test_the_client_identifies_itself() -> None:
    """Open Food Facts asks every client to, and rate-limits anonymous
    traffic harder. Being a good citizen of a free service is the price
    of depending on one."""
    assert "User-Agent" in OFF and "myvitals" in OFF
