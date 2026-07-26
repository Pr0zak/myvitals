"""strength_sets: add set_type column (SETTYPE-1)

Classifies each logged set as 'working' (default), 'warmup', 'drop', or
'failure'. Warmups are logged but excluded from working-set volume counts
(weekly_muscle_volume) and PR detection so they don't inflate the MEV/MAV
audit or false-trigger records. NOT NULL with a 'working' server_default so
every existing row backfills to working.

Revision ID: 0044
Revises: 0043
Create Date: 2026-07-25 12:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "strength_sets",
        sa.Column("set_type", sa.String(16), nullable=False,
                  server_default="working"),
    )


def downgrade() -> None:
    op.drop_column("strength_sets", "set_type")
