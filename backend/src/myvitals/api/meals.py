"""Foods, recipes and pantry — MEAL-1.

Phase 1 of docs/MEALS_PLAN.md: the nouns, with no planning, logging or AI
on top of them yet.

Route shape follows the house rule: decorators are bare ("/recipes"), not
"/api/recipes". Caddy strips the "/api" prefix exactly once, so a route
that spells it out is unreachable from the browser — the recurring 404
documented in CLAUDE.md.

Every nutrition figure a client displays is computed here. Recipes scale,
units convert and lines fail to resolve, and doing that arithmetic twice
in Vue and Compose is how the two surfaces end up disagreeing about how
much fat is in dinner.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..analytics import foods as food_lib
from ..analytics import nutrition as nutri
from ..analytics import canmake as cm
from ..analytics import common_pantry as common
from ..analytics import shopping as shop
from ..analytics import staples as stap
from ..auth import require_any
from ..db import models
from ..db.session import get_session

log = logging.getLogger(__name__)

router = APIRouter(prefix="/meals", dependencies=[Depends(require_any)])


# ---------------------------------------------------------------- schemas


class FoodOut(BaseModel):
    id: int
    slug: str
    name: str
    source: str
    category: str | None = None
    kcal: float | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None
    saturated_fat_g: float | None = None
    fiber_g: float | None = None
    sugar_g: float | None = None
    sodium_mg: float | None = None
    # Fat-soluble (MEAL-2). Absorbing these depends on absorbing fat, so
    # they are what a cholecystectomy puts at risk. Null is common —
    # USDA covers them for 65-89% of foods — and stays null.
    vitamin_a_ug: float | None = None
    vitamin_d_ug: float | None = None
    vitamin_e_mg: float | None = None
    vitamin_k_ug: float | None = None
    unit_grams: dict[str, float] | None = None
    #: The packaging's ingredient declaration, verbatim. Only ever set on
    #: a user-added packaged food; USDA rows have none.
    ingredients: str | None = None
    #: True when this food is a whole ingredient rather than a prepared
    #: dish. The recipe picker filters on it; the food log does not.
    is_ingredient: bool = False
    #: The canonical pantry concept — "chicken breast" for a row USDA
    #: calls "Chicken, broiler or fryers, breast, skinless, boneless,
    #: meat only, raw". Clients show THIS as the title and the USDA name
    #: underneath: the full name carries the precision that makes the
    #: nutrition right, but nobody scans a list of them.
    concept: str | None = None


class FoodIn(BaseModel):
    """A food the user enters themselves — typically something packaged,
    read off a label. Roughly half of what this user eats is packaged, so
    this is a first-class path, not an escape hatch."""

    name: str = Field(min_length=1, max_length=255)
    category: str | None = Field(default=None, max_length=80)
    kcal: float | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None
    saturated_fat_g: float | None = None
    fiber_g: float | None = None
    sugar_g: float | None = None
    sodium_mg: float | None = None
    # Fat-soluble (MEAL-2). Absorbing these depends on absorbing fat, so
    # they are what a cholecystectomy puts at risk. Null is common —
    # USDA covers them for 65-89% of foods — and stays null.
    vitamin_a_ug: float | None = None
    vitamin_d_ug: float | None = None
    vitamin_e_mg: float | None = None
    vitamin_k_ug: float | None = None
    unit_grams: dict[str, float] | None = None
    #: The packaging's ingredient declaration, verbatim. Stored in its
    #: original ORDER, which is meaningful — items are declared by
    #: descending weight — so it is never re-sorted or summarised.
    ingredients: str | None = None


class IngredientIn(BaseModel):
    food_id: int | None = None
    raw_text: str | None = Field(default=None, max_length=500)
    quantity: float | None = None
    unit: str | None = Field(default=None, max_length=32)


class IngredientOut(BaseModel):
    id: int
    food_id: int | None
    food_name: str | None
    raw_text: str | None
    quantity: float | None
    unit: str | None
    order_index: int
    #: Resolved weight, or null when this line could not be costed.
    grams: float | None = None
    #: Why it could not be, in words a person can act on.
    unresolved_reason: str | None = None
    nutrition: dict[str, float | None] = Field(default_factory=dict)


class RecipeIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    servings: int = Field(default=1, ge=1, le=100)
    prep_min: int | None = Field(default=None, ge=0, le=1440)
    cook_min: int | None = Field(default=None, ge=0, le=1440)
    method: str | None = None
    notes: str | None = None
    tags: list[str] | None = None
    source_url: str | None = Field(default=None, max_length=1000)
    ingredients: list[IngredientIn] | None = None


class RecipePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    servings: int | None = Field(default=None, ge=1, le=100)
    prep_min: int | None = Field(default=None, ge=0, le=1440)
    cook_min: int | None = Field(default=None, ge=0, le=1440)
    method: str | None = None
    notes: str | None = None
    tags: list[str] | None = None
    source_url: str | None = Field(default=None, max_length=1000)
    archived: bool | None = None
    #: When present, REPLACES the whole ingredient list. Absent leaves it
    #: untouched, so a rename does not have to resend every line.
    ingredients: list[IngredientIn] | None = None


class RecipeOut(BaseModel):
    id: int
    name: str
    servings: int
    prep_min: int | None
    cook_min: int | None
    method: str | None
    notes: str | None
    tags: list[str] | None
    source_url: str | None
    archived: bool
    created_at: datetime
    updated_at: datetime | None
    ingredients: list[IngredientOut] = Field(default_factory=list)
    #: Whole-recipe totals. A nutrient is null when NO line supplied it.
    totals: dict[str, float | None] = Field(default_factory=dict)
    per_serving: dict[str, float | None] = Field(default_factory=dict)
    #: How many ingredient lines could not be costed. Non-zero means the
    #: totals above understate the real figures, and the clients say so
    #: rather than presenting them as complete.
    unresolved_count: int = 0
    #: MEAL-2. Per-SERVING fat judgment, because a serving is the meal.
    #: Carries `verdict`, `basis` and `reason` — the basis matters as
    #: much as the verdict, since the app refuses to invent a threshold
    #: and has to say what it judged against.
    fat_assessment: dict[str, Any] = Field(default_factory=dict)
    #: Share of energy from each macro, per serving.
    energy_split: dict[str, Any] = Field(default_factory=dict)
    #: Fat-soluble vitamins per serving, as awareness with no targets.
    fat_soluble: dict[str, Any] = Field(default_factory=dict)


class DietProfileIn(BaseModel):
    """Diet settings. Every field optional — a PATCH-shaped PUT.

    Lives in `user_profile.extra` under one key, written through a scoped
    merging endpoint. `PUT /profile` assigns `extra` wholesale, so a
    client saving one field there would erase preferences it does not
    carry forward; see the scoped-endpoint rule in CLAUDE.md.
    """

    #: Grams of fat the user is aiming to stay under IN A SINGLE MEAL.
    #: There is deliberately no default and no app-supplied value — see
    #: `analytics/nutrition.py`. Null means "not set", which makes the
    #: assessment fall back to the user's own history or refuse outright.
    fat_per_meal_target_g: float | None = Field(default=None, ge=0, le=500)
    #: Free text: where the number came from. Rendered next to it,
    #: because a figure a clinician gave and a figure the user guessed
    #: deserve different confidence and the app should not flatten them.
    fat_target_source: str | None = Field(default=None, max_length=200)
    #: Show the fat-soluble vitamins (A/D/E/K) on meal breakdowns.
    track_fat_soluble: bool | None = None
    daily_kcal_target: int | None = Field(default=None, ge=0, le=20000)


class DietProfileOut(BaseModel):
    fat_per_meal_target_g: float | None = None
    fat_target_source: str | None = None
    track_fat_soluble: bool = True
    daily_kcal_target: int | None = None
    #: How many saved recipes can act as a comparison baseline, and how
    #: many are needed. Surfaced so the "no basis to judge this" message
    #: can say how far off it is instead of just refusing.
    comparison_meals: int = 0
    comparison_meals_needed: int = nutri.MIN_HISTORY


class PlanEntryIn(BaseModel):
    day: date
    slot: str = Field(default="dinner", max_length=16)
    recipe_id: int | None = None
    note: str | None = Field(default=None, max_length=500)
    #: Meal-prep multiplier. There is no household model — single person
    #: — so this is simply "how many containers of this".
    servings: int = Field(default=1, ge=1, le=100)


class PlanEntryPatch(BaseModel):
    day: date | None = None
    slot: str | None = Field(default=None, max_length=16)
    recipe_id: int | None = None
    note: str | None = Field(default=None, max_length=500)
    servings: int | None = Field(default=None, ge=1, le=100)


class PlanEntryOut(BaseModel):
    id: int
    day: date
    slot: str
    recipe_id: int | None
    recipe_name: str | None
    note: str | None
    servings: int
    #: Per-serving figures carried through from the recipe so the grid
    #: can show what a day adds up to without a second round trip.
    kcal_per_serving: float | None = None
    fat_per_serving_g: float | None = None
    #: The per-meal fat verdict for THIS entry. Same three-basis logic as
    #: everywhere else, and the same refusal when there is no basis.
    fat_verdict: str = "unknown"


class PlanDayOut(BaseModel):
    day: date
    entries: list[PlanEntryOut] = Field(default_factory=list)
    #: Day totals across planned entries. Null when nothing planned has
    #: a costable value — never 0, which would read as "you ate nothing".
    kcal: float | None = None
    fat_g: float | None = None


class ShoppingItemOut(BaseModel):
    id: int
    food_id: int | None
    label: str
    grams: float | None
    #: Gram total rendered in a unit someone would shop in.
    amount: str | None = None
    #: Lines that would not convert to grams, kept in their own units.
    amount_text: str | None = None
    #: The pantry holds some of this but in an unknown amount, so it
    #: could not be subtracted. The item stays on the list, flagged.
    pantry_uncertain: bool = False
    pantry_covered_g: float | None = None
    checked: bool = False
    order_index: int = 0
    #: Tier-1 Walmart deep link. Generated, never fetched — the server
    #: does not talk to Walmart at all.
    walmart_url: str | None = None


class ShoppingListOut(BaseModel):
    id: int
    name: str | None
    start_day: date | None
    end_day: date | None
    status: str
    created_at: datetime
    items: list[ShoppingItemOut] = Field(default_factory=list)
    #: How many planned meals fed into this, so an empty list can say
    #: "nothing planned" rather than "nothing needed".
    planned_meals: int = 0
    #: Items dropped because the pantry demonstrably covered them. Shown
    #: as a count so the subtraction is visible rather than mysterious.
    covered_by_pantry: int = 0


class ShoppingListIn(BaseModel):
    start: date | None = None
    days: int = Field(default=7, ge=1, le=31)
    name: str | None = Field(default=None, max_length=255)


class CanMakeRecipeOut(BaseModel):
    recipe_id: int
    name: str
    servings: int
    #: Matched over required. 1.0 with `cookable` true means go and cook.
    coverage: float
    cookable: bool
    #: Nothing missing, but a line could not be identified — so the app
    #: will not claim it is cookable. Kept apart from `cookable` so the
    #: headline count is one the user can trust literally.
    uncertain: bool
    have: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    #: Counted as had because they are assumed staples, not because the
    #: pantry says so. Shown, or the user cannot tell why it says yes.
    from_staples: list[str] = Field(default_factory=list)
    unknown: list[str] = Field(default_factory=list)


class UnlockOut(BaseModel):
    item: str
    unlocks: int
    recipes: list[str] = Field(default_factory=list)


class CanMakeOut(BaseModel):
    summary: dict[str, Any] = Field(default_factory=dict)
    recipes: list[CanMakeRecipeOut] = Field(default_factory=list)
    #: Which single purchase frees the most recipes. The payoff of the
    #: whole endpoint — knowing you can cook three things is mild;
    #: knowing one packet of rice makes it seven changes a shopping trip.
    unlock: list[UnlockOut] = Field(default_factory=list)
    #: What was assumed present, so an unexpected "yes" is explicable.
    staples_assumed: list[str] = Field(default_factory=list)
    pantry_concepts: int = 0


class CommonItemOut(BaseModel):
    label: str
    category: str
    food_id: int | None = None
    concept: str | None = None
    #: What USDA actually calls it. Shown small, so the one-tap label
    #: stays scannable while the precision behind it is visible.
    food_name: str | None = None
    #: Already in the pantry — the chip renders as done rather than
    #: adding a duplicate.
    in_pantry: bool = False


class QuickAddIn(BaseModel):
    """Food ids to drop into the pantry in one go.

    No quantities. A pantry is a "do I have this" list, which is the
    whole reason SuperCook's boolean pantry gets kept up to date and a
    quantity-demanding one does not.
    """

    food_ids: list[int] = Field(default_factory=list, max_length=200)


class StaplesIn(BaseModel):
    added: list[str] | None = None
    removed: list[str] | None = None


class StaplesOut(BaseModel):
    defaults: list[str] = Field(default_factory=list)
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    effective: list[str] = Field(default_factory=list)


class LogEntryIn(BaseModel):
    day: date | None = None
    slot: str = Field(default="dinner", max_length=16)
    food_id: int | None = None
    recipe_id: int | None = None
    label: str | None = Field(default=None, max_length=255)
    quantity: float | None = None
    unit: str | None = Field(default=None, max_length=32)
    servings: float | None = None
    #: Typed off a menu when nothing else is available. Kept apart from
    #: computed figures so the API can say which is which.
    manual_kcal: float | None = None
    manual_fat_g: float | None = None


class LogEntryOut(BaseModel):
    id: int
    day: date
    slot: str
    food_id: int | None
    recipe_id: int | None
    label: str
    quantity: float | None
    unit: str | None = None
    servings: float | None
    logged_at: datetime
    nutrition: dict[str, float | None] = Field(default_factory=dict)
    #: "catalog" | "recipe" | "manual" | "none". Rendered, because a
    #: looked-up figure and a typed-in one deserve different confidence.
    source: str = "none"
    #: Set when this entry could not be costed at all.
    unresolved_reason: str | None = None


class LogMealOut(BaseModel):
    """One slot's worth of a day — the unit fat is judged on."""

    slot: str
    entries: list[LogEntryOut] = Field(default_factory=list)
    totals: dict[str, float | None] = Field(default_factory=dict)
    #: The per-meal fat verdict, from the same three-basis logic used
    #: everywhere else. A meal is exactly what this feature exists for.
    fat_assessment: dict[str, Any] = Field(default_factory=dict)


class LogDayOut(BaseModel):
    day: date
    meals: list[LogMealOut] = Field(default_factory=list)
    totals: dict[str, float | None] = Field(default_factory=dict)
    #: Declared by the user, never inferred. Default false.
    complete: bool = False
    note: str | None = None
    entry_count: int = 0
    #: How many entries could not be costed. Non-zero means the day
    #: totals understate, and the clients say so.
    unresolved_count: int = 0


class LogDayPatch(BaseModel):
    complete: bool | None = None
    note: str | None = Field(default=None, max_length=255)


class LogStatsOut(BaseModel):
    """Derived numbers, built ONLY from days the user marked complete.

    When there are too few, this refuses and says so rather than
    averaging partial days — which would read as "you barely ate" instead
    of "you barely logged", and would be wrong in the direction that
    looks like progress.
    """

    complete_days: int = 0
    partial_days: int = 0
    days_needed: int = 0
    #: None whenever `reason` is set. Never a number the caller has to
    #: know is untrustworthy.
    avg_kcal: float | None = None
    avg_fat_g: float | None = None
    max_meal_fat_g: float | None = None
    #: Distribution of per-meal fat across complete days, which is the
    #: number this user's condition actually cares about.
    meals_counted: int = 0
    median_meal_fat_g: float | None = None
    reason: str | None = None


class PantryIn(BaseModel):
    food_id: int | None = None
    label: str | None = Field(default=None, max_length=255)
    quantity: float | None = None
    unit: str | None = Field(default=None, max_length=32)
    expires_on: date | None = None


class PantryOut(BaseModel):
    id: int
    food_id: int | None
    label: str | None
    food_name: str | None
    quantity: float | None
    unit: str | None
    expires_on: date | None
    updated_at: datetime
    #: Days until expiry; negative when already past. Derived here so the
    #: two clients cannot disagree about what "expiring soon" means, and
    #: so it is computed against the user's LOCAL day rather than UTC.
    days_to_expiry: int | None = None


# ------------------------------------------------------------- helpers


def _food_dict(f: models.Food | None) -> dict[str, Any] | None:
    """ORM row -> the plain shape the conversion helpers expect."""
    if f is None:
        return None
    d: dict[str, Any] = {
        "slug": f.slug, "name": f.name, "category": f.category,
        "unit_grams": f.unit_grams or {},
    }
    for c in food_lib.NUTRIENT_COLUMNS:
        d[c] = getattr(f, c, None)
    return d


def _food_out(f: models.Food) -> FoodOut:
    return FoodOut(
        id=f.id, slug=f.slug, name=f.name, source=f.source, category=f.category,
        unit_grams=f.unit_grams, concept=f.concept,
        ingredients=f.ingredients,
        is_ingredient=(f.category or "") in food_lib.INGREDIENT_CATEGORIES,
        **{c: getattr(f, c, None) for c in food_lib.NUTRIENT_COLUMNS},
    )


def _local_today() -> date:
    """Today in the USER's timezone.

    Delegates to the one canonical resolver rather than repeating the
    zoneinfo block. The container runs TZ=UTC while the user is Central,
    so a UTC-derived date rolls over at 7pm and pantry items would be
    reported as expiring a day early every evening. That bug has shipped
    four separate times here; `backend/tests/test_local_day_boundary.py`
    lists this module and fails the suite on the offending expression.
    """
    from .summary import resolve_day
    return resolve_day()[0]


#: The single key everything MEAL-2 stores lives under, inside
#: `user_profile.extra`. One key keeps the scoped merge trivial and keeps
#: the diet settings from colliding with the tile / display prefs that
#: already share that column.
DIET_KEY = "diet"

_DIET_DEFAULTS: dict[str, Any] = {
    # No default fat target, on purpose and permanently. Tolerance after
    # a cholecystectomy varies widely between people and commonly
    # improves over months, so a number this app invented could be wrong
    # in either direction — and wrong-and-permissive is the bad one.
    "fat_per_meal_target_g": None,
    "fat_target_source": None,
    "track_fat_soluble": True,
    "daily_kcal_target": None,
}


async def _diet_settings(db: AsyncSession) -> dict[str, Any]:
    p = await db.get(models.UserProfile, 1)
    extra = (p.extra if p and p.extra else {}) or {}
    saved = extra.get(DIET_KEY) or {}
    return {**_DIET_DEFAULTS, **saved}


async def _fat_history(
    db: AsyncSession, exclude_id: int | None = None,
) -> list[float]:
    """Per-serving fat across the user's OTHER saved recipes.

    This is the comparison baseline when no explicit target is set. It is
    a statement about what this person actually cooks, which is why it
    needs no medical basis — unlike a gram threshold, which would.

    The recipe being judged is excluded so a meal cannot pull its own
    median toward itself.

    Deliberately does NOT call `_hydrate_recipe`: that would recurse
    (hydration asks for the history, the history hydrates) and would make
    listing N recipes cost N^2 hydrations. It reads the ingredient rows
    directly in two queries instead, regardless of recipe count.
    """
    recipes = (await db.execute(
        select(models.Recipe.id, models.Recipe.servings)
        .where(models.Recipe.archived.is_(False))
    )).all()
    wanted = [(rid, sv) for rid, sv in recipes if rid != exclude_id]
    if not wanted:
        return []

    ings = (await db.execute(
        select(models.RecipeIngredient)
        .where(models.RecipeIngredient.recipe_id.in_([r for r, _ in wanted]))
    )).scalars().all()
    food_ids = {i.food_id for i in ings if i.food_id is not None}
    foods: dict[int, models.Food] = {}
    if food_ids:
        for f in (await db.execute(
            select(models.Food).where(models.Food.id.in_(food_ids))
        )).scalars().all():
            foods[f.id] = f

    per_recipe: dict[int, list[float]] = {}
    for i in ings:
        food = foods.get(i.food_id) if i.food_id is not None else None
        _, reason, nut = _line_nutrition(i, food)
        if reason is not None:
            continue
        v = nut.get("fat_g")
        if v is not None:
            per_recipe.setdefault(i.recipe_id, []).append(v)

    out: list[float] = []
    for rid, servings in wanted:
        lines = per_recipe.get(rid)
        # A recipe with no costable fat line contributes nothing rather
        # than contributing a zero — an unknown must not drag the median
        # of "what this person cooks" down toward nothing.
        if not lines:
            continue
        out.append(sum(lines) / max(servings, 1))
    return out


def _flatten_label(text: str | None) -> str | None:
    """One line, trimmed to the column width.

    A pasted menu or nutrition block arrives with newlines and runs of
    spaces, and renders as a wall of text in every list it appears in.
    Flattening keeps the content while making it a usable name.
    """
    if not text:
        return None
    return re.sub(r"\s+", " ", text).strip()[:255] or None


def _slugify_user_food(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:140]
    return f"user-{base}" if base else "user-food"


def _line_nutrition(
    ing: models.RecipeIngredient, food: models.Food | None,
) -> tuple[float | None, str | None, dict[str, float | None]]:
    """Cost one ingredient line. Returns (grams, reason_if_unresolved, nutrition).

    An unresolved line is reported, never treated as zero. Silently
    costing "a splash of olive oil" at nothing produces a fat total that
    looks authoritative and is wrong, which for this user is the one
    number that matters.
    """
    empty = {c: None for c in food_lib.NUTRIENT_COLUMNS}
    if food is None:
        return None, "no food matched", empty
    if ing.quantity is None or not ing.unit:
        return None, "no quantity given", empty
    grams = food_lib.to_grams(ing.quantity, ing.unit, _food_dict(food))
    if grams is None:
        return None, f"cannot convert {ing.unit!r} for this food", empty
    return grams, None, food_lib.nutrition_for(_food_dict(food), grams)


def _sum_nutrition(lines: list[dict[str, float | None]]) -> dict[str, float | None]:
    """Total a set of lines, keeping unknown distinct from zero.

    A nutrient stays null only when NO line supplied it. If any line has a
    figure the total is that sum — understated when other lines are
    unresolved, which `unresolved_count` is what tells the client about.
    """
    out: dict[str, float | None] = {}
    for col in food_lib.NUTRIENT_COLUMNS:
        vals = [ln.get(col) for ln in lines if ln.get(col) is not None]
        out[col] = round(sum(vals), 2) if vals else None
    return out


def _divide(totals: dict[str, float | None], n: int) -> dict[str, float | None]:
    if n <= 0:
        n = 1
    return {
        k: (round(v / n, 2) if v is not None else None) for k, v in totals.items()
    }


async def _hydrate_recipe(
    db: AsyncSession,
    r: models.Recipe,
    *,
    diet: dict[str, Any] | None = None,
    history: list[float] | None = None,
) -> RecipeOut:
    """Cost a recipe and, when given the diet context, judge it.

    `diet` and `history` are passed IN rather than fetched here so that
    listing N recipes costs one settings read and one history pass, not
    N of each.
    """
    rows = (await db.execute(
        select(models.RecipeIngredient)
        .where(models.RecipeIngredient.recipe_id == r.id)
        .order_by(models.RecipeIngredient.order_index,
                  models.RecipeIngredient.id)
    )).scalars().all()

    food_ids = {i.food_id for i in rows if i.food_id is not None}
    foods: dict[int, models.Food] = {}
    if food_ids:
        for f in (await db.execute(
            select(models.Food).where(models.Food.id.in_(food_ids))
        )).scalars().all():
            foods[f.id] = f

    out_lines: list[IngredientOut] = []
    nutritions: list[dict[str, float | None]] = []
    unresolved = 0
    for i in rows:
        food = foods.get(i.food_id) if i.food_id is not None else None
        grams, reason, nut = _line_nutrition(i, food)
        if reason is not None:
            unresolved += 1
        else:
            nutritions.append(nut)
        out_lines.append(IngredientOut(
            id=i.id, food_id=i.food_id,
            food_name=food.name if food else None,
            raw_text=i.raw_text, quantity=i.quantity, unit=i.unit,
            order_index=i.order_index, grams=grams,
            unresolved_reason=reason, nutrition=nut,
        ))

    totals = _sum_nutrition(nutritions)
    per_srv = _divide(totals, r.servings)

    # A SERVING is the meal. Judging the whole-recipe total would flag a
    # batch of six portions as an enormous fat load when each plate is
    # ordinary, which is exactly the per-meal-not-per-day distinction
    # this feature exists for.
    settings = diet or _DIET_DEFAULTS
    assessment = nutri.assess_meal_fat(
        per_srv.get("fat_g"),
        target_g=settings.get("fat_per_meal_target_g"),
        history_fat_g=list(history or []),
    )
    assessment["target_source"] = settings.get("fat_target_source")

    return RecipeOut(
        id=r.id, name=r.name, servings=r.servings, prep_min=r.prep_min,
        cook_min=r.cook_min, method=r.method, notes=r.notes, tags=r.tags,
        source_url=r.source_url, archived=r.archived,
        created_at=r.created_at, updated_at=r.updated_at,
        ingredients=out_lines, totals=totals,
        per_serving=per_srv, unresolved_count=unresolved,
        fat_assessment=assessment,
        energy_split=nutri.energy_split(per_srv),
        fat_soluble=(
            nutri.fat_soluble_summary(per_srv)
            if settings.get("track_fat_soluble", True) else {}
        ),
    )


async def _replace_ingredients(
    db: AsyncSession, recipe_id: int, lines: list[IngredientIn],
) -> None:
    await db.execute(
        sa_delete(models.RecipeIngredient)
        .where(models.RecipeIngredient.recipe_id == recipe_id)
    )
    for idx, line in enumerate(lines):
        db.add(models.RecipeIngredient(
            recipe_id=recipe_id, food_id=line.food_id,
            raw_text=line.raw_text,
            quantity=line.quantity,
            unit=food_lib.canonical_unit(line.unit) or None,
            order_index=idx,
        ))


# --------------------------------------------------------------- foods


@router.get("/foods/search", response_model=list[FoodOut])
async def search_foods(
    q: str = Query(min_length=1, max_length=100),
    ingredients_only: bool = False,
    limit: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
):
    """Search the seeded catalog plus anything the user has added.

    Ranking lives in `analytics/foods.py` and runs over the bundled JSON,
    which is in memory and needs no round trip. The DB is then hit once
    to turn those slugs into rows with real ids, because a client needs
    an id to reference a food. User-created foods are matched separately
    in SQL, since they are not in the bundled file.
    """
    ranked = food_lib.search(q, ingredients_only=ingredients_only, limit=limit)
    order = {r["slug"]: n for n, r in enumerate(ranked)}

    # User foods are matched with the SAME token-AND rule the bundled
    # catalog gets, one ILIKE per term. A single `ilike("%{q}%")` on the
    # whole query is a contiguous-substring test, so "marketside" and
    # "tortelloni" each found "Marketside Chicken & Mozzarella
    # Tortelloni" and "marketside tortelloni" found nothing — leaving the
    # food you added yourself the hardest one in the app to find.
    terms = [t for t in q.split() if t]
    user_match = models.Food.source != "usda"
    for t in terms:
        user_match = user_match & models.Food.name.ilike(f"%{t}%")

    stmt = select(models.Food).where(
        or_(models.Food.slug.in_(list(order)), user_match)
    ).limit(limit * 2)
    rows = (await db.execute(stmt)).scalars().all()

    # User foods first — someone who bothered to enter a food wants it
    # ahead of the catalog — then the catalog in ranked order.
    rows.sort(key=lambda f: (
        0 if f.source != "usda" else 1,
        order.get(f.slug, 10_000),
        f.name,
    ))
    return [_food_out(f) for f in rows[:limit]]


@router.get("/foods/{food_id}", response_model=FoodOut)
async def get_food(food_id: int, db: AsyncSession = Depends(get_session)):
    f = await db.get(models.Food, food_id)
    if f is None:
        raise HTTPException(404, "food not found")
    return _food_out(f)


@router.post("/foods", response_model=FoodOut, status_code=201)
async def create_food(body: FoodIn, db: AsyncSession = Depends(get_session)):
    """Add a food the catalog does not have — usually off a package label."""
    slug = _slugify_user_food(body.name)
    # Slugs are unique. A second "Trader Joe's chili crisp" gets a
    # numeric suffix rather than a 500 from the constraint.
    taken = set((await db.execute(
        select(models.Food.slug).where(models.Food.slug.like(f"{slug}%"))
    )).scalars().all())
    if slug in taken:
        n = 2
        while f"{slug}-{n}" in taken:
            n += 1
        slug = f"{slug}-{n}"

    f = models.Food(
        slug=slug, name=body.name.strip(), source="user",
        category=body.category, unit_grams=body.unit_grams,
        ingredients=(body.ingredients or None),
        # Set explicitly as well as relying on the column's server
        # default. The two together mean a food row can be created
        # through the ORM whether or not the model happens to know what
        # the table does — which is exactly the gap that 500'd here.
        created_at=datetime.now(timezone.utc),
        **{c: getattr(body, c) for c in food_lib.NUTRIENT_COLUMNS},
    )
    db.add(f)
    await db.commit()
    await db.refresh(f)
    return _food_out(f)


@router.patch("/foods/{food_id}", response_model=FoodOut)
async def update_food(
    food_id: int, body: FoodIn, db: AsyncSession = Depends(get_session),
):
    """Edit a food.

    Editing a BUNDLED food flips its source to "user", which takes it out
    of the seeder's reach. Without that, the next startup would overwrite
    the correction from the catalog and the fix would appear to un-happen.
    """
    f = await db.get(models.Food, food_id)
    if f is None:
        raise HTTPException(404, "food not found")
    f.name = body.name.strip()
    f.category = body.category
    f.unit_grams = body.unit_grams
    f.ingredients = body.ingredients or None
    for c in food_lib.NUTRIENT_COLUMNS:
        setattr(f, c, getattr(body, c))
    f.source = "user"
    await db.commit()
    await db.refresh(f)
    return _food_out(f)


@router.delete("/foods/{food_id}", status_code=204)
async def delete_food(food_id: int, db: AsyncSession = Depends(get_session)):
    """Delete a USER food. Bundled rows are refused.

    Deleting a seeded food would achieve nothing anyway — the next
    startup seeds it straight back — so a 409 that says why is more
    useful than a delete that silently undoes itself.
    """
    f = await db.get(models.Food, food_id)
    if f is None:
        raise HTTPException(404, "food not found")
    if f.source == "usda":
        raise HTTPException(
            409, "bundled catalog foods cannot be deleted; edit it instead",
        )
    await db.delete(f)
    await db.commit()


# ------------------------------------------------------------- recipes


@router.get("/recipes", response_model=list[RecipeOut])
async def list_recipes(
    include_archived: bool = False,
    db: AsyncSession = Depends(get_session),
):
    stmt = select(models.Recipe).order_by(models.Recipe.name)
    if not include_archived:
        stmt = stmt.where(models.Recipe.archived.is_(False))
    rows = (await db.execute(stmt)).scalars().all()

    diet = await _diet_settings(db)
    # One baseline for the whole list. Each recipe is then judged against
    # the others by excluding its own value from the passed-in history,
    # which is a list operation rather than another query.
    all_fat = await _fat_history(db)
    out: list[RecipeOut] = []
    for r in rows:
        hydrated = await _hydrate_recipe(db, r, diet=diet, history=all_fat)
        mine = hydrated.per_serving.get("fat_g")
        if mine is not None and diet.get("fat_per_meal_target_g") is None:
            others = list(all_fat)
            # Remove one occurrence of this recipe's own value so a meal
            # cannot be compared against itself.
            try:
                others.remove(mine)
            except ValueError:
                pass
            hydrated.fat_assessment = nutri.assess_meal_fat(
                mine, target_g=None, history_fat_g=others,
            )
            hydrated.fat_assessment["target_source"] = diet.get("fat_target_source")
        out.append(hydrated)
    return out


@router.post("/recipes", response_model=RecipeOut, status_code=201)
async def create_recipe(body: RecipeIn, db: AsyncSession = Depends(get_session)):
    r = models.Recipe(
        name=body.name.strip(), servings=body.servings, prep_min=body.prep_min,
        cook_min=body.cook_min, method=body.method, notes=body.notes,
        tags=body.tags, source_url=body.source_url,
        created_at=datetime.now(timezone.utc),
    )
    db.add(r)
    await db.flush()
    if body.ingredients:
        await _replace_ingredients(db, r.id, body.ingredients)
    await db.commit()
    await db.refresh(r)
    return await _hydrate_recipe(
        db, r,
        diet=await _diet_settings(db),
        history=await _fat_history(db, exclude_id=r.id),
    )


@router.get("/recipes/{recipe_id}", response_model=RecipeOut)
async def get_recipe(recipe_id: int, db: AsyncSession = Depends(get_session)):
    r = await db.get(models.Recipe, recipe_id)
    if r is None:
        raise HTTPException(404, "recipe not found")
    return await _hydrate_recipe(
        db, r,
        diet=await _diet_settings(db),
        history=await _fat_history(db, exclude_id=r.id),
    )


@router.patch("/recipes/{recipe_id}", response_model=RecipeOut)
async def update_recipe(
    recipe_id: int, body: RecipePatch, db: AsyncSession = Depends(get_session),
):
    r = await db.get(models.Recipe, recipe_id)
    if r is None:
        raise HTTPException(404, "recipe not found")

    fields = body.model_dump(exclude_unset=True, exclude={"ingredients"})
    for k, v in fields.items():
        setattr(r, k, v.strip() if k == "name" and isinstance(v, str) else v)
    if body.ingredients is not None:
        await _replace_ingredients(db, r.id, body.ingredients)
    r.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(r)
    return await _hydrate_recipe(
        db, r,
        diet=await _diet_settings(db),
        history=await _fat_history(db, exclude_id=r.id),
    )


@router.delete("/recipes/{recipe_id}", status_code=204)
async def delete_recipe(recipe_id: int, db: AsyncSession = Depends(get_session)):
    r = await db.get(models.Recipe, recipe_id)
    if r is None:
        raise HTTPException(404, "recipe not found")
    await db.delete(r)
    await db.commit()


@router.get("/recipes/{recipe_id}/scaled", response_model=dict)
async def scale_recipe(
    recipe_id: int,
    servings: int = Query(ge=1, le=100),
    db: AsyncSession = Depends(get_session),
):
    """The same recipe at a different serving count.

    Cooking is for one here, so this is the meal-prep lever: a recipe
    written for 2 becomes a batch of 6 by multiplying every quantity.
    Kept server-side so the phone and the web agree on the arithmetic.
    """
    r = await db.get(models.Recipe, recipe_id)
    if r is None:
        raise HTTPException(404, "recipe not found")
    hydrated = await _hydrate_recipe(
        db, r,
        diet=await _diet_settings(db),
        history=await _fat_history(db, exclude_id=r.id),
    )
    factor = servings / max(r.servings, 1)
    return {
        "recipe_id": r.id,
        "name": r.name,
        "base_servings": r.servings,
        "servings": servings,
        "factor": round(factor, 4),
        "ingredients": [
            {
                "food_id": i.food_id,
                "food_name": i.food_name,
                "raw_text": i.raw_text,
                "quantity": round(i.quantity * factor, 2) if i.quantity is not None else None,
                "unit": i.unit,
                "grams": round(i.grams * factor, 2) if i.grams is not None else None,
                "unresolved_reason": i.unresolved_reason,
            }
            for i in hydrated.ingredients
        ],
        "totals": {
            k: (round(v * factor, 2) if v is not None else None)
            for k, v in hydrated.totals.items()
        },
        "per_serving": hydrated.per_serving,
        "unresolved_count": hydrated.unresolved_count,
    }


# --------------------------------------------------------- diet profile


@router.get("/diet-profile", response_model=DietProfileOut)
async def get_diet_profile(db: AsyncSession = Depends(get_session)):
    settings = await _diet_settings(db)
    history = await _fat_history(db)
    return DietProfileOut(
        **{k: settings.get(k) for k in _DIET_DEFAULTS if k != "track_fat_soluble"},
        track_fat_soluble=bool(settings.get("track_fat_soluble", True)),
        comparison_meals=len(history),
    )


@router.put("/diet-profile", response_model=DietProfileOut)
async def put_diet_profile(
    body: DietProfileIn, db: AsyncSession = Depends(get_session),
):
    """Scoped write — merges into `extra` rather than replacing it.

    `PUT /profile` assigns `extra` wholesale, so writing diet settings
    through it would erase the tile and display preferences that share
    the column. Same pattern as `/profile/tile-prefs`.
    """
    p = await db.get(models.UserProfile, 1)
    now = datetime.now(timezone.utc)
    if p is None:
        p = models.UserProfile(id=1, updated_at=now)
        db.add(p)

    # Copy-then-reassign: SQLAlchemy does not track in-place mutation of
    # a JSON column, so mutating p.extra would commit nothing.
    extra = dict(p.extra or {})
    diet = dict(extra.get(DIET_KEY) or {})
    # exclude_unset so omitting a field leaves it alone, while explicitly
    # sending null CLEARS it — which is how a user removes a fat target
    # they no longer want the app judging against.
    diet.update(body.model_dump(exclude_unset=True))
    extra[DIET_KEY] = diet
    p.extra = extra
    p.updated_at = now
    await db.commit()

    settings = {**_DIET_DEFAULTS, **diet}
    history = await _fat_history(db)
    return DietProfileOut(
        **{k: settings.get(k) for k in _DIET_DEFAULTS if k != "track_fat_soluble"},
        track_fat_soluble=bool(settings.get("track_fat_soluble", True)),
        comparison_meals=len(history),
    )


@router.get("/nutrition/assess", response_model=dict)
async def assess_arbitrary_meal(
    fat_g: float = Query(ge=0, le=1000),
    db: AsyncSession = Depends(get_session),
):
    """Judge a fat figure the user is holding in their hand.

    Exists so the awareness half works with no recipe and no log at all —
    read a number off a package, ask whether it is a lot for you. That is
    the floor this feature is designed to have: useful with zero data
    entered.
    """
    diet = await _diet_settings(db)
    result = nutri.assess_meal_fat(
        fat_g,
        target_g=diet.get("fat_per_meal_target_g"),
        history_fat_g=await _fat_history(db),
    )
    result["target_source"] = diet.get("fat_target_source")
    return result


# -------------------------------------------------------------- pantry


@router.get("/pantry", response_model=list[PantryOut])
async def list_pantry(db: AsyncSession = Depends(get_session)):
    rows = (await db.execute(select(models.PantryItem))).scalars().all()
    food_ids = {p.food_id for p in rows if p.food_id is not None}
    names: dict[int, str] = {}
    if food_ids:
        for fid, name in (await db.execute(
            select(models.Food.id, models.Food.name)
            .where(models.Food.id.in_(food_ids))
        )).all():
            names[fid] = name

    today = _local_today()
    out = [
        PantryOut(
            id=p.id, food_id=p.food_id, label=p.label,
            food_name=names.get(p.food_id) if p.food_id else None,
            quantity=p.quantity, unit=p.unit, expires_on=p.expires_on,
            updated_at=p.updated_at,
            days_to_expiry=((p.expires_on - today).days if p.expires_on else None),
        )
        for p in rows
    ]
    # Expiring first — that is the only ordering the list is ever read
    # for. Items with no date sort last rather than pretending to be
    # urgent.
    out.sort(key=lambda p: (
        p.days_to_expiry if p.days_to_expiry is not None else 10**6,
        (p.food_name or p.label or "").lower(),
    ))
    return out


@router.post("/pantry", response_model=PantryOut, status_code=201)
async def add_pantry(body: PantryIn, db: AsyncSession = Depends(get_session)):
    if body.food_id is None and not (body.label or "").strip():
        raise HTTPException(422, "a pantry item needs either a food or a label")
    p = models.PantryItem(
        food_id=body.food_id, label=(body.label or None),
        quantity=body.quantity,
        unit=food_lib.canonical_unit(body.unit) or None,
        expires_on=body.expires_on,
        updated_at=datetime.now(timezone.utc),
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    name = None
    if p.food_id:
        f = await db.get(models.Food, p.food_id)
        name = f.name if f else None
    today = _local_today()
    return PantryOut(
        id=p.id, food_id=p.food_id, label=p.label, food_name=name,
        quantity=p.quantity, unit=p.unit, expires_on=p.expires_on,
        updated_at=p.updated_at,
        days_to_expiry=((p.expires_on - today).days if p.expires_on else None),
    )


@router.patch("/pantry/{item_id}", response_model=PantryOut)
async def update_pantry(
    item_id: int, body: PantryIn, db: AsyncSession = Depends(get_session),
):
    p = await db.get(models.PantryItem, item_id)
    if p is None:
        raise HTTPException(404, "pantry item not found")
    fields = body.model_dump(exclude_unset=True)
    for k, v in fields.items():
        setattr(p, k, food_lib.canonical_unit(v) or None if k == "unit" else v)
    p.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(p)
    name = None
    if p.food_id:
        f = await db.get(models.Food, p.food_id)
        name = f.name if f else None
    today = _local_today()
    return PantryOut(
        id=p.id, food_id=p.food_id, label=p.label, food_name=name,
        quantity=p.quantity, unit=p.unit, expires_on=p.expires_on,
        updated_at=p.updated_at,
        days_to_expiry=((p.expires_on - today).days if p.expires_on else None),
    )


@router.delete("/pantry/{item_id}", status_code=204)
async def delete_pantry(item_id: int, db: AsyncSession = Depends(get_session)):
    p = await db.get(models.PantryItem, item_id)
    if p is None:
        raise HTTPException(404, "pantry item not found")
    await db.delete(p)
    await db.commit()


# ---------------------------------------------------------- meal plan


def _week_start(d: date) -> date:
    """Monday of the week containing `d`."""
    return d - timedelta(days=d.weekday())


async def _plan_rows(
    db: AsyncSession, start: date, end: date,
) -> list[models.MealPlanEntry]:
    return list((await db.execute(
        select(models.MealPlanEntry)
        .where(models.MealPlanEntry.day >= start)
        .where(models.MealPlanEntry.day <= end)
        .order_by(models.MealPlanEntry.day,
                  models.MealPlanEntry.order_index,
                  models.MealPlanEntry.id)
    )).scalars().all())


@router.get("/plan", response_model=list[PlanDayOut])
async def get_plan(
    start: date | None = None,
    days: int = Query(default=7, ge=1, le=31),
    db: AsyncSession = Depends(get_session),
):
    """The plan grid for a window, one object per day.

    `start` defaults to the Monday of the user's LOCAL current week. The
    container runs TZ=UTC while the user is Central, so deriving it from
    a UTC date would roll the week over at 7pm on a Sunday and show the
    wrong seven days all evening.
    """
    begin = start or _week_start(_local_today())
    end = begin + timedelta(days=days - 1)

    rows = await _plan_rows(db, begin, end)
    recipe_ids = {r.recipe_id for r in rows if r.recipe_id is not None}

    diet = await _diet_settings(db)
    history = await _fat_history(db)
    recipes: dict[int, RecipeOut] = {}
    if recipe_ids:
        for r in (await db.execute(
            select(models.Recipe).where(models.Recipe.id.in_(recipe_ids))
        )).scalars().all():
            recipes[r.id] = await _hydrate_recipe(
                db, r, diet=diet, history=history,
            )

    by_day: dict[date, list[PlanEntryOut]] = {}
    for e in rows:
        hydrated = recipes.get(e.recipe_id) if e.recipe_id else None
        kcal = hydrated.per_serving.get("kcal") if hydrated else None
        fat = hydrated.per_serving.get("fat_g") if hydrated else None
        by_day.setdefault(e.day, []).append(PlanEntryOut(
            id=e.id, day=e.day, slot=e.slot, recipe_id=e.recipe_id,
            recipe_name=hydrated.name if hydrated else None,
            note=e.note, servings=e.servings,
            kcal_per_serving=kcal, fat_per_serving_g=fat,
            fat_verdict=(
                hydrated.fat_assessment.get("verdict", "unknown")
                if hydrated else "unknown"
            ),
        ))

    out: list[PlanDayOut] = []
    for i in range(days):
        d = begin + timedelta(days=i)
        entries = by_day.get(d, [])
        # A day total sums the SERVINGS planned, not one portion each —
        # planning three containers of something is three meals' worth of
        # shopping and three meals' worth of energy.
        kcals = [
            e.kcal_per_serving * e.servings
            for e in entries if e.kcal_per_serving is not None
        ]
        fats = [
            e.fat_per_serving_g * e.servings
            for e in entries if e.fat_per_serving_g is not None
        ]
        out.append(PlanDayOut(
            day=d, entries=entries,
            # Null, not zero: a day with nothing costable planned has an
            # unknown total, which is not the same as an empty one.
            kcal=round(sum(kcals), 1) if kcals else None,
            fat_g=round(sum(fats), 1) if fats else None,
        ))
    return out


@router.post("/plan", response_model=PlanEntryOut, status_code=201)
async def add_plan_entry(
    body: PlanEntryIn, db: AsyncSession = Depends(get_session),
):
    if body.recipe_id is None and not (body.note or "").strip():
        raise HTTPException(422, "a plan entry needs either a recipe or a note")
    if body.recipe_id is not None:
        if await db.get(models.Recipe, body.recipe_id) is None:
            raise HTTPException(404, "recipe not found")

    n = (await db.execute(
        select(func.count()).select_from(models.MealPlanEntry)
        .where(models.MealPlanEntry.day == body.day)
    )).scalar_one()

    e = models.MealPlanEntry(
        day=body.day, slot=body.slot, recipe_id=body.recipe_id,
        note=(body.note or None), servings=body.servings,
        order_index=n, created_at=datetime.now(timezone.utc),
    )
    db.add(e)
    await db.commit()
    await db.refresh(e)

    name = None
    if e.recipe_id:
        r = await db.get(models.Recipe, e.recipe_id)
        name = r.name if r else None
    return PlanEntryOut(
        id=e.id, day=e.day, slot=e.slot, recipe_id=e.recipe_id,
        recipe_name=name, note=e.note, servings=e.servings,
    )


@router.patch("/plan/{entry_id}", response_model=PlanEntryOut)
async def update_plan_entry(
    entry_id: int, body: PlanEntryPatch, db: AsyncSession = Depends(get_session),
):
    e = await db.get(models.MealPlanEntry, entry_id)
    if e is None:
        raise HTTPException(404, "plan entry not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(e, k, v)
    await db.commit()
    await db.refresh(e)
    name = None
    if e.recipe_id:
        r = await db.get(models.Recipe, e.recipe_id)
        name = r.name if r else None
    return PlanEntryOut(
        id=e.id, day=e.day, slot=e.slot, recipe_id=e.recipe_id,
        recipe_name=name, note=e.note, servings=e.servings,
    )


@router.delete("/plan/{entry_id}", status_code=204)
async def delete_plan_entry(
    entry_id: int, db: AsyncSession = Depends(get_session),
):
    e = await db.get(models.MealPlanEntry, entry_id)
    if e is None:
        raise HTTPException(404, "plan entry not found")
    await db.delete(e)
    await db.commit()


# ----------------------------------------------------- shopping lists


def _shopping_out(
    lst: models.ShoppingList,
    items: list[models.ShoppingListItem],
    foods: dict[int, models.Food],
    planned: int = 0,
    covered: int = 0,
) -> ShoppingListOut:
    return ShoppingListOut(
        id=lst.id, name=lst.name, start_day=lst.start_day, end_day=lst.end_day,
        status=lst.status, created_at=lst.created_at,
        planned_meals=planned, covered_by_pantry=covered,
        items=[
            ShoppingItemOut(
                id=i.id, food_id=i.food_id, label=i.label, grams=i.grams,
                amount=(
                    shop.humanise(i.grams, _food_dict(foods.get(i.food_id)))
                    if i.grams else None
                ),
                amount_text=i.amount_text,
                pantry_uncertain=i.pantry_uncertain,
                pantry_covered_g=i.pantry_covered_g,
                checked=i.checked, order_index=i.order_index,
                walmart_url=shop.walmart_search_url(i.label),
            )
            for i in items
        ],
    )


@router.post("/shopping-list", response_model=ShoppingListOut, status_code=201)
async def generate_shopping_list(
    body: ShoppingListIn, db: AsyncSession = Depends(get_session),
):
    """Plan minus pantry, computed here so both clients agree.

    Persisted rather than recomputed on view: the user ticks items off
    while shopping, and regenerating would silently undo that.
    """
    begin = body.start or _week_start(_local_today())
    end = begin + timedelta(days=body.days - 1)

    entries = await _plan_rows(db, begin, end)
    planned = [e for e in entries if e.recipe_id is not None]

    # Every ingredient line of every planned recipe, scaled by how many
    # servings of it are planned.
    lines: list[dict[str, Any]] = []
    if planned:
        recipe_ids = {e.recipe_id for e in planned}
        recipes = {
            r.id: r for r in (await db.execute(
                select(models.Recipe).where(models.Recipe.id.in_(recipe_ids))
            )).scalars().all()
        }
        ings = (await db.execute(
            select(models.RecipeIngredient)
            .where(models.RecipeIngredient.recipe_id.in_(recipe_ids))
        )).scalars().all()
        food_ids = {i.food_id for i in ings if i.food_id is not None}
        foods_by_id: dict[int, models.Food] = {}
        if food_ids:
            for f in (await db.execute(
                select(models.Food).where(models.Food.id.in_(food_ids))
            )).scalars().all():
                foods_by_id[f.id] = f

        by_recipe: dict[int, list[models.RecipeIngredient]] = {}
        for i in ings:
            by_recipe.setdefault(i.recipe_id, []).append(i)

        for e in planned:
            recipe = recipes.get(e.recipe_id)
            if recipe is None:
                continue
            # Planning 4 servings of a recipe written for 2 means buying
            # twice the ingredients.
            mult = e.servings / max(recipe.servings, 1)
            for i in by_recipe.get(e.recipe_id, []):
                food = foods_by_id.get(i.food_id) if i.food_id else None
                grams = (
                    food_lib.to_grams(i.quantity, i.unit, _food_dict(food))
                    if food else None
                )
                lines.append({
                    "food_id": i.food_id,
                    "label": (food.name if food else (i.raw_text or "Unnamed")),
                    "quantity": i.quantity,
                    "unit": i.unit,
                    "grams": grams,
                    "multiplier": mult,
                })

    needs = shop.aggregate_needs(lines)

    # Pantry, grouped by CONCEPT rather than by food id.
    #
    # This is the MEAL-6 correctness fix. Raw and grilled chicken breast
    # are different USDA rows with genuinely different nutrition, but they
    # are one thing to have in the house — so a pantry holding the raw row
    # used to fail to cancel a recipe naming the cooked one, and the list
    # told you to buy chicken you already had.
    pantry_rows = (await db.execute(select(models.PantryItem))).scalars().all()
    pantry_food_ids = {p.food_id for p in pantry_rows if p.food_id is not None}
    concept_of: dict[int, str | None] = {}
    if pantry_food_ids:
        for fid, concept in (await db.execute(
            select(models.Food.id, models.Food.concept)
            .where(models.Food.id.in_(pantry_food_ids))
        )).all():
            concept_of[fid] = concept

    pantry_by_food: dict[int, list[dict[str, Any]]] = {}
    pantry_by_label: dict[str, list[dict[str, Any]]] = {}
    pantry_by_concept: dict[str, list[dict[str, Any]]] = {}
    for p in pantry_rows:
        rec = {"quantity": p.quantity, "unit": p.unit}
        if p.food_id is not None:
            pantry_by_food.setdefault(p.food_id, []).append(rec)
            c = concept_of.get(p.food_id)
            if c:
                pantry_by_concept.setdefault(c, []).append(rec)
        elif p.label:
            pantry_by_label.setdefault(p.label.lower(), []).append(rec)

    all_food_ids = {n.food_id for n in needs.values() if n.food_id is not None}
    need_foods: dict[int, models.Food] = {}
    if all_food_ids:
        for f in (await db.execute(
            select(models.Food).where(models.Food.id.in_(all_food_ids))
        )).scalars().all():
            need_foods[f.id] = f

    lst = models.ShoppingList(
        name=body.name, start_day=begin, end_day=end, status="open",
        created_at=datetime.now(timezone.utc),
    )
    db.add(lst)
    await db.flush()

    covered_count = 0
    order = 0
    kept: list[models.ShoppingListItem] = []
    for need in sorted(needs.values(), key=lambda n: n.label.lower()):
        food = need_foods.get(need.food_id) if need.food_id is not None else None
        # Exact food id first (most precise), then the shared concept,
        # then a hand-typed label. Concept matching is what makes a
        # pantry of raw chicken cancel a recipe's cooked chicken.
        if need.food_id is not None:
            have = list(pantry_by_food.get(need.food_id, []))
            concept = getattr(food, "concept", None) if food else None
            if not have and concept:
                have = list(pantry_by_concept.get(concept, []))
        else:
            have = list(pantry_by_label.get(need.label.lower(), []))
            # A hand-typed recipe line can still match a stocked food
            # whose concept is literally what was typed.
            if not have:
                have = list(pantry_by_concept.get(need.label.lower(), []))
        row = shop.subtract_pantry(need, have, _food_dict(food))
        if row["fully_covered"]:
            # The ONLY case where a line is dropped: the arithmetic was
            # complete and the pantry demonstrably covers it. Counted so
            # the subtraction is visible rather than mysterious.
            covered_count += 1
            continue
        item = models.ShoppingListItem(
            list_id=lst.id, food_id=row["food_id"], label=row["label"],
            grams=row["grams"], amount_text=row["amount_text"],
            pantry_uncertain=row["pantry_uncertain"],
            pantry_covered_g=row["pantry_covered_g"],
            checked=False, order_index=order,
        )
        order += 1
        db.add(item)
        kept.append(item)

    await db.commit()
    for i in kept:
        await db.refresh(i)
    await db.refresh(lst)
    return _shopping_out(lst, kept, need_foods, len(planned), covered_count)


@router.get("/shopping-lists", response_model=list[ShoppingListOut])
async def list_shopping_lists(db: AsyncSession = Depends(get_session)):
    lists = (await db.execute(
        select(models.ShoppingList)
        .order_by(models.ShoppingList.created_at.desc())
        .limit(20)
    )).scalars().all()
    out: list[ShoppingListOut] = []
    for lst in lists:
        items = list((await db.execute(
            select(models.ShoppingListItem)
            .where(models.ShoppingListItem.list_id == lst.id)
            .order_by(models.ShoppingListItem.order_index)
        )).scalars().all())
        food_ids = {i.food_id for i in items if i.food_id is not None}
        foods: dict[int, models.Food] = {}
        if food_ids:
            for f in (await db.execute(
                select(models.Food).where(models.Food.id.in_(food_ids))
            )).scalars().all():
                foods[f.id] = f
        out.append(_shopping_out(lst, items, foods))
    return out


@router.get("/shopping-list/{list_id}", response_model=ShoppingListOut)
async def get_shopping_list(list_id: int, db: AsyncSession = Depends(get_session)):
    lst = await db.get(models.ShoppingList, list_id)
    if lst is None:
        raise HTTPException(404, "shopping list not found")
    items = list((await db.execute(
        select(models.ShoppingListItem)
        .where(models.ShoppingListItem.list_id == list_id)
        .order_by(models.ShoppingListItem.order_index)
    )).scalars().all())
    food_ids = {i.food_id for i in items if i.food_id is not None}
    foods: dict[int, models.Food] = {}
    if food_ids:
        for f in (await db.execute(
            select(models.Food).where(models.Food.id.in_(food_ids))
        )).scalars().all():
            foods[f.id] = f
    return _shopping_out(lst, items, foods)


@router.patch("/shopping-list/{list_id}/items/{item_id}", response_model=dict)
async def check_shopping_item(
    list_id: int, item_id: int, checked: bool,
    db: AsyncSession = Depends(get_session),
):
    item = await db.get(models.ShoppingListItem, item_id)
    if item is None or item.list_id != list_id:
        raise HTTPException(404, "item not found")
    item.checked = checked
    await db.commit()
    return {"id": item.id, "checked": item.checked}


@router.patch("/shopping-list/{list_id}", response_model=dict)
async def set_shopping_status(
    list_id: int, status: str = Query(pattern="^(open|done)$"),
    db: AsyncSession = Depends(get_session),
):
    lst = await db.get(models.ShoppingList, list_id)
    if lst is None:
        raise HTTPException(404, "shopping list not found")
    lst.status = status
    await db.commit()
    return {"id": lst.id, "status": lst.status}


@router.delete("/shopping-list/{list_id}", status_code=204)
async def delete_shopping_list(
    list_id: int, db: AsyncSession = Depends(get_session),
):
    lst = await db.get(models.ShoppingList, list_id)
    if lst is None:
        raise HTTPException(404, "shopping list not found")
    await db.delete(lst)
    await db.commit()


# --------------------------------------------------------- food log
#
# Intermittent logging is the DESIGN ASSUMPTION here, not a failure mode.
# There is deliberately no streak, no completion percentage and no
# nagging notification anywhere in this section — a tracker that turns
# red the moment you stop is a tracker you stop opening. The awareness
# half of the feature works with zero entries; this is opt-in on top and
# is meant to survive lying fallow for months.

#: Complete days needed before any average is reported. Below this the
#: stats endpoint refuses rather than averaging a handful of days.
MIN_COMPLETE_DAYS = 5

_SLOT_ORDER = {"breakfast": 0, "lunch": 1, "dinner": 2, "snack": 3}


def _entry_nutrition(
    e: models.FoodLogEntry,
    food: models.Food | None,
    recipe_per_serving: dict[str, float | None] | None,
) -> tuple[dict[str, float | None], str, str | None]:
    """Cost one log entry. Returns (nutrition, source, unresolved_reason).

    Resolution order is most-trustworthy first, and the source is
    reported: a figure looked up from the catalog and a figure typed off
    a menu are both useful and should not be presented identically.
    """
    empty = {c: None for c in food_lib.NUTRIENT_COLUMNS}

    if food is not None:
        grams = food_lib.to_grams(e.quantity, e.unit, _food_dict(food))
        if grams is None:
            return empty, "catalog", (
                f"cannot convert {e.unit!r} for this food"
                if e.unit else "no quantity given"
            )
        return food_lib.nutrition_for(_food_dict(food), grams), "catalog", None

    if recipe_per_serving is not None:
        n = e.servings if e.servings is not None else 1.0
        return (
            {
                k: (None if v is None else round(v * n, 2))
                for k, v in recipe_per_serving.items()
            },
            "recipe",
            None,
        )

    if e.manual_kcal is not None or e.manual_fat_g is not None:
        out = dict(empty)
        out["kcal"] = e.manual_kcal
        out["fat_g"] = e.manual_fat_g
        return out, "manual", None

    return empty, "none", "nothing to cost this against"


async def _log_days(
    db: AsyncSession, start: date, end: date,
) -> list[LogDayOut]:
    entries = list((await db.execute(
        select(models.FoodLogEntry)
        .where(models.FoodLogEntry.day >= start)
        .where(models.FoodLogEntry.day <= end)
        .order_by(models.FoodLogEntry.day, models.FoodLogEntry.id)
    )).scalars().all())

    food_ids = {e.food_id for e in entries if e.food_id is not None}
    foods: dict[int, models.Food] = {}
    if food_ids:
        for f in (await db.execute(
            select(models.Food).where(models.Food.id.in_(food_ids))
        )).scalars().all():
            foods[f.id] = f

    recipe_ids = {e.recipe_id for e in entries if e.recipe_id is not None}
    per_serving: dict[int, dict[str, float | None]] = {}
    if recipe_ids:
        diet = await _diet_settings(db)
        for r in (await db.execute(
            select(models.Recipe).where(models.Recipe.id.in_(recipe_ids))
        )).scalars().all():
            hydrated = await _hydrate_recipe(db, r, diet=diet, history=[])
            per_serving[r.id] = hydrated.per_serving

    marks = {
        m.day: m for m in (await db.execute(
            select(models.FoodLogDay)
            .where(models.FoodLogDay.day >= start)
            .where(models.FoodLogDay.day <= end)
        )).scalars().all()
    }

    diet = await _diet_settings(db)
    history = await _fat_history(db)

    by_day: dict[date, list[models.FoodLogEntry]] = {}
    for e in entries:
        by_day.setdefault(e.day, []).append(e)

    out: list[LogDayOut] = []
    cursor = start
    while cursor <= end:
        rows = by_day.get(cursor, [])
        mark = marks.get(cursor)

        by_slot: dict[str, list[LogEntryOut]] = {}
        day_nutritions: list[dict[str, float | None]] = []
        unresolved = 0
        for e in rows:
            food = foods.get(e.food_id) if e.food_id is not None else None
            rps = per_serving.get(e.recipe_id) if e.recipe_id is not None else None
            nut, source, reason = _entry_nutrition(e, food, rps)
            if reason is not None:
                unresolved += 1
            else:
                day_nutritions.append(nut)
            # Written out rather than nested in a conditional expression.
            # The one-liner this replaces bound as
            #   food.name if food else ((e.label or "Recipe #N")
            #                            if e.recipe_id else "Unnamed")
            # so a free-text entry — no food, no recipe — skipped its own
            # label and rendered "Unnamed" however carefully it was named.
            if food is not None:
                label = food.name
            elif e.label:
                label = e.label
            elif e.recipe_id:
                label = f"Recipe #{e.recipe_id}"
            else:
                label = "Unnamed"
            by_slot.setdefault(e.slot, []).append(LogEntryOut(
                id=e.id, day=e.day, slot=e.slot, food_id=e.food_id,
                recipe_id=e.recipe_id, label=label, quantity=e.quantity,
                unit=e.unit, servings=e.servings, logged_at=e.logged_at,
                nutrition=nut, source=source, unresolved_reason=reason,
            ))

        meals: list[LogMealOut] = []
        for slot in sorted(by_slot, key=lambda s: (_SLOT_ORDER.get(s, 9), s)):
            slot_entries = by_slot[slot]
            slot_totals = _sum_nutrition([
                x.nutrition for x in slot_entries if x.unresolved_reason is None
            ])
            assessment = nutri.assess_meal_fat(
                slot_totals.get("fat_g"),
                target_g=diet.get("fat_per_meal_target_g"),
                history_fat_g=history,
            )
            assessment["target_source"] = diet.get("fat_target_source")
            meals.append(LogMealOut(
                slot=slot, entries=slot_entries, totals=slot_totals,
                fat_assessment=assessment,
            ))

        out.append(LogDayOut(
            day=cursor, meals=meals,
            totals=_sum_nutrition(day_nutritions),
            complete=bool(mark.complete) if mark else False,
            note=mark.note if mark else None,
            entry_count=len(rows), unresolved_count=unresolved,
        ))
        cursor += timedelta(days=1)
    return out


@router.get("/log", response_model=list[LogDayOut])
async def get_log(
    start: date | None = None,
    days: int = Query(default=7, ge=1, le=62),
    db: AsyncSession = Depends(get_session),
):
    """The log for a window, one object per day.

    Days with no entries are returned as EMPTY days, not omitted — a gap
    is shown as a gap. Their totals are null rather than zero, because a
    day that was not logged is not a day nothing was eaten.
    """
    begin = start or (_local_today() - timedelta(days=days - 1))
    return await _log_days(db, begin, begin + timedelta(days=days - 1))


@router.post("/log", response_model=LogEntryOut, status_code=201)
async def add_log_entry(
    body: LogEntryIn, db: AsyncSession = Depends(get_session),
):
    if body.food_id is None and body.recipe_id is None and not (body.label or "").strip():
        raise HTTPException(
            422, "a log entry needs a food, a recipe, or at least a name",
        )
    if body.food_id is not None and await db.get(models.Food, body.food_id) is None:
        raise HTTPException(404, "food not found")
    if body.recipe_id is not None and await db.get(models.Recipe, body.recipe_id) is None:
        raise HTTPException(404, "recipe not found")

    e = models.FoodLogEntry(
        day=body.day or _local_today(),
        slot=body.slot,
        food_id=body.food_id,
        recipe_id=body.recipe_id,
        # Collapse whitespace: people paste a whole nutrition block into
        # the name field, and a multi-line value renders as a wall of
        # text everywhere it appears. Nothing is discarded — it is
        # flattened and capped to the column width.
        label=(_flatten_label(body.label) or None),
        quantity=body.quantity,
        unit=food_lib.canonical_unit(body.unit) or None,
        servings=body.servings,
        manual_kcal=body.manual_kcal,
        manual_fat_g=body.manual_fat_g,
        logged_at=datetime.now(timezone.utc),
    )
    db.add(e)
    await db.commit()
    await db.refresh(e)

    food = await db.get(models.Food, e.food_id) if e.food_id else None
    rps = None
    if e.recipe_id:
        r = await db.get(models.Recipe, e.recipe_id)
        if r is not None:
            rps = (await _hydrate_recipe(db, r, history=[])).per_serving
    nut, source, reason = _entry_nutrition(e, food, rps)
    return LogEntryOut(
        id=e.id, day=e.day, slot=e.slot, food_id=e.food_id,
        recipe_id=e.recipe_id,
        label=(food.name if food else (e.label or "Unnamed")),
        quantity=e.quantity, unit=e.unit, servings=e.servings,
        logged_at=e.logged_at, nutrition=nut, source=source,
        unresolved_reason=reason,
    )


@router.delete("/log/{entry_id}", status_code=204)
async def delete_log_entry(
    entry_id: int, db: AsyncSession = Depends(get_session),
):
    e = await db.get(models.FoodLogEntry, entry_id)
    if e is None:
        raise HTTPException(404, "log entry not found")
    await db.delete(e)
    await db.commit()


@router.patch("/log/day/{day}", response_model=LogDayOut)
async def mark_log_day(
    day: date, body: LogDayPatch, db: AsyncSession = Depends(get_session),
):
    """Mark a day complete, or add a note to it.

    Completeness is DECLARED, never inferred. The app cannot tell "I
    stopped logging" from "I stopped eating", and guessing wrong in
    either direction corrupts every average built on top.
    """
    mark = await db.get(models.FoodLogDay, day)
    now = datetime.now(timezone.utc)
    if mark is None:
        mark = models.FoodLogDay(day=day, complete=False, updated_at=now)
        db.add(mark)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(mark, k, v)
    mark.updated_at = now
    await db.commit()
    return (await _log_days(db, day, day))[0]


@router.get("/log/stats", response_model=LogStatsOut)
async def log_stats(
    days: int = Query(default=30, ge=7, le=365),
    db: AsyncSession = Depends(get_session),
):
    """Averages over COMPLETE days only, or a refusal explaining why not.

    Partial days are excluded rather than counted, because a half-logged
    day reads as "you barely ate" and drags every average down in the
    direction that looks like success. The count of both is reported so
    the exclusion is visible instead of mysterious.
    """
    end = _local_today()
    begin = end - timedelta(days=days - 1)
    rows = await _log_days(db, begin, end)

    complete = [d for d in rows if d.complete]
    partial = [d for d in rows if not d.complete and d.entry_count > 0]

    out = LogStatsOut(
        complete_days=len(complete),
        partial_days=len(partial),
        days_needed=MIN_COMPLETE_DAYS,
    )

    # Per-meal fat is worth reporting even when whole-day averages are
    # not: a single meal is the unit of interest, so one complete meal is
    # already meaningful in a way that one complete day is not.
    meal_fats = [
        m.totals.get("fat_g")
        for d in rows for m in d.meals
        if m.totals.get("fat_g") is not None
    ]
    if meal_fats:
        import statistics

        out.meals_counted = len(meal_fats)
        out.median_meal_fat_g = round(statistics.median(meal_fats), 1)
        out.max_meal_fat_g = round(max(meal_fats), 1)

    if len(complete) < MIN_COMPLETE_DAYS:
        out.reason = (
            f"{len(complete)} complete day"
            f"{'' if len(complete) == 1 else 's'} in the last {days} "
            f"(needs {MIN_COMPLETE_DAYS}). Daily averages are left blank "
            "rather than computed from partly-logged days, which would "
            "read as eating less than you did."
        )
        return out

    kcals = [d.totals.get("kcal") for d in complete if d.totals.get("kcal") is not None]
    fats = [d.totals.get("fat_g") for d in complete if d.totals.get("fat_g") is not None]
    out.avg_kcal = round(sum(kcals) / len(kcals), 1) if kcals else None
    out.avg_fat_g = round(sum(fats) / len(fats), 1) if fats else None
    return out


# ------------------------------------------------- can-make + staples

#: Where the user's staple edits live, inside `user_profile.extra`.
STAPLES_KEY = "meal_staples"


async def _staple_prefs(db: AsyncSession) -> tuple[list[str], list[str]]:
    p = await db.get(models.UserProfile, 1)
    extra = (p.extra if p and p.extra else {}) or {}
    saved = extra.get(STAPLES_KEY) or {}
    return list(saved.get("added") or []), list(saved.get("removed") or [])


async def _pantry_concepts(db: AsyncSession) -> set[str]:
    """The set of concepts currently in the house.

    Reads through `foods.concept`, never through `foods.id`. That is the
    whole point of the concept layer: raw and grilled chicken breast are
    different rows and one thing to have in the house.
    """
    rows = (await db.execute(
        select(models.Food.concept)
        .select_from(models.PantryItem)
        .join(models.Food, models.Food.id == models.PantryItem.food_id)
        .where(models.Food.concept.is_not(None))
    )).scalars().all()
    out = {c for c in rows if c}

    # Hand-typed pantry entries have no food row. Their label is matched
    # against known concepts directly, so "rice" typed by hand still
    # cancels a recipe's rice.
    labels = (await db.execute(
        select(models.PantryItem.label)
        .where(models.PantryItem.food_id.is_(None))
        .where(models.PantryItem.label.is_not(None))
    )).scalars().all()
    out |= {(lbl or "").strip().lower() for lbl in labels if lbl}
    return out


async def _recipe_lines_for_matching(db: AsyncSession) -> list[dict[str, Any]]:
    recipes = (await db.execute(
        select(models.Recipe).where(models.Recipe.archived.is_(False))
    )).scalars().all()
    if not recipes:
        return []
    ings = (await db.execute(
        select(models.RecipeIngredient)
        .where(models.RecipeIngredient.recipe_id.in_([r.id for r in recipes]))
        .order_by(models.RecipeIngredient.order_index)
    )).scalars().all()
    food_ids = {i.food_id for i in ings if i.food_id is not None}
    concepts: dict[int, tuple[str | None, str]] = {}
    if food_ids:
        for fid, concept, name in (await db.execute(
            select(models.Food.id, models.Food.concept, models.Food.name)
            .where(models.Food.id.in_(food_ids))
        )).all():
            concepts[fid] = (concept, name)

    by_recipe: dict[int, list[dict[str, Any]]] = {}
    for i in ings:
        concept, name = (
            concepts.get(i.food_id, (None, "")) if i.food_id else (None, "")
        )
        if concept is None and i.food_id is None and i.raw_text:
            # A hand-typed line is matched on its own text. Imperfect,
            # but silently dropping it would inflate coverage.
            concept = i.raw_text.strip().lower() or None
        by_recipe.setdefault(i.recipe_id, []).append({
            "concept": concept,
            "label": name or i.raw_text or "unnamed",
        })

    return [
        {
            "id": r.id, "name": r.name, "servings": r.servings,
            "lines": by_recipe.get(r.id, []),
        }
        for r in recipes
    ]


@router.get("/can-make", response_model=CanMakeOut)
async def can_make(db: AsyncSession = Depends(get_session)):
    """Which of your own recipes you can cook right now.

    Deterministic and free — no AI call. This answers a question the
    suggestion card cannot: not "what could I eat" but "what can I make
    tonight from what is actually here".
    """
    added, removed = await _staple_prefs(db)
    staples = stap.effective_staples(added, removed)
    pantry = await _pantry_concepts(db)
    recipes = await _recipe_lines_for_matching(db)

    matches = cm.match_recipes(recipes, pantry, staples)
    return CanMakeOut(
        summary=cm.summarise(matches),
        recipes=[
            CanMakeRecipeOut(
                recipe_id=m.recipe_id, name=m.name, servings=m.servings,
                coverage=round(m.coverage, 3), cookable=m.cookable,
                uncertain=m.uncertain, have=m.have, missing=m.missing,
                from_staples=m.from_staples, unknown=m.unknown,
            )
            for m in matches
        ],
        unlock=[UnlockOut(**u) for u in cm.unlock_ranking(matches)],
        staples_assumed=sorted(staples),
        pantry_concepts=len(pantry),
    )


@router.get("/common-ingredients", response_model=list[CommonItemOut])
async def common_ingredients(db: AsyncSession = Depends(get_session)):
    """Everyday staples, one tap each.

    Filling a pantry by searching USDA is miserable, and typing plain
    names only appears to work — measured against this catalog, nine of
    twenty everyday staples match a concept when typed and the rest fail
    silently. This is the curated list every app in the category ships
    instead.

    Each entry resolves its search term through the SAME ranked search
    the pickers use, so an entry that stops resolving disappears rather
    than pointing at the wrong food.
    """
    have = await _pantry_concepts(db)

    slugs: dict[str, tuple[str, str]] = {}
    for cat, label, term in common.flat():
        hits = food_lib.search(term, ingredients_only=True, limit=1)
        if not hits:
            hits = food_lib.search(term, limit=1)
        if hits:
            slugs[hits[0]["slug"]] = (cat, label)

    rows: dict[str, models.Food] = {}
    if slugs:
        for f in (await db.execute(
            select(models.Food).where(models.Food.slug.in_(list(slugs)))
        )).scalars().all():
            rows[f.slug] = f

    out: list[CommonItemOut] = []
    for slug, (cat, label) in slugs.items():
        f = rows.get(slug)
        if f is None:
            continue
        out.append(CommonItemOut(
            label=label, category=cat, food_id=f.id, concept=f.concept,
            food_name=f.name,
            in_pantry=bool(f.concept and f.concept in have),
        ))
    return out


@router.post("/pantry/quick-add", response_model=dict)
async def quick_add_pantry(
    body: QuickAddIn, db: AsyncSession = Depends(get_session),
):
    """Add several foods to the pantry at once, without quantities.

    Skips anything already stocked under the same concept rather than
    creating a duplicate — tapping a chip twice should be harmless.
    """
    if not body.food_ids:
        return {"added": 0, "skipped": 0}

    foods = {
        f.id: f for f in (await db.execute(
            select(models.Food).where(models.Food.id.in_(body.food_ids))
        )).scalars().all()
    }
    have = await _pantry_concepts(db)

    added = skipped = 0
    now = datetime.now(timezone.utc)
    for fid in body.food_ids:
        f = foods.get(fid)
        if f is None:
            skipped += 1
            continue
        if f.concept and f.concept in have:
            skipped += 1
            continue
        db.add(models.PantryItem(food_id=f.id, updated_at=now))
        if f.concept:
            have.add(f.concept)
        added += 1

    await db.commit()
    return {"added": added, "skipped": skipped}


@router.get("/staples", response_model=StaplesOut)
async def get_staples(db: AsyncSession = Depends(get_session)):
    added, removed = await _staple_prefs(db)
    return StaplesOut(
        defaults=sorted(stap.DEFAULT_STAPLES),
        added=added, removed=removed,
        effective=sorted(stap.effective_staples(added, removed)),
    )


@router.put("/staples", response_model=StaplesOut)
async def put_staples(body: StaplesIn, db: AsyncSession = Depends(get_session)):
    """Scoped write — merges into `extra` rather than replacing it."""
    p = await db.get(models.UserProfile, 1)
    now = datetime.now(timezone.utc)
    if p is None:
        p = models.UserProfile(id=1, updated_at=now)
        db.add(p)
    extra = dict(p.extra or {})
    saved = dict(extra.get(STAPLES_KEY) or {})
    for k, v in body.model_dump(exclude_unset=True).items():
        saved[k] = v
    extra[STAPLES_KEY] = saved
    p.extra = extra
    p.updated_at = now
    await db.commit()

    added = list(saved.get("added") or [])
    removed = list(saved.get("removed") or [])
    return StaplesOut(
        defaults=sorted(stap.DEFAULT_STAPLES),
        added=added, removed=removed,
        effective=sorted(stap.effective_staples(added, removed)),
    )


@router.get("/stats", response_model=dict)
async def meals_stats(db: AsyncSession = Depends(get_session)):
    """Counts for the empty states and the nav badge."""
    foods_n = (await db.execute(
        select(func.count()).select_from(models.Food)
    )).scalar_one()
    user_foods_n = (await db.execute(
        select(func.count()).select_from(models.Food)
        .where(models.Food.source != "usda")
    )).scalar_one()
    recipes_n = (await db.execute(
        select(func.count()).select_from(models.Recipe)
        .where(models.Recipe.archived.is_(False))
    )).scalar_one()
    pantry_n = (await db.execute(
        select(func.count()).select_from(models.PantryItem)
    )).scalar_one()

    today = _local_today()
    expiring = (await db.execute(
        select(func.count()).select_from(models.PantryItem)
        .where(models.PantryItem.expires_on.is_not(None))
        .where(models.PantryItem.expires_on <= today + timedelta(days=3))
    )).scalar_one()

    return {
        "foods": foods_n,
        "user_foods": user_foods_n,
        "recipes": recipes_n,
        "pantry_items": pantry_n,
        "expiring_soon": expiring,
    }
