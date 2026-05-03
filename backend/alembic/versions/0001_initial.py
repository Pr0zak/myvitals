"""initial schema with timescaledb hypertables

Revision ID: 0001
Revises:
Create Date: 2026-05-03 06:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


HYPERTABLES: tuple[str, ...] = (
    "vitals_heartrate",
    "vitals_hrv",
    "vitals_spo2",
    "vitals_skin_temp",
    "vitals_steps",
    "sleep_stages",
    "workouts",
    "env_readings",
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    # --- time-series tables (will be converted to hypertables below) ---

    op.create_table(
        "vitals_heartrate",
        sa.Column("time", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("bpm", sa.Float, nullable=False),
        sa.Column("source", sa.String(64), nullable=False, server_default="watch"),
    )

    op.create_table(
        "vitals_hrv",
        sa.Column("time", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("rmssd_ms", sa.Float, nullable=False),
    )

    op.create_table(
        "vitals_spo2",
        sa.Column("time", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("percent", sa.Float, nullable=False),
    )

    op.create_table(
        "vitals_skin_temp",
        sa.Column("time", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("celsius_delta", sa.Float, nullable=False),
    )

    op.create_table(
        "vitals_steps",
        sa.Column("time", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("count", sa.Integer, nullable=False),
    )

    op.create_table(
        "sleep_stages",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("duration_s", sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint("time", "stage"),
    )

    op.create_table(
        "workouts",
        sa.Column("time", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("duration_s", sa.Integer, nullable=False),
        sa.Column("kcal", sa.Float, nullable=True),
        sa.Column("avg_hr", sa.Float, nullable=True),
        sa.Column("max_hr", sa.Float, nullable=True),
    )

    op.create_table(
        "env_readings",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("metric", sa.String(64), nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.PrimaryKeyConstraint("time", "source", "metric"),
    )

    # Convert each to a hypertable, partitioned on `time`.
    # 7-day chunks fit a personal-scale single-user workload comfortably.
    for table in HYPERTABLES:
        op.execute(
            f"SELECT create_hypertable("
            f"'{table}', 'time', "
            f"chunk_time_interval => INTERVAL '7 days', "
            f"if_not_exists => TRUE"
            f")"
        )

    # --- regular relational tables ---

    op.create_table(
        "annotations",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("note", sa.Text, nullable=True),
    )
    op.create_index("ix_annotations_ts", "annotations", ["ts"])
    op.create_index("ix_annotations_type", "annotations", ["type"])

    # Daily summary written by analytics jobs.
    op.create_table(
        "daily_summary",
        sa.Column("date", sa.Date, primary_key=True),
        sa.Column("resting_hr", sa.Float, nullable=True),
        sa.Column("hrv_avg", sa.Float, nullable=True),
        sa.Column("recovery_score", sa.Float, nullable=True),
        sa.Column("sleep_duration_s", sa.Integer, nullable=True),
        sa.Column("sleep_score", sa.Float, nullable=True),
        sa.Column("steps_total", sa.Integer, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
    )

    op.create_table(
        "alerts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("acknowledged", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_alerts_ts", "alerts", ["ts"])


def downgrade() -> None:
    op.drop_index("ix_alerts_ts", table_name="alerts")
    op.drop_table("alerts")
    op.drop_table("daily_summary")
    op.drop_index("ix_annotations_type", table_name="annotations")
    op.drop_index("ix_annotations_ts", table_name="annotations")
    op.drop_table("annotations")
    for table in reversed(HYPERTABLES):
        op.drop_table(table)
    # Leave the timescaledb extension in place — other DBs may use it.
