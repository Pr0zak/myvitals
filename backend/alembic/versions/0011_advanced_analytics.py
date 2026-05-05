"""advanced analytics columns: readiness, training load, sleep consistency,
HR recovery, sleep target

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-04 21:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("daily_summary") as batch:
        batch.add_column(sa.Column("readiness_score", sa.Float, nullable=True))
        batch.add_column(sa.Column("training_stress_score", sa.Float, nullable=True))
        batch.add_column(sa.Column("ctl", sa.Float, nullable=True))      # 42d EWMA fitness
        batch.add_column(sa.Column("atl", sa.Float, nullable=True))      # 7d EWMA fatigue
        batch.add_column(sa.Column("tsb", sa.Float, nullable=True))      # ctl - atl (form)
        batch.add_column(sa.Column("sleep_consistency_score", sa.Float, nullable=True))
        batch.add_column(sa.Column("sleep_debt_h", sa.Float, nullable=True))

    with op.batch_alter_table("activities") as batch:
        batch.add_column(sa.Column("hr_recovery_60s", sa.Float, nullable=True))
        batch.add_column(sa.Column("hr_recovery_120s", sa.Float, nullable=True))

    with op.batch_alter_table("user_profile") as batch:
        batch.add_column(sa.Column("sleep_target_h", sa.Float, nullable=True, server_default="8"))


def downgrade() -> None:
    with op.batch_alter_table("user_profile") as batch:
        batch.drop_column("sleep_target_h")
    with op.batch_alter_table("activities") as batch:
        batch.drop_column("hr_recovery_120s")
        batch.drop_column("hr_recovery_60s")
    with op.batch_alter_table("daily_summary") as batch:
        batch.drop_column("sleep_debt_h")
        batch.drop_column("sleep_consistency_score")
        batch.drop_column("tsb")
        batch.drop_column("atl")
        batch.drop_column("ctl")
        batch.drop_column("training_stress_score")
        batch.drop_column("readiness_score")
