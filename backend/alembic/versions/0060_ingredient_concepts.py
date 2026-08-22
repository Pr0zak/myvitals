"""foods.concept — the canonical pantry-ingredient layer

MEAL-6. One additive nullable column, plus an index.

USDA rows are NUTRITION rows, not pantry concepts. "Chicken, broiler or
fryers, breast, skinless, boneless, meat only, raw" and the same food
"cooked, grilled" are separate rows with separate ids, and rightly so —
their nutrition genuinely differs. But a pantry item and a recipe
ingredient that mean the same food then fail to match, so the shopping
list does not subtract what you already have. That is a correctness bug,
not a missing feature.

`concept` is the coarse layer that fixes it: both rows carry the concept
"chicken breast", while every number still comes from the specific row.
This is the same split every app in this space makes — SuperCook exposes
roughly 2,000 pantry ingredients over millions of indexed recipes.

Nullable on purpose. A prepared dish (a Big Mac, a restaurant entree) is
not a pantry ingredient and gets NULL rather than a made-up concept, so
"has a concept" is exactly the same question as "is stockable".

No backfill here. The value is derived from the bundled catalog by
`analytics/concepts.py`, and the startup seeder rewrites it for every
`source = 'usda'` row — the same path that filled in the vitamin columns
in 0057.

Revision ID: 0060
Revises: 0059
Create Date: 2026-08-22 19:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0060"
down_revision: str | None = "0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("foods", sa.Column("concept", sa.String(80), nullable=True))
    # Pantry matching looks foods up BY concept on every shopping-list
    # generation and every can-make query, so this index is load-bearing
    # rather than precautionary.
    op.create_index("ix_foods_concept", "foods", ["concept"])


def downgrade() -> None:
    op.drop_index("ix_foods_concept", table_name="foods")
    op.drop_column("foods", "concept")
