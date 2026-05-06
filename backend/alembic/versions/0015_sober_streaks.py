"""sober_streaks

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-06 21:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sober_streaks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("addiction", sa.String(64), nullable=False, server_default="alcohol"),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
    )
    op.create_index(
        "ix_sober_streaks_addiction_start", "sober_streaks", ["addiction", "start_at"]
    )
    # At most one active (end_at IS NULL) streak per addiction.
    op.create_index(
        "ux_sober_streaks_active",
        "sober_streaks",
        ["addiction"],
        unique=True,
        postgresql_where=sa.text("end_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_sober_streaks_active", table_name="sober_streaks")
    op.drop_index("ix_sober_streaks_addiction_start", table_name="sober_streaks")
    op.drop_table("sober_streaks")
