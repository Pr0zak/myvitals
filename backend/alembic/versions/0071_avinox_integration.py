"""avinox_integration — e-bike ride metrics and Avinox config table

Adds columns to `activities` for Avinox e-bike telemetry (motor power,
cadence, battery, assist levels, odometer, elevation loss, moving time)
and creates `avinox_config` for Avinox server connection state.

Revision ID: 0071
Revises: 0070
"""
from alembic import op
import sqlalchemy as sa

revision = "0071"
down_revision = "0070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("activities", sa.Column("elevation_loss_m", sa.Float(), nullable=True))
    op.add_column("activities", sa.Column("avg_motor_power_w", sa.Float(), nullable=True))
    op.add_column("activities", sa.Column("max_motor_power_w", sa.Float(), nullable=True))
    op.add_column("activities", sa.Column("avg_cadence", sa.Float(), nullable=True))
    op.add_column("activities", sa.Column("battery_start", sa.Integer(), nullable=True))
    op.add_column("activities", sa.Column("battery_end", sa.Integer(), nullable=True))
    op.add_column("activities", sa.Column("odometer_end_km", sa.Float(), nullable=True))
    op.add_column("activities", sa.Column("assist_seconds", sa.JSON(), nullable=True))
    op.add_column("activities", sa.Column("moving_time_s", sa.Integer(), nullable=True))

    op.create_table(
        "avinox_config",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("server_url", sa.String(255), nullable=True),
        sa.Column("query_token", sa.String(128), nullable=True),
        sa.Column("webhook_secret", sa.String(64), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_push_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("auto_sync_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("avinox_config")
    op.drop_column("activities", "moving_time_s")
    op.drop_column("activities", "assist_seconds")
    op.drop_column("activities", "odometer_end_km")
    op.drop_column("activities", "battery_end")
    op.drop_column("activities", "battery_start")
    op.drop_column("activities", "avg_cadence")
    op.drop_column("activities", "max_motor_power_w")
    op.drop_column("activities", "avg_motor_power_w")
    op.drop_column("activities", "elevation_loss_m")
