"""device_status hypertable — Pixel Watch liveness from HA WebSocket

Adds a per-(time, device_id) row capturing the watch's wear / battery /
charge / activity-state snapshot at each HA event. Each HA event mutates
one field; the consumer reads the latest row, copies forward unchanged
fields, and inserts a new dense row.

Source-of-truth: HA only. HC has no equivalent liveness signal.

Revision ID: 0033
Revises: 0032
Create Date: 2026-05-14 18:30:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "device_status",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("device_id", sa.String(96), nullable=False),
        sa.Column("battery_pct", sa.Integer(), nullable=True),
        sa.Column("battery_state", sa.String(32), nullable=True),
        sa.Column("is_charging", sa.Boolean(), nullable=True),
        sa.Column("activity_state", sa.String(48), nullable=True),
        sa.Column("is_worn", sa.Boolean(), nullable=True),
        sa.Column("online", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("time", "device_id", name="device_status_pkey"),
    )
    # Hypertable (idempotent for re-runs against a freshly-restored DB).
    op.execute(
        "SELECT create_hypertable('device_status', 'time', "
        "if_not_exists => TRUE)"
    )
    op.create_index(
        "ix_device_status_device_time",
        "device_status",
        ["device_id", sa.text("time DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_device_status_device_time", table_name="device_status")
    op.drop_table("device_status")
