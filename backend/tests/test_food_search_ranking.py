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
