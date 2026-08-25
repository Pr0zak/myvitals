"""Turn a meal plan into a shopping list (MEAL-3).

Plan minus pantry equals list. The subtraction happens here, server-side,
so the web and the phone cannot disagree about what to buy.

The whole module is shaped by one rule: **an item is never silently
dropped or silently reduced.** A shopping list that quietly omits
something sends the user home without it, and they find out while
cooking. So every case where the arithmetic cannot be done confidently
produces a flagged line rather than a missing one:

* An ingredient that cannot be converted to grams ("1 clove garlic")
  keeps its own units and is listed alongside the gram subtotal, not
  folded into it. There is no general weight for one clove.
* A pantry item with no quantity ("we have olive oil") cannot be
  subtracted. The item stays on the list at full amount, flagged as
  *you may already have this*, because "some, amount unknown" is not
  evidence of "enough".
* A pantry item whose unit will not convert is treated the same way.

The opposite choices — assuming a clove is 3 g, assuming an unmeasured
pantry item covers the need — are each a single line of code and each
produces a list that looks tidier and is wrong.
"""

from __future__ import annotations

import urllib.parse
from collections import defaultdict
from typing import Any

from .foods import canonical_unit, to_grams

#: Walmart per-item search. Tier 1 of the three approaches researched in
#: docs/MEALS_PLAN.md, and the only one that works without a partner
#: agreement: no auth, no API key, no Walmart item IDs.
#:
#: The server NEVER fetches this. A cart belongs to a logged-in browser
#: session, so only the user's own browser can act on it — the server's
#: job ends at producing the URL. That also sidesteps the Akamai bot
#: wall that a server-side fetch from this network hits.
WALMART_SEARCH = "https://www.walmart.com/search?q={q}"

#: Units big enough to be worth rendering a total in, largest first.
#: Below these the answer is just grams, which is what a scale shows.
_PREFERRED_UNITS = ("cup", "tbsp", "tsp")


#: Above this many of a unit, the unit is the wrong one to shop in.
#: A shopping list is read standing in an aisle: "19.4 cup" of broccoli
#: is arithmetically correct and completely unusable, because nobody
#: measures produce in cups at the shop and nobody can picture nineteen
#: of them. Ten is the point where a count stops being something you can
#: hold in your head and start needing a bigger unit.
_MAX_UNIT_COUNT = 10.0


def _fmt_qty(v: float) -> str:
    """Trim a quantity to SHOPPING precision, not arithmetic precision.

    A shopping list says "2 cup", not "2.0 cup", and "1.8 kg", not
    "1.7649999". Two decimals is false precision here: the amount is
    already an estimate of a plan, the packet sizes in the shop are
    whatever they are, and printing "3.04 kg" invites a care about the
    last digit that nothing downstream deserves.
    """
    r = round(v, 2)
    if abs(r - round(r)) < 0.05:
        return str(int(round(r)))
    # Ten or more of something: whole numbers. Below that one decimal is
    # the most that can matter when a bag is 500 g anyway.
    return str(int(round(r))) if r >= 10 else f"{round(r, 1):g}"


def humanise(grams: float, food: dict[str, Any] | None) -> str:
    """Render a gram total in whatever unit a person would shop in.

    Uses the food's OWN measures, so a cup means 216 g for olive oil and
    227 g for butter. Falls back to grams, which is never wrong — only
    less convenient.

    A unit has to fit from BOTH ends. The first version only checked that
    the total was at least one of the unit, so any large amount kept
    counting up in the smallest unit that qualified and a tray of
    broccoli was billed as "19.4 cup". A unit is used only while the
    count stays under [_MAX_UNIT_COUNT]; past that the next unit up is
    tried, and kilograms are the last resort — which is also what the
    scale in the produce aisle shows.
    """
    if grams <= 0:
        return "0 g"
    units = {canonical_unit(k): v for k, v in ((food or {}).get("unit_grams") or {}).items()}
    for name in _PREFERRED_UNITS:
        per = units.get(name)
        if per and per <= grams < per * _MAX_UNIT_COUNT:
            return f"{_fmt_qty(grams / per)} {name}"
    if grams >= 1000:
        return f"{_fmt_qty(grams / 1000)} kg"
    return f"{_fmt_qty(grams)} g"


class _Need:
    """Accumulated requirement for one food across the whole plan."""

    def __init__(self, label: str, food_id: int | None) -> None:
        self.label = label
        self.food_id = food_id
        self.grams = 0.0
        self.has_grams = False
        #: canonical unit -> quantity, for the lines that would not
        #: convert. Kept per-unit because "2 clove" and "1 cup" cannot be
        #: added together and pretending otherwise invents a number.
        self.loose: dict[str, float] = defaultdict(float)

    def add(self, quantity: float | None, unit: str | None, grams: float | None) -> None:
        if grams is not None:
            self.grams += grams
            self.has_grams = True
            return
        if quantity is None:
            # No quantity at all — the line still has to appear, so it is
            # recorded with an empty unit and rendered as "some".
            self.loose[""] += 0.0
            return
        self.loose[canonical_unit(unit) or ""] += quantity

    def loose_text(self) -> str | None:
        if not self.loose:
            return None
        parts = []
        for unit, qty in sorted(self.loose.items()):
            if qty <= 0:
                parts.append("some")
            elif unit:
                parts.append(f"{_fmt_qty(qty)} {unit}")
            else:
                parts.append(_fmt_qty(qty))
        return ", ".join(parts)


def aggregate_needs(lines: list[dict[str, Any]]) -> dict[str, _Need]:
    """Collapse every planned ingredient line into one need per food.

    `lines` carry `food_id`, `label`, `quantity`, `unit`, `grams` and a
    `multiplier` (the plan entry's servings over the recipe's servings).

    Keyed by food id where there is one, and by lower-cased label
    otherwise, so two hand-typed "olive oil" lines still merge while two
    genuinely different foods never do.
    """
    needs: dict[str, _Need] = {}
    for ln in lines:
        fid = ln.get("food_id")
        key = f"food:{fid}" if fid is not None else f"text:{(ln.get('label') or '').lower()}"
        need = needs.get(key)
        if need is None:
            need = _Need(ln.get("label") or "Unnamed", fid)
            needs[key] = need
        mult = float(ln.get("multiplier") or 1.0)
        grams = ln.get("grams")
        qty = ln.get("quantity")
        need.add(
            None if qty is None else qty * mult,
            ln.get("unit"),
            None if grams is None else grams * mult,
        )
    return needs


def subtract_pantry(
    need: _Need,
    pantry: list[dict[str, Any]],
    food: dict[str, Any] | None,
) -> dict[str, Any]:
    """Take what is already in the house off one requirement.

    Returns the shopping-list item shape. Subtraction only happens when
    BOTH sides are in grams. Anything else leaves the requirement intact
    and sets `pantry_uncertain`, because the alternative — assuming an
    unmeasured jar covers the need — is how a list ends up missing the
    one thing that was actually short.
    """
    covered = 0.0
    uncertain = False
    for p in pantry:
        qty = p.get("quantity")
        if qty is None:
            # "We have olive oil." True, useful, and not a number.
            uncertain = True
            continue
        g = to_grams(qty, p.get("unit"), food)
        if g is None:
            uncertain = True
            continue
        covered += g

    remaining = need.grams
    if need.has_grams and covered > 0:
        remaining = max(0.0, need.grams - covered)

    return {
        "food_id": need.food_id,
        "label": need.label,
        "grams": round(remaining, 2) if need.has_grams else None,
        "amount_text": need.loose_text(),
        "pantry_uncertain": uncertain,
        "pantry_covered_g": round(covered, 2) if covered > 0 else None,
        # Fully covered by a measured pantry amount, with nothing loose
        # left over. This is the ONLY case where a line may be dropped,
        # and it is safe because the arithmetic was complete.
        "fully_covered": (
            need.has_grams and remaining <= 0 and not need.loose and not uncertain
        ),
    }


def walmart_search_url(label: str) -> str:
    """Deep link to a Walmart search for one item.

    Tier 1 of docs/MEALS_PLAN.md. Deliberately a SEARCH rather than an
    add-to-cart: the add-to-cart endpoints are either deprecated and
    gated to Impact Radius publishers, or require a partner approval that
    is not obtainable for a single-user self-hosted install.

    The USDA name is trimmed to its lead noun before searching. "Oil,
    olive, salad or cooking" returns nothing useful on a retail site;
    "Oil olive" does.
    """
    head = label.split("(")[0]
    parts = [p.strip() for p in head.split(",") if p.strip()]
    # Two segments is enough to disambiguate ("Oil, olive") without
    # dragging in USDA's preparation qualifiers, which no shop indexes.
    query = " ".join(parts[:2]) if parts else head.strip()
    return WALMART_SEARCH.format(q=urllib.parse.quote_plus(query))
