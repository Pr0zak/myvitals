"""bump default daily call limit 10 -> 30

Revision ID: 0020
Revises: 0019
Create Date: 2026-05-07 00:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("ai_config", "daily_call_limit", server_default="30")
    # Bump existing rows that haven't been customised
    op.execute("UPDATE ai_config SET daily_call_limit = 30 WHERE daily_call_limit = 10")


def downgrade() -> None:
    op.alter_column("ai_config", "daily_call_limit", server_default="10")
