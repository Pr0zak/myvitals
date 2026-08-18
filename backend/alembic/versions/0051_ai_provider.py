"""ai_config: add provider and base_url

The AI layer constructed AsyncAnthropic at every one of its nineteen call
sites, so Anthropic was not a choice the app made once -- it was baked into
each surface. These two columns make it a setting.

The motivation is the self-hosting thesis the rest of the app already lives
by: everything else here runs on the user's own hardware, and the AI layer is
the one part that needs an external account and a credit card. An
OpenAI-compatible endpoint pointed at Ollama on the LAN takes the running
cost to zero and keeps every byte inside the house.

Both nullable with no default and no backfill. A null provider means
Anthropic, so every existing installation behaves exactly as it did and an
instance that never opens the new setting notices nothing.

Revision ID: 0051
Revises: 0050
Create Date: 2026-08-17 20:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0051"
down_revision: str | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ai_config", sa.Column("provider", sa.String(32), nullable=True))
    op.add_column("ai_config", sa.Column("base_url", sa.String(512), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_config", "base_url")
    op.drop_column("ai_config", "provider")
