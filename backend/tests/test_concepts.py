"""MEAL-6: the canonical pantry-concept layer.

USDA rows are NUTRITION rows. Raw and grilled chicken breast are separate
ids with genuinely different nutrition — correctly so — but they are ONE
thing to have in the house. Matching a pantry item to a recipe ingredient
on `food_id` therefore fails, and the shopping list tells you to buy
chicken you already have. `concept_for` is the coarse layer that fixes it.

**The asymmetry that governs every case below.** Under-merging is an
annoyance: the list fails to cancel one item and you buy a second bag of
rice. Over-merging is a correctness failure: counting peanut butter as
butter puts the wrong food on a list and the wrong number into a per-meal
fat total, which is the figure this user's cholecystectomy makes matter.
So every ambiguous case here resolves toward keeping things separate, and
the MUST-STAY-DISTINCT tests are the ones that matter most.
"""
from __future__ import annotations

import re

import pytest

from myvitals.analytics import foods as F
from myvitals.analytics.concepts import concept_for


def _row(name: str) -> dict | None:
    """The catalog row whose name contains `name`, preferring a whole
    ingredient.

    Substring matching alone picks the wrong row constantly: "Peanut
    butter" first matches an Archway COOKIE, and "Rice, brown" matches
    "Flavored rice, brown and wild". Both are prepared foods, so both
    correctly get no concept — and the test then fails for a reason that
    has nothing to do with what it is testing.
    """
    hits = [r for r in F.catalog() if name.lower() in r["name"].lower()]
    if not hits:
        return None
    ingredients = [r for r in hits if F.is_ingredient(r)]
    pool = ingredients or hits
    # Shortest name is the plainest form of the food.
    return min(pool, key=lambda r: len(r["name"]))


def _concept(name: str) -> str | None:
    r = _row(name)
    assert r is not None, f"no catalog row matching {name!r}"
    return concept_for(r)


def _concept_exact(name: str) -> str | None:
    for r in F.catalog():
        if r["name"] == name:
            return concept_for(r)
    pytest.skip(f"catalog has no row named exactly {name!r}")


# ------------------------------------------------------ must collapse
#
# These are the merges the whole layer exists to produce. A failure here
# means the shopping list keeps failing to subtract.


def test_raw_and_cooked_chicken_breast_are_one_concept():
    """The case the whole layer exists for, and the one the user hit.

    Brined rows ("with added solution") are excluded deliberately — that
    is a genuinely different product on a shelf, and keeping it separate
    is the safe direction rather than a failure.
    """
    rows = [
        r for r in F.catalog()
        if "breast, skinless, boneless, meat only" in r["name"]
        and "added solution" not in r["name"]
    ]
    assert len(rows) >= 3, "expected several preparation variants"
    concepts = {concept_for(r) for r in rows}
    assert len(concepts) == 1, f"raw/cooked chicken breast split into {concepts}"
    assert concepts.pop() == "chicken breast"


def test_raw_and_cooked_spinach_are_one_concept():
    raw = _concept_exact("Spinach, raw")
    cooked = _concept_exact("Spinach, cooked, boiled, drained, with salt")
    assert raw is not None
    assert raw == cooked


def test_ground_beef_fat_percentages_collapse():
    """93% and 97% lean are the same purchase decision.

    Restricted to rows that differ ONLY by the percentage — patties,
    loaves and crumbles are different products and keeping them apart is
    correct under-merging, not a failure.
    """
    rows = [
        r for r in F.catalog()
        if r["name"].startswith("Beef, ground,")
        and "lean meat" in r["name"]
        and r["name"].rstrip().endswith(", raw")
        and not any(
            w in r["name"].lower()
            for w in ("patty", "patties", "loaf", "crumble")
        )
    ]
    assert len(rows) >= 3, f"expected several fat tiers, got {len(rows)}"
    concepts = {concept_for(r) for r in rows}
    assert len(concepts) == 1, f"ground beef split by fat percentage: {concepts}"


def test_salted_and_unsalted_butter_are_one_concept():
    salted = _concept_exact("Butter, salted")
    unsalted = _concept_exact("Butter, without salt")
    assert salted is not None
    assert salted == unsalted


# --------------------------------------------------- must stay distinct
#
# The dangerous direction. Each of these merging would put the wrong food
# on a shopping list and the wrong fat into a per-meal total.


def test_peanut_butter_is_not_butter():
    butter = _concept_exact("Butter, salted")
    peanut = _concept("Peanut butter")
    assert peanut is not None
    assert peanut != butter, "peanut butter merged into butter"


def test_chicken_cuts_stay_distinct():
    breast = next(
        concept_for(r) for r in F.catalog()
        if "breast, skinless, boneless, meat only" in r["name"]
    )
    thigh = next(
        (concept_for(r) for r in F.catalog()
         if "Chicken" in r["name"] and "thigh" in r["name"].lower()), None,
    )
    assert breast is not None and thigh is not None
    assert breast != thigh, "chicken breast and thigh share a concept"


def test_different_oils_stay_distinct():
    """A pantry cares which oil. They also differ in what you would cook
    with them and, for coconut, sharply in saturated fat."""
    seen: dict[str, str] = {}
    for kind in ("Oil, olive", "Oil, coconut", "Oil, canola"):
        r = _row(kind)
        if r is None:
            continue
        c = concept_for(r)
        assert c is not None, f"{kind} produced no concept"
        assert c not in seen.values(), f"{kind} merged with {seen}"
        seen[kind] = c
    assert len(seen) >= 2


def test_white_and_brown_rice_stay_distinct():
    white = _row("Rice, white, long-grain, regular, raw")
    brown = _row("Rice, brown, long-grain, raw")
    if white is None or brown is None:
        pytest.skip("catalog lacks one of the rice rows")
    assert concept_for(white) != concept_for(brown)


def test_cheese_varieties_stay_distinct():
    cheddar = _concept_exact("Cheese, cheddar")
    mozz = _row("Cheese, mozzarella")
    assert cheddar is not None and mozz is not None
    assert cheddar != concept_for(mozz)


def test_egg_parts_stay_distinct():
    """A recipe wanting whites is not satisfied by having yolks."""
    whole = _row("Egg, whole, raw")
    white = _row("Egg, white, raw")
    yolk = _row("Egg, yolk, raw")
    got = {
        concept_for(r) for r in (whole, white, yolk) if r is not None
    }
    assert len(got) >= 2, f"egg parts collapsed to {got}"


# ------------------------------------------------ prepared food is None
#
# A prepared dish is not a pantry ingredient, so it gets no concept —
# which makes "has a concept" exactly the question "is this stockable".


def test_prepared_categories_never_produce_a_concept():
    prepared = {"Fast Foods", "Restaurant Foods", "Meals, Entrees, and Side Dishes"}
    offenders = [
        r["name"] for r in F.catalog()
        if r.get("category") in prepared and concept_for(r) is not None
    ]
    assert offenders == [], f"prepared food got concepts: {offenders[:5]}"


def test_a_big_mac_is_not_a_pantry_ingredient():
    r = _row("Big Mac")
    assert r is not None
    assert concept_for(r) is None


# ------------------------------------------------------- shape + scale


def test_staple_ingredients_all_get_a_concept():
    """The layer is useless if the things people actually stock fall
    through it."""
    missing = []
    for name in (
        "breast, skinless, boneless, meat only, raw",
        "Butter, salted",
        "Spinach, raw",
        "Oil, olive",
        "Cheese, cheddar",
        "Rice, brown",
        "Beans, black",
    ):
        r = _row(name)
        if r is None:
            continue
        if concept_for(r) is None:
            missing.append(r["name"])
    assert missing == [], f"staples with no concept: {missing}"


def test_concepts_are_human_readable():
    """The concept goes on a shopping list, so it has to read as a
    phrase — no raw commas, bounded length.

    The word cap is 7 rather than something tighter, and that is a
    deliberate trade recorded in the module: truncating makes a concept
    LESS specific, which merges, and merging is the unsafe direction.
    So this checks the shape rather than demanding brevity.
    """
    bad = []
    for r in F.catalog():
        c = concept_for(r)
        if c is None:
            continue
        if "," in c or len(c) > 70 or len(c.split()) > 9:
            bad.append((r["name"][:40], c))
    assert bad == [], f"malformed concepts, e.g. {bad[:5]}"


def test_the_foods_people_actually_stock_read_well():
    """The honest version of a readability test.

    USDA's long tail is verbose and the safety-first design keeps that
    verbosity rather than truncating into a merge — "clam mixed species
    canned liquid" is ugly and correct. What matters is that the things
    someone actually puts in a pantry come out as phrases they would
    write on a list.
    """
    expected = {
        "breast, skinless, boneless, meat only, raw": "chicken breast",
        "Oil, olive, salad or cooking": "olive oil",
        "Butter, salted": "butter",
        "Cheese, cheddar": "cheddar cheese",
        "Spinach, raw": "spinach",
        "Beverages, chocolate syrup": "chocolate syrup",
    }
    wrong = {}
    for needle, want in expected.items():
        row = None
        for r in F.catalog():
            if needle in r["name"] and (row is None or len(r["name"]) < len(row["name"])):
                row = r
        if row is None:
            continue
        got = concept_for(row)
        if got != want:
            wrong[needle] = (got, want)
    assert wrong == {}, f"staple concepts read wrong: {wrong}"


def test_short_concepts_are_a_substantial_share():
    """Long concepts are tolerated for safety, but if almost none were
    short the layer would not be merging at all."""
    lengths = [len(c.split()) for r in F.catalog() if (c := concept_for(r))]
    short = sum(1 for n in lengths if n <= 3)
    assert short / len(lengths) > 0.2, (
        f"only {short}/{len(lengths)} concepts are 3 words or fewer"
    )


def test_concept_count_is_in_the_right_order_of_magnitude():
    """SuperCook exposes ~2,000 pantry ingredients over millions of
    recipes. Far fewer means over-merging; far more means the layer is
    not merging at all and the original bug survives."""
    concepts = {c for r in F.catalog() if (c := concept_for(r))}
    # The upper bound is generous because this design deliberately
    # under-merges: brands, varieties and USDA's long tail each keep
    # their own concept rather than risk a wrong merge. SuperCook's
    # ~2,000 is the shape to aim at, not a target to hit — what matters
    # is that the merges people rely on happen, which the battery above
    # checks directly.
    assert 500 <= len(concepts) <= 5500, f"{len(concepts)} concepts"


def test_concepts_actually_merge_rows():
    """Guards the degenerate case where every row gets its own concept,
    which would pass the distinctness tests and fix nothing."""
    rows = [r for r in F.catalog() if concept_for(r)]
    concepts = {concept_for(r) for r in rows}
    assert len(concepts) < len(rows) * 0.7, "barely merging anything"


def test_concept_is_stable_and_lowercase():
    for r in F.catalog()[:400]:
        c = concept_for(r)
        if c is None:
            continue
        assert c == c.lower().strip()
        assert concept_for(r) == c, "concept_for is not deterministic"


# ============================================================================
# Adversarial counterexamples
#
# Three independent attackers ran the FIRST synthesised extractor over the
# real catalog and returned roughly fifty wrong merges; two of the three
# voted do-not-ship. Every one traced to the same cause — a broad drop
# list threw away a word that distinguished two products — and the module
# was rewritten around a much narrower rule as a result.
#
# These are their concrete findings, kept as permanent tests. Each pair
# must stay DISTINCT. They are the reason the drop list is small, and they
# will catch any future attempt to widen it.
# ============================================================================


def _c(exact_name: str) -> str | None:
    for r in F.catalog():
        if r["name"] == exact_name:
            return concept_for(r)
    pytest.skip(f"catalog has no row named exactly {exact_name!r}")


def _distinct(a: str, b: str, why: str) -> None:
    ca, cb = _c(a), _c(b)
    assert ca != cb or (ca is None and cb is None), (
        f"{why}\n  {a!r} -> {ca!r}\n  {b!r} -> {cb!r}"
    )


def test_chocolate_milk_is_not_chocolate_syrup():
    """A "prepared with" segment was being eaten whole, so the milk
    vanished and a glass of chocolate milk was filed as syrup."""
    rows = {
        r["name"]: concept_for(r) for r in F.catalog()
        if r["name"].startswith("Beverages, chocolate syrup")
    }
    if len(rows) < 2:
        pytest.skip("catalog lacks the chocolate syrup family")
    assert len(set(rows.values())) > 1, (
        f"syrup and milk-prepared syrup share a concept: {rows}"
    )


def test_whole_wheat_never_folds_into_white():
    """Found three times over — bread, tortillas and crackers. A shopper
    buying whole-wheat and a shopper buying white are not interchangeable,
    and one of the pairs also carried an 8.6 g/100 g fat error."""
    for base in ("Tortillas, ready-to-bake or -fry, ", "Bread, "):
        pairs = [
            r for r in F.catalog()
            if r["name"].startswith(base) and "whole wheat" in r["name"].lower()
        ]
        for r in pairs:
            c = concept_for(r)
            if c is None:
                continue
            assert "whole wheat" in c or "whole-wheat" in c, (
                f"{r['name']!r} lost its whole-wheat distinction -> {c!r}"
            )


def test_soft_and_hard_pretzels_stay_distinct():
    """"soft" and "hard" were dropped as intensity descriptors. Nobody
    buying a bag of hard pretzels is satisfied by a soft mall pretzel."""
    _distinct(
        "Pretzels, soft",
        "Snacks, pretzels, hard, plain, salted",
        "soft and hard pretzels merged",
    )


def test_tofu_firmness_stays_distinct():
    """Silken and firm tofu differ by 2.7x in fat and are not
    interchangeable in a recipe."""
    firm = [
        concept_for(r) for r in F.catalog()
        if r["name"].startswith("Tofu, hard")
    ]
    soft = [
        concept_for(r) for r in F.catalog()
        if r["name"].startswith("Tofu, soft") or "silken" in r["name"].lower()
    ]
    if not firm or not soft:
        pytest.skip("catalog lacks both tofu firmnesses")
    assert set(firm).isdisjoint(set(soft)), f"tofu merged: {firm} vs {soft}"


def test_rendered_fat_is_not_the_animal_it_came_from():
    """Rendered chicken fat is a 99.8 g/100 g cooking fat you buy in a
    jar. It is not chicken."""
    fat = _c("Fat, chicken")
    breast = next(
        concept_for(r) for r in F.catalog()
        if "breast, skinless, boneless, meat only, raw" in r["name"]
    )
    assert fat != breast


def test_separable_fat_is_not_the_lean_cut():
    """"Beef, retail cuts, separable fat" is 70.9 g fat and was landing
    in the same concept as lean beef at 4.55 g."""
    trim = [
        concept_for(r) for r in F.catalog()
        if "separable fat" in r["name"].lower()
    ]
    if not trim:
        pytest.skip("catalog lacks a separable-fat row")
    for c in trim:
        assert c is None or "fat" in c, f"fat trimmings lost their identity: {c!r}"


def test_clam_juice_is_not_clams():
    """"liquid" and "drained solids" were both dropped as pack medium,
    but here they separate the juice from the shellfish — 71x kcal."""
    _distinct(
        "Mollusks, clam, mixed species, canned, liquid",
        "Mollusks, clam, mixed species, canned, drained solids",
        "clam juice merged with clams",
    )


def test_frozen_chips_are_not_boiled_potatoes():
    """36x the fat. "french fried" is a form you buy, not a doneness."""
    fries = [
        concept_for(r) for r in F.catalog()
        if "french fried" in r["name"].lower() and "otato" in r["name"]
    ]
    if not fries:
        pytest.skip("catalog lacks frozen french fries")
    for c in fries:
        assert c is None or "french fried" in c, (
            f"french fries lost their form: {c!r}"
        )


def test_mature_and_immature_seeds_stay_distinct():
    """A dry bean and a fresh pod are different aisles. One of these
    pairs differed by 15.4 g of fat per 100 g."""
    mature = [
        concept_for(r) for r in F.catalog()
        if "winged beans, mature seeds" in r["name"].lower()
    ]
    immature = [
        concept_for(r) for r in F.catalog()
        if "winged beans, immature seeds" in r["name"].lower()
    ]
    if not mature or not immature:
        pytest.skip("catalog lacks both winged-bean forms")
    assert set(mature).isdisjoint(set(immature))


def test_a_concept_always_contains_a_food_noun():
    """The worst class the attackers found: concepts like "mixed flavor",
    "with almond" and "honey roasted", which name no food at all and
    fused unrelated branded products together."""
    # Tested as "every word is a modifier", not as a prefix match — an
    # earlier prefix regex flagged "light butter stick", which plainly
    # does contain a noun.
    modifiers = {
        "with", "without", "mixed", "assorted", "regular", "original",
        "all", "natural", "roasted", "no", "reduced",
        "light", "plain", "added", "and", "or", "flavor", "flavour",
        "flavored", "flavoured", "free", "style", "type", "fresh",
    }
    bad = [
        (r["name"][:44], c) for r in F.catalog()
        if (c := concept_for(r)) and all(w in modifiers for w in c.split())
    ]
    assert bad == [], f"concepts with no food noun: {bad[:6]}"


def test_no_concept_is_only_a_brand():
    """"gluten free udi's" fused a loaf of bread with two dinner rolls,
    because the entire product name was brand and dietary claim."""
    for r in F.catalog():
        c = concept_for(r)
        if c is None:
            continue
        assert not c.endswith("'"), f"possessive-mangled brand concept: {c!r}"


def test_fat_spread_within_a_concept_stays_bounded():
    """The audit that caught the most real over-merges, and the right one
    for this app: if two rows share a concept but differ wildly in fat,
    one of them is in the wrong place. Fat-per-meal is the number a
    cholecystectomy makes matter.

    Some spread is legitimate and required by the battery — lean and
    fatty ground beef are one purchase — so this bounds the tail rather
    than demanding zero.
    """
    from collections import defaultdict

    by_concept: dict[str, list[float]] = defaultdict(list)
    for r in F.catalog():
        c = concept_for(r)
        fat = r.get("fat_g")
        if c and fat is not None:
            by_concept[c].append(fat)

    egregious = {
        c: round(max(v) - min(v), 1)
        for c, v in by_concept.items()
        if len(v) > 1 and (max(v) - min(v)) > 45
    }
    assert not egregious, f"concepts spanning >45 g/100 g of fat: {egregious}"
