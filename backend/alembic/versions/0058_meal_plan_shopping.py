"""meal_plan_entries, shopping_lists, shopping_list_items

MEAL-3: the weekly plan and the shopping list it generates.

Three shape decisions worth stating here, because each has a tempting
wrong alternative:

**The shopping list is PERSISTED, not recomputed on view.** The user
ticks items off while standing in a shop, and that state has to survive
a reload and follow them to the other client. Recomputing the list each
time would silently undo their ticks the moment a plan entry changed.

**`recipe_id` on a plan entry is nullable, ON DELETE SET NULL.** Deleting
a recipe must not silently empty days out of the plan. The entry keeps
its note and shows as needing attention instead of vanishing.

**Shopping-list items snapshot their label.** The line stores the display
name at generation time rather than joining to `foods` at read time, so a
renamed or deleted food cannot leave a blank line on a list someone is
halfway through shopping.

There is deliberately no portion or household model. Confirmed
2026-08-22: cooking for one, so `servings` is a plain multiplier for meal
prep ("make four containers") and nothing more.

Revision ID: 0058
Revises: 0057
Create Date: 2026-08-22 17:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0058"
down_revision: str | None = "0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "meal_plan_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("slot", sa.String(16), nullable=False),
        sa.Column("recipe_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("servings", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_meal_plan_entries_day", "meal_plan_entries", ["day"])
    op.create_index(
        "ix_meal_plan_entries_recipe_id", "meal_plan_entries", ["recipe_id"],
    )

    op.create_table(
        "shopping_lists",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("start_day", sa.Date(), nullable=True),
        sa.Column("end_day", sa.Date(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )

    op.create_table(
        "shopping_list_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("list_id", sa.Integer(), nullable=False),
        sa.Column("food_id", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("grams", sa.Float(), nullable=True),
        sa.Column("amount_text", sa.String(255), nullable=True),
        sa.Column("pantry_uncertain", sa.Boolean(), nullable=False,
                  server_default="false"),
        sa.Column("pantry_covered_g", sa.Float(), nullable=True),
        sa.Column("checked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["list_id"], ["shopping_lists.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["food_id"], ["foods.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_shopping_list_items_list_id", "shopping_list_items", ["list_id"],
    )


def downgrade() -> None:
    op.drop_table("shopping_list_items")
    op.drop_table("shopping_lists")
    op.drop_table("meal_plan_entries")
