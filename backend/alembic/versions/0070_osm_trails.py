"""osm_trails — named trails from the trailmap project's OSM state packs

The trail list used to come only from the RainoutLine status board, which
covers the mountain-bike systems that post open/closed status. Paved
greenways and most multi-use paths are not on it, so a ride on one could
never be linked to it — reported from live use with the Gary L. Haller
Trail.

`osm_trails` holds one row per named trail (same-named ways clustered
by proximity) per state, built from the
weekly per-state packs the trailmap project publishes (OpenStreetMap
data, pre-extracted from Geofabrik). Geometry is kept as encoded
polylines plus a bbox so a ride can be matched against the trail's actual
path, not a single pin.

A `trails` row is created for an OSM trail only when the user links an
activity to it (`trails.osm_trail_id`). Such a row has no DNIS, no
extension and no pin: `dnis`/`extension` become nullable, and "has a
DNIS" is what marks a status-board trail. Leaving the pin NULL keeps the
row out of every pin-based path (auto-link on ingest, the picker's pinned
list, the pin ranking) by construction.

Revision ID: 0070
Revises: 0069
"""
from alembic import op
import sqlalchemy as sa

revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "osm_trails",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        # name + rounded centroid: several unrelated trails in one state
        # share a name ("Nature Trail"), so the name alone is not a key.
        sa.Column("key", sa.String(320), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("surface", sa.String(32), nullable=True),
        sa.Column("paths", sa.JSON, nullable=False),
        sa.Column("length_m", sa.Float, nullable=False),
        sa.Column("min_lat", sa.Float, nullable=False),
        sa.Column("max_lat", sa.Float, nullable=False),
        sa.Column("min_lon", sa.Float, nullable=False),
        sa.Column("max_lon", sa.Float, nullable=False),
        sa.Column("pack_built", sa.String(32), nullable=True),
        sa.UniqueConstraint("state", "key", name="uq_osm_trails_state_key"),
    )
    op.create_index("ix_osm_trails_bbox", "osm_trails",
                    ["min_lat", "max_lat", "min_lon", "max_lon"])
    op.alter_column("trails", "dnis", existing_type=sa.String(16), nullable=True)
    op.alter_column("trails", "extension", existing_type=sa.Integer, nullable=True)
    op.add_column("trails", sa.Column("osm_trail_id", sa.BigInteger, nullable=True))
    op.create_index("ix_trails_osm_trail_id", "trails", ["osm_trail_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_trails_osm_trail_id", table_name="trails")
    op.drop_column("trails", "osm_trail_id")
    op.execute("DELETE FROM trails WHERE dnis IS NULL")
    op.alter_column("trails", "extension", existing_type=sa.Integer, nullable=False)
    op.alter_column("trails", "dnis", existing_type=sa.String(16), nullable=False)
    op.drop_index("ix_osm_trails_bbox", table_name="osm_trails")
    op.drop_table("osm_trails")
