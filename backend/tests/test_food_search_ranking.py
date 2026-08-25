"""Which row a plain ingredient search lands on.

Every case here is one a person actually types while cooking, and every
one of them was wrong at some point. They are pinned as tests because
food search is the widest blast radius in the app: the row it picks is
the row that costs a recipe, a shopping list, a food-log entry and a prep
component, and it does so silently. A wrong row does not error — it
returns confident nutrition for a different food.

The failure that prompted this file: a prep component "Roasted sweet
potato" resolved to **Sweet potato leaves, raw**, a leafy green with
roughly half the calories of the tuber. Nothing flagged it. The
"null is not zero" discipline throughout the meals code protects against
a food that could not be found; it cannot protect against a food that was
found and is the wrong one.

The three rules being protected, in the order they apply:

1. A regular plural counts as a whole-word match. USDA names roots in the
   plural ("Beets, raw") and leaves in the singular ("Beet greens, raw"),
   so without this the greens score as an exact hit and the root as a
   mere prefix — and the stronger tier wins before anything else runs.
2. An unrequested word naming a DIFFERENT PART of the organism demotes
   the row. "Leaves" is a far stronger signal of "not what you asked for"
   than name length is.
3. Name length is measured with a trailing parenthetical stripped. USDA
   appends provenance notes that say nothing about the food and triple
   the length, which the length tiebreak reads as "more qualified".
"""
from __future__ import annotations

import pytest

from myvitals.analytics import foods as F


def top(term: str, *, ingredients_only: bool = True) -> str:
    hits = F.search(term, ingredients_only=ingredients_only, limit=1)
    assert hits, f"no result for {term!r}"
    return hits[0]["name"]


# ---------------------------------------- a different part of the plant


@pytest.mark.parametrize(
    "term,wanted,not_wanted",
    [
        ("sweet potato", "sweet potato,", "leaves"),
        ("beet", "beets,", "greens"),
        ("turnip", "turnips,", "greens"),
    ],
)
def test_a_root_search_does_not_return_the_leaves(term, wanted, not_wanted):
    """Roughly half the calories, silently substituted."""
    name = top(term).lower()
    assert name.startswith(wanted), name
    assert not_wanted not in name, name


def test_asking_for_the_leaves_still_finds_the_leaves():
    """Demotion applies only to words the user did NOT type. Otherwise
    the fix makes a real food unreachable, which is worse than the bug."""
    assert "leaves" in top("sweet potato leaves").lower()
    assert "greens" in top("beet greens").lower()


# ------------------------------------------------- plurals and provenance


@pytest.mark.parametrize(
    "term,prefix",
    [
        ("onion", "onions,"),
        ("carrot", "carrots,"),
        ("banana", "bananas,"),
        ("apple", "apples,"),
        ("potato", "potatoes,"),
    ],
)
def test_a_singular_search_matches_the_plural_usda_name(term, prefix):
    assert top(term).lower().startswith(prefix), top(term)


def test_a_provenance_note_does_not_demote_the_plainest_row():
    """"Sweet potato, raw, unprepared (Includes foods for USDA's Food
    Distribution Program)" is the plain raw tuber. The parenthetical is
    bookkeeping, and counting it as name length buried the row."""
    assert F._plainness("Apples, raw (Includes foods for USDA's X)") == len("Apples, raw")
    assert top("apple").lower().startswith("apples, raw")


# --------------------------------------------- derived and made dishes


@pytest.mark.parametrize(
    "term,not_wanted",
    [
        ("potato", "pancakes"),
        ("tomato", "sun-dried"),
        ("spinach", "souffle"),
    ],
)
def test_the_ingredient_beats_a_dish_made_from_it(term, not_wanted):
    assert not_wanted not in top(term).lower(), top(term)


def test_salad_is_not_a_demoted_word():
    """It appears in "Oil, olive, salad or cooking" — the correct answer
    for "olive oil", and the original bug this ranking exists to fix.
    Demoting the word would re-break the flagship case."""
    assert "salad" not in F._PROCESSED_FORM_WORDS
    assert top("olive oil") == "Oil, olive, salad or cooking"


# ------------------------------- the cases that were fixed before this


@pytest.mark.parametrize(
    "term,prefix",
    [
        # A substring search returned MAYONNAISE for this.
        ("olive oil", "oil, olive"),
        # A prefix-only match answered "Eggnog".
        ("egg", "egg,"),
        # Ranked breaded nuggets first.
        ("salmon", "fish, salmon"),
        # Unfindable until the ingredient tier existed.
        ("chicken breast", "chicken, broiler or fryers, breast"),
        # Filed under "Sweets", so it needs the unfiltered fallback.
        ("honey", "honey"),
        ("broccoli", "broccoli,"),
        ("greek yogurt", "yogurt, greek"),
        ("ground turkey", "turkey, ground"),
    ],
)
def test_previously_broken_staples_stay_fixed(term, prefix):
    assert top(term).lower().startswith(prefix), top(term)


def test_search_still_returns_nothing_for_an_empty_term():
    assert F.search("") == []
    assert F.search("   ") == []


# ------------------------------------- curated default variety (SEARCH-1)


def test_every_curated_preference_actually_lands():
    """The table is only worth its maintenance cost if each line works.

    A qualifier that does not discriminate is silently inert: the entry
    looks like a fix, the search returns the same wrong row, and nobody
    finds out. Assert the whole table end to end, in both lenses.
    """
    misses = []
    for term, wanted in F._PREFERRED_VARIETY.items():
        for lens in (True, False):
            hits = F.search(term, ingredients_only=lens, limit=1)
            name = hits[0]["name"].lower() if hits else "<no result>"
            if not any(w in name for w in wanted):
                misses.append(f"{term!r} (ingredients_only={lens}) -> {name}")
    assert not misses, "\n".join(misses)


@pytest.mark.parametrize(
    "term,expect",
    [
        # 37 vs 22 kcal/100 g, decided by an alphabetical coin flip.
        ("mushrooms", "mushrooms, white, raw"),
        # "Bacon, meatless" is not bacon.
        ("bacon", "pork, cured, bacon"),
        # Oil-packed is 198 kcal / 8.2 g fat; water-packed is 90.
        ("tuna", "canned in water"),
        # Wild Atlantic salmon is half the fat of the farmed fish sold.
        ("salmon", "atlantic, farmed"),
        # Plain "mustard" returned mustard SPINACH, a leafy green.
        ("mustard", "mustard, prepared"),
        # "lean only" silently trims a third of the fat off a steak.
        ("steak", "separable lean and fat"),
        # The plain hit was the low-sodium renal-diet product.
        ("baking powder", "double-acting"),
        # Yolk and white both beat "whole" on name length.
        ("egg", "egg, whole"),
        # The 365 kcal dry-milling grain outranked the vegetable.
        ("corn", "corn, sweet"),
        ("milk", "3.25% milkfat"),
        ("flour", "all-purpose"),
        ("sugar", "sugars, granulated"),
        ("almond", "nuts, almonds"),
    ],
)
def test_named_default_variety_cases(term, expect):
    assert expect in top(term).lower(), top(term)


def test_the_preference_tier_runs_before_the_demotion():
    """Placement is load-bearing, not cosmetic.

    Eight entries name a row the processed-form or part-word demotion is
    currently firing on — "prepared" mustard, "canned" tuna, "cured"
    bacon, salsa "sauce", kidney "seeds". Ranked after the demotion
    instead of before it, all eight would silently do nothing.
    """
    for term, expect in [
        ("mustard", "prepared"), ("tuna", "canned"), ("bacon", "cured"),
        ("salsa", "sauce"), ("kidney beans", "seeds"),
    ]:
        name = top(term).lower()
        assert expect in name, f"{term} -> {name}"


def test_a_preference_is_a_hint_not_a_filter():
    """If nothing matches the qualifier the tier must fall through, so a
    line that rots after a catalog rebuild stops helping rather than
    starting to hurt."""
    F._PREFERRED_VARIETY["broccoli"] = ("no-such-qualifier-anywhere",)
    try:
        assert top("broccoli") == "Broccoli, raw"
    finally:
        del F._PREFERRED_VARIETY["broccoli"]


def test_an_unlisted_term_is_completely_unaffected():
    assert "kale" not in F._PREFERRED_VARIETY
    assert top("kale") == "Kale, raw"


# --------------------------------------------- query aliases (SEARCH-1)


@pytest.mark.parametrize(
    "term,expect",
    [
        # These three returned ZERO rows. A tiebreak cannot help an empty
        # candidate set, and the quick-add staples list was offering
        # items that could never resolve.
        ("bell pepper", "peppers, sweet"),
        ("breadcrumbs", "bread, crumbs"),
        ("chilli powder", "chili powder"),
        # The herb is "Spearmint", and \bmint cannot match inside it, so
        # a recipe asking for mint got a NESTLE After Eight.
        ("mint", "spearmint"),
        # Regional spellings.
        ("courgette", "zucchini"),
        ("aubergine", "eggplant"),
        ("prawns", "shrimp"),
        ("yoghurt", "yogurt"),
        ("rocket", "arugula"),
        ("green onion", "scallions"),
    ],
)
def test_query_aliases_reach_the_catalogs_own_vocabulary(term, expect):
    assert expect in top(term).lower(), top(term)


def test_aliasing_is_whole_query_only():
    """Rewriting a substring of a longer phrase could corrupt a query
    that merely contains one of these words."""
    assert "mint" in F._QUERY_ALIASES
    # "peppermint tea" is not the bare word, so it must not be rewritten.
    assert F._QUERY_ALIASES.get("peppermint tea") is None


def test_every_alias_target_resolves():
    """An alias pointing at vocabulary the catalog does not have is worse
    than no alias: it replaces one empty result with another, and hides
    the original term in the process."""
    dead = [
        f"{k} -> {v}" for k, v in F._QUERY_ALIASES.items()
        if not F.search(v, limit=1)
    ]
    assert not dead, "\n".join(dead)


def test_the_curated_staples_list_still_resolves_end_to_end():
    """The pantry quick-add offers search TERMS, not ids, so an entry
    that stops resolving degrades to "not offered" — silently. This is
    the assertion that catches it."""
    from myvitals.analytics import common_pantry as CP

    dead = []
    for group, items in CP.COMMON_PANTRY.items():
        for _label, term in items:
            if not F.search(term, limit=1):
                dead.append(f"{group}: {term}")
    assert not dead, "\n".join(dead)


def test_water_is_not_a_leafy_green() -> None:
    """From a saved AI recipe, verbatim: an ingredient of "2 tbsp Water"
    was costed as 29.58 g of "Water convolvulus, raw" — water spinach.

    A ranking hint cannot fix this. `_resolve_food_term` tries the
    INGREDIENTS lens first, and in that lens bottled water is filtered
    out as a beverage before ranking runs, so the vegetable is the only
    candidate there is. The query itself has to change, which is what
    `_QUERY_ALIASES` is for.
    """
    from myvitals.analytics import foods
    assert foods.search("water", ingredients_only=True, limit=3) == [], \
        "the ingredients lens should offer no 'water' rather than a vegetable"
    top = foods.search("water", limit=1)
    assert top and "convolvulus" not in top[0]["name"].lower()
    assert top[0]["name"] == "Water, bottled, generic"
