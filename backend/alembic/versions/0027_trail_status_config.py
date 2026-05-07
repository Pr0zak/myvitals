"""trail_status_config — single-row DNIS holder

Revision ID: 0027
Revises: 0026
Create Date: 2026-05-07 04:50:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trail_status_config",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("dnis", sa.String(16), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("trail_status_config")
