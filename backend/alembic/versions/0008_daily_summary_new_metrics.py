"""daily_summary: weight + body fat + BP + skin temp columns

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-04 17:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("daily_summary") as batch:
        batch.add_column(sa.Column("weight_kg", sa.Float, nullable=True))
        batch.add_column(sa.Column("body_fat_pct", sa.Float, nullable=True))
        batch.add_column(sa.Column("bp_systolic_avg", sa.Float, nullable=True))
        batch.add_column(sa.Column("bp_diastolic_avg", sa.Float, nullable=True))
        batch.add_column(sa.Column("skin_temp_delta_avg", sa.Float, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("daily_summary") as batch:
        batch.drop_column("skin_temp_delta_avg")
        batch.drop_column("bp_diastolic_avg")
        batch.drop_column("bp_systolic_avg")
        batch.drop_column("body_fat_pct")
        batch.drop_column("weight_kg")
