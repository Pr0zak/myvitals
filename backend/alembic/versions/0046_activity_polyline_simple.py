"""activities.polyline_simple — cached RDP-simplified track

The all-activities map needs every GPS track at once. Simplifying on the
fly costs ~15 s for the current 559 tracks (1.73 M points through
Ramer-Douglas-Peucker in Python), which is far too slow for a screen the
user opens directly.

Store the simplified track alongside the full one. It's derived data, so
it's nullable and backfilled lazily by `GET /activities/map` — a null
just means "not computed yet", never "no GPS". The full-fidelity
`polyline` column is untouched and remains the source of truth for the
activity-detail map.

Revision ID: 0046
Revises: 0045
Create Date: 2026-08-02 14:35:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "activities",
        sa.Column("polyline_simple", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("activities", "polyline_simple")
