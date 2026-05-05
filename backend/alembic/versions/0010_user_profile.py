"""user profile

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-04 19:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_profile",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("birth_date", sa.Date, nullable=True),
        sa.Column("sex", sa.String(8), nullable=True),
        sa.Column("height_cm", sa.Float, nullable=True),
        sa.Column("weight_goal_kg", sa.Float, nullable=True),
        sa.Column("resting_hr_baseline", sa.Float, nullable=True),
        sa.Column("activity_level", sa.String(16), nullable=True),
        sa.Column("extra", sa.JSON, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("user_profile")
