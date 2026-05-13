"""strength_workouts — track the Activity row that auto-completed the workout.

When a Concept2 row or Strava bike ride lands for a date that has a
planned/in-progress cardio StrengthWorkout, the integration flips the
StrengthWorkout to 'completed' and stashes which activity did it. The
columns are composite-keyed (source + source_id) to match Activity's
own PK shape — no real FK so the row survives if the activity is
deleted upstream.

Revision ID: 0031
Revises: 0030
Create Date: 2026-05-13 00:35:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "strength_workouts",
        sa.Column("completed_by_activity_source", sa.String(64), nullable=True),
    )
    op.add_column(
        "strength_workouts",
        sa.Column("completed_by_activity_source_id", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("strength_workouts", "completed_by_activity_source_id")
    op.drop_column("strength_workouts", "completed_by_activity_source")
