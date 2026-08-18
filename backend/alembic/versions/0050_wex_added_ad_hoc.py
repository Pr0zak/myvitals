"""strength_workout_exercises: add added_ad_hoc

Records that the user appended this slot themselves rather than the generator
prescribing it. The distinction matters downstream in the same way SKIP-1's
`skipped` flag does: `explain_workout` should not claim to have reasoned its
way to an exercise the user chose, and the AI reviewer reads a self-added
accessory differently from one it planned.

Additive boolean with a server default, so existing rows need no backfill and
the pre-upgrade image tolerates the new column during the rollout window.

Revision ID: 0050
Revises: 0049
Create Date: 2026-08-17 19:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0050"
down_revision: str | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "strength_workout_exercises",
        sa.Column("added_ad_hoc", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("strength_workout_exercises", "added_ad_hoc")
