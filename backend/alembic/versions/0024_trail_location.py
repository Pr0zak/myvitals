"""trails — add latitude / longitude / city / state for maps navigation

Revision ID: 0024
Revises: 0023
Create Date: 2026-05-07 02:30:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("trails", sa.Column("latitude", sa.Float, nullable=True))
    op.add_column("trails", sa.Column("longitude", sa.Float, nullable=True))
    op.add_column("trails", sa.Column("city", sa.String(64), nullable=True))
    op.add_column("trails", sa.Column("state", sa.String(8), nullable=True))


def downgrade() -> None:
    op.drop_column("trails", "state")
    op.drop_column("trails", "city")
    op.drop_column("trails", "longitude")
    op.drop_column("trails", "latitude")
