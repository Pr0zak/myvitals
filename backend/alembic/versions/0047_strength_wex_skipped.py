"""strength_workout_exercises: add skipped column

Records that the user deliberately declined an exercise slot, as distinct from
never having touched it. Before this column the only way to express "I'm not
doing this one" was to write placeholder StrengthSet rows with skipped=True,
which two downstream consumers misread: recent_mobility_history counts a
skipped set as a *failed* set and lowers the next hold prescription, and the
deload payload folds skipped sets into missed_or_skipped_sets, which the coach
prompt reads as accumulating fatigue. Putting the flag on the slot keeps the
set table an honest record of work actually performed.

Additive boolean with a server default, so existing rows need no backfill and
the pre-upgrade image tolerates the new column during the rollout window.

Revision ID: 0047
Revises: 0046
Create Date: 2026-08-14 12:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "strength_workout_exercises",
        sa.Column("skipped", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("strength_workout_exercises", "skipped")
