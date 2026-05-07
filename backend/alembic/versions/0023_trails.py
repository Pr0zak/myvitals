"""trails — RainoutLine status integration

Revision ID: 0023
Revises: 0022
Create Date: 2026-05-07 02:00:00.000000

A trail catalog (one row per RainoutLine "extension" under a DNIS),
its status-snapshot history (hypertable for cheap append + range
queries), per-trail subscriptions (single-user, so just a row when
the user wants pings), and a trail_alerts table mirroring ai_alerts
so the existing ack/notify plumbing can be reused.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trails",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("dnis", sa.String(16), nullable=False),
        sa.Column("extension", sa.Integer, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_trails_dnis_ext", "trails", ["dnis", "extension"], unique=True)
    op.create_index("ix_trails_slug", "trails", ["slug"], unique=True)

    op.create_table(
        "trail_status_snapshots",
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trail_id", sa.BigInteger, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),  # open|closed|pending|unknown
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("source_ts", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("fetched_at", "trail_id"),
    )
    op.execute(
        "SELECT create_hypertable('trail_status_snapshots', 'fetched_at', "
        "chunk_time_interval => INTERVAL '30 days', if_not_exists => TRUE)"
    )
    op.create_index(
        "ix_trail_snapshots_trail", "trail_status_snapshots",
        ["trail_id", "fetched_at"],
    )

    op.create_table(
        "trail_subscriptions",
        sa.Column("trail_id", sa.BigInteger, primary_key=True),
        sa.Column("subscribed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notify_on", sa.String(16), nullable=False, server_default="any"),
        # any | open_only | close_only
    )

    op.create_table(
        "trail_alerts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("trail_id", sa.BigInteger, nullable=False),
        sa.Column("from_status", sa.String(16), nullable=True),
        sa.Column("to_status", sa.String(16), nullable=False),
        sa.Column("source_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("phone_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_trail_alerts_trail", "trail_alerts", ["trail_id", "created_at"])
    op.create_index("ix_trail_alerts_acked", "trail_alerts", ["acked_at"])


def downgrade() -> None:
    op.drop_index("ix_trail_alerts_acked", table_name="trail_alerts")
    op.drop_index("ix_trail_alerts_trail", table_name="trail_alerts")
    op.drop_table("trail_alerts")
    op.drop_table("trail_subscriptions")
    op.drop_index("ix_trail_snapshots_trail", table_name="trail_status_snapshots")
    op.drop_table("trail_status_snapshots")
    op.drop_index("ix_trails_slug", table_name="trails")
    op.drop_index("ix_trails_dnis_ext", table_name="trails")
    op.drop_table("trails")
