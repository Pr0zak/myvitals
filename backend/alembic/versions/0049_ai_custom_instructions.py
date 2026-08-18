"""ai_config: add custom_instructions

The entire user model handed to the AI was a three-value tone enum. There was
no way to tell the coach anything about the person it was coaching -- that a
left shoulder is being rehabbed and overhead pressing should never be
suggested, that the fasts are religious and a compressed HRV during one is
not overtraining, that a cardiologist has capped intensity.

Nullable text with no default and no backfill: absent means "no extra
instructions", which is exactly the behaviour every existing row has. The
column is appended verbatim to every system prompt under a fixed heading,
inside the prefix that already carries Anthropic's cache_control breakpoint,
so it costs nothing per call once cached.

Length is capped in the API layer rather than the schema, so the limit can be
tuned without a migration. It is capped at all because this is a
prompt-injection surface aimed at the model's own guardrails, and because an
unbounded string in the cached prefix would quietly inflate every request.

Revision ID: 0049
Revises: 0048
Create Date: 2026-08-17 18:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_config",
        sa.Column("custom_instructions", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_config", "custom_instructions")
