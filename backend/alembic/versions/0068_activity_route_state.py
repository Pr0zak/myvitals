"""route_state on activities — SA-P3

`activities.polyline` already answers "is there a track". It cannot answer
why there is not one, and the three reasons are not the same thing:

  * Health Connect holds a route for this session and is withholding it
    until the user grants route access (`consent_required`);
  * Health Connect genuinely has no route — an indoor dumbbell session
    never had GPS (`none`);
  * nobody has asked yet, because the session was ingested before the
    phone read routes at all (NULL).

Collapsing those into "polyline is null" is what made a missing map read
as a broken map: the Route card simply vanished, on a walk whose track was
sitting in Health Connect two days later. A user cannot act on a card that
is not there, and the action differs per case — grant access, or accept
that there is nothing to draw.

Nullable, additive, no backfill and no default. Every row that exists
predates any route read, and NULL means exactly that: unasked. Inventing
`none` for them would claim Health Connect was consulted and said no,
which is a measurement nobody took — the same distinction 0067 draws for
`last_error_kind`.

`String(24)` rather than a native enum, for 0067's reason: the values are a
short Literal in the application, and an enum type would cost a migration
every time that list moves.

Revision ID: 0068
Revises: 0067
"""
from alembic import op
import sqlalchemy as sa

revision = "0068"
down_revision = "0067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "activities", sa.Column("route_state", sa.String(24), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("activities", "route_state")
