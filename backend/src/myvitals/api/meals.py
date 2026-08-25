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
from math import ceil
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
from ..integrations import openfoodfacts
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
    #: The pack's barcode, when the food came from a scan. Without this
    #: stored, the "look here before the network" path in
    #: `lookup_barcode` never matches and every scan is a fresh fetch of
    #: whatever Open Food Facts currently says — including undoing any
    #: correction the user made.
    barcode: str | None = Field(default=None, max_length=20)


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


class SuggestedIngredientIn(BaseModel):
    """One ingredient as the model named it: a search term and an amount.

    Never nutrition. The same split as `PREP_PLAN_TOOL` — the model says
    what the meal is made of, the server says what that costs.
    """

    food_search: str = Field(min_length=1, max_length=200)
    #: Deliberately not `float | None`. A live run came back with
    #: `{"food_search": "Salt, table", "quantity": "pinch", "unit": "tsp"}` —
    #: which is a perfectly sensible thing for a person to write down, and
    #: which a float field rejects with a 422 that loses the WHOLE recipe
    #: over a pinch of salt. Anything non-numeric is carried through as
    #: text and dealt with below, rather than failing the save.
    quantity: float | str | None = None
    unit: str | None = Field(default=None, max_length=32)

    @property
    def numeric_quantity(self) -> float | None:
        """The amount as a number, or None when it is a word."""
        if isinstance(self.quantity, (int, float)):
            return float(self.quantity)
        try:
            return float(str(self.quantity).strip())
        except (TypeError, ValueError):
            return None

    @property
    def quantity_word(self) -> str | None:
        """The amount as the model wrote it, when it is not a number —
        "pinch", "to taste", "a handful". Kept so the user sees what was
        meant rather than a blank."""
        return None if self.numeric_quantity is not None else (
            str(self.quantity).strip() or None if self.quantity else None
        )


class SuggestionSaveIn(BaseModel):
    """An AI meal suggestion, on its way to becoming a real recipe."""

    name: str = Field(min_length=1, max_length=255)
    servings: int = Field(default=1, ge=1, le=100)
    method: str | None = None
    #: The model's reasoning, kept as provenance on the saved recipe.
    why: str | None = None
    est_prep_min: int | None = Field(default=None, ge=0, le=1440)
    ingredients: list[SuggestedIngredientIn] = Field(default_factory=list)


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


class RecentEntryOut(BaseModel):
    """One thing you log often enough to be worth offering back.

    Carries everything `LogEntryIn` needs, so re-logging is a single POST
    of the same shape rather than a search that has to find the food
    again. The portion travels with it: re-finding "chicken breast" is
    only half the work, and re-typing "1 piece" is the other half.
    """

    label: str
    food_id: int | None = None
    recipe_id: int | None = None
    quantity: float | None = None
    unit: str | None = None
    servings: float | None = None
    manual_kcal: float | None = None
    manual_fat_g: float | None = None
    #: The slot it is usually eaten at, so a breakfast suggestion does not
    #: default into dinner. The mode, not the latest — one late-night
    #: cereal should not re-file porridge as a snack forever.
    usual_slot: str = "dinner"
    #: How many times it has been logged in the window, and when last.
    #: Both are shown: "12 times, yesterday" and "12 times, in March" are
    #: very different recommendations.
    times: int
    last_day: date


class RepeatDayIn(BaseModel):
    """Copy one day's entries onto another."""

    source: date
    target: date | None = None


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
    #: The MEAL-6 concept for the food — the short, shopping-shaped name.
    #: Null for a hand-typed item and for prepared food, which has none.
    food_concept: str | None = None
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
        barcode=("".join(c for c in body.barcode if c.isdigit()) or None)
        if body.barcode else None,
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


class BarcodeHit(BaseModel):
    """What a scan found, and where it came from."""

    barcode: str
    #: Set when this barcode is already a food here — nothing to confirm,
    #: the client can use it straight away.
    food_id: int | None = None
    name: str
    #: "local" | "openfoodfacts". Rendered, because a crowd-sourced figure
    #: and one already in this catalog deserve different confidence.
    origin: str
    #: Per 100 g, the shape `foods` stores. Absent nutrients stay null.
    nutrition: dict[str, float | None] = Field(default_factory=dict)
    ingredients: str | None = None
    #: Verbatim from the pack — "1 oz (28.3 g)" — so the user can tell at
    #: a glance whether the entry matches the thing in their hand.
    package_size: str | None = None
    serving_size_text: str | None = None


@router.get("/foods/barcode/{code}", response_model=BarcodeHit | None)
async def lookup_barcode(code: str, db: AsyncSession = Depends(get_session)):
    """Find a packaged food by its barcode.

    MEALS_PLAN phase 7, deferred until the typing friction was measurable
    rather than predicted. It is: roughly half this diet is packaged and
    the bundled catalog is USDA, which carries generic foods and no
    brands — so every packaged entry began by typing a product name into
    a catalog that does not contain it.

    Looks here FIRST. A barcode scanned twice should return the food the
    user already corrected, not a fresh copy of whatever Open Food Facts
    currently says. That also means a scan costs no network call at all
    once the product is known.

    Returns 404 for a barcode neither source knows, which is an ordinary
    outcome rather than a failure — Open Food Facts is strong on European
    and own-brand products and thinner on US regional ones. The client
    offers the label scanner instead, which needs no database at all.

    NOTHING IS SAVED HERE. The result is a candidate; the user confirms
    it through the ordinary food-create path. Same rule as the photo
    features: a catalog that grows entries the user did not put there
    stops being trustworthy, and everything built on it goes with it.
    """
    digits = "".join(ch for ch in code if ch.isdigit())
    if not (7 <= len(digits) <= 14):
        raise HTTPException(422, "that is not a barcode")

    existing = (await db.execute(
        select(models.Food).where(models.Food.barcode == digits).limit(1),
    )).scalars().first()
    if existing is not None:
        return BarcodeHit(
            barcode=digits, food_id=existing.id, name=existing.name,
            origin="local",
            nutrition={
                "kcal": existing.kcal, "protein_g": existing.protein_g,
                "carbs_g": existing.carbs_g, "fat_g": existing.fat_g,
                "saturated_fat_g": existing.saturated_fat_g,
                "fiber_g": existing.fiber_g, "sugar_g": existing.sugar_g,
                "sodium_mg": existing.sodium_mg,
            },
            ingredients=existing.ingredients,
        )

    try:
        hit = await openfoodfacts.lookup(digits)
    except openfoodfacts.BarcodeLookupError as e:
        # A lookup that could not be COMPLETED is different from a barcode
        # that is not in the database, and the user can act on the first
        # (try again, or use the label scanner) but not the second.
        raise HTTPException(502, str(e)) from e
    if hit is None:
        raise HTTPException(404, "no product with that barcode")

    return BarcodeHit(
        barcode=digits, food_id=None, name=hit["name"], origin="openfoodfacts",
        nutrition={
            k: hit.get(k) for k in (
                "kcal", "protein_g", "carbs_g", "fat_g", "saturated_fat_g",
                "fiber_g", "sugar_g", "sodium_mg",
            )
        },
        ingredients=hit.get("ingredients"),
        package_size=hit.get("package_size"),
        serving_size_text=hit.get("serving_size_text"),
    )


@router.post("/recipes/from-suggestion", response_model=RecipeOut, status_code=201)
async def save_suggestion_as_recipe(
    body: SuggestionSaveIn, db: AsyncSession = Depends(get_session),
):
    """Turn an AI meal suggestion into a real, costed recipe.

    This exists because the recipe book could not fill itself. Suggestions
    were the only feature generating meal ideas, and a planned suggestion
    goes into the plan as a NOTE rather than a recipe — deliberately,
    since the model's `est_fat_g` is an estimate and a recipe carrying
    invented nutrition is worse than no recipe. The consequence was that
    the book stayed empty, and everything downstream of it stayed empty
    too: "cook from pantry" had nothing to check and the plan had nothing
    to plan.

    The way out is the prep planner's, not an exception to the rule. The
    model proposes ingredients as SEARCH TERMS with amounts; every one is
    resolved through `_resolve_food_term` — the same ranked catalog search
    the pickers use — and the recipe's nutrition is then computed from the
    catalog rows by the ordinary hydration path. The model's own
    `est_fat_g` and `est_kcal` are discarded here rather than carried
    across: if the two disagree, the catalog is right, and keeping both
    would leave the app showing two different numbers for one meal.

    An ingredient that does not resolve is kept as a hand-typed line, not
    dropped. That is what makes the saved recipe honest about itself — the
    recipe page already reports uncosted lines and marks the totals as
    partial, and a silently shorter ingredient list would hide the gap
    while making the fat total look better than it is.
    """
    lines: list[IngredientIn] = []
    unresolved: list[str] = []
    unmeasured: list[str] = []
    for ing in body.ingredients:
        term = ing.food_search.strip()
        if not term:
            continue
        food = await _resolve_food_term(db, term)
        if food is None:
            unresolved.append(term)
        qty = ing.numeric_quantity
        word = ing.quantity_word
        if word:
            # "a pinch" has no number and inventing one would put a
            # fabricated weight into a fat total. The line stays, uncosted
            # and labelled, and is named in the notes below.
            unmeasured.append(f"{word} {term}")
        lines.append(IngredientIn(
            food_id=food.id if food else None,
            # Keep the model's wording on an unmatched line so the user can
            # see what was meant and fix it, rather than an empty row. An
            # unmeasured amount is carried the same way.
            raw_text=(
                term if food is None
                else (f"{word} — amount not measurable" if word else None)
            ),
            quantity=qty,
            unit=food_lib.canonical_unit(ing.unit) if ing.unit and qty is not None else None,
        ))

    provenance = f"Saved from an AI suggestion on {_local_today().isoformat()}."
    if body.why:
        provenance += f"\n\n{body.why.strip()}"
    if unmeasured:
        provenance += (
            "\n\nThese amounts are not measurable and so are not costed: "
            + ", ".join(unmeasured) + "."
        )
    if unresolved:
        # Named, not hidden. The user is the only one who can say what
        # "smoked paprika" should have matched.
        provenance += (
            "\n\nThese ingredients did not match a catalog food and are "
            "not costed: " + ", ".join(unresolved) + "."
        )

    r = models.Recipe(
        name=body.name.strip(),
        servings=body.servings,
        prep_min=body.est_prep_min,
        cook_min=None,
        method=(body.method or None),
        notes=provenance,
        tags=["ai-suggested"],
        source_url=None,
        created_at=datetime.now(timezone.utc),
    )
    db.add(r)
    await db.flush()
    if lines:
        await _replace_ingredients(db, r.id, lines)
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
    concepts: dict[int, str | None] = {}
    if food_ids:
        for fid, name, concept in (await db.execute(
            select(models.Food.id, models.Food.name, models.Food.concept)
            .where(models.Food.id.in_(food_ids))
        )).all():
            names[fid] = name
            concepts[fid] = concept

    today = _local_today()
    out = [
        PantryOut(
            id=p.id, food_id=p.food_id, label=p.label,
            food_name=names.get(p.food_id) if p.food_id else None,
            # MEAL-6's concept is already the key this list is MATCHED on,
            # and it is also the right thing to READ it by. A pantry answers
            # "do I have this", and USDA's discriminating detail is noise
            # for that question: "Chicken, broiler or fryers, breast,
            # skinless, boneless, meat only, raw" buried the one word that
            # mattered. The full name is still sent alongside.
            food_concept=concepts.get(p.food_id) if p.food_id else None,
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



async def _shopping_from_lines(
    db: AsyncSession,
    lines: list[dict[str, Any]],
    *,
    name: str,
    begin: date,
    end: date,
    source_count: int,
) -> "ShoppingListOut":
    """Turn planned ingredient lines into a persisted shopping list.

    Shared by the recipe-plan list and the prep-plan list. It exists as
    one function because pantry subtraction is subtle — food id, then
    shared concept, then hand-typed label, and only a demonstrably
    complete cancellation may drop a line — and two copies of that
    would drift into telling the user to buy chicken on one screen and
    not the other.
    """
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
        name=name, start_day=begin, end_day=end, status="open",
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
    return _shopping_out(lst, kept, need_foods, source_count, covered_count)


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

    return await _shopping_from_lines(
        db, lines, name=body.name, begin=begin, end=end,
        source_count=len(planned),
    )


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


@router.get("/log/recent", response_model=list[RecentEntryOut])
async def recent_log_entries(
    limit: int = Query(default=12, ge=1, le=50),
    days: int = Query(default=90, ge=7, le=365),
    db: AsyncSession = Depends(get_session),
):
    """The things you actually eat, ranked so the common ones come back.

    Until this existed every log entry began at an empty search box, and
    then went through the ranked catalog search that exists precisely
    because finding the right food is hard. About half this diet is
    packaged or eaten out, which means the same items recur constantly,
    so the app was making the user re-find each one every time. Nothing
    new is recorded to support this — the log already holds it.

    Identity is the whole PORTION, not the food: `(food, recipe, label,
    quantity, unit, servings)`. Two eggs and six eggs are different
    things to re-log, and collapsing them would hand back a quantity the
    user then has to correct, which is most of the tap saving gone.

    Ranking is frequency with a recency half-life rather than either
    alone. Pure recency turns the list over completely after one unusual
    day; pure frequency pins it to whatever was eaten most six months ago
    and never surfaces a new staple. The half-life is 21 days: long
    enough that a fortnight away does not erase a habit, short enough
    that a genuinely dropped food falls off within a couple of months.
    """
    since = _local_today() - timedelta(days=days - 1)
    rows = (await db.execute(
        select(models.FoodLogEntry)
        .where(models.FoodLogEntry.day >= since)
        .order_by(models.FoodLogEntry.day.desc()),
    )).scalars().all()
    if not rows:
        return []

    # Resolve catalog names once. An entry keyed on a food carries no
    # label of its own, and grouping on a null label would fold every
    # catalog food into one bucket.
    food_ids = {r.food_id for r in rows if r.food_id is not None}
    names: dict[int, str] = {}
    if food_ids:
        for f in (await db.execute(
            select(models.Food).where(models.Food.id.in_(food_ids)),
        )).scalars().all():
            names[f.id] = f.name
    recipe_ids = {r.recipe_id for r in rows if r.recipe_id is not None}
    if recipe_ids:
        for rc in (await db.execute(
            select(models.Recipe).where(models.Recipe.id.in_(recipe_ids)),
        )).scalars().all():
            names[-rc.id] = rc.name

    today = _local_today()
    HALF_LIFE_DAYS = 21.0
    buckets: dict[tuple, dict[str, Any]] = {}
    for r in rows:
        # Flatten on READ as well as on write. `add_log_entry` collapses a
        # pasted nutrition block into one line, but entries made before
        # that landed still hold the raw multi-line text — and a chip row
        # is exactly where a wall of text does the most damage. Flattening
        # here also merges two entries that differ only in whitespace,
        # which would otherwise occupy two slots for the same meal.
        flat = _flatten_label(r.label)
        key = (r.food_id, r.recipe_id, (flat or "").lower(),
               r.quantity, r.unit, r.servings)
        age = (today - r.day).days
        weight = 0.5 ** (age / HALF_LIFE_DAYS)
        b = buckets.get(key)
        if b is None:
            label = (
                names.get(r.food_id) if r.food_id is not None
                else names.get(-r.recipe_id) if r.recipe_id is not None
                else None
            ) or flat or "Unnamed"
            b = buckets[key] = {
                "label": label, "food_id": r.food_id, "recipe_id": r.recipe_id,
                "quantity": r.quantity, "unit": r.unit, "servings": r.servings,
                "manual_kcal": r.manual_kcal, "manual_fat_g": r.manual_fat_g,
                "times": 0, "score": 0.0, "last_day": r.day,
                "slots": {},
            }
        b["times"] += 1
        b["score"] += weight
        if r.day > b["last_day"]:
            b["last_day"] = r.day
        b["slots"][r.slot] = b["slots"].get(r.slot, 0) + 1

    ranked = sorted(buckets.values(), key=lambda b: (-b["score"], -b["times"]))
    out: list[RecentEntryOut] = []
    for b in ranked[:limit]:
        # The MODE slot, not the most recent one: a single late-night
        # bowl of cereal should not re-file porridge as a snack forever.
        usual = max(b["slots"].items(), key=lambda kv: kv[1])[0] if b["slots"] else "dinner"
        out.append(RecentEntryOut(
            label=b["label"], food_id=b["food_id"], recipe_id=b["recipe_id"],
            quantity=b["quantity"], unit=b["unit"], servings=b["servings"],
            manual_kcal=b["manual_kcal"], manual_fat_g=b["manual_fat_g"],
            usual_slot=usual, times=b["times"], last_day=b["last_day"],
        ))
    return out


@router.post("/log/repeat-day", response_model=list[LogEntryOut], status_code=201)
async def repeat_day(
    body: RepeatDayIn, db: AsyncSession = Depends(get_session),
):
    """Copy every entry from one day onto another — "same as yesterday".

    Refuses when the source day is empty rather than silently succeeding
    with nothing: "I copied yesterday" and "yesterday had nothing to
    copy" are different answers, and the second one is the user's cue
    that they did not log yesterday either.

    It APPENDS. It does not replace what the target day already holds,
    because the user may have logged breakfast before reaching for this,
    and deleting that to make room would destroy a real record to save a
    tap. Duplicates are the user's to remove, and are visible.
    """
    target = body.target or _local_today()
    src = (await db.execute(
        select(models.FoodLogEntry)
        .where(models.FoodLogEntry.day == body.source)
        .order_by(models.FoodLogEntry.id),
    )).scalars().all()
    if not src:
        raise HTTPException(404, f"nothing logged on {body.source.isoformat()}")

    now = datetime.now(timezone.utc)
    made: list[models.FoodLogEntry] = []
    for r in src:
        e = models.FoodLogEntry(
            day=target, slot=r.slot, food_id=r.food_id, recipe_id=r.recipe_id,
            label=r.label, quantity=r.quantity, unit=r.unit,
            servings=r.servings, manual_kcal=r.manual_kcal,
            manual_fat_g=r.manual_fat_g, logged_at=now,
        )
        db.add(e)
        made.append(e)
    await db.commit()
    for e in made:
        await db.refresh(e)

    out: list[LogEntryOut] = []
    for e in made:
        food = await db.get(models.Food, e.food_id) if e.food_id else None
        rps = None
        if e.recipe_id:
            rc = await db.get(models.Recipe, e.recipe_id)
            if rc is not None:
                rps = (await _hydrate_recipe(db, rc, history=[])).per_serving
        nut, source, reason = _entry_nutrition(e, food, rps)
        out.append(LogEntryOut(
            id=e.id, day=e.day, slot=e.slot, food_id=e.food_id,
            recipe_id=e.recipe_id,
            label=(food.name if food else (e.label or "Unnamed")),
            quantity=e.quantity, unit=e.unit, servings=e.servings,
            logged_at=e.logged_at, nutrition=nut, source=source,
            unresolved_reason=reason,
        ))
    return out


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


# ── Weekly component prep planner (MEAL-9) ───────────────────────────
#
# "Make meals on the weekend for the week ahead" — one cooking session,
# a handful of components, and the week assembled from them.
#
# The division of labour with the AI is the important part and is
# documented at length in `analytics/prep.py`: the model proposes what to
# cook and how to combine it; every number rendered next to that comes
# from the food catalog through `analytics/prep.py`, computed here. The
# model never emits a calorie.
#
# Nothing on this surface scores adherence. A meal can be accepted,
# skipped or eaten out, and the last two are outcomes rather than
# failures — they release their portions back into `leftover_ledger` so
# the app can say "two portions of chicken spare, Thursday's bowl still
# works on Saturday". A planner that turns red on Wednesday is a planner
# that gets deleted in week two, which is the failure mode this whole
# feature is shaped around avoiding.


class PrepComponentOut(BaseModel):
    id: int
    name: str
    kind: str
    food_id: int | None = None
    food_name: str | None = None
    quantity: float | None = None
    unit: str | None = None
    portions: int
    prep_note: str | None = None
    done: bool
    order_index: int
    grams_total: float | None = None
    grams_per_portion: float | None = None
    #: Per-portion nutrition from the catalog. Null when the component
    #: could not be costed — never zero.
    per_portion: dict[str, float | None] | None = None
    unresolved: bool = False
    unresolved_reason: str | None = None
    #: Portions cooked minus portions the live plan consumes.
    spare: float | None = None
    short: bool = False


class PrepMealOut(BaseModel):
    id: int
    day: date
    slot: str
    name: str
    status: str
    uses: list[dict[str, Any]] = []
    est_kcal: float | None = None
    est_protein_g: float | None = None
    est_fat_g: float | None = None
    assembly_note: str | None = None
    order_index: int
    #: Same deterministic fat verdict every other surface uses, so the
    #: planner cannot disagree with the recipe page about dinner.
    fat_assessment: dict[str, Any] | None = None
    unresolved_count: int = 0


class PrepDayOut(BaseModel):
    day: date
    weekday: str
    meals: list[PrepMealOut]
    planned_kcal: float | None = None
    planned_protein_g: float | None = None
    planned_fat_g: float | None = None
    budget_kcal: float | None = None
    budget_protein_g: float | None = None
    off_plan: int = 0


class PrepPlanOut(BaseModel):
    id: int
    start_day: date
    days: int
    status: str
    target_kcal: int | None = None
    target_protein_g: int | None = None
    target_basis: str | None = None
    notes: str | None = None
    headline: str | None = None
    components: list[PrepComponentOut]
    schedule: list[PrepDayOut]
    #: Slot coverage. `uncovered_kcal` is what the plan deliberately does
    #: NOT include (breakfast, usually) — surfaced so the client can say
    #: so rather than presenting the week as short of target.
    budgets: dict[str, Any] = {}
    warnings: list[str] = []
    shopping_list_id: int | None = None


class PrepGenerateIn(BaseModel):
    start: date | None = None
    days: int = Field(default=5, ge=1, le=7)
    slots: list[str] = Field(default_factory=lambda: ["lunch", "dinner"])


class PrepPlanPatch(BaseModel):
    status: str | None = None
    notes: str | None = None


class PrepComponentPatch(BaseModel):
    done: bool | None = None
    quantity: float | None = None
    unit: str | None = None
    portions: int | None = None
    name: str | None = None


class PrepMealPatch(BaseModel):
    status: str | None = None
    day: date | None = None
    name: str | None = None


def _prep_note_key(plan: models.PrepPlan) -> tuple[str | None, str | None]:
    """Split the stored notes blob into headline and the rest.

    The headline is the model's one-line description of the week and the
    notes are its caveats. They live in one Text column because they are
    always written and read together, and a second column would have
    meant a second migration for one string.
    """
    if not plan.notes:
        return None, None
    head, _, rest = plan.notes.partition("\n\n")
    return (head or None), (rest or None)


async def _prep_hydrate(
    db: AsyncSession, plan: models.PrepPlan,
) -> PrepPlanOut:
    """Load a plan and compute every number on it.

    Called by every route that returns a plan, so a client never has to
    re-derive anything and the two surfaces cannot disagree.
    """
    from ..analytics import prep as prep_lib

    comps = (await db.execute(
        select(models.PrepComponent)
        .where(models.PrepComponent.plan_id == plan.id)
        .order_by(models.PrepComponent.order_index)
    )).scalars().all()
    meals = (await db.execute(
        select(models.PrepMeal)
        .where(models.PrepMeal.plan_id == plan.id)
        .order_by(models.PrepMeal.day, models.PrepMeal.order_index)
    )).scalars().all()

    food_ids = {c.food_id for c in comps if c.food_id is not None}
    food_rows: dict[int, models.Food] = {}
    if food_ids:
        for f in (await db.execute(
            select(models.Food).where(models.Food.id.in_(food_ids))
        )).scalars().all():
            food_rows[f.id] = f
    food_dicts = {fid: _food_dict(f) for fid, f in food_rows.items()}

    resolved = prep_lib.resolve_components(
        [
            {
                "id": c.id, "name": c.name, "kind": c.kind,
                "food_id": c.food_id, "quantity": c.quantity, "unit": c.unit,
                "portions": c.portions, "prep_note": c.prep_note,
                "done": c.done, "order_index": c.order_index,
            }
            for c in comps
        ],
        food_dicts,
    )
    by_id = {c["id"]: c for c in resolved}

    diet = await _diet_settings(db)
    fat_target = diet.get("fat_per_meal_target_g")

    meal_dicts: list[dict[str, Any]] = []
    for m in meals:
        uses = m.component_ids or []
        cost = prep_lib.cost_meal(uses, by_id)
        nut = cost["nutrition"] or {}
        est_kcal = nut.get("kcal")
        est_protein = nut.get("protein_g")
        est_fat = nut.get("fat_g")
        meal_dicts.append({
            "id": m.id, "day": m.day, "slot": m.slot, "name": m.name,
            "status": m.status, "uses": uses,
            "est_kcal": est_kcal, "est_protein_g": est_protein,
            "est_fat_g": est_fat,
            "assembly_note": m.assembly_note, "order_index": m.order_index,
            "fat_assessment": nutri.assess_meal_fat(
                est_fat, target_g=fat_target, history_fat_g=[],
            ),
            "unresolved_count": cost["unresolved_count"],
        })

    ledger = {
        r["component_id"]: r
        for r in prep_lib.leftover_ledger(resolved, meal_dicts)
    }
    budgets = prep_lib.slot_budgets(
        plan.target_kcal, plan.target_protein_g,
        sorted({m["slot"] for m in meal_dicts}, key=lambda s: prep_lib.SLOT_ORDER.get(s, 9))
        or ["lunch", "dinner"],
    )
    rows = prep_lib.day_rollup(
        meal_dicts, plan.target_kcal, plan.target_protein_g, budgets,
    )

    # Days with no meals at all still appear, so the week reads as a week
    # rather than as a list that mysteriously skips Wednesday.
    have = {r["day"] for r in rows}
    for i in range(plan.days):
        d = plan.start_day + timedelta(days=i)
        if d not in have:
            share = budgets.get("covered_share") or 1.0
            rows.append({
                "day": d, "meals": [], "planned_kcal": None,
                "planned_protein_g": None, "planned_fat_g": None,
                "budget_kcal": (
                    round(plan.target_kcal * share) if plan.target_kcal else None
                ),
                "budget_protein_g": (
                    round(plan.target_protein_g * share)
                    if plan.target_protein_g else None
                ),
                "off_plan": 0,
            })
    rows.sort(key=lambda r: r["day"])

    lst_id = (await db.execute(
        select(models.ShoppingList.id)
        .where(models.ShoppingList.start_day == plan.start_day)
        .where(models.ShoppingList.name.ilike("%prep%"))
        .order_by(models.ShoppingList.id.desc())
        .limit(1)
    )).scalar_one_or_none()

    headline, rest = _prep_note_key(plan)
    return PrepPlanOut(
        id=plan.id, start_day=plan.start_day, days=plan.days,
        status=plan.status, target_kcal=plan.target_kcal,
        target_protein_g=plan.target_protein_g,
        target_basis=plan.target_basis,
        headline=headline, notes=rest,
        components=[
            PrepComponentOut(
                **{k: v for k, v in c.items() if k != "per_portion"},
                per_portion=c.get("per_portion"),
                food_name=(
                    food_rows[c["food_id"]].name
                    if c.get("food_id") in food_rows else None
                ),
                spare=ledger.get(c["id"], {}).get("spare"),
                short=ledger.get(c["id"], {}).get("short", False),
            )
            for c in resolved
        ],
        schedule=[
            PrepDayOut(
                day=r["day"],
                weekday=r["day"].strftime("%A"),
                meals=[PrepMealOut(**m) for m in r["meals"]],
                planned_kcal=r["planned_kcal"],
                planned_protein_g=r["planned_protein_g"],
                planned_fat_g=r["planned_fat_g"],
                budget_kcal=r["budget_kcal"],
                budget_protein_g=r["budget_protein_g"],
                off_plan=r["off_plan"],
            )
            for r in rows
        ],
        budgets=budgets,
        warnings=prep_lib.keeps_until_warnings(
            resolved, meal_dicts, plan.start_day,
        ),
        shopping_list_id=lst_id,
    )


@router.get("/prep/targets", response_model=dict)
async def prep_targets(db: AsyncSession = Depends(get_session)):
    """Daily energy and protein targets for this user, or why not.

    Separate from plan generation because the numbers are useful on their
    own, cost nothing to compute, and a user should be able to see and
    sanity-check what a plan will be built against BEFORE spending an AI
    call on it.
    """
    from ..integrations.claude import compute_targets_for_user

    targets = await compute_targets_for_user(db)
    diet = await _diet_settings(db)
    override = diet.get("daily_kcal_target")
    if override:
        # An explicitly typed target is a decision, not another estimate
        # to be averaged in. Both are returned so the UI can show that
        # the equation was overridden rather than silently ignored.
        targets["override_kcal"] = override
    targets["fat_per_meal_target_g"] = diet.get("fat_per_meal_target_g")
    return targets


@router.get("/prep", response_model=list[dict])
async def list_prep_plans(
    limit: int = Query(default=12, ge=1, le=60),
    db: AsyncSession = Depends(get_session),
):
    plans = (await db.execute(
        select(models.PrepPlan)
        .order_by(models.PrepPlan.start_day.desc())
        .limit(limit)
    )).scalars().all()
    out = []
    for p in plans:
        head, _ = _prep_note_key(p)
        n_comp = (await db.execute(
            select(func.count(models.PrepComponent.id))
            .where(models.PrepComponent.plan_id == p.id)
        )).scalar_one()
        n_meal = (await db.execute(
            select(func.count(models.PrepMeal.id))
            .where(models.PrepMeal.plan_id == p.id)
        )).scalar_one()
        out.append({
            "id": p.id, "start_day": p.start_day.isoformat(), "days": p.days,
            "status": p.status, "headline": head,
            "target_kcal": p.target_kcal,
            "components": n_comp, "meals": n_meal,
        })
    return out


@router.get("/prep/current", response_model=PrepPlanOut | None)
async def current_prep_plan(db: AsyncSession = Depends(get_session)):
    """The plan covering today, or the next one starting.

    Resolved against the LOCAL day. The container runs UTC and the user
    does not; a planner that rolls over at 7pm would show tomorrow's
    dinner at dinner time.
    """
    today = _local_today()
    plan = (await db.execute(
        select(models.PrepPlan)
        .where(models.PrepPlan.start_day <= today)
        .order_by(models.PrepPlan.start_day.desc())
        .limit(1)
    )).scalar_one_or_none()
    if plan is not None and (
        plan.start_day + timedelta(days=plan.days - 1) >= today
    ):
        return await _prep_hydrate(db, plan)
    upcoming = (await db.execute(
        select(models.PrepPlan)
        .where(models.PrepPlan.start_day > today)
        .order_by(models.PrepPlan.start_day)
        .limit(1)
    )).scalar_one_or_none()
    if upcoming is not None:
        return await _prep_hydrate(db, upcoming)
    return None


@router.get("/prep/{plan_id}", response_model=PrepPlanOut)
async def get_prep_plan(plan_id: int, db: AsyncSession = Depends(get_session)):
    plan = await db.get(models.PrepPlan, plan_id)
    if plan is None:
        raise HTTPException(404, "Prep plan not found")
    return await _prep_hydrate(db, plan)


async def _resolve_food_term(
    db: AsyncSession, term: str,
) -> models.Food | None:
    """Best catalog match for a plain ingredient name.

    Ingredients first, because that is what a batch-cooking component is
    — a search for "chicken breast" must land on the raw cut, not on a
    restaurant entree. Falls back to the whole catalog so an unusual term
    still resolves to something rather than to nothing.

    Returns None rather than a poor guess. A component with no food is
    rendered as uncosted and the user is told which one, which is far
    better than a plan whose protein total quietly assumes the wrong
    food.
    """
    if not term or not term.strip():
        return None
    for ingredients_only in (True, False):
        ranked = food_lib.search(
            term, ingredients_only=ingredients_only, limit=5,
        )
        if not ranked:
            continue
        slugs = [r["slug"] for r in ranked]
        rows = {
            f.slug: f for f in (await db.execute(
                select(models.Food).where(models.Food.slug.in_(slugs))
            )).scalars().all()
        }
        for s in slugs:
            if s in rows:
                return rows[s]
    return None


@router.post("/prep/generate", response_model=PrepPlanOut, status_code=201)
async def generate_prep_plan(
    body: PrepGenerateIn, db: AsyncSession = Depends(get_session),
):
    """Generate a week of batch cooking and persist it.

    One AI call. The model returns components and assemblies; every
    number attached to them is computed here from the catalog. See
    `analytics/prep.py` for why that split is not negotiable.

    Any existing plan for the same start day is replaced, because two
    overlapping plans for one week is not a state a user ever wants and
    silently stacking them is how the list view fills with drafts.
    """
    import json as _json

    from ..api.ai import _check_and_bump_quota, _get_config
    from ..integrations.claude import compute_targets_for_user, prep_plan

    begin = body.start or _week_start(_local_today())
    slots = [s for s in body.slots if s in ("breakfast", "lunch", "dinner", "snack")]
    if not slots:
        slots = ["lunch", "dinner"]

    cfg = await _get_config(db)
    await _check_and_bump_quota(db, cfg)
    result = await prep_plan(
        db, cfg, start_day=begin, days=body.days, slots=slots,
    )
    cfg.calls_today += 1
    try:
        data = _json.loads(result.content)
    except ValueError:
        raise HTTPException(502, "The planner returned an unreadable plan.")

    raw_components = data.get("components") or []
    raw_meals = data.get("meals") or []
    if not raw_components or not raw_meals:
        raise HTTPException(
            502,
            "The planner returned no meals. Try again — if it keeps "
            "happening, check the AI provider under Settings → AI.",
        )

    targets = await compute_targets_for_user(db)
    diet = await _diet_settings(db)
    target_kcal = diet.get("daily_kcal_target") or (
        targets.get("target_kcal") if targets.get("ok") else None
    )
    target_protein = (
        diet.get("daily_protein_target_g")
        or (targets.get("protein_g") if targets.get("ok") else None)
    )
    basis = (
        "explicit" if diet.get("daily_kcal_target")
        else (targets.get("basis") if targets.get("ok") else None)
    )

    # Replace rather than stack. CASCADE on the FKs takes the children.
    for old in (await db.execute(
        select(models.PrepPlan).where(models.PrepPlan.start_day == begin)
    )).scalars().all():
        await db.delete(old)
    await db.flush()

    headline = (data.get("headline") or "").strip()
    notes = [str(n).strip() for n in (data.get("notes") or []) if str(n).strip()]
    plan = models.PrepPlan(
        start_day=begin, days=body.days, status="draft",
        target_kcal=int(target_kcal) if target_kcal else None,
        target_protein_g=int(target_protein) if target_protein else None,
        target_basis=basis,
        notes="\n\n".join([headline] + notes) if (headline or notes) else None,
        created_at=datetime.now(timezone.utc),
    )
    db.add(plan)
    await db.flush()

    # Components, in prep-sheet order: protein and grain go on first
    # because they take longest, sauce is made while they cook.
    from ..analytics import prep as prep_lib
    from ..analytics.prep import COMPONENT_KINDS, KIND_ORDER, MEAL_STATUSES

    prepared: list[tuple[int, models.PrepComponent]] = []
    index_map: dict[int, models.PrepComponent] = {}
    ordered = sorted(
        enumerate(raw_components),
        key=lambda p: KIND_ORDER.get(str(p[1].get("kind") or "other"), 9),
    )
    for order, (orig_index, c) in enumerate(ordered):
        kind = str(c.get("kind") or "other")
        if kind not in COMPONENT_KINDS:
            kind = "other"
        food = await _resolve_food_term(db, str(c.get("food_search") or ""))
        try:
            qty = float(c.get("quantity")) if c.get("quantity") is not None else None
        except (TypeError, ValueError):
            qty = None
        try:
            portions = max(1, int(c.get("portions") or 1))
        except (TypeError, ValueError):
            portions = 1
        row = models.PrepComponent(
            plan_id=plan.id,
            name=str(c.get("name") or "Unnamed")[:255],
            kind=kind,
            food_id=food.id if food else None,
            quantity=qty,
            unit=food_lib.canonical_unit(c.get("unit")) or None,
            portions=portions,
            prep_note=(str(c["prep_note"])[:500] if c.get("prep_note") else None),
            done=False,
            order_index=order,
        )
        db.add(row)
        prepared.append((orig_index, row))
        index_map[orig_index] = row
    await db.flush()

    # Meals. `uses` arrives as indices into the model's own component
    # array, which is why the original index is carried through the
    # reorder above rather than the sorted position.
    per_day_counter: dict[date, int] = {}
    for m in raw_meals:
        try:
            di = int(m.get("day_index"))
        except (TypeError, ValueError):
            continue
        if di < 0 or di >= body.days:
            continue
        day = begin + timedelta(days=di)
        slot = str(m.get("slot") or "dinner")
        if slot not in ("breakfast", "lunch", "dinner", "snack"):
            slot = "dinner"
        uses = []
        for u in (m.get("uses") or []):
            try:
                ci = int(u.get("component"))
                portions = float(u.get("portions") or 1)
            except (TypeError, ValueError):
                continue
            comp = index_map.get(ci)
            if comp is None:
                continue
            uses.append({"component_id": comp.id, "portions": portions})
        idx = per_day_counter.get(day, 0)
        per_day_counter[day] = idx + 1
        db.add(models.PrepMeal(
            plan_id=plan.id, day=day, slot=slot,
            name=str(m.get("name") or "Meal")[:255],
            status="suggested",
            component_ids=uses,
            assembly_note=(
                str(m["assembly_note"])[:500] if m.get("assembly_note") else None
            ),
            order_index=idx,
        ))

    await db.flush()

    # ── Reconcile portions against what the meals actually draw ──────
    #
    # The prompt states the balance rule and the model still gets it
    # wrong. The first live plan cooked 6 portions of chicken and then
    # assigned 11.5 of them across the week. Shipping that means shopping
    # for 1.2 kg and running out on Wednesday — worse than useless,
    # because the user followed the plan and the plan was wrong.
    #
    # The meals ARE the week, so the batch has to cover them. Scaling
    # `quantity` in step with `portions` holds grams-per-portion fixed,
    # so every per-meal figure is unchanged and only the shopping
    # quantity moves. A SURPLUS is left alone: cooking more than the week
    # needs is the flexibility feature, and the ledger reports it as
    # spare rather than as an error.
    meal_rows = (await db.execute(
        select(models.PrepMeal).where(models.PrepMeal.plan_id == plan.id)
    )).scalars().all()
    demand: dict[int, float] = {}
    for m in meal_rows:
        for u in (m.component_ids or []):
            cid = u.get("component_id")
            if cid is not None:
                demand[cid] = demand.get(cid, 0.0) + float(u.get("portions") or 1)

    scaled: list[str] = []
    for _, row in prepared:
        want = demand.get(row.id, 0.0)
        if want <= row.portions + 1e-6:
            continue
        needed = ceil(want)
        if row.quantity is not None:
            row.quantity = round(row.quantity * needed / row.portions, 2)
        scaled.append(f"{row.name} ({row.portions} to {needed} portions)")
        row.portions = needed

    extra_notes: list[str] = []
    if scaled:
        # Say so out loud. A silently doubled shopping quantity is the
        # kind of correction that erodes trust in every other number.
        extra_notes.append(
            "Batch sizes were raised to cover the meals planned: "
            + "; ".join(scaled) + "."
        )

    await db.flush()
    hydrated = await _prep_hydrate(db, plan)

    # ── Grow the batches to reach the energy budget ──────────────────
    #
    # The model consistently undersizes: live plans came back at 40-63%
    # of the budget for the slots they cover, a 700 kcal dinner rendered
    # as a chicken breast and 50 g of grain. Two prompt revisions did not
    # fix it. Since every quantity is already the server's to compute,
    # the honest repair is arithmetic rather than a third prompt
    # sentence, and a planner that lands at 40% of target does the
    # opposite of what a weight-loss plan is for.
    #
    # Sauce is held out — see SCALABLE_KINDS. Uniformly tripling the
    # olive oil to close a calorie gap is the single worst way to close
    # it for someone whose per-meal fat is a medical constraint.
    covered_share = hydrated.budgets.get("covered_share") or 1.0
    day_budget = (target_kcal * covered_share) if target_kcal else None
    factor = prep_lib.energy_scale_factor(
        [
            {
                "id": c.id, "kind": c.kind,
                "per_portion": (
                    next(
                        (h.per_portion for h in hydrated.components if h.id == c.id),
                        None,
                    )
                ),
                "unresolved": any(
                    h.id == c.id and h.unresolved for h in hydrated.components
                ),
            }
            for _, c in prepared
        ],
        [
            {"day": m.day, "status": m.status, "uses": m.component_ids or []}
            for m in meal_rows
        ],
        day_budget,
    )
    if factor > 1.0:
        for _, row in prepared:
            if row.kind in prep_lib.SCALABLE_KINDS and row.quantity is not None:
                row.quantity = round(row.quantity * factor, 2)
        await db.flush()
        hydrated = await _prep_hydrate(db, plan)
        extra_notes.append(
            f"Portion sizes were scaled up {factor:g}x to reach your "
            f"{round(day_budget)} kcal budget for these meals — the plan "
            f"came back light. The sauce was left alone, since fat per "
            f"meal is not something to scale."
        )

    # ── Note an under-target week as a fact about the PLAN ───────────
    #
    # Computed once, here, against the plan as generated — never on read.
    # Recomputing it in `_prep_hydrate` would turn it into a comment on
    # the user's behaviour the moment they skipped a meal, and nothing in
    # this feature does that.
    lean = [
        d for d in hydrated.schedule
        if d.budget_kcal and d.planned_kcal
        and d.planned_kcal < d.budget_kcal * 0.8
    ]
    if lean and len(lean) >= max(2, len(hydrated.schedule) // 2):
        avg = round(sum(d.planned_kcal for d in lean) / len(lean))
        avg_budget = round(sum(d.budget_kcal for d in lean) / len(lean))
        extra_notes.append(
            f"These meals come to about {avg} kcal on most days against a "
            f"{avg_budget} kcal budget for the slots they cover. That is "
            f"the plan being light, not you — add a side, a bigger grain "
            f"portion, or regenerate for larger batches."
        )

    if extra_notes:
        plan.notes = "\n\n".join([p for p in [plan.notes, *extra_notes] if p])

    await db.commit()
    await db.refresh(plan)
    assert MEAL_STATUSES  # imported for the patch route's validation
    return await _prep_hydrate(db, plan)


@router.patch("/prep/{plan_id}", response_model=PrepPlanOut)
async def patch_prep_plan(
    plan_id: int, body: PrepPlanPatch, db: AsyncSession = Depends(get_session),
):
    plan = await db.get(models.PrepPlan, plan_id)
    if plan is None:
        raise HTTPException(404, "Prep plan not found")
    if body.status is not None:
        if body.status not in ("draft", "active", "done"):
            raise HTTPException(422, "status must be draft, active or done")
        plan.status = body.status
    if body.notes is not None:
        head, _ = _prep_note_key(plan)
        plan.notes = "\n\n".join([p for p in (head, body.notes) if p]) or None
    await db.commit()
    await db.refresh(plan)
    return await _prep_hydrate(db, plan)


@router.delete("/prep/{plan_id}", status_code=204)
async def delete_prep_plan(plan_id: int, db: AsyncSession = Depends(get_session)):
    plan = await db.get(models.PrepPlan, plan_id)
    if plan is None:
        raise HTTPException(404, "Prep plan not found")
    await db.delete(plan)
    await db.commit()


@router.patch("/prep/component/{component_id}", response_model=PrepPlanOut)
async def patch_prep_component(
    component_id: int,
    body: PrepComponentPatch,
    db: AsyncSession = Depends(get_session),
):
    """Tick a component off the prep sheet, or correct its amount.

    Returns the whole rehydrated plan rather than the component, because
    changing a quantity changes every meal that draws on it — the same
    one-round-trip rule the workout skip endpoint follows.
    """
    comp = await db.get(models.PrepComponent, component_id)
    if comp is None:
        raise HTTPException(404, "Component not found")
    if body.done is not None:
        comp.done = body.done
    if body.name is not None:
        comp.name = body.name[:255]
    if body.quantity is not None:
        comp.quantity = body.quantity
    if body.unit is not None:
        comp.unit = food_lib.canonical_unit(body.unit) or None
    if body.portions is not None:
        comp.portions = max(1, body.portions)
    await db.commit()
    plan = await db.get(models.PrepPlan, comp.plan_id)
    return await _prep_hydrate(db, plan)


@router.patch("/prep/meal/{meal_id}", response_model=PrepPlanOut)
async def patch_prep_meal(
    meal_id: int, body: PrepMealPatch, db: AsyncSession = Depends(get_session),
):
    """Accept a meal, skip it, or say you ate out.

    All three are ordinary outcomes. Skipping and eating out release the
    meal's portions back into the ledger so the plan can tell you what is
    spare, instead of leaving you with unexplained food in the fridge and
    a week that has quietly gone wrong.
    """
    from ..analytics.prep import MEAL_STATUSES

    meal = await db.get(models.PrepMeal, meal_id)
    if meal is None:
        raise HTTPException(404, "Meal not found")
    if body.status is not None:
        if body.status not in MEAL_STATUSES:
            raise HTTPException(
                422, "status must be one of " + ", ".join(sorted(MEAL_STATUSES)),
            )
        meal.status = body.status
    if body.day is not None:
        plan = await db.get(models.PrepPlan, meal.plan_id)
        last = plan.start_day + timedelta(days=plan.days - 1)
        if not (plan.start_day <= body.day <= last):
            raise HTTPException(
                422,
                f"That day is outside the plan "
                f"({plan.start_day.isoformat()} to {last.isoformat()}).",
            )
        meal.day = body.day
    if body.name is not None:
        meal.name = body.name[:255]
    await db.commit()
    plan = await db.get(models.PrepPlan, meal.plan_id)
    return await _prep_hydrate(db, plan)


@router.post("/prep/{plan_id}/shopping-list", response_model=ShoppingListOut,
             status_code=201)
async def prep_shopping_list(
    plan_id: int, db: AsyncSession = Depends(get_session),
):
    """Everything to buy for the week, minus what is already in the house.

    Runs through the SAME `_shopping_from_lines` the recipe planner uses,
    so pantry subtraction, gram merging and the "some" fallback behave
    identically on both. A second implementation here would eventually
    disagree with the other one about whether you need chicken.
    """
    from ..analytics import prep as prep_lib

    plan = await db.get(models.PrepPlan, plan_id)
    if plan is None:
        raise HTTPException(404, "Prep plan not found")

    comps = (await db.execute(
        select(models.PrepComponent)
        .where(models.PrepComponent.plan_id == plan.id)
        .order_by(models.PrepComponent.order_index)
    )).scalars().all()
    if not comps:
        raise HTTPException(422, "This plan has nothing to cook yet.")

    food_ids = {c.food_id for c in comps if c.food_id is not None}
    food_dicts: dict[int, dict[str, Any]] = {}
    if food_ids:
        for f in (await db.execute(
            select(models.Food).where(models.Food.id.in_(food_ids))
        )).scalars().all():
            food_dicts[f.id] = _food_dict(f)

    resolved = prep_lib.resolve_components(
        [
            {
                "id": c.id, "name": c.name, "kind": c.kind,
                "food_id": c.food_id, "quantity": c.quantity,
                "unit": c.unit, "portions": c.portions,
            }
            for c in comps
        ],
        food_dicts,
    )
    lines = prep_lib.component_shopping_lines(resolved)
    end = plan.start_day + timedelta(days=plan.days - 1)
    return await _shopping_from_lines(
        db, lines,
        # "%-d" would be cleaner but is not portable; strip the zero.
        # An ISO date is a storage format, not what a week is called
        # when someone is standing in a shop reading the list.
        name=("Prep week of "
              + plan.start_day.strftime("%a %d %b").replace(" 0", " ")),
        begin=plan.start_day, end=end, source_count=len(comps),
    )


@router.post("/prep/meal/{meal_id}/log", response_model=dict, status_code=201)
async def log_prep_meal(
    meal_id: int, db: AsyncSession = Depends(get_session),
):
    """Log a planned meal into the food diary and mark it accepted.

    This closes the loop the rest of the meals feature already has —
    without it the planner is a separate universe from the log, and the
    user would be retyping a meal the app already knows the composition
    of. One entry per component so the diary keeps the real per-food
    breakdown rather than one opaque line.
    """
    meal = await db.get(models.PrepMeal, meal_id)
    if meal is None:
        raise HTTPException(404, "Meal not found")

    comp_ids = [
        u.get("component_id") for u in (meal.component_ids or [])
        if u.get("component_id")
    ]
    comps: dict[int, models.PrepComponent] = {}
    if comp_ids:
        for c in (await db.execute(
            select(models.PrepComponent)
            .where(models.PrepComponent.id.in_(comp_ids))
        )).scalars().all():
            comps[c.id] = c

    created = 0
    for u in (meal.component_ids or []):
        comp = comps.get(u.get("component_id"))
        if comp is None:
            continue
        share = float(u.get("portions") or 1)
        portions = max(1, comp.portions)
        # The logged quantity is this meal's share of the whole batch,
        # in the batch's own unit — so a quarter of a 1 kg tray of
        # chicken logs as 250 g, not as "1 portion" of something the
        # diary cannot cost.
        qty = (
            (comp.quantity / portions) * share
            if comp.quantity is not None else None
        )
        db.add(models.FoodLogEntry(
            day=meal.day,
            slot=meal.slot,
            food_id=comp.food_id,
            label=comp.name if comp.food_id is None else None,
            quantity=qty,
            unit=comp.unit,
            logged_at=datetime.now(timezone.utc),
        ))
        created += 1

    if not created:
        raise HTTPException(
            422, "This meal has no components to log.",
        )
    meal.status = "accepted"
    await db.commit()
    return {"logged": created, "day": meal.day.isoformat(), "slot": meal.slot}
