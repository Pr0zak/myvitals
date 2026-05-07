"""vitals_steps — add source column, make (time, source) the PK

Health Connect surfaces step records from multiple writers (Pixel
Watch, phone pedometer, Google Fit aggregation). Without source
tagging the ingest path overwrites or sums them; we want them
distinguished so the summary can pick the watch as canonical.

Revision ID: 0028
Revises: 0027
Create Date: 2026-05-08 12:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add the column with a default of 'unknown' so the existing PK
    # (time-only) doesn't collide. New rows from the phone will start
    # writing actual data origins.
    op.add_column(
        "vitals_steps",
        sa.Column(
            "source", sa.String(96), nullable=False,
            server_default=sa.text("'unknown'"),
        ),
    )
    # Drop the old time-only PK and re-create as (time, source).
    op.execute("ALTER TABLE vitals_steps DROP CONSTRAINT IF EXISTS vitals_steps_pkey")
    op.create_primary_key(
        "vitals_steps_pkey", "vitals_steps", ["time", "source"],
    )


def downgrade() -> None:
    op.execute("ALTER TABLE vitals_steps DROP CONSTRAINT IF EXISTS vitals_steps_pkey")
    op.create_primary_key("vitals_steps_pkey", "vitals_steps", ["time"])
    op.drop_column("vitals_steps", "source")
