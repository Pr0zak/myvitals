"""ai_config tone column + ai_goals table

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-06 23:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_config",
        sa.Column("tone", sa.String(16), nullable=False, server_default="supportive"),
    )

    op.create_table(
        "ai_goals",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(32), nullable=False),  # weight | sober | sleep | steps | custom
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("target_value", sa.Float, nullable=True),
        sa.Column("target_unit", sa.String(32), nullable=True),
        sa.Column("target_date", sa.Date, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("ai_goals")
    op.drop_column("ai_config", "tone")
