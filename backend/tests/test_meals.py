"""MEAL-1: the food catalog, unit conversion and recipe nutrition.

Three of these tests exist because the corresponding bug was found by
hand during development and would not have been caught by anything else:

* `test_search_finds_inverted_usda_names` — USDA writes "Oil, olive,
  salad or cooking", so a substring search for "olive oil" answered
  MAYONNAISE.
* `test_tbsp_alias_uses_the_foods_own_measure` — the food's table is
  keyed "tablespoon" and users type "tbsp", so the lookup fell through
  to a generic estimate and mis-costed 2 tbsp of olive oil by 9.5%.
* `test_seed_chunk_stays_under_bind_parameter_ceiling` — asyncpg refuses
  more than 32,767 bind parameters, and the catalog is 3x over that in a
  single statement. This ceiling has been hit twice elsewhere.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from myvitals.analytics import foods as F
from myvitals.db import models
from myvitals.db.seed_foods import CHUNK, _COLUMNS

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "myvitals"


# ------------------------------------------------------------- catalog


def test_catalog_loads_and_is_substantial():
    rows = F.catalog()
    assert len(rows) > 5000, "bundled catalog looks truncated"
    assert all(r.get("slug") and r.get("name") for r in rows)


def test_every_food_has_energy():
    """A food with no kcal cannot contribute to any total the app shows,
    so the extractor drops it. If one slips through, a recipe silently
    loses calories."""
    assert [r["name"] for r in F.catalog() if r.get("kcal") is None] == []


def test_slugs_are_unique():
    slugs = [r["slug"] for r in F.catalog()]
    assert len(slugs) == len(set(slugs))


def test_most_foods_carry_household_measures():
    """Recipes are written in cups and tablespoons. When this regressed to
    83 of 7,032 foods the feature was unusable, and the cause was a
    silent parse miss rather than an error."""
    rows = F.catalog()
    with_units = sum(1 for r in rows if r.get("unit_grams"))
    assert with_units / len(rows) > 0.9


# -------------------------------------------------------------- search


def test_search_finds_inverted_usda_names():
    top = F.search("olive oil", ingredients_only=True, limit=5)
    assert top, "no result for a staple ingredient"
    assert top[0]["name"] == "Oil, olive, salad or cooking"


def test_search_prefers_whole_words_over_prefixes():
    """"egg" must not answer "Eggnog" — both match as a prefix and Eggnog
    has the shorter name, so every other tiebreak picks it."""
    names = [r["name"] for r in F.search("egg", ingredients_only=True, limit=10)]
    assert not names[0].lower().startswith("eggnog")
    assert all(n.lower().startswith("egg,") for n in names[:3])


def test_search_demotes_processed_forms_unless_asked_for():
    plain = [r["name"] for r in F.search("salmon", ingredients_only=True, limit=5)]
    assert not any("breaded" in n.lower() for n in plain)
    # ...but asking for a processed form still finds it.
    dried = [r["name"] for r in F.search("dried egg", ingredients_only=True, limit=5)]
    assert any("dried" in n.lower() for n in dried)


def test_search_requires_every_term():
    assert F.search("olive zzzznotaword", limit=5) == []


def test_ingredients_only_excludes_prepared_dishes():
    everything = F.search("chicken", limit=100)
    ingredients = F.search("chicken", ingredients_only=True, limit=100)
    assert len(ingredients) <= len(everything)
    assert all(F.is_ingredient(r) for r in ingredients)


# ---------------------------------------------------------- conversion


def _find(name: str) -> dict:
    for r in F.catalog():
        if r["name"] == name:
            return r
    raise AssertionError(f"missing expected catalog entry: {name}")


def test_tbsp_alias_uses_the_foods_own_measure():
    """The per-food table is authoritative and must win over the generic
    fallback. Olive oil lists "tablespoon" at 13.5 g; the generic table
    says 14.79. Getting this wrong overstated fat by 9.5%, which is the
    one nutrient this user's cholecystectomy makes matter."""
    oil = _find("Oil, olive, salad or cooking")
    assert F.to_grams(2, "tbsp", oil) == 27.0
    assert F.to_grams(2, "tablespoon", oil) == 27.0
    assert F.to_grams(2, "Tbsp.", oil) == 27.0


def test_per_food_measures_differ_between_foods():
    """A cup is not a unit of mass. If these ever agree, something has
    collapsed to a single generic density."""
    oil = _find("Oil, olive, salad or cooking")
    butter = _find("Butter, salted")
    assert F.to_grams(1, "cup", oil) == 216.0
    assert F.to_grams(1, "cup", butter) == 227.0


def test_mass_units_are_exact():
    assert F.to_grams(6, "oz", None) == pytest.approx(170.1, abs=0.1)
    assert F.to_grams(1, "lb", None) == pytest.approx(453.59, abs=0.01)
    assert F.to_grams(250, "g", None) == 250.0


def test_countable_units_do_not_get_a_generic_guess():
    """There is no general weight for one clove or one slice. Returning
    None marks the line unresolved; a guess would silently corrupt the
    total instead."""
    assert F.to_grams(1, "clove", None) is None
    assert F.to_grams(2, "slice", None) is None
    assert F.to_grams(1, "pinch", None) is None


def test_unknown_unit_returns_none_not_zero():
    oil = _find("Oil, olive, salad or cooking")
    assert F.to_grams(1, "smidgen", oil) is None
    assert F.to_grams(0, "tbsp", oil) is None
    assert F.to_grams(None, "tbsp", oil) is None


# --------------------------------------------------------- nutrition


def test_nutrition_scales_from_per_100g():
    oil = _find("Oil, olive, salad or cooking")
    n = F.nutrition_for(oil, 50.0)
    assert n["kcal"] == pytest.approx(442.0, abs=0.5)
    assert n["fat_g"] == pytest.approx(50.0, abs=0.5)


def test_missing_nutrient_stays_none_through_scaling():
    """Null must not become 0.0. "We do not know this food's sodium" is a
    different claim from "this food has no sodium", and only one of them
    lets a total be presented as complete."""
    fake = {"kcal": 100.0, "fat_g": None}
    n = F.nutrition_for(fake, 200.0)
    assert n["kcal"] == 200.0
    assert n["fat_g"] is None


def test_nutrition_of_nothing_is_all_none():
    assert set(F.nutrition_for(None, None).values()) == {None}


# -------------------------------------------------------------- seed


def test_seed_chunk_stays_under_bind_parameter_ceiling():
    """asyncpg refuses a statement with >32,767 bind parameters. A
    multi-row INSERT binds one per column per row, so the chunk size and
    the column count together decide whether the seed works at all."""
    per_row = len(_COLUMNS) + 1  # +1 for the `source` literal
    assert CHUNK * per_row < 32_767


def test_unchunked_seed_would_actually_exceed_the_ceiling():
    """Guards against someone "simplifying" the chunking away: the real
    catalog is several times over the limit in one statement."""
    per_row = len(_COLUMNS) + 1
    assert len(F.catalog()) * per_row > 32_767


def test_seed_columns_all_exist_on_the_model():
    """Every column the seeder names must resolve on Food.

    Four separate bugs this session were names that did not resolve —
    Activity.id, models.Concept2Creds, a missing import, a wrong router
    prefix — and all four passed the full suite because nothing executed
    the path."""
    cols = set(models.Food.__table__.columns.keys())
    missing = [c for c in (*_COLUMNS, "source") if c not in cols]
    assert missing == [], f"seeder writes columns that do not exist: {missing}"


def test_catalog_keys_match_the_nutrient_columns():
    """The bundled JSON and the DB schema have to agree, or the seed
    silently writes nulls."""
    seen: set[str] = set()
    for r in F.catalog()[:500]:
        seen |= set(r) & set(F.NUTRIENT_COLUMNS)
    assert seen == set(F.NUTRIENT_COLUMNS)


def test_seed_only_overwrites_bundled_rows():
    """A user correcting a bundled food must not have it reverted on the
    next restart, so the upsert is guarded on source == 'usda'."""
    from myvitals.db import seed_foods as mod
    src = inspect.getsource(mod.seed_foods)
    tree = ast.parse(src.lstrip())
    literals = {
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    assert "usda" in literals
    assert "where=" in src or "where =" in src


# --------------------------------------------------------- API shape


def test_routes_do_not_hardcode_the_api_prefix():
    """Caddy strips "/api" exactly once. A route that spells it out is
    unreachable from the browser — the recurring 404 in CLAUDE.md."""
    from myvitals.api import meals
    bad = [r.path for r in meals.router.routes if r.path.startswith("/api")]
    assert bad == [], f"routes must not carry the /api prefix: {bad}"


def _mounted_paths(app) -> set[str]:
    """Every path the app actually serves.

    FastAPI 0.141 wraps each `include_router` in an `_IncludedRouter`
    rather than splicing the child routes into `app.routes`, so a naive
    `{r.path for r in app.routes}` sees none of them and would pass this
    test vacuously.
    """
    out: set[str] = set()
    for r in app.routes:
        inner = getattr(r, "original_router", None)
        if inner is not None:
            out |= {getattr(x, "path", "") for x in inner.routes}
        else:
            out.add(getattr(r, "path", ""))
    return out


def test_meals_router_is_registered():
    """The router being written is not the same as it being mounted. A
    module that is never included answers 404 for every path in it while
    every unit test in this file still passes."""
    from myvitals.main import app
    paths = _mounted_paths(app)
    for wanted in ("/meals/foods/search", "/meals/recipes", "/meals/pantry",
                   "/meals/stats"):
        assert wanted in paths, f"{wanted} is not mounted"


def test_the_mount_check_can_actually_fail():
    """Guards the guard. If `_mounted_paths` ever stops seeing child
    routes it would silently return an empty set and the test above
    would pass for the wrong reason."""
    from myvitals.main import app
    assert "/meals/definitely-not-a-real-route" not in _mounted_paths(app)
    assert len(_mounted_paths(app)) > 100


def test_recipe_totals_exclude_unresolved_lines_and_say_so():
    """The whole point of `unresolved_count`: a total built from three of
    four lines must not be presented as the recipe's nutrition."""
    from myvitals.api.meals import _sum_nutrition
    lines = [
        {"kcal": 100.0, "fat_g": 5.0},
        {"kcal": 50.0, "fat_g": None},
    ]
    out = _sum_nutrition(lines)
    assert out["kcal"] == 150.0
    assert out["fat_g"] == 5.0
    # A nutrient no line supplied stays unknown rather than becoming zero.
    assert out["sodium_mg"] is None


def test_per_serving_divides_and_preserves_none():
    from myvitals.api.meals import _divide
    out = _divide({"kcal": 900.0, "fat_g": None}, 4)
    assert out["kcal"] == 225.0
    assert out["fat_g"] is None


def test_per_serving_never_divides_by_zero():
    from myvitals.api.meals import _divide
    assert _divide({"kcal": 100.0}, 0)["kcal"] == 100.0


# ------------------------------------------- restaurant / chain coverage
#
# Roughly half this user's diet is packaged or eaten out. The first cut of
# the catalog dropped every named chain on the reasoning that a search for
# "chicken" should not return forty entrees before the plain breast — right
# about the ranking problem, wrong about the fix. The ranking is handled in
# `search` now and the chains are back; these tests keep both properties
# true at once.


def test_named_chain_items_are_present():
    for query, expect in [
        ("big mac", "mcdonald"),
        ("whopper", "burger king"),
        ("mcchicken", "mcdonald"),
        ("burrito supreme", "taco bell"),
    ]:
        hits = F.search(query, limit=3)
        assert hits, f"no catalog entry for {query!r}"
        joined = " ".join(h["name"].lower() for h in hits)
        assert expect in joined, f"{query!r} did not surface a {expect} item"


def test_chain_items_carry_a_whole_item_portion():
    """Per-100 g nutrition alone makes a chain item unloggable — nobody
    weighs a burger. The branded extractor turns the label's serving size
    into a named portion, and without it the row is dead weight."""
    hits = [h for h in F.search("big mac", limit=5)
            if "big mac" in h["name"].lower()]
    assert hits
    assert any(h.get("unit_grams") for h in hits), "no portion on any Big Mac row"


def test_a_chain_item_totals_a_plausible_meal():
    """Guards the per-100 g vs per-serving confusion. A Big Mac is about
    500-600 kcal; reading the label figure as per-serving would give ~260
    and reading the portion wrong would give thousands."""
    hits = [h for h in F.search("big mac", limit=5)
            if "big mac" in h["name"].lower() and h.get("unit_grams")]
    assert hits
    food = hits[0]
    unit, grams = next(iter(food["unit_grams"].items()))
    total = F.nutrition_for(food, grams)
    assert 400 <= total["kcal"] <= 750, (
        f"{food['name']} at 1 {unit} ({grams} g) = {total['kcal']} kcal"
    )


def test_fast_food_never_reaches_the_ingredient_picker():
    """The whole reason the two lenses exist. If a chain item can appear
    in a recipe's ingredient search, the catalog broadening has broken the
    thing it was carefully kept away from."""
    for q in ("chicken", "beef", "cheese", "burger", "big mac"):
        for r in F.search(q, ingredients_only=True, limit=25):
            assert r.get("category") not in {
                "Fast Foods", "Restaurant Foods",
                "Meals, Entrees, and Side Dishes",
            }, f"{r['name']!r} ({r['category']}) leaked into the ingredient picker"


def test_ingredient_search_still_leads_with_plain_foods():
    """Broadening the catalog must not push the plain ingredient down the
    list — that regression is exactly what dropping the chains was
    (wrongly) protecting against."""
    assert F.search("olive oil", ingredients_only=True, limit=1)[0]["name"] == (
        "Oil, olive, salad or cooking"
    )
    top = F.search("chicken breast", ingredients_only=True, limit=1)[0]["name"]
    assert "raw" in top.lower() or "breast" in top.lower()


def test_infant_and_institutional_food_stays_out():
    """The drop list was narrowed to let chains back in. These must not
    have come along with them."""
    names = " ".join(r["name"].lower() for r in F.catalog())
    assert "infant formula" not in names
    assert "baby food" not in names


def test_brand_filter_matches_the_owner_not_the_description():
    """A flavour word and a restaurant name are the same string.

    Matching the chain regex against the product description as well as
    the brand pulled in every chipotle-flavoured supermarket item —
    McCormick seasoning, B&G sauces — none of which is a restaurant menu.
    """
    import re
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "scripts" / "build_food_catalog.py").read_text()
    body_start = src.index("def _convert_branded(")
    body = src[body_start:body_start + 2000]
    code = "\n".join(
        ln for ln in body.splitlines() if not ln.strip().startswith("#")
    )
    assert "RESTAURANT_BRANDS.search(brand)" in code
    assert "RESTAURANT_BRANDS.search(f\"{brand} {desc}\")" not in code


def test_no_supermarket_brands_came_through_the_branded_path():
    """The concrete items the description-matching bug let through.

    Scoped to the trailing "(Brand)" parenthetical, which is the format
    `_tidy_branded_name` produces and therefore the only naming the
    branded extractor can be responsible for. SR Legacy carries some
    brand names inside its own descriptions ("Snacks, KELLOGG, RICE
    KRISPIES TREATS Squares") and those are legitimate foods to log —
    asserting on the bare substring would fail on them and say nothing
    about the bug.
    """
    import re
    owners = []
    for r in F.catalog():
        m = re.search(r"\(([^)]+)\)$", r["name"])
        if m:
            owners.append(m.group(1).lower())
    for junk in ("mccormick", "b&g foods", "domino foods", "firehouse station",
                 "bush brothers", "campbell soup"):
        assert not any(junk in o for o in owners), (
            f"{junk!r} is a manufacturer, not a restaurant chain"
        )


def test_the_brand_check_can_actually_fail():
    """Guards the guard: the parenthetical extraction must be finding
    real brand owners, not silently matching nothing."""
    import re
    owners = {
        m.group(1).lower()
        for r in F.catalog()
        if (m := re.search(r"\(([^)]+)\)$", r["name"]))
    }
    assert len(owners) > 20
    assert any("mcdonald" in o for o in owners)


def test_every_model_default_actually_runs():
    """Execute every Python-side column default in the whole models module.

    `Food.created_at` shipped as
    `default=lambda: datetime.now(timezone.utc)` while `models.py` imports
    only `date` and `datetime` — so every INSERT raised
    `NameError: name 'timezone' is not defined`. The entire suite passed,
    because no test executed an insert against a real database, and the
    startup seeder logged-and-swallowed the failure. The tables were
    created and stayed empty.

    A default is a callable nobody calls until production does. This
    calls all of them.

    Note this guard is currently DORMANT: the fix removed the only
    callable default in the module, so it iterates zero columns. It is
    kept because it arms itself automatically the moment anyone adds
    one back. `test_model_lambdas_only_use_names_that_resolve` is the
    test that actively pins the regression.
    """
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
                failures.append(f"{table.name}.{col.name}: {type(e).__name__}: {e}")
    assert failures == [], "column defaults that raise:\n  " + "\n  ".join(failures)


def test_meal_tables_rely_on_a_server_default_for_timestamps():
    """The non-null timestamp columns have no Python default, so the
    INSERT must be able to omit them. Migration 0056 supplies now()."""
    mig = (pathlib.Path(__file__).resolve().parents[1]
           / "alembic" / "versions" / "0056_meals.py").read_text()
    assert mig.count('server_default=sa.text("now()")') >= 3

    from myvitals.db.models import Food, PantryItem
    for model, col in ((Food, "created_at"), (PantryItem, "updated_at")):
        assert model.__table__.columns[col].default is None, (
            f"{model.__name__}.{col} has a Python default; the seeder omits "
            f"the column and relies on the server default"
        )


def test_model_lambdas_only_use_names_that_resolve():
    """Every name inside a lambda in `models.py` must be importable there.

    This is the fifth instance this session of a name that parses fine and
    does not exist at runtime — after `Activity.id`, `models.Concept2Creds`,
    a missing `select` import, and a router prefix typo. The pattern is
    always the same: the reference sits on a path no test executes, so the
    whole suite stays green and production raises.

    A lambda body is the worst case, because it is not evaluated at import
    time either — the module loads cleanly and fails on first use.
    """
    import ast
    import builtins
    from myvitals.db import models as models_mod

    src = pathlib.Path(models_mod.__file__).read_text()
    tree = ast.parse(src)

    module_names = set(vars(models_mod)) | set(dir(builtins))

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Lambda):
            continue
        bound = {a.arg for a in node.args.args}
        bound |= {a.arg for a in node.args.kwonlyargs}
        if node.args.vararg:
            bound.add(node.args.vararg.arg)
        if node.args.kwarg:
            bound.add(node.args.kwarg.arg)
        for sub in ast.walk(node.body):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                if sub.id not in bound and sub.id not in module_names:
                    offenders.append(f"line {sub.lineno}: {sub.id}")

    assert offenders == [], (
        "these names are used in a models.py lambda but are not importable "
        "there, so the default raises NameError on first INSERT:\n  "
        + "\n  ".join(offenders)
    )


def test_the_lambda_name_check_can_actually_fail():
    """Guards the guard, since the real check passes on a clean module."""
    import ast
    import builtins

    tree = ast.parse("f = lambda: datetime.now(timezone.utc)\n")
    module_names = {"datetime"} | set(dir(builtins))
    found = [
        n.id for node in ast.walk(tree) if isinstance(node, ast.Lambda)
        for n in ast.walk(node.body)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
        and n.id not in module_names
    ]
    assert found == ["timezone"]


# ---------------------------------------- whole ingredients rank first
#
# Reported from live use: adding raw chicken breast to the pantry was
# effectively impossible. A search for "chicken breast" answered with
# deli roll, fat-free sliced chicken and a White Castle sandwich, because
# those put both terms in the first ten characters and have short names,
# while USDA spells the actual ingredient "Chicken, broiler or fryers,
# breast, skinless, boneless, meat only, raw" — thirty characters in and
# four times the length. Position and name-length both pushed the right
# answer down.


def test_plain_ingredient_beats_deli_and_restaurant_forms():
    top = F.search("chicken breast", limit=1)[0]
    assert F.is_ingredient(top), f"{top['name']!r} is {top['category']!r}"
    assert "raw" in top["name"].lower()


def test_bare_noun_searches_lead_with_ingredients():
    """The same bug in its milder form: "chicken" alone answered "Chicken
    kiev" and "Chicken curry"."""
    for q in ("chicken", "beef", "cheese", "yogurt", "rice"):
        top = F.search(q, limit=3)
        assert top, q
        assert all(F.is_ingredient(r) for r in top), (
            f"{q!r} returned prepared food: "
            f"{[r['name'] for r in top if not F.is_ingredient(r)]}"
        )


def test_the_ingredient_tier_does_not_break_the_food_log():
    """It must be a no-op when only prepared foods match, or logging a
    meal out stops working — which is the failure the catalog broadening
    existed to fix in the first place."""
    for q, expect in (
        ("big mac", "mcdonald"),
        ("whopper", "burger king"),
        ("burrito supreme", "taco bell"),
    ):
        hits = F.search(q, limit=3)
        assert hits, q
        assert expect in " ".join(h["name"].lower() for h in hits)


def test_ingredient_tier_ranks_below_the_processed_word_demotion():
    """Order matters: an unrequested "breaded"/"dried" must still outrank
    the ingredient/prepared split, or "salmon" leads with breaded fish
    fillets simply because they are categorised as an ingredient."""
    top = F.search("salmon", limit=3)
    assert not any("breaded" in r["name"].lower() for r in top)


def test_pantry_picker_defaults_to_ingredients_on_both_surfaces():
    """The ranking fix alone is not enough — the pantry picker was
    searching the whole catalog, so packaged forms still crowded the
    list. Both clients now default to ingredients with a toggle."""
    web = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"
           / "views" / "meals" / "Pantry.vue").read_text()
    assert "ingredientsOnly = ref(true)" in web
    assert ":ingredients-only=\"ingredientsOnly\"" in web

    phone = (pathlib.Path(__file__).resolve().parents[2] / "android" / "app"
             / "src" / "main" / "kotlin" / "app" / "myvitals" / "ui" / "meals"
             / "MealsScreen.kt").read_text()
    assert "var ingredientsOnly by remember { mutableStateOf(true) }" in phone
    assert "ingredientsOnly = ingredientsOnly" in phone


# ------------------------------------------ the food knows its own units
#
# Reported from live use, immediately after the search fix: having found
# raw chicken breast, there was no way to know what to enter for quantity
# and unit. The food carries {oz: 28.25, package: 926, piece: 272} from
# USDA — "1 piece" is one breast — but the UI showed a blank box, so the
# user had to guess at a word the app already knew.


def test_staple_ingredients_carry_a_countable_measure():
    """A pantry is filled in pieces and packages, not grams. If these
    disappear from the extract, the pickers go back to guesswork."""
    for name_part, wanted in (
        ("breast, skinless, boneless, meat only, raw", "piece"),
        ("Butter, salted", "stick"),
        ("Spinach, raw", "bunch"),
    ):
        hit = next(
            (r for r in F.catalog() if name_part in r["name"]), None,
        )
        assert hit is not None, f"missing catalog entry for {name_part!r}"
        units = {k.lower() for k in (hit.get("unit_grams") or {})}
        assert wanted in units, f"{hit['name']!r} lost its {wanted!r} measure"


def test_one_chicken_breast_is_a_plausible_weight():
    """Guards the portion extractor: `gramWeight` is the weight of
    `amount` units, not of one, and reading it directly used to double
    every quantity."""
    hit = next(
        r for r in F.catalog()
        if "breast, skinless, boneless, meat only, raw" in r["name"]
    )
    piece = hit["unit_grams"]["piece"]
    assert 150 <= piece <= 400, f"one chicken breast reported as {piece} g"


def test_a_piece_of_chicken_costs_sensibly():
    hit = next(
        r for r in F.catalog()
        if "breast, skinless, boneless, meat only, raw" in r["name"]
    )
    grams = F.to_grams(1, "piece", hit)
    n = F.nutrition_for(hit, grams)
    # ~272 g of raw breast: roughly 325 kcal and 7 g fat.
    assert 250 <= n["kcal"] <= 450
    assert 4 <= n["fat_g"] <= 12


def test_quantity_pickers_exist_on_both_surfaces():
    """The ranking fix made the food findable; this made it enterable.
    Both clients offer the food's own measures rather than a blank box."""
    root = pathlib.Path(__file__).resolve().parents[2]
    web = (root / "frontend" / "src" / "components" / "QuantityPicker.vue")
    phone = (root / "android" / "app" / "src" / "main" / "kotlin" / "app"
             / "myvitals" / "ui" / "meals" / "QuantityPicker.kt")
    assert web.exists() and phone.exists()
    for f in (web, phone):
        src = f.read_text()
        assert "unit_grams" in src or "unitGrams" in src


def test_quantity_pickers_offer_no_generic_volume_unit():
    """A cup of flour and a cup of honey differ by more than a factor of
    two, so a generic "cup" would be a wrong answer dressed as a
    convenience. Volume must come from the food's own table or not at
    all."""
    root = pathlib.Path(__file__).resolve().parents[2]
    for f in (
        root / "frontend" / "src" / "components" / "QuantityPicker.vue",
        root / "android" / "app" / "src" / "main" / "kotlin" / "app"
        / "myvitals" / "ui" / "meals" / "QuantityPicker.kt",
    ):
        src = f.read_text()
        # A fixed window rather than a delimiter: the TS list closes with
        # "]" and the Kotlin one with ")", and hard-coding either makes
        # the test throw on the other file instead of failing usefully.
        start = src.index("GENERIC")
        generic = src[start:start + 400]
        for volume in ('"cup"', '"tbsp"', '"tsp"', '"ml"'):
            assert volume not in generic, f"{f.name} offers a generic {volume}"


def test_food_search_exposes_the_readable_concept():
    """Reported from live use, twice.

    Ranking put raw chicken breast first, but the row still READ as
    "Chicken, broiler or fryers, breast, skinless, boneless, meat only,
    raw" — so the list looked like it had no plain chicken breast in it.
    The concept is the scannable title; the USDA name stays underneath
    because its precision is what makes the nutrition right.
    """
    from myvitals.api.meals import FoodOut

    assert "concept" in FoodOut.model_fields


def test_both_pickers_title_on_concept_not_the_usda_name():
    root = pathlib.Path(__file__).resolve().parents[2]
    web = (root / "frontend" / "src" / "components" / "FoodPicker.vue").read_text()
    phone = (root / "android" / "app" / "src" / "main" / "kotlin" / "app"
             / "myvitals" / "ui" / "meals" / "FoodPicker.kt").read_text()
    assert "title(f)" in web and "f.concept" in web
    assert "f.concept?.replaceFirstChar" in phone


def test_pantry_and_foods_explain_what_they_are_for():
    """Asked directly: "what is the difference between the pantry and
    foods section". If a user has to ask, the screens have to say."""
    root = pathlib.Path(__file__).resolve().parents[2]
    pantry = (root / "frontend" / "src" / "views" / "meals" / "Pantry.vue").read_text()
    foods = (root / "frontend" / "src" / "views" / "meals" / "Foods.vue").read_text()
    assert "in the house" in pantry
    assert "reference catalog" in foods
    assert "does <strong>not</strong>" in foods or "does not" in foods


# ------------------------------------------------ one-tap common staples
#
# Asked directly: "should I just name them and leave it as it is? would
# that be good enough?". Measured against this catalog, no — typing plain
# names works for nine of twenty everyday staples and fails SILENTLY for
# the rest, because their concepts are "whole egg", "wheat flour",
# "granulated sugar". A pantry item that looks right and never matches is
# worse than one that is obviously missing.


def test_typing_a_plain_name_is_not_reliable():
    """The measurement behind the curated list. If this ever passes for
    everything, the list has become unnecessary and can go."""
    from myvitals.analytics.concepts import concept_for

    concepts = {c for r in F.catalog() if (c := concept_for(r))}
    typed = ["eggs", "flour", "sugar", "milk", "salt", "cheese", "bread"]
    missing = [t for t in typed if t not in concepts]
    assert missing, "plain names now all resolve; the curated list is redundant"


def test_every_common_staple_resolves_to_a_real_food():
    """Terms are resolved through the same ranked search the pickers use,
    so a term that stops working must be caught here rather than silently
    dropping a staple off the list."""
    from myvitals.analytics.common_pantry import flat
    from myvitals.analytics.concepts import concept_for

    misses = []
    for _cat, label, term in flat():
        hits = F.search(term, ingredients_only=True, limit=1) or F.search(term, limit=1)
        if not hits or not concept_for(hits[0]):
            misses.append(label)
    assert misses == [], f"staples that no longer resolve: {misses}"


def test_honey_resolves_to_honey_not_a_dressing():
    """Two bugs in one case. Honey is filed under "Sweets", which the
    ingredients-only picker used to exclude entirely — so searching the
    pantry for honey returned nothing. And the first search term chosen
    for it resolved to honey-mustard DRESSING."""
    from myvitals.analytics.common_pantry import flat
    from myvitals.analytics.concepts import concept_for

    _cat, _label, term = next(x for x in flat() if x[1] == "Honey")
    hit = (F.search(term, ingredients_only=True, limit=1) or F.search(term, limit=1))[0]
    assert concept_for(hit) == "honey", f"Honey resolved to {hit['name']!r}"


def test_sweets_are_searchable_as_ingredients():
    """Honey, sugar and syrup are things you cook with. Excluding the
    whole category to keep candy bars out was the wrong trade."""
    assert "Sweets" in F.INGREDIENT_CATEGORIES
    assert F.search("honey", ingredients_only=True, limit=1)


def test_deli_meat_is_still_excluded_from_the_ingredient_picker():
    """Widening the ingredient categories once reintroduced the ORIGINAL
    bug: adding "Sausages and Luncheon Meats" put deli chicken breast,
    sliced fat-free chicken and rotisserie-seasoned chicken ahead of raw
    chicken breast again."""
    assert "Sausages and Luncheon Meats" not in F.INGREDIENT_CATEGORIES
    top = F.search("chicken breast", ingredients_only=True, limit=1)[0]
    assert top["category"] == "Poultry Products"
    assert "raw" in top["name"].lower()


def test_quick_add_asks_for_no_quantities():
    """A pantry is a "do I have this" list. Demanding amounts is what
    stops one being kept up to date — SuperCook's boolean pantry is the
    precedent."""
    from myvitals.api.meals import QuickAddIn

    assert set(QuickAddIn.model_fields) == {"food_ids"}
