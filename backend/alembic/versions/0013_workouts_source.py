"""workouts.source column

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-06 01:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workouts", sa.Column("source", sa.String(64), nullable=True))
    op.add_column("workouts", sa.Column("title", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("workouts", "title")
    op.drop_column("workouts", "source")
