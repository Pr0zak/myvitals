"""strength_workouts.nudge_declines — OG3-C2

Dismissing an AI variety suggestion was purely client state: a `dismissed`
set in `VarietyNudge.vue`, a `CoachCardState` keyed on workout id in
Compose. It never reached the server, and `POST /ai/strength/nudge/{id}`
takes no `force` parameter and caches by payload hash — so "Get fresh
suggestions" was guaranteed to return exactly the two swaps just dismissed.

The accept path never had this problem: accepting mutates the plan, which
moves the hash, which makes the next ask a genuinely different question.
Only the decline path was broken, and it made the "indecisive AI" feel that
v0.7.157 was chasing strictly worse — the user declines, asks again, and is
offered the same thing, which reads as the coach not listening.

A JSON list on the workout rather than a table. Declines are scoped to one
workout's plan by nature (a swap names a slot in it), they are capped at ten,
and they die with the plan they refer to. A table would add a join to the
payload builder and an orphan-cleanup question, for a list that never grows
beyond a handful of short strings.

Nullable with no server default, read through `or []`. A default of `'[]'`
would have to be maintained in two places, and absent already means the same
thing as empty here.

Revision ID: 0066
Revises: 0065
"""
from alembic import op
import sqlalchemy as sa

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "strength_workouts",
        sa.Column("nudge_declines", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("strength_workouts", "nudge_declines")
