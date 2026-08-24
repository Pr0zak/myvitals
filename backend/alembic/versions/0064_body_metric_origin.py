"""body_metrics.origin — which app actually wrote a reading

Health Connect is a bus, not a source. Several apps can write a
WeightRecord to it, and the phone's DataMapper flattened every one of
them to `source = "health_connect"` before posting. That was harmless
while exactly one app wrote weight; it stops being harmless the moment a
second one does — turning on Garmin Connect's Health Connect export, for
instance, would put Garmin and Google Health readings into the same
column under the same label, permanently indistinguishable.

`source` is deliberately left alone. For this table it already means the
PIPE a reading came down — "health_connect", "garmin", "fitbit",
"manual" — and two of those values come from ZIP importers that have
nothing to do with package names. Overloading it would break the meaning
of 1,243 existing rows. `origin` is the new, narrower fact: the Android
package that authored the record, or NULL when there is no such thing.

Nullable and additive, so every existing row keeps exactly the meaning it
already had. 96 characters to match `vitals_steps.source`, which already
stores package names and needs the room: Health Connect's synthetic
package names run to 65 characters and the 32 this column allows for
`source` would silently truncate them.

Revision ID: 0064
Revises: 0063
Create Date: 2026-08-24 10:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0064"
down_revision: str | None = "0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "body_metrics",
        sa.Column("origin", sa.String(96), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("body_metrics", "origin")
