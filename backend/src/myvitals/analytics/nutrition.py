"""Per-meal nutrition awareness (MEAL-2).

The point of this module is one number: **fat in a single meal**.

Why per-meal and not per-day. The gall bladder stores bile and releases
it as a bolus when a fatty meal arrives. Without one, bile drips
continuously into the small intestine instead, so the constraint is not
the daily total — it is how much fat turns up *at once*, with no
concentrated bile waiting for it. A day totalling 70 g spread across
four meals and a day where 60 g of it arrives at dinner are the same
daily number and completely different experiences. A tracker that only
shows the daily total cannot tell them apart, which is why this one does
not.

## The app does not invent a threshold

Tolerance after a cholecystectomy varies widely between people and
commonly improves over months, so any gram limit this code made up could
be wrong in either direction — and being wrong in the permissive
direction is the bad one. There is therefore no default.

Three sources of judgment, in order, and the module says which one it
used:

1. **A target the user entered**, ideally whatever a clinician actually
   said. Authoritative; nothing else overrides it.
2. **The user's own history**, when there is enough of it. A meal is
   flagged when it is high relative to what this person actually cooks,
   which needs no medical claim at all — it is a statement about their
   own data.
3. **Neither** — and then it REFUSES, with a reason the clients render,
   exactly like `analytics/projection.py` does when a goal cannot be
   honestly projected. Showing an unqualified "high in fat" with nothing
   behind it would be inventing the threshold by the back door.
"""

from __future__ import annotations

import statistics
from typing import Any

from .foods import FAT_SOLUBLE_COLUMNS, NUTRIENT_COLUMNS

#: Below this many comparison meals, the distribution is not a
#: distribution. Six is already thin; it is chosen as the point where a
#: median and a spread stop being actively misleading rather than the
#: point where they become good. `reason` always carries the count so the
#: user can judge for themselves.
MIN_HISTORY = 6

#: How far above the user's own median counts as "unusually high".
#: Deliberately a RATIO of their own habit, not a gram figure — the whole
#: reason this path needs no medical claim.
HIGH_RATIO = 1.5
VERY_HIGH_RATIO = 2.0

#: Fraction of an absolute user target that counts as approaching it.
NEAR_TARGET = 0.8


def _clean(values: list[float | None]) -> list[float]:
    return [v for v in values if v is not None]


def assess_meal_fat(
    fat_g: float | None,
    *,
    target_g: float | None = None,
    history_fat_g: list[float | None] | None = None,
) -> dict[str, Any]:
    """Judge one meal's fat load.

    Returns a dict carrying `verdict`, `basis` and `reason`. `verdict` is
    one of "unknown", "ok", "approaching", "high", "very_high", and
    `basis` names which of the three sources produced it, so the UI can
    say "against your 20 g target" rather than asserting a bare fact.

    A `verdict` of "unknown" is a first-class answer, not an error.
    """
    out: dict[str, Any] = {
        "fat_g": fat_g,
        "verdict": "unknown",
        "basis": "none",
        "reason": None,
        "target_g": target_g,
        "median_g": None,
        "comparison_meals": 0,
    }

    if fat_g is None:
        out["reason"] = (
            "This meal's fat could not be worked out — at least one "
            "ingredient has no nutrition data."
        )
        return out

    # 1. A user-entered target wins outright.
    if target_g is not None and target_g > 0:
        out["basis"] = "target"
        if fat_g >= target_g:
            out["verdict"] = "very_high" if fat_g >= target_g * 1.25 else "high"
        elif fat_g >= target_g * NEAR_TARGET:
            out["verdict"] = "approaching"
        else:
            out["verdict"] = "ok"
        out["reason"] = (
            f"{fat_g:.1f} g against your {target_g:g} g per-meal target."
        )
        return out

    # 2. Otherwise compare against what this person actually cooks. This
    #    is a claim about their own data and needs no medical basis.
    history = _clean(history_fat_g or [])
    if len(history) >= MIN_HISTORY:
        median = statistics.median(history)
        out["basis"] = "history"
        out["median_g"] = round(median, 1)
        out["comparison_meals"] = len(history)
        if median <= 0:
            out["verdict"] = "unknown"
            out["reason"] = (
                "Your other meals have no fat recorded, so there is "
                "nothing to compare this one against."
            )
            return out
        ratio = fat_g / median
        if ratio >= VERY_HIGH_RATIO:
            out["verdict"] = "very_high"
        elif ratio >= HIGH_RATIO:
            out["verdict"] = "high"
        elif ratio >= 1.2:
            out["verdict"] = "approaching"
        else:
            out["verdict"] = "ok"
        out["reason"] = (
            f"{fat_g:.1f} g, against a median of {median:.1f} g across "
            f"{len(history)} of your other meals."
        )
        return out

    # 3. Refuse. Say what would fix it.
    out["comparison_meals"] = len(history)
    out["reason"] = (
        f"No per-meal fat target set, and only {len(history)} other "
        f"recipe{'' if len(history) == 1 else 's'} to compare against "
        f"(needs {MIN_HISTORY}). This app does not guess a limit — "
        "tolerance after gall bladder removal varies a lot between "
        "people. Set a target in Meals settings, ideally the one your "
        "clinician gave you."
    )
    return out


def fat_soluble_summary(nutrition: dict[str, float | None]) -> dict[str, Any]:
    """Report the fat-soluble vitamins present in a meal.

    Awareness only — no targets, no percentages of anything. These
    vitamins are carried because absorbing them depends on absorbing
    fat, so they are the ones a cholecystectomy puts at risk; but this
    app has no business asserting an RDA, and USDA does not carry these
    for every food, so `missing` reports how much of the meal could not
    be accounted for.
    """
    present: dict[str, float] = {}
    missing: list[str] = []
    for col in FAT_SOLUBLE_COLUMNS:
        v = nutrition.get(col)
        if v is None:
            missing.append(col)
        else:
            present[col] = v
    return {
        "present": present,
        "missing": missing,
        # True when NOTHING is known, which is a different message from
        # "this meal contains none of them".
        "no_data": len(present) == 0,
    }


def energy_split(nutrition: dict[str, float | None]) -> dict[str, Any]:
    """Where a meal's calories come from, as a percentage of energy.

    Atwater factors: 4 kcal/g protein and carbohydrate, 9 kcal/g fat.
    Computed from the macros rather than read from `kcal`, and the two
    are reported side by side — a large gap between them means the
    macros are incomplete, which is worth seeing rather than hiding.

    Returns `None` percentages rather than zeros when a macro is
    unknown, so a meal missing its fat figure does not render as 0% fat.
    """
    protein = nutrition.get("protein_g")
    carbs = nutrition.get("carbs_g")
    fat = nutrition.get("fat_g")
    stated = nutrition.get("kcal")

    parts = {
        "protein": None if protein is None else protein * 4.0,
        "carbs": None if carbs is None else carbs * 4.0,
        "fat": None if fat is None else fat * 9.0,
    }
    known = [v for v in parts.values() if v is not None]
    derived = sum(known) if known else None

    pct: dict[str, float | None] = {k: None for k in parts}
    if derived and derived > 0:
        for k, v in parts.items():
            if v is not None:
                pct[k] = round(100.0 * v / derived, 1)

    return {
        "kcal_stated": stated,
        "kcal_from_macros": None if derived is None else round(derived, 1),
        "percent": pct,
        "incomplete": any(v is None for v in parts.values()),
    }


def per_serving(
    totals: dict[str, float | None], servings: int,
) -> dict[str, float | None]:
    """Divide whole-recipe totals by servings, keeping None as None."""
    n = max(servings, 1)
    return {
        k: (None if v is None else round(v / n, 2))
        for k, v in totals.items()
        if k in NUTRIENT_COLUMNS
    }
