"""Daily energy and protein targets (MEAL-9).

Every number here is an ESTIMATE from an equation, and the module says
so in the payload rather than leaving the client to imply certainty. The
honest version of this — TDEE derived from observed intake against
observed weight change — needs weeks of complete food logs, which do not
exist yet. See `docs/MEALS_PLAN.md` phase 8; when they do exist, that
derivation replaces the equation here and the `basis` field changes to
say so.

## Why Mifflin-St Jeor

It is the equation with the best measured accuracy for non-athletic
adults, and it needs only height, weight, age and sex — all of which the
profile already carries. Harris-Benedict overestimates for people with
more body fat, which is exactly the population using a weight-loss
target, so using it here would set the deficit too small.

## Why protein is scaled to GOAL weight

Protein requirement tracks lean mass, not total mass. Someone 24 kg above
their goal does not need protein for the fat they are carrying, and
scaling to current weight inflates the target by roughly a quarter. Goal
weight is the closer proxy, and it is the convention in the literature
for people with significant fat to lose.

The range is deliberately 1.6-2.0 g/kg. Below about 1.6 a calorie
deficit costs lean mass; above about 2.2 there is no further measured
benefit. Strength training moves you toward the top of the band, which
is why `training_load` shifts it.
"""

from __future__ import annotations

from datetime import date
from typing import Any

#: Activity multipliers on BMR. The gap between "light" and "moderate" is
#: about 400 kcal for this user, which is most of a deficit — so the
#: value is taken from the profile rather than assumed, and the payload
#: names which one was used.
ACTIVITY_FACTORS: dict[str, float] = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "athlete": 1.9,
}

#: Kilocalories in a kilogram of body fat. The standard 7,700 figure.
#: Used only to translate a deficit into an expected rate, never to
#: promise one — actual rate varies with water, glycogen and adherence.
KCAL_PER_KG_FAT = 7700.0

#: The deficit a weight-loss target uses, and the floor it will not go
#: below. 500 kcal/day is ~0.45 kg/week, which is the rate that most
#: reliably preserves lean mass while lifting.
DEFAULT_DEFICIT_KCAL = 500.0

#: Never prescribe below this, whatever the arithmetic says. A target
#: under about 1,500 kcal for an adult male is where adherence collapses
#: and lean-mass loss accelerates, and an app should not quietly walk
#: someone into it because a goal date was ambitious.
MIN_MALE_KCAL = 1500.0
MIN_FEMALE_KCAL = 1200.0


def _age(birth: date | None, today: date) -> int | None:
    if not birth:
        return None
    return today.year - birth.year - (
        (today.month, today.day) < (birth.month, birth.day)
    )


def bmr_mifflin(
    weight_kg: float, height_cm: float, age: int, sex: str,
) -> float:
    """Mifflin-St Jeor resting metabolic rate."""
    base = 10.0 * weight_kg + 6.25 * height_cm - 5.0 * age
    return base + (5.0 if (sex or "").lower().startswith("m") else -161.0)


def compute_targets(
    *,
    weight_kg: float | None,
    height_cm: float | None,
    birth_date: date | None,
    sex: str | None,
    activity_level: str | None,
    goal_weight_kg: float | None,
    today: date,
    training_load_band: str | None = None,
) -> dict[str, Any]:
    """Daily kcal and protein targets, or a refusal explaining what is missing.

    Returns `basis: "estimate"` always, for now. Nothing here is measured
    — it is an equation applied to a profile — and a client that renders
    it as fact is misrepresenting it.
    """
    missing = [
        name for name, v in (
            ("weight", weight_kg), ("height", height_cm),
            ("date of birth", birth_date), ("sex", sex),
        ) if not v
    ]
    if missing:
        return {
            "ok": False,
            "reason": (
                "Cannot estimate a target without "
                + ", ".join(missing)
                + ". Fill these in under Settings → Profile."
            ),
            "missing": missing,
        }

    age = _age(birth_date, today)
    if age is None or age <= 0:
        return {"ok": False, "reason": "Date of birth looks wrong.",
                "missing": ["date of birth"]}

    bmr = bmr_mifflin(weight_kg, height_cm, age, sex or "male")
    factor = ACTIVITY_FACTORS.get(
        (activity_level or "light").lower(), ACTIVITY_FACTORS["light"],
    )
    tdee = bmr * factor

    losing = bool(goal_weight_kg and goal_weight_kg < weight_kg - 0.5)
    deficit = DEFAULT_DEFICIT_KCAL if losing else 0.0
    floor = (
        MIN_MALE_KCAL if (sex or "").lower().startswith("m") else MIN_FEMALE_KCAL
    )
    target_kcal = max(tdee - deficit, floor)
    # Report the deficit ACTUALLY applied, which the floor may have cut.
    applied_deficit = tdee - target_kcal

    # Protein against GOAL weight — see the module docstring. Training
    # pushes toward the top of the band, because that is when the extra
    # protein has something to do.
    basis_weight = goal_weight_kg if losing and goal_weight_kg else weight_kg
    low = round(basis_weight * 1.6)
    high = round(basis_weight * 2.0)
    if (training_load_band or "").lower() in ("optimal", "high", "over"):
        protein_target = high
    else:
        protein_target = round((low + high) / 2)

    weekly_rate_kg = (
        round(applied_deficit * 7 / KCAL_PER_KG_FAT, 2) if applied_deficit else 0.0
    )

    return {
        "ok": True,
        # Always an estimate for now. Replaced by an observed derivation
        # once enough complete food-log days exist (MEALS_PLAN phase 8).
        "basis": "estimate",
        "method": "Mifflin-St Jeor",
        "age": age,
        "weight_kg": round(weight_kg, 1),
        "goal_weight_kg": round(goal_weight_kg, 1) if goal_weight_kg else None,
        "bmr_kcal": round(bmr),
        "activity_level": (activity_level or "light").lower(),
        "activity_factor": factor,
        "tdee_kcal": round(tdee),
        "deficit_kcal": round(applied_deficit),
        "target_kcal": round(target_kcal),
        "hit_floor": target_kcal <= floor + 0.01 and losing,
        "protein_g": protein_target,
        "protein_range_g": [low, high],
        "expected_loss_kg_per_week": weekly_rate_kg,
        "caveat": (
            "Estimated from height, weight, age and activity level — not "
            "measured. Real expenditure varies by 10-15% between people "
            "with identical numbers. Treat it as a starting point and "
            "adjust from what the scale actually does over 3-4 weeks."
        ),
    }
