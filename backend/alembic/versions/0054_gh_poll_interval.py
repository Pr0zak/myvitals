"""google_health_credentials: add poll_interval_min

The poll was a hardcoded hourly job. An hour is a sensible default for what
this ingests — SpO2 is measured passively overnight and skin temperature is
one reading a night — but steps benefit from something tighter, and the right
cadence is the user's call rather than a constant in the scheduler.

Floored at 15 minutes deliberately. A poll fetches ten data types over a
three-day window, and the API rate-limits readily enough that a dozen calls
in quick succession already trips a 429. Polling every few minutes would
spend the quota without producing data that changes that fast.

Revision ID: 0054
Revises: 0053
Create Date: 2026-08-21 13:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0054"
down_revision: str | None = "0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "google_health_credentials",
        sa.Column("poll_interval_min", sa.Integer(), nullable=False,
                  server_default="60"),
    )


def downgrade() -> None:
    op.drop_column("google_health_credentials", "poll_interval_min")
