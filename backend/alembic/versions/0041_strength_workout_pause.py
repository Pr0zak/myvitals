"""strength_workouts: add pause/resume columns (WP-14)

Adds `paused_at` (set while a session is paused, NULL otherwise) and
`total_paused_s` (accumulated paused seconds across the session, so net
training duration = completed_at - started_at - total_paused_s). The new
"paused" status value needs no schema change — `status` is a free String.

Revision ID: 0041
Revises: 0040
Create Date: 2026-06-08 16:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("strength_workouts",
                  sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("strength_workouts",
                  sa.Column("total_paused_s", sa.Integer(), nullable=False,
                            server_default="0"))


def downgrade() -> None:
    op.drop_column("strength_workouts", "total_paused_s")
    op.drop_column("strength_workouts", "paused_at")
