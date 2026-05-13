"""user_profile — add home_latitude / home_longitude.

Used by the Activities Map view (and any future location-aware widget)
to center the map on the user's home instead of the activity centroid
or a global fit-to-bounds. Optional fields; absent = fall back to
polyline centroid.

Revision ID: 0032
Revises: 0031
Create Date: 2026-05-13 01:50:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user_profile", sa.Column("home_latitude", sa.Float(), nullable=True))
    op.add_column("user_profile", sa.Column("home_longitude", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_profile", "home_longitude")
    op.drop_column("user_profile", "home_latitude")
