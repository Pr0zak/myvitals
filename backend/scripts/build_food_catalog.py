#!/usr/bin/env python3
"""Build the bundled food catalog from USDA FoodData Central.

Run manually when refreshing the data; the OUTPUT is committed, not this
script's inputs. Mirrors how the exercise catalog already works — a
bundled public-domain dataset rather than a runtime API call, so the
feature works offline and does not depend on an external service staying
up.

    python backend/scripts/build_food_catalog.py \
        --foundation <foundation.json> --sr-legacy <sr_legacy.json> \
        --survey <surveyDownload.json> --branded <branded_food.zip> \
        --out backend/src/myvitals/data/foods.json

Needs `ijson` for --branded (the branded export is 3.3 GB and must be
streamed). It is not a runtime dependency; only this script uses it.

## Why four datasets

Foundation Foods (395 items, April 2026) is lab-analysed and current, and
carries `foodPortions` — the household-measure conversions that let a
recipe written in cups be costed in grams. But 395 foods does not cover a
kitchen; it has neither plain chicken breast nor olive oil in the form a
recipe means.

SR Legacy (~7,800 items, final 2018) has the coverage. It is not updated
any more, which matters far less for "how much fat is in an egg" than it
would for a branded product.

So: SR Legacy for breadth, Foundation preferred where both have the same
food, because it is newer and lab-analysed.

FNDDS (~5,400 items, 2024) covers prepared dishes — "chicken nuggets",
"pizza, cheese" — which neither of the above does well, and which is
what a food LOG needs rather than a recipe.

The branded export (453,000 items, 3.3 GB) is filtered hard to named
restaurant chains, keeping ~3,000. Roughly half this user's diet is
packaged or eaten out, and no other source has a Big Mac in it. The rest
of the branded set is supermarket packaging and stays out — it would
multiply the bundle by two orders of magnitude for items a barcode
scanner would serve better.

## Why so few nutrients

Twelve, plus portions. The app tracks calories, the macros, and the
nutrients its one medical constraint needs. A cholecystectomy makes
fat-per-meal the number that matters, and makes the four fat-soluble
vitamins (A, D, E, K) the ones most likely to run low, because absorbing
them depends on absorbing fat. USDA carries 119 nutrients per food;
keeping them all would multiply the bundle size for columns nothing
reads.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

#: USDA nutrient id -> our column. Ids are stable across releases; names
#: are not ("Energy" appears twice, in kcal and kJ).
NUTRIENTS: dict[int, str] = {
    1008: "kcal",            # Energy, kcal
    1003: "protein_g",
    1005: "carbs_g",         # Carbohydrate, by difference
    1004: "fat_g",           # Total lipid (fat)
    1258: "saturated_fat_g",
    1079: "fiber_g",
    2000: "sugar_g",         # Total sugars
    1093: "sodium_mg",
    # Fat-soluble vitamins (MEAL-2). These are carried because absorbing
    # them DEPENDS on absorbing fat, so a cholecystectomy makes them the
    # nutrients most likely to run low — which is exactly the thing a
    # macro-only tracker cannot see. Coverage in SR Legacy is partial
    # (A 89%, D 67%, E 72%, K 65%); the missing ones stay null rather
    # than zero, all the way to the UI.
    1106: "vitamin_a_ug",    # Vitamin A, RAE (ug)
    1114: "vitamin_d_ug",    # Vitamin D (D2 + D3) (ug)
    1109: "vitamin_e_mg",    # Vitamin E (alpha-tocopherol) (mg)
    1185: "vitamin_k_ug",    # Vitamin K (phylloquinone) (ug)
}

#: Categories carried into the bundle.
#:
#: This is deliberately broader than "things you cook with". The catalog
#: serves two pickers with opposite needs: a recipe wants "Pork, fresh,
#: loin", and a food LOG wants "Big Mac". Restricting the data to
#: ingredients would make the log useless for the roughly half of this
#: user's diet that is packaged or eaten out.
#:
#: The two views are separated downstream instead, by
#: `analytics/foods.py:INGREDIENT_CATEGORIES` — same rows, different lens.
#: Keep any new prepared-food category OUT of that set.
KEEP_CATEGORIES = {
    "Dairy and Egg Products", "Spices and Herbs", "Fats and Oils",
    "Poultry Products", "Soups, Sauces, and Gravies", "Sausages and Luncheon Meats",
    "Breakfast Cereals", "Fruits and Fruit Juices", "Pork Products",
    "Vegetables and Vegetable Products", "Nut and Seed Products",
    "Beef Products", "Beverages", "Finfish and Shellfish Products",
    "Legumes and Legume Products", "Lamb, Veal, and Game Products",
    "Baked Products", "Cereal Grains and Pasta",
    "Fast Foods", "Meals, Entrees, and Side Dishes",
    "Restaurant Foods", "Snacks", "Sweets",
}

#: Descriptions that are not food this user will ever log.
#:
#: Named restaurant chains USED to be listed here, on the reasoning that a
#: search for "chicken" should not return forty entrees before the plain
#: breast. That reasoning was right about the ranking problem and wrong
#: about the fix: the ranking is now handled properly in
#: `analytics/foods.py:search`, and dropping the data instead meant you
#: could not log lunch. Chains are kept.
#:
#: What remains is food for someone else entirely — infants, school meal
#: programmes, commodity distribution.
DROP_PATTERNS = re.compile(
    r"\b(baby food|infant formula|school lunch|USDA Commodity)\b",
    re.IGNORECASE,
)


def _slug(name: str, fdc_id: int) -> str:
    """Stable slug embedding the FDC id.

    The id is what makes a re-seed an UPDATE rather than a duplicate —
    USDA descriptions get reworded between releases, so a name-only slug
    would fork the row every time the wording changed.
    """
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:120]
    return f"{base}-{fdc_id}"


def _nutrients(food: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for entry in food.get("foodNutrients") or []:
        nut = entry.get("nutrient") or {}
        col = NUTRIENTS.get(nut.get("id"))
        if col is None:
            continue
        amount = entry.get("amount")
        if amount is None:
            continue
        try:
            out[col] = round(float(amount), 3)
        except (TypeError, ValueError):
            continue
    return out


def _portions(food: dict[str, Any]) -> dict[str, float]:
    """Household measure -> grams.

    Without these a recipe written in cups cannot be costed at all, and
    recipes are written in cups. Only sane conversions are kept: a
    zero-gram portion is a data error, and one over a kilogram is a whole
    joint of meat rather than a measure anyone writes in.
    """
    out: dict[str, float] = {}
    for p in food.get("foodPortions") or []:
        grams = p.get("gramWeight")
        if not grams or grams <= 0 or grams > 1000:
            continue

        # SR Legacy sets measureUnit.name to the literal string
        # "undetermined" on 7,533 of its foods and puts the real measure
        # in `modifier` ("cup, chopped", "tbsp", "serving"). Treating
        # "undetermined" as a unit name rather than as absent discarded
        # every household measure in the larger of the two datasets.
        unit = ""
        for candidate in (
            (p.get("measureUnit") or {}).get("name"),
            p.get("portionDescription"),
            p.get("modifier"),
        ):
            c = (candidate or "").strip().lower()
            if c and c not in {"undetermined", "quantity not specified"}:
                unit = c
                break
        if not unit:
            continue

        # gramWeight is the weight of `amount` of them, not of one. A row
        # reading amount=2, modifier="tbsp", gramWeight=30 means a
        # tablespoon is 15 g — taking gramWeight directly would double
        # every quantity written in that unit.
        try:
            amount = float(p.get("amount") or 1.0)
        except (TypeError, ValueError):
            amount = 1.0
        if amount <= 0:
            amount = 1.0
        per_unit = float(grams) / amount

        # The modifier is kept verbatim rather than trimmed to a bare
        # "cup": a cup of chopped spinach and a cup of whole leaves are
        # different weights, and collapsing them would silently pick one.
        unit = re.sub(r"^[\d./\s]+", "", unit)[:40].strip()
        if unit and unit not in out:
            out[unit] = round(per_unit, 2)
    return out


def _convert(food: Any, source_rank: int) -> dict[str, Any] | None:
    # The SR Legacy export contains null entries in its food array.
    if not isinstance(food, dict):
        return None
    name = (food.get("description") or "").strip()
    if not name or DROP_PATTERNS.search(name):
        return None

    cat = food.get("foodCategory")
    cat_name = cat.get("description") if isinstance(cat, dict) else cat
    if cat_name and KEEP_CATEGORIES and cat_name not in KEEP_CATEGORIES:
        return None

    nutrients = _nutrients(food)
    # A food with no energy figure cannot participate in any total this
    # app computes, so it is noise in a picker rather than a gap.
    if "kcal" not in nutrients:
        return None

    fdc_id = int(food.get("fdcId") or 0)
    row: dict[str, Any] = {
        "slug": _slug(name, fdc_id),
        "name": name,
        "category": cat_name,
        "_rank": source_rank,
        **nutrients,
    }
    portions = _portions(food)
    if portions:
        row["unit_grams"] = portions
    return row


# ------------------------------------------------- FNDDS (survey foods)

#: WWEIA categories that are prepared dishes worth logging. FNDDS is the
#: current, well-measured source for "what a plate of X contains", which
#: is exactly what a food log needs and what SR Legacy covers badly.
#: These all land as "Meals, Entrees, and Side Dishes" so they stay OUT
#: of the ingredient picker.
_SURVEY_KEEP = re.compile(
    r"mixed dish|sandwich|burger|pizza|taco|burrito|nachos|fries|"
    r"soup|salad|stew|casserole|lasagna|macaroni|fried|nuggets|wings",
    re.IGNORECASE,
)


def _convert_survey(food: Any, source_rank: int) -> dict[str, Any] | None:
    """FNDDS row -> catalog row.

    FNDDS keys its category as `wweiaFoodCategory`, not `foodCategory`,
    so it cannot share `_convert` — reading the wrong key would silently
    drop every row for failing the category filter.
    """
    if not isinstance(food, dict):
        return None
    name = (food.get("description") or "").strip()
    if not name or DROP_PATTERNS.search(name):
        return None

    wweia = food.get("wweiaFoodCategory") or {}
    cat = (wweia.get("wweiaFoodCategoryDescription") or "").strip()
    if not cat or not _SURVEY_KEEP.search(cat):
        return None

    nutrients = _nutrients(food)
    if "kcal" not in nutrients:
        return None

    fdc_id = int(food.get("fdcId") or 0)
    row: dict[str, Any] = {
        "slug": _slug(name, fdc_id),
        "name": name,
        "category": "Meals, Entrees, and Side Dishes",
        "_rank": source_rank,
        **nutrients,
    }
    portions = _portions(food)
    if portions:
        row["unit_grams"] = portions
    return row


# ------------------------------------------------ branded restaurant menus

#: Restaurant chains whose menu items are worth carrying.
#:
#: Two entries are deliberately more specific than the chain's short
#: name. "Domino" alone matches Domino Foods, which sells sugar; bare
#: "Firehouse" matched a company literally called S. F. Firehouse Station
#: 1 Inc. Both put ~110 supermarket items into the catalog.
#:
#: The branded dataset holds ~2 million items, almost all of them
#: supermarket packages. Filtering to chains is what keeps the bundle
#: small enough to commit while still answering "what did I eat for
#: lunch". Matched against `brandOwner` and `brandName`, case-insensitively.
RESTAURANT_BRANDS = re.compile(
    r"\b("
    r"mcdonald|burger king|wendy|taco bell|subway|kfc|kentucky fried|"
    r"chick-?fil-?a|pizza hut|domino'?s pizza|papa john|little caesar|arby|sonic|"
    r"popeye|dairy queen|chipotle|panera|starbucks|dunkin|jack in the box|"
    r"whataburger|five guys|culver|hardee|carl'?s jr|in-?n-?out|"
    r"raising cane|zaxby|bojangle|del taco|jimmy john|firehouse subs|"
    r"jersey mike|wingstop|church'?s chicken|long john silver|captain d|"
    r"cracker barrel|applebee|chili'?s|olive garden|red lobster|outback|"
    r"denny|ihop|waffle house|texas roadhouse|buffalo wild|panda express|"
    r"qdoba|moe'?s southwest|jason'?s deli|potbelly|quiznos|blimpie|"
    r"checkers|rally'?s|krystal|white castle|steak '?n shake|shake shack|"
    r"portillo|freddy'?s|schlotzsky|einstein bros|bruegger|"
    r"baskin-?robbins|cold stone|krispy kreme|cinnabon|auntie anne|"
    r"jamba|smoothie king|tropical smoothie|caribou coffee|peet'?s|"
    r"noodles & company|pei wei|p\.?f\.? chang|red robin|bj'?s restaurant|"
    r"cheesecake factory|longhorn steakhouse|golden corral|ruby tuesday|"
    r"o'?charley|logan'?s roadhouse|hooters|marco'?s pizza|"
    r"godfather'?s pizza|round table pizza|casey'?s|sbarro|"
    r"boston market|el pollo loco|pollo tropical|wienerschnitzel|"
    r"dave'?s hot chicken|slim chickens|hungry howie|jet'?s pizza"
    r")\b",
    re.IGNORECASE,
)

#: Branded rows whose descriptions are ALL CAPS get title-cased for
#: display. A picker full of SHOUTING is unreadable next to the sentence
#: case of every other source.
_CAPS = re.compile(r"[A-Z]")


def _tidy_branded_name(desc: str, brand: str) -> str:
    d = desc.strip().rstrip(",")
    letters = [c for c in d if c.isalpha()]
    if letters and sum(1 for c in letters if c.isupper()) / len(letters) > 0.8:
        d = d.title()
    # Descriptions repeat themselves ("CINNAMON, RAISIN, CINNAMON,
    # RAISIN") often enough to be worth collapsing.
    parts, seen = [], set()
    for part in [p.strip() for p in d.split(",")]:
        key = part.lower()
        if part and key not in seen:
            seen.add(key)
            parts.append(part)
    d = ", ".join(parts)
    brand = brand.strip().rstrip(",")
    if brand and brand.lower() not in d.lower():
        d = f"{d} ({brand})"
    return d[:250]


def _branded_portions(food: dict[str, Any]) -> dict[str, float]:
    """Serving size -> grams, from the label rather than a USDA measure.

    Branded rows have no `foodPortions`; they carry one serving size and
    a household description of it. That single conversion is what makes
    "one Big Mac" loggable, so without it a chain item can only be
    entered by weight, which nobody does.
    """
    out: dict[str, float] = {}
    try:
        grams = float(food.get("servingSize") or 0)
    except (TypeError, ValueError):
        return out
    unit = (food.get("servingSizeUnit") or "").strip().lower()
    # ml is only equal to grams for water-like liquids, but for a drink
    # that is the intended reading and the label gives nothing better.
    if grams <= 0 or grams > 2000 or unit not in {"g", "gm", "grm", "ml", "mlt"}:
        return out
    out["serving"] = round(grams, 2)

    household = (food.get("householdServingFullText") or "").strip().lower()
    m = re.match(r"^([\d.]+)\s*(?:/\s*(\d+))?\s*(.+)$", household)
    if m:
        try:
            qty = float(m.group(1))
            if m.group(2):
                qty = qty / float(m.group(2))
        except (TypeError, ValueError, ZeroDivisionError):
            qty = 0.0
        label = re.sub(r"[^a-z ]", "", m.group(3)).strip()[:40]
        if qty > 0 and label and label not in out:
            out[label] = round(grams / qty, 2)
    return out


def _convert_branded(food: Any, source_rank: int) -> dict[str, Any] | None:
    if not isinstance(food, dict):
        return None
    brand = (food.get("brandOwner") or food.get("brandName") or "").strip()
    desc = (food.get("description") or "").strip()
    if not desc:
        return None
    # Match the BRAND only, never the description. Matching both pulled in
    # every chipotle-flavoured supermarket product on the strength of the
    # word "chipotle" — McCormick seasoning, B&G sauces — because a flavour
    # name and a restaurant name are the same string. A chain is identified
    # by who owns the brand, not by a word in the product title.
    if not RESTAURANT_BRANDS.search(brand):
        return None
    if DROP_PATTERNS.search(desc):
        return None

    nutrients = _nutrients(food)
    if "kcal" not in nutrients:
        return None

    fdc_id = int(food.get("fdcId") or 0)
    name = _tidy_branded_name(desc, brand)
    row: dict[str, Any] = {
        "slug": _slug(name, fdc_id),
        "name": name,
        "category": "Fast Foods",
        "_rank": source_rank,
        **nutrients,
    }
    portions = _branded_portions(food)
    if portions:
        row["unit_grams"] = portions
    return row


def _load(path: Path) -> list[dict[str, Any]]:
    with path.open() as fh:
        data = json.load(fh)
    for value in data.values():
        if isinstance(value, list):
            return value
    return []


def _stream_branded(path: Path):
    """Yield branded rows one at a time.

    The branded export is 3.3 GB of JSON. `json.load` on it needs well
    over 10 GB of RAM, so this streams with ijson and never holds more
    than one record. The file is read straight out of the zip.
    """
    import zipfile

    import ijson  # optional dependency, only needed to refresh the bundle

    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            with z.open(z.namelist()[0]) as fh:
                yield from ijson.items(fh, "BrandedFoods.item")
    else:
        with path.open("rb") as fh:
            yield from ijson.items(fh, "BrandedFoods.item")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--foundation", type=Path)
    ap.add_argument("--sr-legacy", type=Path)
    ap.add_argument("--survey", type=Path, help="FNDDS surveyDownload.json")
    ap.add_argument(
        "--branded", type=Path,
        help="branded food export (.zip or .json); filtered to restaurant chains",
    )
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    rows: list[dict[str, Any]] = []
    # Source rank decides who wins a name collision, best first:
    #   0 Foundation  — newest, lab-analysed
    #   1 SR Legacy   — broadest ingredient coverage, final 2018
    #   2 FNDDS       — current prepared dishes
    #   3 Branded     — label data, least controlled, but the only place
    #                   a named chain menu item exists at all
    if args.foundation and args.foundation.exists():
        rows += [r for r in (_convert(f, 0) for f in _load(args.foundation)) if r]
        print(f"  foundation: {len(rows)}")
    if args.sr_legacy and args.sr_legacy.exists():
        before = len(rows)
        rows += [r for r in (_convert(f, 1) for f in _load(args.sr_legacy)) if r]
        print(f"  sr_legacy: {len(rows) - before}")
    if args.survey and args.survey.exists():
        before = len(rows)
        rows += [r for r in (_convert_survey(f, 2) for f in _load(args.survey)) if r]
        print(f"  survey (FNDDS): {len(rows) - before}")
    if args.branded and args.branded.exists():
        before = len(rows)
        scanned = 0
        for f in _stream_branded(args.branded):
            scanned += 1
            r = _convert_branded(f, 3)
            if r:
                rows.append(r)
        print(f"  branded: {len(rows) - before} kept from {scanned} scanned")

    # De-dupe on the normalised NAME rather than the slug: the same food
    # appears in several datasets under different fdc ids, and shipping
    # both would put two "Butter, salted" entries in every picker.
    best: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = re.sub(r"[^a-z0-9]+", " ", r["name"].lower()).strip()
        prev = best.get(key)
        if prev is None or r["_rank"] < prev["_rank"]:
            best[key] = r

    out = sorted(best.values(), key=lambda r: r["name"])
    for r in out:
        r.pop("_rank", None)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as fh:
        json.dump(out, fh, separators=(",", ":"), sort_keys=True)

    size_mb = args.out.stat().st_size / 1e6
    with_units = sum(1 for r in out if r.get("unit_grams"))
    print(f"{len(out)} foods -> {args.out} ({size_mb:.1f} MB)")
    print(f"  {with_units} carry household-measure conversions")


if __name__ == "__main__":
    main()
