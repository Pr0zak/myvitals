"""activities — link to trails

Revision ID: 0025
Revises: 0024
Create Date: 2026-05-07 03:00:00.000000

Adds nullable trail_id to activities so cardio sessions (Strava rides
on local mountain-bike trails, etc.) can be linked to a trail entry.
Auto-link is best-effort GPS proximity (<2km between activity start
point and trail pin); manual link via UI for the cases the auto-pass
misses.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("activities", sa.Column("trail_id", sa.BigInteger, nullable=True))
    op.create_index("ix_activities_trail_id", "activities", ["trail_id"])


def downgrade() -> None:
    op.drop_index("ix_activities_trail_id", table_name="activities")
    op.drop_column("activities", "trail_id")
