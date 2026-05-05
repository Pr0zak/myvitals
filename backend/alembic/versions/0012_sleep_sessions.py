"""sleep_sessions canonical boundaries

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-05 04:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sleep_sessions",
        sa.Column("start_at", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="watch"),
        sa.Column("title", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("sleep_sessions")
