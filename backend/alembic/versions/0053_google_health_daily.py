"""google_health_daily — a home for Google's daily aggregates

The Google Health API serves several metrics only as daily summaries:
resting heart rate, heart-rate variability, respiratory rate, VO2 max. This
app has nowhere to put one.

`daily_summary.resting_hr` and `.hrv_avg` look like the obvious targets and
are not: `compute_daily_summary` derives both from raw samples and rewrites
the row whenever it runs lazily, so anything written there would be silently
clobbered. And `vitals_hrv` stores per-sample RMSSD, so a single daily value
dropped in would coexist by timestamp while quietly skewing every average
taken over the table.

So they get their own table, keyed by date, and the existing analytics
consult it only as a FALLBACK — when the sample-derived computation returns
None because the phone was not syncing. That gives resilience without ever
overwriting a measured value with an aggregated one.

Revision ID: 0053
Revises: 0052
Create Date: 2026-08-21 12:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0053"
down_revision: str | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "google_health_daily",
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("resting_hr", sa.Float(), nullable=True),
        # Google reports an average HRV and, separately, a deep-sleep RMSSD.
        # The second is the closer analogue of what vitals_hrv stores, so
        # both are kept rather than collapsing them and losing the
        # distinction.
        sa.Column("hrv_avg_ms", sa.Float(), nullable=True),
        sa.Column("deep_sleep_rmssd_ms", sa.Float(), nullable=True),
        sa.Column("respiratory_rate", sa.Float(), nullable=True),
        sa.Column("vo2_max", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("google_health_daily")
