"""Weekly component batch cooking — the deterministic half (MEAL-9).

The AI proposes *what* to cook and how to combine it. Everything numeric
— grams, calories, protein, fat, what is left in the fridge, what to buy
— is computed here from the food catalog. That division is the standing
rule in CLAUDE.md ("Nutrition is computed server-side, always"), and it
matters more here than anywhere else in the app: a meal plan is a wall of
numbers, and a wall of numbers a language model made up is worse than no
plan at all, because it looks exactly as authoritative as a real one.

## Why components rather than seven dinners

Conventional meal-prep apps hand you a grid of named meals, one per day.
The failure mode is well documented and is the reason most people quit in
week two: miss a day, eat out on Wednesday, and the grid is broken — the
Wednesday container is now a science experiment and Thursday's plan
assumed you had eaten it.

Component batch cooking inverts that. You cook four or five *parts* at
the weekend — a protein, a grain, a tray of roast vegetables, a sauce —
and assemble them into different meals through the week. A missed day
does not break anything; it leaves portions in the fridge, and the
`leftover_ledger` below turns that surplus into an explicit, actionable
statement rather than a silent drift away from the plan.

## The ledger is the flexibility feature

`leftover_ledger` is what makes "options and variables need to be
factored in" real rather than a slogan. It compares portions cooked
against portions actually consumed by non-skipped meals, so the app can
say "two portions of chicken unaccounted for — Thursday's bowl still
works on Saturday" instead of colouring the week red. Nothing in this
module treats a skipped or eaten-out meal as a failure; there is no
adherence score anywhere, deliberately.

## Slot shares are not renormalised

If a plan covers lunch and dinner only, those slots get their real share
of the day (0.30 + 0.35 = 0.65), not a rescale to 1.0. Renormalising
would prescribe a 1,150 kcal lunch to a man eating 2,295 a day, which is
both wrong and the kind of wrong that is hard to notice. What the plan
does not cover is reported as uncovered, and the client says so.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .foods import nutrition_for, to_grams

#: Typical share of a day's energy per meal slot. Round numbers on
#: purpose — these apportion a budget, they do not measure anything, and
#: a decimal place would imply a precision that is not there.
SLOT_SHARE: dict[str, float] = {
    "breakfast": 0.25,
    "lunch": 0.30,
    "dinner": 0.35,
    "snack": 0.10,
}

#: Order meals read in, on a day and on the prep sheet.
SLOT_ORDER: dict[str, int] = {"breakfast": 0, "lunch": 1, "dinner": 2, "snack": 3}

#: Batch-cook categories, ordered the way a prep session actually runs:
#: the protein and the grain go on first because they take longest, the
#: sauce is made while they cook.
COMPONENT_KINDS: tuple[str, ...] = ("protein", "grain", "veg", "sauce", "other")

KIND_ORDER: dict[str, int] = {k: i for i, k in enumerate(COMPONENT_KINDS)}

#: Statuses a planned meal can end in. `eating_out` and `skipped` are
#: first-class outcomes, not failures — see the module docstring.
MEAL_STATUSES: frozenset[str] = frozenset(
    {"suggested", "accepted", "eating_out", "skipped"},
)

#: A cooked batch is only good for so long. Used to warn when a plan
#: spreads one component across more days than it will keep.
FRIDGE_DAYS: dict[str, int] = {
    "protein": 4,
    "grain": 5,
    "veg": 5,
    "sauce": 7,
    "other": 5,
}


def slot_budgets(
    target_kcal: float | None,
    target_protein_g: float | None,
    slots: list[str],
) -> dict[str, Any]:
    """Per-slot energy and protein budgets for the slots a plan covers.

    Deliberately NOT renormalised — see the module docstring. The share
    of the day left uncovered is returned so the caller can say what the
    plan does not include instead of implying it covers everything.
    """
    wanted = [s for s in slots if s in SLOT_SHARE]
    if not wanted:
        wanted = ["lunch", "dinner"]
    covered = sum(SLOT_SHARE[s] for s in wanted)
    per_slot = {}
    for s in wanted:
        share = SLOT_SHARE[s]
        per_slot[s] = {
            "share": round(share, 2),
            "kcal": round(target_kcal * share) if target_kcal else None,
            "protein_g": (
                round(target_protein_g * share) if target_protein_g else None
            ),
        }
    return {
        "slots": wanted,
        "per_slot": per_slot,
        "covered_share": round(covered, 2),
        "uncovered_share": round(max(0.0, 1.0 - covered), 2),
        "uncovered_kcal": (
            round(target_kcal * max(0.0, 1.0 - covered)) if target_kcal else None
        ),
    }


def resolve_components(
    components: list[dict[str, Any]],
    foods: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach catalog nutrition and per-portion weight to each component.

    A component that cannot be costed — no matched food, or a unit that
    will not convert to grams — comes back with `unresolved: True` and
    null nutrition. It is never valued at zero. The same rule the recipe
    coster follows, for the same reason: a fat total that quietly omits
    the oil is worse than one that admits it is partial.
    """
    out: list[dict[str, Any]] = []
    for c in components:
        food = foods.get(c["food_id"]) if c.get("food_id") else None
        grams_total = to_grams(c.get("quantity"), c.get("unit"), food)
        portions = max(1, int(c.get("portions") or 1))
        grams_each = round(grams_total / portions, 1) if grams_total else None

        # Both halves are required. Grams without a food is a weight of
        # something unknown — the generic unit table happily turns "2
        # cup" into 480 g with no idea what is in the cup — and a food
        # without grams cannot be scaled. Either way there is no honest
        # nutrition figure, and the alternative to saying so is a plan
        # whose protein total silently assumes the wrong food.
        #
        # The two reasons are reported separately because they need
        # different fixes: pick a food, or state a convertible amount.
        if food is None:
            reason = "no food matched"
        elif grams_total is None:
            reason = "quantity will not convert to grams"
        else:
            reason = None

        per_portion = (
            nutrition_for(food, grams_each) if (reason is None and grams_each)
            else None
        )
        out.append({
            **c,
            "portions": portions,
            "grams_total": grams_total,
            "grams_per_portion": grams_each,
            "per_portion": per_portion,
            "unresolved": reason is not None,
            "unresolved_reason": reason,
        })
    return out


def cost_meal(
    uses: list[dict[str, Any]],
    by_id: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Sum one meal's nutrition from the components it draws on.

    `uses` is `[{component_id, portions}]`. A nutrient stays None unless
    at least one contributing component supplied it, matching
    `_sum_nutrition` in the recipe coster — a protein figure that
    silently drops the chicken would be actively misleading on a plan
    built around hitting a protein target.
    """
    totals: dict[str, float | None] = {}
    unresolved = 0
    used_g = 0.0
    for u in uses or []:
        comp = by_id.get(u.get("component_id"))
        if comp is None:
            unresolved += 1
            continue
        share = float(u.get("portions") or 1)
        if comp.get("unresolved") or not comp.get("per_portion"):
            unresolved += 1
            continue
        if comp.get("grams_per_portion"):
            used_g += comp["grams_per_portion"] * share
        for k, v in comp["per_portion"].items():
            if v is None:
                continue
            totals[k] = (totals.get(k) or 0.0) + v * share
    return {
        "nutrition": {k: round(v, 1) for k, v in totals.items()} or None,
        "grams": round(used_g, 1) if used_g else None,
        "unresolved_count": unresolved,
    }


def leftover_ledger(
    components: list[dict[str, Any]],
    meals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Portions cooked versus portions the live plan actually consumes.

    This is the feature that lets a week bend. A meal marked `skipped` or
    `eating_out` releases its portions back, so the app can say "two
    portions of chicken spare" and offer to move a meal rather than
    quietly leaving the user with food they did not plan for and a plan
    they have already broken.

    A negative `spare` is equally worth surfacing: the plan assigns more
    of a component than was cooked, which means a meal late in the week
    has nothing behind it.
    """
    used: dict[int, float] = defaultdict(float)
    for m in meals:
        if m.get("status") in ("skipped", "eating_out"):
            continue
        for u in m.get("uses") or []:
            cid = u.get("component_id")
            if cid is not None:
                used[cid] += float(u.get("portions") or 1)
    rows = []
    for c in components:
        cooked = float(c.get("portions") or 1)
        spent = used.get(c["id"], 0.0)
        rows.append({
            "component_id": c["id"],
            "name": c.get("name"),
            "kind": c.get("kind"),
            "portions_cooked": cooked,
            "portions_used": round(spent, 2),
            "spare": round(cooked - spent, 2),
            "short": spent > cooked + 0.001,
        })
    return rows


def keeps_until_warnings(
    components: list[dict[str, Any]],
    meals: list[dict[str, Any]],
    start_day: Any,
) -> list[str]:
    """Warn when a component is used later than a fridge will keep it.

    Cooked chicken is good for about four days. A plan that assigns it on
    day five is not a plan, it is a stomach ache — and it is exactly the
    kind of error a language model makes cheerfully, because the grid
    looks balanced.
    """
    last_day: dict[int, int] = {}
    for m in meals:
        if m.get("status") in ("skipped", "eating_out"):
            continue
        day = m.get("day")
        if day is None or start_day is None:
            continue
        offset = (day - start_day).days
        for u in m.get("uses") or []:
            cid = u.get("component_id")
            if cid is not None:
                last_day[cid] = max(last_day.get(cid, 0), offset)
    warnings = []
    for c in components:
        keeps = FRIDGE_DAYS.get(c.get("kind") or "other", 5)
        latest = last_day.get(c["id"])
        if latest is not None and latest >= keeps:
            warnings.append(
                f"{c.get('name')} is used on day {latest + 1}, past the "
                f"~{keeps} days cooked {c.get('kind') or 'food'} keeps in a "
                f"fridge. Freeze that portion on prep day, or move the meal "
                f"earlier."
            )
    return warnings


def component_shopping_lines(
    components: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Shape components into the line format `shopping.aggregate_needs` eats.

    Reusing that aggregator rather than writing a second one is what
    keeps the prep shopping list and the recipe shopping list agreeing
    about pantry subtraction, gram merging and the "some" fallback.
    """
    return [
        {
            "food_id": c.get("food_id"),
            "label": c.get("name") or "Unnamed",
            "quantity": c.get("quantity"),
            "unit": c.get("unit"),
            "grams": c.get("grams_total"),
            "multiplier": 1.0,
        }
        for c in components
    ]


def day_rollup(
    meals: list[dict[str, Any]],
    target_kcal: float | None,
    target_protein_g: float | None,
    budgets: dict[str, Any],
) -> list[dict[str, Any]]:
    """Per-day totals for the meals the plan covers.

    `planned_kcal` counts every meal that has not been skipped or eaten
    out, and is compared against the *covered* share of the day, never
    the whole day. A plan covering lunch and dinner is not 35% short of
    target; it simply does not include breakfast, and saying otherwise
    would nag the user about a gap the app created itself.
    """
    by_day: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for m in meals:
        by_day[m.get("day")].append(m)

    covered = budgets.get("covered_share") or 1.0
    day_kcal_budget = round(target_kcal * covered) if target_kcal else None
    day_protein_budget = (
        round(target_protein_g * covered) if target_protein_g else None
    )

    rows = []
    for day in sorted(k for k in by_day if k is not None):
        items = sorted(
            by_day[day], key=lambda m: SLOT_ORDER.get(m.get("slot") or "", 9),
        )
        live = [m for m in items if m.get("status") not in ("skipped", "eating_out")]
        kcal = sum(m.get("est_kcal") or 0 for m in live)
        protein = sum(m.get("est_protein_g") or 0 for m in live)
        fat = sum(m.get("est_fat_g") or 0 for m in live)
        rows.append({
            "day": day,
            "meals": items,
            "planned_kcal": round(kcal) if kcal else None,
            "planned_protein_g": round(protein) if protein else None,
            "planned_fat_g": round(fat, 1) if fat else None,
            "budget_kcal": day_kcal_budget,
            "budget_protein_g": day_protein_budget,
            "off_plan": len(items) - len(live),
        })
    return rows


#: Component kinds whose quantity may be scaled to reach an energy
#: target. Sauce is excluded deliberately: it is a condiment, its size
#: does not follow from how much energy the week needs, and for this
#: user fat per meal is a MEDICAL constraint after a cholecystectomy.
#: Uniformly tripling the olive oil to close a calorie gap would be the
#: single worst way to close it.
SCALABLE_KINDS: frozenset[str] = frozenset({"protein", "grain", "veg", "other"})

#: Ceiling on the multiplier. A plan needing more than this is wrong in
#: some way arithmetic will not fix, and quietly tripling a shopping list
#: is worse than saying so. The factor is CLAMPED to it rather than
#: abandoned, because getting a 28%-of-target week to 70% is still
#: unambiguously closer to what the user asked for than leaving it — and
#: the day totals still show the remaining gap.
MAX_ENERGY_SCALE = 2.5


def energy_scale_factor(
    components: list[dict[str, Any]],
    meals: list[dict[str, Any]],
    budget_kcal_per_day: float | None,
) -> float:
    """How much to grow the batches so the week lands near its budget.

    The model consistently undersizes batches — a 700 kcal dinner
    rendered as a chicken breast and 50 g of grain — and a plan at 40% of
    target does the opposite of what a weight-loss planner is for. Since
    every quantity is already the server's to compute, the honest repair
    is arithmetic rather than another prompt sentence.

    Only `SCALABLE_KINDS` move. The energy already coming from sauce is
    held out of both sides of the ratio, so the factor applies to what it
    is actually multiplying.

    Returns 1.0 — meaning leave it alone — when the plan is already at or
    above budget and when there is nothing to scale. Never scales DOWN: a
    rich week is visible in the day totals and is the user's call, while
    silently cutting food is how an app talks someone into under-eating.
    """
    if not budget_kcal_per_day or budget_kcal_per_day <= 0:
        return 1.0

    by_id = {c["id"]: c for c in components}
    days: set[Any] = set()
    planned = 0.0
    fixed = 0.0
    for m in meals:
        if m.get("status") in ("skipped", "eating_out"):
            continue
        days.add(m.get("day"))
        for u in m.get("uses") or []:
            comp = by_id.get(u.get("component_id"))
            if comp is None or comp.get("unresolved"):
                continue
            per = (comp.get("per_portion") or {}).get("kcal")
            if per is None:
                continue
            kcal = per * float(u.get("portions") or 1)
            planned += kcal
            if (comp.get("kind") or "other") not in SCALABLE_KINDS:
                fixed += kcal

    if not days or planned <= 0:
        return 1.0
    budget = budget_kcal_per_day * len(days)
    # Deadband on the TOTAL, which is the number the user reads. A 3%
    # shortfall is noise, and scaling for it would churn every shopping
    # quantity on each regenerate. Measuring the deadband on the scalable
    # part instead would trip on the same 3% whenever a sauce carries a
    # meaningful share of the energy.
    if planned >= budget * 0.95:
        return 1.0
    scalable = planned - fixed
    # Nothing scalable, or the fixed part alone already covers the
    # budget. Either way there is no honest multiplier.
    if scalable <= 0 or budget <= fixed:
        return 1.0

    factor = (budget - fixed) / scalable
    if factor <= 1.0:
        return 1.0
    return round(min(factor, MAX_ENERGY_SCALE), 3)
