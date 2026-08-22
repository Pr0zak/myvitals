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
    unit_grams: dict[str, float] | None = None
    #: True when this food is a whole ingredient rather than a prepared
    #: dish. The recipe picker filters on it; the food log does not.
    is_ingredient: bool = False


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
    unit_grams: dict[str, float] | None = None


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
        unit_grams=f.unit_grams,
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


async def _hydrate_recipe(db: AsyncSession, r: models.Recipe) -> RecipeOut:
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
    return RecipeOut(
        id=r.id, name=r.name, servings=r.servings, prep_min=r.prep_min,
        cook_min=r.cook_min, method=r.method, notes=r.notes, tags=r.tags,
        source_url=r.source_url, archived=r.archived,
        created_at=r.created_at, updated_at=r.updated_at,
        ingredients=out_lines, totals=totals,
        per_serving=_divide(totals, r.servings), unresolved_count=unresolved,
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

    stmt = select(models.Food).where(
        or_(
            models.Food.slug.in_(list(order)),
            (models.Food.source != "usda") & (models.Food.name.ilike(f"%{q}%")),
        )
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
    return [await _hydrate_recipe(db, r) for r in rows]


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
    return await _hydrate_recipe(db, r)


@router.get("/recipes/{recipe_id}", response_model=RecipeOut)
async def get_recipe(recipe_id: int, db: AsyncSession = Depends(get_session)):
    r = await db.get(models.Recipe, recipe_id)
    if r is None:
        raise HTTPException(404, "recipe not found")
    return await _hydrate_recipe(db, r)


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
    return await _hydrate_recipe(db, r)


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
    hydrated = await _hydrate_recipe(db, r)
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
