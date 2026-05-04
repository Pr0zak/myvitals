"""blood pressure readings

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-04 14:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "blood_pressure",
        sa.Column("time", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("systolic", sa.Integer, nullable=False),
        sa.Column("diastolic", sa.Integer, nullable=False),
        sa.Column("pulse_bpm", sa.Integer, nullable=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("notes", sa.Text, nullable=True),
    )
    op.execute(
        "SELECT create_hypertable('blood_pressure', 'time', "
        "chunk_time_interval => INTERVAL '90 days', if_not_exists => TRUE)"
    )


def downgrade() -> None:
    op.drop_table("blood_pressure")
