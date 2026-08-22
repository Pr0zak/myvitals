"""foods: fat-soluble vitamins A, D, E, K

MEAL-2. Four additive nullable columns on `foods`.

These four are carried for a specific medical reason rather than for
completeness. Absorbing the fat-soluble vitamins DEPENDS on absorbing
fat, so a cholecystectomy makes them the nutrients most likely to run
low — and that is precisely the thing a calories-and-macros tracker
cannot see. Every other nutrient USDA publishes stays out; see
`scripts/build_food_catalog.py` for why the bundled set is small.

Nullable, like every other nutrient column here, and for the same
reason: USDA covers these for 65-89% of foods depending on the vitamin,
and "we do not know this food's vitamin D" has to stay distinguishable
from "this food contains none". A null that silently became 0.0 would
make a partial daily total look like a deficiency.

No backfill. The startup seeder re-upserts the whole bundled catalog
whenever the row count is short, and it only touches `source = 'usda'`
rows, so the user's own foods keep their (absent) values and the
bundled ones pick the new columns up on the next boot.

Revision ID: 0057
Revises: 0056
Create Date: 2026-08-22 16:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0057"
down_revision: str | None = "0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (column, type). Units are in the names because a bare "vitamin_a" is
#: ambiguous — USDA publishes vitamin A in both RAE micrograms and IU,
#: and they differ by a factor that depends on the food.
_COLUMNS = (
    ("vitamin_a_ug", sa.Float()),
    ("vitamin_d_ug", sa.Float()),
    ("vitamin_e_mg", sa.Float()),
    ("vitamin_k_ug", sa.Float()),
)


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        op.add_column("foods", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in _COLUMNS:
        op.drop_column("foods", name)
