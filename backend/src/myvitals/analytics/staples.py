"""Kitchen staples — the things a recipe assumes you already have (MEAL-6).

Without this, "can I make this?" answers no to almost everything. Nearly
every savoury recipe lists salt, pepper, oil or water, so a strict
coverage test fails on ingredients nobody actually shops for per-recipe.
SuperCook and its peers all assume staples for exactly this reason.

The list is a DEFAULT, not a law. It lives here rather than in the
database so a fresh install behaves sensibly with an empty pantry, and
the user's own additions and removals are merged over it — someone who
genuinely has no oil in the house needs to be able to say so.

Deliberately short. Every entry is something that
  (a) essentially every kitchen has,
  (b) is bought on its own schedule rather than per recipe, and
  (c) contributes little enough to a meal's fat that assuming it does not
      distort the one number this app's medical constraint cares about.
Butter fails (c) and is NOT here, even though many kitchens always have
it — half a stick is 46 g of fat, which would silently vanish from a
per-meal total. Oil is borderline and is included only because recipes
list it constantly; when it is a main component the recipe names an
amount, and the shopping list still counts that amount.
"""

from __future__ import annotations

#: Concepts assumed present unless the user says otherwise. These are
#: CONCEPT strings (see `analytics/concepts.py`), not food names.
DEFAULT_STAPLES: frozenset[str] = frozenset({
    "salt",
    "black pepper",
    "pepper",
    "water",
    "olive oil",
    "vegetable oil",
    "sugar",
    "flour",
    "baking soda",
    "baking powder",
    "vinegar",
    "garlic powder",
    "onion powder",
})


def effective_staples(
    added: list[str] | None = None,
    removed: list[str] | None = None,
) -> set[str]:
    """The staple set after the user's own edits.

    `removed` wins over `added` and over the defaults, so a user can
    always take something out — which matters, because a wrongly assumed
    staple is invisible: the item silently never appears on a shopping
    list and you find out in the kitchen.
    """
    out = set(DEFAULT_STAPLES)
    out |= {s.strip().lower() for s in (added or []) if s and s.strip()}
    out -= {s.strip().lower() for s in (removed or []) if s and s.strip()}
    return out
