"""activity notes + tags

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-04 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("activities", sa.Column("notes", sa.Text, nullable=True))
    op.add_column(
        "activities",
        sa.Column("tags", postgresql.ARRAY(sa.String(64)), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("activities", "tags")
    op.drop_column("activities", "notes")
