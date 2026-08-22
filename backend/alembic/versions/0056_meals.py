"""meals: foods, recipes, recipe_ingredients, pantry_items

Phase 1 of docs/MEALS_PLAN.md. Four tables, no user-facing behaviour yet.

Two shape decisions worth stating here because they are hard to change
later:

**Nutrition is per 100 g.** That is how USDA FoodData Central publishes
it, and it makes every conversion in the app a single multiply. Storing
per-serving figures would mean re-deriving them whenever a recipe scales
or a portion changes, and the two copies would eventually disagree.

**Every nutrient column is nullable.** USDA does not carry every nutrient
for every food, and a null has to stay distinguishable from a zero: "we
do not know this food's sodium" is a different claim from "this food
contains no sodium". Defaulting them to 0 would make a recipe total look
complete when it is not.

There is deliberately no household or portion table. Confirmed
2026-08-22: cooking for one, so a recipe's `servings` plus a multiplier
covers meal prep entirely.

`recipe_ingredients.food_id` and `pantry_items.food_id` are nullable with
ON DELETE SET NULL rather than CASCADE. Deleting a food must not silently
shorten a recipe or empty a shelf — the line keeps its raw text and is
reported as unresolved, which the nutrition endpoint surfaces so a total
is never quietly incomplete.

Revision ID: 0056
Revises: 0055
Create Date: 2026-08-22 12:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0056"
down_revision: str | None = "0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "foods",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("slug", sa.String(160), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="usda"),
        sa.Column("category", sa.String(80), nullable=True),
        sa.Column("kcal", sa.Float(), nullable=True),
        sa.Column("protein_g", sa.Float(), nullable=True),
        sa.Column("carbs_g", sa.Float(), nullable=True),
        sa.Column("fat_g", sa.Float(), nullable=True),
        sa.Column("saturated_fat_g", sa.Float(), nullable=True),
        sa.Column("fiber_g", sa.Float(), nullable=True),
        sa.Column("sugar_g", sa.Float(), nullable=True),
        sa.Column("sodium_mg", sa.Float(), nullable=True),
        sa.Column("unit_grams", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_foods_slug", "foods", ["slug"], unique=True)
    op.create_index("ix_foods_name", "foods", ["name"])
    op.create_index("ix_foods_category", "foods", ["category"])

    op.create_table(
        "recipes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("servings", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("prep_min", sa.Integer(), nullable=True),
        sa.Column("cook_min", sa.Integer(), nullable=True),
        sa.Column("method", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("source_url", sa.String(1000), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_recipes_name", "recipes", ["name"])

    op.create_table(
        "recipe_ingredients",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("recipe_id", sa.Integer(), nullable=False),
        sa.Column("food_id", sa.Integer(), nullable=True),
        sa.Column("raw_text", sa.String(500), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["food_id"], ["foods.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_recipe_ingredients_recipe_id", "recipe_ingredients", ["recipe_id"],
    )

    op.create_table(
        "pantry_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("food_id", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["food_id"], ["foods.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_pantry_items_food_id", "pantry_items", ["food_id"])


def downgrade() -> None:
    op.drop_table("pantry_items")
    op.drop_table("recipe_ingredients")
    op.drop_table("recipes")
    op.drop_table("foods")
