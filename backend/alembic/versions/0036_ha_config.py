"""ha_config — singleton row for Home Assistant URL / token / enabled

Replaces the env-var (HA_URL / HA_TOKEN / HA_REALTIME_ENABLED) approach
so the user can set + rotate the long-lived token from Settings instead
of editing /opt/myvitals/.env. The legacy env-vars stay supported as a
fallback for first boot, but Settings overrides them.

Schema mirrors ai_config / concept2_credentials patterns: id=1 singleton,
PKey on id so PG enforces it.

Revision ID: 0036
Revises: 0035
Create Date: 2026-05-14 23:10:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ha_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("url", sa.String(512), nullable=True),
        sa.Column("token", sa.Text(), nullable=True),
        sa.Column("realtime_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("device_id", sa.String(96), nullable=False, server_default=sa.text("'pixel_watch_3'")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def downgrade() -> None:
    op.drop_table("ha_config")
