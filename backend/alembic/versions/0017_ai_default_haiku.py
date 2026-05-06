"""ai_config default model -> haiku 4.5

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-06 23:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Cheaper default — Haiku is plenty for the structured-output reads
    # we're producing. Existing user rows still showing the old default
    # are bumped here; if they had set a different model deliberately,
    # we leave it.
    op.alter_column("ai_config", "model", server_default="claude-haiku-4-5-20251001")
    op.execute(
        "UPDATE ai_config SET model = 'claude-haiku-4-5-20251001' "
        "WHERE model = 'claude-sonnet-4-6'"
    )


def downgrade() -> None:
    op.alter_column("ai_config", "model", server_default="claude-sonnet-4-6")
