"""strava credentials + activities tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-03 22:35:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "strava_credentials",
        # Single-user app: this table holds at most one row (id=1).
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("athlete_id", sa.BigInteger, nullable=False),
        sa.Column("athlete_name", sa.String(255), nullable=True),
        sa.Column("access_token", sa.Text, nullable=False),
        sa.Column("refresh_token", sa.Text, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope", sa.String(255), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )

    op.create_table(
        "activities",
        # Composite primary key so we can have activities from multiple sources
        # (Strava + future Garmin etc.) without ID collision.
        sa.Column("source", sa.String(32), primary_key=True),
        sa.Column("source_id", sa.String(64), primary_key=True),
        sa.Column("type", sa.String(64), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("duration_s", sa.Integer, nullable=False),
        sa.Column("distance_m", sa.Float, nullable=True),
        sa.Column("elevation_gain_m", sa.Float, nullable=True),
        sa.Column("avg_hr", sa.Float, nullable=True),
        sa.Column("max_hr", sa.Float, nullable=True),
        sa.Column("avg_power_w", sa.Float, nullable=True),
        sa.Column("max_power_w", sa.Float, nullable=True),
        sa.Column("kcal", sa.Float, nullable=True),
        sa.Column("suffer_score", sa.Float, nullable=True),
        sa.Column("polyline", sa.Text, nullable=True),
        sa.Column("raw", sa.JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("activities")
    op.drop_table("strava_credentials")
