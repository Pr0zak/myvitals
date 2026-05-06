"""ai_alerts — anomaly notifications

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-06 23:50:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_alerts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="warn"),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("metric", sa.String(64), nullable=True),
        sa.Column("z_score", sa.Float, nullable=True),
        sa.Column("dedup_key", sa.String(128), nullable=True),
        sa.Column("acked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("phone_notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_ai_alerts_dedup", "ai_alerts", ["dedup_key", "created_at"]
    )
    op.create_index("ix_ai_alerts_acked", "ai_alerts", ["acked_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_alerts_acked", table_name="ai_alerts")
    op.drop_index("ix_ai_alerts_dedup", table_name="ai_alerts")
    op.drop_table("ai_alerts")
