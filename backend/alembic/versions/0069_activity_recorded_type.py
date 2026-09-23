"""recorded_type on activities — the user can correct an activity's type

A watch auto-detects workouts, and it guesses. Mowing a lawn arrives from
Health Connect as "cycling": 26 minutes, 62 metres, no track. Until now only
`source=manual` rows could be edited, because a provider re-sync writes
`type` back and the correction would silently revert.

The correction is written to `type` itself, so every reader (stats, icons,
training load, filters) sees it with no change of its own. `recorded_type`
keeps what the device originally said, and doubles as the flag that the
type is the user's decision: while it is non-NULL, neither the sink nor the
bulk importer may overwrite `type`.

Nullable, additive, no backfill. NULL means "never corrected", which is true
of every existing row.

Revision ID: 0069
Revises: 0068
"""
from alembic import op
import sqlalchemy as sa

revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "activities", sa.Column("recorded_type", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("activities", "recorded_type")
