"""sync_heartbeat for companion-app diagnostics

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-06 19:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sync_heartbeat",
        sa.Column("attempt_at", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column("permissions_lost", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("perms_granted", sa.Integer, nullable=True),
        sa.Column("perms_required", sa.Integer, nullable=True),
        sa.Column("perms_missing", sa.JSON, nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_summary", sa.String(2000), nullable=True),
        sa.Column("records_pulled", sa.Integer, nullable=True),
        sa.Column("app_version", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("sync_heartbeat")
