"""strava_app_config table for dashboard-editable OAuth credentials

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-03 22:50:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "strava_app_config",
        # Single-row (id=1). DB row overrides env vars.
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("client_id", sa.String(64), nullable=False),
        sa.Column("client_secret", sa.String(255), nullable=False),
        sa.Column("callback_url", sa.String(512), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("strava_app_config")
