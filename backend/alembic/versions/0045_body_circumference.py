"""body_circumference table (BODY-1)

Tape-measure circumference sites in cm — manual entry only (no Health
Connect record type for limb circumference). One row per measurement
session keyed on `time`; any subset of sites may be filled. Plain table:
circumference is logged at most weekly, so hypertable overhead never pays
off (same rationale as fasting_sessions, 0034).

Revision ID: 0045
Revises: 0044
Create Date: 2026-07-28 13:50:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "body_circumference",
        sa.Column("time", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("waist_cm", sa.Float(), nullable=True),
        sa.Column("chest_cm", sa.Float(), nullable=True),
        sa.Column("arms_cm", sa.Float(), nullable=True),
        sa.Column("hips_cm", sa.Float(), nullable=True),
        sa.Column("thighs_cm", sa.Float(), nullable=True),
        sa.Column("neck_cm", sa.Float(), nullable=True),
        sa.Column("calves_cm", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False,
                  server_default="manual"),
    )


def downgrade() -> None:
    op.drop_table("body_circumference")
