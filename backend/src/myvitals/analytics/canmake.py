"""What can I cook right now? (MEAL-6)

The deterministic counterpart to the AI suggestion card. This one costs
nothing, runs offline, and answers a question the AI cannot: *which of my
own saved recipes can I make tonight.*

The core measure is the **ingredient coverage ratio** — matched over
required — which is what every app in this category ranks on. Two details
decide whether it is useful or infuriating:

**Staples are assumed present.** Nearly every savoury recipe lists salt,
pepper, oil or water, so a strict test answers "no" to almost everything.
See `analytics/staples.py` for what is assumed and, more importantly,
what is not (butter is not: half a stick is 46 g of fat, and silently
assuming it would distort the per-meal fat total this app exists to
track).

**Matching happens on CONCEPT, never on food id.** Raw and grilled
chicken breast are different USDA rows with genuinely different
nutrition, but they are one thing to have in the house. Matching on id
was the bug this module exists to fix.

The highest-value output is not the list of recipes you can already make
— if you could, you would know. It is **missing-by-one**: the recipes one
item away, and which item unlocks the most of them.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RecipeMatch:
    recipe_id: int
    name: str
    servings: int
    required: list[str] = field(default_factory=list)
    have: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    #: Lines with no concept at all — a hand-typed "splash of something".
    #: Counted as neither had nor missing, and reported, because guessing
    #: either way would make the ratio a lie.
    unknown: list[str] = field(default_factory=list)
    from_staples: list[str] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        """Matched over required. 1.0 means cookable now.

        Unknown lines are excluded from the denominator rather than
        counted as missing. A recipe with one unresolvable line should
        not be permanently stuck at 90% — the count is surfaced instead
        so the user can see why and fix the line.
        """
        n = len(self.required)
        if n == 0:
            return 0.0
        return len(self.have) / n

    @property
    def cookable(self) -> bool:
        """Everything needed is on hand AND every line was understood.

        An unresolvable line vetoes this. A recipe with "a splash of
        something" in it might be cookable, but the app cannot know, and
        claiming it is puts the least certain recipe at the TOP of the
        list — where it is most likely to be acted on. Those surface as
        `uncertain` instead, which says exactly what is wrong.
        """
        return bool(self.required) and not self.missing and not self.unknown

    @property
    def uncertain(self) -> bool:
        """Nothing is missing, but a line could not be identified."""
        return bool(self.unknown) and not self.missing


def match_recipes(
    recipes: list[dict[str, Any]],
    pantry_concepts: set[str],
    staples: set[str],
) -> list[RecipeMatch]:
    """Score every recipe against the pantry.

    `recipes` carry `id`, `name`, `servings` and `lines`, where each line
    has a `concept` (possibly None) and a `label` for display.

    Sorted cookable-first, then by coverage, then fewest missing — so the
    top of the list is always the most actionable thing.
    """
    out: list[RecipeMatch] = []
    for r in recipes:
        m = RecipeMatch(
            recipe_id=r["id"], name=r["name"], servings=r.get("servings", 1),
        )
        seen: set[str] = set()
        for line in r.get("lines") or []:
            concept = line.get("concept")
            label = line.get("label") or concept or "unnamed"
            if not concept:
                m.unknown.append(label)
                continue
            # A recipe listing the same concept twice (oil in the marinade
            # and oil in the pan) is ONE shopping decision.
            if concept in seen:
                continue
            seen.add(concept)
            m.required.append(concept)
            if concept in pantry_concepts:
                m.have.append(concept)
            elif concept in staples:
                m.have.append(concept)
                m.from_staples.append(concept)
            else:
                m.missing.append(label)
        out.append(m)

    # Cookable first, then near-misses by coverage, and only then the
    # uncertain ones — a recipe the app could not fully read must never
    # outrank one it verified.
    out.sort(key=lambda x: (
        not x.cookable, bool(x.unknown), -x.coverage, len(x.missing), x.name,
    ))
    return out


def unlock_ranking(
    matches: list[RecipeMatch], limit: int = 10,
) -> list[dict[str, Any]]:
    """Which single purchase unlocks the most recipes.

    This is the payoff of the whole module. Knowing you can cook three
    things is mildly useful; knowing that one packet of rice makes it
    seven is what changes a shopping trip.

    Only recipes missing EXACTLY one item contribute — an item that is
    one of three things a recipe still needs unlocks nothing on its own,
    and counting it would overstate the payoff.
    """
    counter: Counter[str] = Counter()
    unlocks: dict[str, list[str]] = {}
    for m in matches:
        # An unreadable line means buying the one missing item might
        # still not be enough, so it cannot be advertised as an unlock.
        if len(m.missing) != 1 or m.unknown:
            continue
        item = m.missing[0]
        counter[item] += 1
        unlocks.setdefault(item, []).append(m.name)

    return [
        {
            "item": item,
            "unlocks": n,
            "recipes": unlocks[item][:5],
        }
        for item, n in counter.most_common(limit)
    ]


def summarise(matches: list[RecipeMatch]) -> dict[str, Any]:
    """Headline counts for the top of the screen."""
    cookable = [m for m in matches if m.cookable]
    nearly = [m for m in matches if len(m.missing) == 1]
    uncertain = [m for m in matches if m.uncertain]
    return {
        "total_recipes": len(matches),
        "cookable_now": len(cookable),
        "missing_one": len(nearly),
        # Nothing missing, but a line could not be identified. Kept apart
        # from `cookable_now` so the headline count is one the user can
        # trust literally.
        "probably_cookable": len(uncertain),
        # Reported so an empty answer can distinguish "you have nothing"
        # from "your recipes have unresolvable ingredient lines".
        "recipes_with_unknown_lines": sum(1 for m in matches if m.unknown),
    }
