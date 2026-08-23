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
    # Added after a live report: searching the ingredients-only pantry
    # picker for "honey" returned nothing, because USDA files honey —
    # and sugar, syrup and cocoa — under "Sweets". They are unambiguously
    # things you cook with, and excluding a whole category to keep candy
    # bars out was the wrong trade: the search ranking already demotes
    # prepared forms, and a picker that cannot find sugar is broken.
    "Sweets",
    # Bread, tortillas and breadcrumbs are ingredients in their own
    # right, and this is where oats and breakfast grains live.
    "Baked Products", "Breakfast Cereals",
    # NOT "Sausages and Luncheon Meats". Adding it put deli chicken
    # breast, sliced fat-free chicken and rotisserie-seasoned chicken
    # ahead of raw chicken breast again — the exact regression this
    # picker was fixed for. Bacon and sausage are reachable anyway:
    # "Pork, cured, bacon" is filed under Pork Products.
})

#: Nutrient columns carried per 100 g. Every one is nullable downstream:
#: USDA does not have every nutrient for every food, and "unknown" must
#: stay distinguishable from "zero".
NUTRIENT_COLUMNS: tuple[str, ...] = (
    "kcal", "protein_g", "carbs_g", "fat_g",
    "saturated_fat_g", "fiber_g", "sugar_g", "sodium_mg",
    # Fat-soluble (MEAL-2). Absorbing these depends on absorbing fat, so
    # they are the nutrients a cholecystectomy puts at risk. USDA covers
    # them for 65-89% of foods; the rest stay null.
    "vitamin_a_ug", "vitamin_d_ug", "vitamin_e_mg", "vitamin_k_ug",
)

#: The subset that is fat-soluble, surfaced as awareness rather than as a
#: target. The app deliberately sets no RDA thresholds for these — see
#: `analytics/nutrition.py` for why it refuses to invent numbers.
FAT_SOLUBLE_COLUMNS: tuple[str, ...] = (
    "vitamin_a_ug", "vitamin_d_ug", "vitamin_e_mg", "vitamin_k_ug",
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
    # Derived forms. Each of these outranked the plain ingredient on
    # name length alone: "Potato flour" is shorter than "Potatoes, raw",
    # and "Tomatoes, sun-dried" shorter than "Tomatoes, red, ripe, raw".
    "sun-dried", "flour", "flakes", "syrup", "juice", "paste", "puree",
    "chips", "sauce", "soup", "bread", "meal",
    # Dishes MADE of the ingredient. USDA files several of these under
    # "Vegetables and Vegetable Products", so the ingredient tier does
    # not separate them and "Potato pancakes" outranked "Potatoes, raw".
    # "salad" is deliberately NOT here: it appears in "Oil, olive, salad
    # or cooking", which is the correct answer for "olive oil" and the
    # original bug this ranking exists to fix.
    "pancakes", "pancake", "fritters", "fritter", "croquettes",
})

#: Words naming a DIFFERENT PART of the same organism. An unrequested
#: one is a much stronger signal of "not what you asked for" than name
#: length is, and length alone gets it wrong: "Sweet potato leaves, raw"
#: is shorter than "Sweet potato, raw, unprepared", so a search for
#: "sweet potato" answered with a leafy green that has half the calories
#: of the tuber — and answered it silently, in the shopping list, the
#: recipe coster and the prep planner alike.
#:
#: Demotion only applies to words the user did NOT type, exactly as it
#: does for processed forms above, so searching "sweet potato leaves" or
#: "sunflower seeds" still finds them first.
_PART_WORDS: frozenset[str] = frozenset({
    "leaves", "leaf", "greens", "tops", "stems", "stalks", "sprouts",
    "shoots", "flowers", "blossoms", "seeds", "kernels", "hulls",
    "shells", "peel", "rind", "skins", "pods", "roots", "bran", "germ",
})

_WORD_RE = re.compile(r"[a-z][a-z-]+")

#: Words people type that the catalog does not use (SEARCH-1).
#:
#: The ranking tiers can only reorder candidates. When a query produces
#: NO candidates at all there is nothing to reorder, and no amount of
#: tiebreaking will help: USDA writes "Peppers, sweet", so "bell pepper"
#: matches nothing whatsoever, and the quick-add staples list has been
#: silently offering three items that could never resolve.
#:
#: Rewriting happens on the WHOLE query, before tokenising, and only on
#: an exact match — so this cannot corrupt a longer phrase that happens
#: to contain one of these words. Every mapping is a vocabulary
#: difference (regional spelling, or the shop's name for the thing versus
#: USDA's), never a change of food.
_QUERY_ALIASES: dict[str, str] = {
    # USDA files these under a name a shopper would not type.
    "bell pepper": "sweet pepper",
    "bell peppers": "sweet pepper",
    "breadcrumbs": "bread crumbs",
    "green onion": "scallions",
    "green onions": "scallions",
    "spring onion": "scallions",
    "spring onions": "scallions",
    # The herb is "Spearmint" in the catalog, and the search's whole-word
    # matcher cannot see "mint" inside it — so a recipe asking for mint
    # got a NESTLE After Eight.
    "mint": "spearmint",
    # British spellings. Harmless where the US form already works, and
    # the difference between a result and an empty list where it does not.
    "chilli": "chili",
    "chilli powder": "chili powder",
    "courgette": "zucchini",
    "courgettes": "zucchini",
    "aubergine": "eggplant",
    "aubergines": "eggplant",
    "prawn": "shrimp",
    "prawns": "shrimp",
    "yoghurt": "yogurt",
    "rocket": "arugula",
    "coriander leaves": "cilantro",
}

#: Which variety a bare ingredient name means (SEARCH-1).
#:
#: When a user types "mushrooms" the catalog offers enoki, morel, white,
#: oyster, maitake, shiitake, portabella and chanterelle. Every ranking
#: tier ties, so the winner is decided ALPHABETICALLY — a coin flip that
#: landed on enoki, at 37 kcal/100 g against white's 22. The row that wins
#: is the row that costs a recipe, a shopping list, a food-log entry and a
#: prep component, and it does so silently.
#:
#: There is no data-driven answer to "which variety did they mean", so
#: this is the same curated list `common_pantry.py` ships for the same
#: reason: it is what every app in this category does instead of
#: pretending the question has an algorithmic answer.
#:
#: A value is a tuple of lowercase SUBSTRINGS. A row scores better if its
#: name contains any of them. Substrings, not words, because several of
#: the discriminating qualifiers are phrases or numbers that no word
#: tokeniser produces — "atlantic, farmed", "canned in water", "3.25%".
#:
#: It is a TIEBREAK HINT, not a filter. If no row matches, the tier is a
#: no-op and ranking falls through unchanged. That is what keeps a rotted
#: entry harmless after a catalog rebuild: it stops helping rather than
#: starting to hurt.
#:
#: Every entry below was verified against the live catalog. Terms whose
#: current answer is already right are deliberately absent — each line
#: here is hand-maintained, so the table has to earn its size.
_PREFERRED_VARIETY: dict[str, tuple[str, ...]] = {
    # Nuts: the plain search hits the OIL first, which is a different food.
    "almond": ("nuts",),
    "almonds": ("nuts",),
    # Florida avocados are a third less fat than the Californian fruit US
    # shops actually sell; "all commercial varieties" is the honest row.
    "avocado": ("commercial",),
    "avocados": ("commercial",),
    # "Bacon, meatless" is not bacon.
    "bacon": ("cured",),
    # The plain hit is the low-sodium renal-diet product, ~100x off.
    "baking powder": ("double-acting",),
    "bread": ("commercially prepared",),
    "cheese": ("cheddar",),
    "cinnamon": ("spices",),
    # Otherwise the 365 kcal dry-milling grain outranks the vegetable.
    "corn": ("sweet",),
    # Yolk and white both beat "whole" on name length.
    "egg": ("whole",),
    "eggs": ("whole",),
    "flour": ("all-purpose",),
    "grape": ("seedless",),
    "grapes": ("seedless",),
    "ground beef": ("80%",),
    "hot sauce": ("ready-to-serve",),
    "kidney beans": ("red",),
    # USDA names the fruit "Lemons"; every impostor uses the singular.
    "lemon": ("lemons",),
    "mayonnaise": ("regular",),
    # NOT ("whole",) — that matches "Milk, buttermilk, fluid, whole",
    # which is shorter and wins. Only the fat percentage discriminates.
    "milk": ("3.25%",),
    "mozzarella": ("whole",),
    "mushroom": ("white",),
    "mushrooms": ("white",),
    # Plain "mustard" returns mustard SPINACH, a leafy green.
    "mustard": ("prepared",),
    "noodles": ("dry",),
    "parmesan": ("hard",),
    "potato": ("flesh",),
    "potatoes": ("flesh",),
    "quinoa": ("uncooked",),
    # NOT ("atlantic",) alone: that lands on the WILD row at half the fat
    # of the farmed fish a US shop sells. Under-reporting fat is the
    # failure direction this app cannot afford.
    "salmon": ("atlantic, farmed",),
    "salsa": ("ready-to-serve",),
    "sour cream": ("cultured",),
    # Pins the trim, not the cut. "lean only" silently trims a third of
    # the fat off every steak logged.
    "steak": ("lean and fat",),
    "sugar": ("granulated",),
    "tofu": ("magnesium chloride",),
    # NOT ("ripe",) — that matches the COOKED row, which is shorter.
    "tomato": ("year round",),
    "tomatoes": ("year round",),
    # NOT ("canned",) or ("light",): both land on the oil-packed row at
    # 198 kcal / 8.2 g fat against 90 kcal for water-packed.
    "tuna": ("canned in water",),
    "zucchini": ("summer",),
}



#: USDA appends provenance notes to some names — "Sweet potato, raw,
#: unprepared (Includes foods for USDA's Food Distribution Program)".
#: The note says nothing about the food, but it triples the name length,
#: and the length tiebreak reads a long name as a more qualified and
#: therefore less plain form. So the plainest raw sweet potato lost to
#: "Sweet potato leaves, raw" — a different plant with half the
#: calories, silently substituted into anything the user costed.
_PROVENANCE_RE = re.compile(r"\s*\([^)]*\)\s*$")


def _plainness(name: str) -> int:
    """Name length for tiebreaking, ignoring a trailing parenthetical.

    Length is a good proxy for "plainest form of this food" precisely
    because USDA qualifies with commas: "Broccoli, raw" beats "Broccoli,
    frozen, chopped, cooked, boiled, drained, without salt". A trailing
    provenance note carries no such qualification and must not count.
    """
    return len(_PROVENANCE_RE.sub("", name))


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
    # Rewrite the whole query first, so an alias feeds every tier below —
    # including the preferred-variety lookup, which is keyed on the
    # catalog's vocabulary rather than the user's.
    normalised = " ".join(term.strip().lower().split())
    normalised = _QUERY_ALIASES.get(normalised, normalised)
    terms = [t for t in re.split(r"\s+", normalised) if t]
    if not terms:
        return []
    # Two patterns per term. The whole-word form is what the user almost
    # always means; the prefix form is the fallback that still lets a
    # half-typed word match. Ranking whole-word matches strictly first is
    # what stops a search for "egg" answering "Eggnog" — both match as a
    # prefix, and Eggnog has the shorter name, so every other tiebreak
    # picks the wrong one.
    # A regular plural counts as a whole-word match. USDA names roots in
    # the plural and leaves in the singular — "Beets, raw" but "Beet
    # greens, raw" — so without this a search for "beet" scores the
    # greens as an exact hit and the root as a mere prefix, and the
    # stronger tier wins before the part-word demotion below ever runs.
    # You asked for a root vegetable and got a leafy green.
    exact = [
        re.compile(r"\b" + re.escape(t) + r"(?:e?s)?\b") for t in terms
    ]
    prefix = [re.compile(r"\b" + re.escape(t)) for t in terms]

    rows = catalog()
    if ingredients_only:
        rows = [r for r in rows if is_ingredient(r)]

    asked = set(terms)
    # Empty when the query has no curated default, which makes the
    # preference tier a no-op for every row rather than a filter.
    wanted_variety = _PREFERRED_VARIETY.get(" ".join(terms), ())
    scored: list[
        tuple[int, int, int, int, int, int, str, dict[str, Any]]
    ] = []
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
                if (w in _PROCESSED_FORM_WORDS or w in _PART_WORDS)
                and w not in asked
            )
            # Whole ingredients outrank prepared foods, even in the
            # unfiltered lens. Without this, a search for "chicken breast"
            # answers with deli roll and a White Castle sandwich, because
            # those put both terms in the first ten characters while USDA
            # spells the actual ingredient "Chicken, broiler or fryers,
            # breast, skinless, boneless, meat only, raw" — thirty
            # characters in and four times the length, so position and
            # name-length both push the right answer DOWN.
            #
            # This tier is a no-op whenever only one kind matches, so a
            # food log searching "big mac" is unaffected. It only reorders
            # when both an ingredient and a prepared dish match, which is
            # exactly when the ingredient is wanted.
            kind = 0 if is_ingredient(r) else 1
            # Curated default variety. Ranked BEFORE the processed-form
            # and part-word demotion, not after, and the placement is
            # load-bearing: eight of the entries name a row that the
            # demotion is currently firing on ("prepared" mustard,
            # "canned" tuna, "cured" bacon, salsa "sauce"). Placed after,
            # those entries would silently do nothing.
            preferred = 0 if any(w in name for w in wanted_variety) else 1
            # Fewest partial matches, then fewest unrequested processed
            # forms, then ingredients first, then earliest in the name
            # (which floats USDA's inverted "Oil, olive, ..." form to the
            # top), then the shortest name, which is the plainest form.
            scored.append(
                (partials, preferred, processed, kind, sum(positions),
                 _plainness(r["name"]), r["name"], r),
            )

    scored.sort(key=lambda s: s[:7])
    return [s[7] for s in scored[:limit]]
