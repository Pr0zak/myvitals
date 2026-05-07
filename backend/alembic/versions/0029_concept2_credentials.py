"""concept2_credentials — single-row table for Concept2 Logbook API token.

Long-lived personal token (pasted in Settings) is the simplest path for
single-user; OAuth refresh fields are present for a future flow.

Revision ID: 0029
Revises: 0028
Create Date: 2026-05-08 13:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "concept2_credentials",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("user_id", sa.BigInteger, nullable=True),
        sa.Column("user_name", sa.String(255), nullable=True),
        sa.Column("access_token", sa.Text, nullable=False),
        sa.Column("refresh_token", sa.Text, nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scope", sa.String(255), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("concept2_credentials")
