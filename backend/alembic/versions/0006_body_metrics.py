"""body metrics (weight / body fat / bmi)

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-04 13:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "body_metrics",
        sa.Column("time", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("weight_kg", sa.Float, nullable=True),
        sa.Column("body_fat_pct", sa.Float, nullable=True),
        sa.Column("bmi", sa.Float, nullable=True),
        sa.Column("lean_mass_kg", sa.Float, nullable=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
    )
    # Hypertable for consistency with other vitals — daily granularity is fine.
    op.execute(
        "SELECT create_hypertable('body_metrics', 'time', "
        "chunk_time_interval => INTERVAL '90 days', if_not_exists => TRUE)"
    )


def downgrade() -> None:
    op.drop_table("body_metrics")
