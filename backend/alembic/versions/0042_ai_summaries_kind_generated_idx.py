"""ai_summaries: composite (range_kind, generated_at DESC) index

Every coach/verdict/deload `/latest` poll on both surfaces runs
`... WHERE range_kind = ? ORDER BY generated_at DESC LIMIT 1`. The two
single-column indexes from 0016 each only cover half of that; a composite
matching the exact access pattern turns it into an index-only seek as the
ai_summaries table grows. Paired with the retention prune in the weekly job.

Revision ID: 0042
Revises: 0041
Create Date: 2026-06-13 09:00:00.000000
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_ai_summaries_kind_generated",
        "ai_summaries",
        ["range_kind", "generated_at"],
        postgresql_ops={"generated_at": "DESC"},
    )


def downgrade() -> None:
    op.drop_index("ix_ai_summaries_kind_generated", table_name="ai_summaries")
