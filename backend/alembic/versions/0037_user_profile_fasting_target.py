"""user_profile — add fasting_target_hours_per_week.

Weekly cumulative-fasting-hours target. Auto-syncs with the
fast_streak AiGoal kind (FAST-17) the same way weight_goal_kg syncs
with kind="weight". Null = fasting not tracked as a goal.

Revision ID: 0037
Revises: 0036
Create Date: 2026-05-15 13:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_profile",
        sa.Column("fasting_target_hours_per_week", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_profile", "fasting_target_hours_per_week")
