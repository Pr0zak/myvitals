"""prep_plans, prep_components, prep_meals

MEAL-9: weekly component batch cooking.

The model is COMPONENTS rather than seven fixed dinners, and that is the
decision the whole feature rests on. You cook a protein, a grain, a tray
of vegetables and a sauce at the weekend and assemble them into different
meals during the week. A day you end up eating out leaves components in
the fridge instead of breaking a plan, and you are not eating the
identical container five times — which is why rigid meal-prep plans get
abandoned by Wednesday.

Three shape decisions worth stating:

**Targets are snapshotted onto the plan** rather than recomputed on read.
A plan records what was decided at the time; if profile weight changes
mid-week, last week's plan should still show the numbers it was built
against. `target_basis` says whether those numbers were an equation
estimate or derived from observed intake, so a plan never implies more
certainty than it had.

**`done` lives on the component**, not the plan. A prep session is a list
you work through, and losing your place in it halfway is the difference
between using the feature and abandoning it.

**`prep_meals.status` carries "eating_out" and "skipped" as first-class
outcomes**, not failures. Nothing is rendered as a missed target. A plan
that turns red the moment life happens is a plan that gets deleted.

Revision ID: 0063
Revises: 0062
Create Date: 2026-08-23 12:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0063"
down_revision: str | None = "0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prep_plans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("start_day", sa.Date(), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("target_kcal", sa.Integer(), nullable=True),
        sa.Column("target_protein_g", sa.Integer(), nullable=True),
        sa.Column("target_basis", sa.String(16), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_prep_plans_start_day", "prep_plans", ["start_day"])

    op.create_table(
        "prep_components",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="other"),
        sa.Column("food_id", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.Column("portions", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("prep_note", sa.String(500), nullable=True),
        sa.Column("done", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["plan_id"], ["prep_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["food_id"], ["foods.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_prep_components_plan_id", "prep_components", ["plan_id"])

    op.create_table(
        "prep_meals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("slot", sa.String(16), nullable=False, server_default="dinner"),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False,
                  server_default="suggested"),
        sa.Column("component_ids", sa.JSON(), nullable=True),
        sa.Column("est_kcal", sa.Float(), nullable=True),
        sa.Column("est_protein_g", sa.Float(), nullable=True),
        sa.Column("est_fat_g", sa.Float(), nullable=True),
        sa.Column("assembly_note", sa.String(500), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["plan_id"], ["prep_plans.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_prep_meals_plan_id", "prep_meals", ["plan_id"])
    op.create_index("ix_prep_meals_day", "prep_meals", ["day"])


def downgrade() -> None:
    op.drop_table("prep_meals")
    op.drop_table("prep_components")
    op.drop_table("prep_plans")
