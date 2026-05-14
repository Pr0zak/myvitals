"""daily_summary.fasting_hours

Hours of fasting that overlap each local day. Computed in
compute_daily_summary as the sum of
  max(0, min(day_end, COALESCE(ended_at, now())) - max(day_start, started_at))
across all fasting_sessions touching the day. Active fasts contribute
their elapsed portion up to now().

Revision ID: 0035
Revises: 0034
Create Date: 2026-05-14 22:25:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "daily_summary",
        sa.Column("fasting_hours", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("daily_summary", "fasting_hours")
