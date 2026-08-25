"""foods.barcode — MEAL-BARCODE

A barcode is an identity, not a nutrient, so it gets its own column
rather than riding in the slug. Nullable because the bundled USDA
catalog has none: those are generic foods, and a generic food has no
pack to carry a barcode.

Not unique. Two national variants of one product genuinely share an
EAN, and OFF carries regional entries that collide; a unique constraint
would turn an ordinary data quirk into a failed save. Indexed instead,
because the lookup path queries by it on every scan.

Revision ID: 0065
Revises: 0064
"""
from alembic import op
import sqlalchemy as sa

revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("foods", sa.Column("barcode", sa.String(20), nullable=True))
    op.create_index("ix_foods_barcode", "foods", ["barcode"])


def downgrade() -> None:
    op.drop_index("ix_foods_barcode", table_name="foods")
    op.drop_column("foods", "barcode")
