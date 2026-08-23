"""foods.ingredients — the packaging's ingredient declaration

MEAL-8b. One additive nullable text column.

Populated only from a photo of a packaged product's ingredients list,
transcribed verbatim. USDA rows do not carry one and stay null, so this
is exclusively user-supplied information about a packaged food.

Text rather than a parsed list, and stored in the original order and
wording, because an ingredients declaration is a legal document whose
ORDER is meaningful — items are listed by descending weight. Splitting it
into a structured array would invite normalising and re-sorting it, which
destroys the single thing it is good for.

Deliberately NOT used for allergen warnings. Confirmed 2026-08-22: no
allergies here, and see docs/MEALS_PLAN.md hard part 4 for why an
allergen system built on ingredient text would have to be a warning
system rather than a filter that promises safety.

Revision ID: 0062
Revises: 0061
Create Date: 2026-08-23 09:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0062"
down_revision: str | None = "0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("foods", sa.Column("ingredients", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("foods", "ingredients")
