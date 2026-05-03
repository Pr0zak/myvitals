"""app_logs table for phone + server log shipping

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-03 14:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_logs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),  # "phone" | "server"
        sa.Column("level", sa.String(8), nullable=False),
        sa.Column("tag", sa.String(128), nullable=True),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("stack", sa.Text, nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_app_logs_ts", "app_logs", ["ts"], postgresql_using="btree")
    op.create_index("ix_app_logs_source", "app_logs", ["source"])
    op.create_index("ix_app_logs_level", "app_logs", ["level"])


def downgrade() -> None:
    op.drop_index("ix_app_logs_level", table_name="app_logs")
    op.drop_index("ix_app_logs_source", table_name="app_logs")
    op.drop_index("ix_app_logs_ts", table_name="app_logs")
    op.drop_table("app_logs")
