"""ai_config + ai_summaries

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-06 22:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Single-row config table — id=1 always.
    op.create_table(
        "ai_config",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("anthropic_api_key", sa.String(256), nullable=True),
        sa.Column("model", sa.String(64), nullable=False, server_default="claude-haiku-4-5-20251001"),
        sa.Column("daily_call_limit", sa.Integer, nullable=False, server_default=sa.text("10")),
        sa.Column("calls_today", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("calls_today_date", sa.Date, nullable=True),
        sa.Column("weekly_digest_enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "INSERT INTO ai_config (id, enabled, model, daily_call_limit, calls_today, "
        "weekly_digest_enabled) VALUES (1, false, 'claude-haiku-4-5-20251001', 10, 0, false) "
        "ON CONFLICT DO NOTHING"
    )

    op.create_table(
        "ai_summaries",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("range_kind", sa.String(16), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=True),
        sa.Column("output_tokens", sa.Integer, nullable=True),
        sa.Column("content", sa.Text, nullable=False),
    )
    op.create_index(
        "ix_ai_summaries_range_hash", "ai_summaries", ["range_kind", "payload_hash"]
    )
    op.create_index(
        "ix_ai_summaries_generated_at", "ai_summaries", ["generated_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_ai_summaries_generated_at", table_name="ai_summaries")
    op.drop_index("ix_ai_summaries_range_hash", table_name="ai_summaries")
    op.drop_table("ai_summaries")
    op.drop_table("ai_config")
