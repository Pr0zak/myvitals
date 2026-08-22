"""food_log_entries, food_log_days

MEAL-5: the tracking half. Two tables.

The second one is the interesting one. `food_log_days.complete` records
whether the user says a day's log is finished, and it exists because
logging here is expected to be intermittent.

A half-logged day is worse than an unlogged one. It reads as "you barely
ate" rather than "you barely logged", and any average built from it is
wrong in the direction that looks like success. The app cannot tell the
two apart from the data — only the user knows whether they stopped
logging or stopped eating — so completeness is DECLARED, never inferred,
and it defaults to partial. Everything derived counts only complete days
and reports how many it used.

`food_log_entries` points at a food, a recipe, or neither. "Neither" is
deliberate: someone logging a meal out has a name and perhaps a fat
figure off a menu, and refusing that would make the log useless exactly
where it matters. `manual_kcal` / `manual_fat_g` are kept separate from
the computed columns so the API can say which numbers were looked up and
which were typed in.

Both foreign keys are ON DELETE SET NULL. Deleting a recipe must not
erase the history of having eaten it.

Revision ID: 0059
Revises: 0058
Create Date: 2026-08-22 18:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0059"
down_revision: str | None = "0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "food_log_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("slot", sa.String(16), nullable=False, server_default="dinner"),
        sa.Column("food_id", sa.Integer(), nullable=True),
        sa.Column("recipe_id", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.Column("servings", sa.Float(), nullable=True),
        sa.Column("manual_kcal", sa.Float(), nullable=True),
        sa.Column("manual_fat_g", sa.Float(), nullable=True),
        sa.Column("logged_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["food_id"], ["foods.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_food_log_entries_day", "food_log_entries", ["day"])
    op.create_index("ix_food_log_entries_food_id", "food_log_entries", ["food_id"])
    op.create_index(
        "ix_food_log_entries_recipe_id", "food_log_entries", ["recipe_id"],
    )

    op.create_table(
        "food_log_days",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("complete", sa.Boolean(), nullable=False,
                  server_default="false"),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("food_log_days")
    op.drop_table("food_log_entries")
