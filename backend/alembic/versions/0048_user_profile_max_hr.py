"""user_profile: add an explicit max_hr column

Every HR-zone boundary in the app is a percentage of maximum heart rate, and
until now that maximum was always the Tanaka estimate derived from birth_date
-- with a silent fallback to age 40 when birth_date was unset. An estimate is
the right default, but a user who has actually seen their max in a ramp test
or a hard race had no way to say so, and the app had no way to tell the user
which of the two it was using.

Nullable with no server default and no backfill: null means "estimate it",
which is exactly the behaviour every existing row already has. The zone API
reports which of the two produced the number it used, so a chart built on a
guess says that it is built on a guess.

Revision ID: 0048
Revises: 0047
Create Date: 2026-08-17 12:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_profile",
        sa.Column("max_hr", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_profile", "max_hr")
