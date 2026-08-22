"""The bundled food catalog, and how a quantity becomes grams (MEAL-1).

The catalog is a public-domain USDA extract committed to the repo, built
by `backend/scripts/build_food_catalog.py`. Same pattern as the exercise
catalog: bundled rather than fetched, so the feature works offline and
does not depend on an external service staying up.

9,791 foods, 3.3 MB, eight nutrients each plus household-measure
conversions for 9,648 of them. Four USDA sources: Foundation and SR
Legacy for ingredients, FNDDS for prepared dishes, and the branded
export filtered to restaurant chains so a meal eaten out can be logged.
"""

from __future__ import annotations

import json
import re
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_DATA = Path(__file__).resolve().parent.parent / "data" / "foods.json"

#: Categories that are things you COOK WITH. The catalog also carries
#: prepared foods — restaurant entrees, snacks, sweets — because those
#: are things you EAT and the food log needs them. The two pickers want
#: different subsets of the same table, so the split lives here rather
#: than in the data: dropping prepared foods would break logging, and
#: showing them in an ingredient picker buries plain chicken breast under
#: forty sandwiches.
INGREDIENT_CATEGORIES: frozenset[str] = frozenset({
    "Dairy and Egg Products", "Spices and Herbs", "Fats and Oils",
    "Poultry Products", "Pork Products", "Beef Products",
    "Lamb, Veal, and Game Products", "Finfish and Shellfish Products",
    "Vegetables and Vegetable Products", "Fruits and Fruit Juices",
    "Nut and Seed Products", "Legumes and Legume Products",
    "Cereal Grains and Pasta", "Soups, Sauces, and Gravies",
})

#: Nutrient columns carried per 100 g. Every one is nullable downstream:
#: USDA does not have every nutrient for every food, and "unknown" must
#: stay distinguishable from "zero".
NUTRIENT_COLUMNS: tuple[str, ...] = (
    "kcal", "protein_g", "carbs_g", "fat_g",
    "saturated_fat_g", "fiber_g", "sugar_g", "sodium_mg",
)

#: Spelling variants collapsed to one canonical unit.
#:
#: This exists because the two sides use different words for the same
#: measure. USDA writes "tablespoon"; people type "tbsp". Without the
#: alias the per-food entry does not match, the lookup falls through to
#: the generic table, and 2 tbsp of olive oil is costed at 29.58 g
#: instead of its true 27.0 g — a 9.5% error on the one nutrient a
#: cholecystectomy makes matter most. Plural and punctuated forms are
#: folded in for the same reason.
_UNIT_ALIASES: dict[str, str] = {
    "gram": "g", "grams": "g", "gm": "g", "gs": "g",
    "kilogram": "kg", "kilograms": "kg",
    "ounce": "oz", "ounces": "oz", "ozs": "oz",
    "pound": "lb", "pounds": "lb", "lbs": "lb",
    "milliliter": "ml", "millilitre": "ml", "milliliters": "ml", "mls": "ml",
    "liter": "l", "litre": "l", "liters": "l", "litres": "l",
    "teaspoon": "tsp", "teaspoons": "tsp", "tsps": "tsp", "t": "tsp",
    "tablespoon": "tbsp", "tablespoons": "tbsp", "tbsps": "tbsp",
    "tbl": "tbsp", "tbs": "tbsp", "T": "tbsp",
    "cups": "cup", "c": "cup",
    "fluid ounce": "fl oz", "fluid ounces": "fl oz", "floz": "fl oz",
    "quart": "qt", "quarts": "qt",
    "pint": "pt", "pints": "pt",
    "pieces": "piece", "pcs": "piece", "pc": "piece",
    "items": "item", "each": "item", "ea": "item", "whole": "item",
    "slices": "slice", "cloves": "clove", "leaves": "leaf",
    "packages": "package", "pkg": "package", "sticks": "stick",
    "bunches": "bunch", "cans": "can", "servings": "serving",
}

#: Fallback conversions for units USDA does not give per-food, used only
#: when a food has no matching entry of its own. Keyed by canonical unit.
#:
#: Volume-to-weight is food-specific — a cup of flour and a cup of honey
#: differ by more than a factor of two — so these are LAST resort and the
#: per-food table always wins. Water-equivalent density is the honest
#: default for the ones that remain, and it is right for most liquids.
#:
#: Deliberately absent: "item", "slice", "clove" and friends. There is no
#: general weight for one of something, so those resolve only from the
#: food's own table and otherwise return None. Guessing would be worse
#: than reporting the line as unresolved.
_GENERIC_UNIT_G: dict[str, float] = {
    "g": 1.0,
    "kg": 1000.0,
    "mg": 0.001,
    "oz": 28.3495,
    "lb": 453.592,
    "ml": 1.0,
    "l": 1000.0,
    "tsp": 4.93,
    "tbsp": 14.79,
    "cup": 240.0,
    "fl oz": 29.57,
    "pt": 473.18,
    "qt": 946.35,
}


def canonical_unit(unit: str | None) -> str:
    """Fold a unit to its canonical spelling. Unknown units pass through
    lowercased, so a food's own exotic measure ("pat (1\" sq)") still
    matches itself."""
    u = (unit or "").strip().lower().rstrip(".")
    return _UNIT_ALIASES.get(u, u)


@lru_cache(maxsize=1)
def catalog() -> list[dict[str, Any]]:
    """Every bundled food. Cached — the file is 3.3 MB and immutable."""
    try:
        with _DATA.open() as fh:
            return json.load(fh)
    except FileNotFoundError:
        log.warning("food catalog missing at %s", _DATA)
        return []


@lru_cache(maxsize=1)
def by_slug() -> dict[str, dict[str, Any]]:
    return {r["slug"]: r for r in catalog()}


#: Words marking a food as a processed or preserved FORM of the thing
#: searched for, rather than the thing itself.
#:
#: Without this, name-length tiebreaking hands the top slot to whichever
#: form happens to have the shortest description: "egg" answered "Egg,
#: yolk, dried" before "Egg, whole, raw, fresh", and "salmon" led with
#: breaded nuggets. Each of these words only counts against a food when
#: the user did NOT type it, so searching "dried egg" still finds it.
_PROCESSED_FORM_WORDS: frozenset[str] = frozenset({
    "dried", "dehydrated", "freeze-dried", "powder", "powdered",
    "breaded", "nuggets", "battered", "canned", "frozen", "instant",
    "imitation", "concentrate", "extract", "mix", "prepared",
    "restaurant", "sweetened", "creamed", "smoked", "cured",
})

_WORD_RE = re.compile(r"[a-z][a-z-]+")


def is_ingredient(row: dict[str, Any]) -> bool:
    return (row.get("category") or "") in INGREDIENT_CATEGORIES


def to_grams(
    quantity: float | None, unit: str | None, food: dict[str, Any] | None,
) -> float | None:
    """Convert a recipe or log quantity to grams, or None if it cannot.

    Returns None rather than guessing. A recipe line the app cannot cost
    must be reported as unresolved, not silently valued at zero — a
    nutrition total that quietly omits the olive oil is worse than one
    that says it is incomplete.

    Resolution order, most specific first:

    1. The food's OWN household measures, from USDA, compared after both
       sides are folded through `canonical_unit`. "cup" means 216 g for
       olive oil and 227 g for butter; there is no general answer, so
       this must win whenever it can.
    2. A prefix match against those, so a food that only lists
       "cup, chopped" still resolves when the user typed "cup".
    3. The generic table, which is only correct for mass units and for
       liquids near water density.
    """
    if quantity is None or quantity <= 0:
        return None
    u = canonical_unit(unit)
    if not u:
        return None

    per_unit = None
    if food:
        units = {canonical_unit(k): v for k, v in (food.get("unit_grams") or {}).items()}
        if u in units:
            per_unit = units[u]
        else:
            # Longest key first: "cup, chopped" and "cup, whole" are
            # different weights, and matching the shortest would pick one
            # arbitrarily. Sorting makes the choice at least stable.
            for k in sorted(units, key=len, reverse=True):
                if k.startswith(u) or u.startswith(k.split(",")[0].strip()):
                    per_unit = units[k]
                    break
    if per_unit is None:
        per_unit = _GENERIC_UNIT_G.get(u)
    if per_unit is None:
        return None
    return round(float(quantity) * float(per_unit), 2)


def nutrition_for(
    food: dict[str, Any] | None, grams: float | None,
) -> dict[str, float | None]:
    """Scale a food's per-100 g nutrition to a gram weight.

    A missing nutrient stays None through the multiply rather than
    becoming 0.0. That distinction survives all the way to the API,
    where a total built from rows with unknown sodium reports the sodium
    as unknown instead of understating it.
    """
    out: dict[str, float | None] = {c: None for c in NUTRIENT_COLUMNS}
    if not food or grams is None or grams <= 0:
        return out
    factor = grams / 100.0
    for col in NUTRIENT_COLUMNS:
        v = food.get(col)
        if v is not None:
            out[col] = round(float(v) * factor, 2)
    return out


def search(
    term: str, *, ingredients_only: bool = False, limit: int = 25,
) -> list[dict[str, Any]]:
    """Find foods by name, tolerating USDA's inverted naming.

    USDA writes names lead-noun-first: olive oil is "Oil, olive, salad or
    cooking", and spinach is "Spinach, raw". A plain substring search for
    what a person actually types therefore MISSES the food they want and
    surfaces whatever prepared dish happens to contain the phrase — a
    search for "olive oil" returned mayonnaise before this was fixed.

    So: every whitespace-separated term must appear as a whole word, in
    any order. Ranking is by the sum of where those terms land, which
    naturally floats the inverted form to the top ("Oil, olive, ..." puts
    both terms in the first ten characters; "Mayonnaise, reduced fat,
    with olive oil" puts them thirty characters in). Shorter names break
    ties, because the plainest form of a food has the shortest name.

    Whole-word matching also stops "oil" matching "boiled".
    """
    terms = [t for t in re.split(r"\s+", term.strip().lower()) if t]
    if not terms:
        return []
    # Two patterns per term. The whole-word form is what the user almost
    # always means; the prefix form is the fallback that still lets a
    # half-typed word match. Ranking whole-word matches strictly first is
    # what stops a search for "egg" answering "Eggnog" — both match as a
    # prefix, and Eggnog has the shorter name, so every other tiebreak
    # picks the wrong one.
    exact = [re.compile(r"\b" + re.escape(t) + r"\b") for t in terms]
    prefix = [re.compile(r"\b" + re.escape(t)) for t in terms]

    rows = catalog()
    if ingredients_only:
        rows = [r for r in rows if is_ingredient(r)]

    asked = set(terms)
    scored: list[tuple[int, int, int, int, str, dict[str, Any]]] = []
    for r in rows:
        name = r["name"].lower()
        positions: list[int] = []
        partials = 0
        for ex, pre in zip(exact, prefix):
            m = ex.search(name)
            if m is None:
                m = pre.search(name)
                if m is None:
                    break
                partials += 1
            positions.append(m.start())
        else:
            processed = sum(
                1 for w in _WORD_RE.findall(name)
                if w in _PROCESSED_FORM_WORDS and w not in asked
            )
            # Fewest partial matches, then fewest unrequested processed
            # forms, then earliest in the name (which floats USDA's
            # inverted "Oil, olive, ..." form to the top), then the
            # shortest name, which is the plainest form.
            scored.append(
                (partials, processed, sum(positions), len(r["name"]), r["name"], r),
            )

    scored.sort(key=lambda s: s[:5])
    return [s[5] for s in scored[:limit]]
