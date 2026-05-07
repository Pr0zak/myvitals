"""trails — add osm_paths_geojson cache + fetched_at

Revision ID: 0026
Revises: 0025
Create Date: 2026-05-07 04:30:00.000000

OpenStreetMap via Overpass API gives us official trail geometry for
free (no key, no rate-limit pain for a single user). One-shot fetch
per trail; cache the GeoJSON locally so we're not hammering Overpass
every time the user expands a card.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("trails", sa.Column("osm_paths_geojson", sa.JSON, nullable=True))
    op.add_column("trails", sa.Column(
        "osm_paths_fetched_at", sa.DateTime(timezone=True), nullable=True,
    ))


def downgrade() -> None:
    op.drop_column("trails", "osm_paths_fetched_at")
    op.drop_column("trails", "osm_paths_geojson")
