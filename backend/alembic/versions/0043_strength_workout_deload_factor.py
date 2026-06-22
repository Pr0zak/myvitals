"""strength_workouts: add deload_factor column

Persists the automatic recovery/readiness deload multiplier applied to a
plan's target weights (1.0 = none). Surfaced on WorkoutOut so the client can
show a "load eased for recovery — use full weight" banner and let the user
override via regenerate(force_full_weight=True). NULL on legacy rows, treated
as 1.0 by the API.

Revision ID: 0043
Revises: 0042
Create Date: 2026-06-22 12:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("strength_workouts",
                  sa.Column("deload_factor", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("strength_workouts", "deload_factor")
