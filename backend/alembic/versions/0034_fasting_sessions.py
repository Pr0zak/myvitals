"""fasting_sessions + fasting_logs tables

Foundation for the Intermittent Fasting feature (#FAST family).

`fasting_sessions` is a regular table — one row per
completed-or-active fast. The partial unique index on
`(true) WHERE ended_at IS NULL` enforces a single live fast per user
(single-user system, no user_id column).

Originally specced as a TimescaleDB hypertable on `started_at`, but
hypertable + partial-unique-without-partition-col is rejected by
Timescale: "cannot create a unique index without the column 'started_at'".
A regular table is fine — fast cardinality is bounded (one per day at
most), so the hypertable overhead would never pay off.

`fasting_logs` is companion freeform data (hunger / mood / hydration /
notes) — multiple rows per fast, joined on `session_id`. Plain BTREE
on (session_id, time) is plenty.

Revision ID: 0034
Revises: 0033
Create Date: 2026-05-14 22:14:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── fasting_sessions ──
    op.create_table(
        "fasting_sessions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        # Protocol slug: '16:8' / '18:6' / '20:4' / 'omad' / '5:2' /
        # 'eat_stop_eat' / 'adf' / 'extended_24' / 'extended_36' /
        # 'extended_48' / 'extended_72' / 'ramadan' / 'lent' / 'yom_kippur'
        # / 'custom'.
        sa.Column("protocol", sa.String(32), nullable=False),
        # 'active' = user manually starts/ends; 'scheduled' = auto via
        # eating-window timer (#FAST-12 wires this up).
        sa.Column("mode", sa.String(16), nullable=False, server_default="active"),
        sa.Column("target_hours", sa.Float(), nullable=True),
        sa.Column("target_eating_window_h", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    # Single-active-fast invariant — partial unique on a constant so
    # multiple ended rows are fine but only one ongoing row can exist.
    op.execute(
        "CREATE UNIQUE INDEX ix_fasting_active_uniq "
        "ON fasting_sessions ((true)) WHERE ended_at IS NULL"
    )
    op.create_index(
        "ix_fasting_started_at",
        "fasting_sessions",
        [sa.text("started_at DESC")],
    )

    # ── fasting_logs ──
    op.create_table(
        "fasting_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("session_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hunger", sa.Integer(), nullable=True),       # 0-10
        sa.Column("mood", sa.Integer(), nullable=True),         # 0-10
        sa.Column("hydration_ml", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_fasting_logs_session_time",
        "fasting_logs",
        ["session_id", sa.text("time DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_fasting_logs_session_time", table_name="fasting_logs")
    op.drop_table("fasting_logs")
    op.drop_index("ix_fasting_started_at", table_name="fasting_sessions")
    op.execute("DROP INDEX IF EXISTS ix_fasting_active_uniq")
    op.drop_table("fasting_sessions")
