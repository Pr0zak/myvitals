"""widen ai_summaries.range_kind 16 -> 64 chars

Revision ID: 0022
Revises: 0021
Create Date: 2026-05-07 00:40:00.000000

The original 16-char limit was sized for "week" / "month" / "today".
Strength reviews (Phase 6) use range_kind="strength_review:{workout_id}"
which is 18+ characters and tripped a StringDataRightTruncationError.
Bumping to 64 leaves room for any future per-entity cache key.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "ai_summaries", "range_kind",
        existing_type=sa.String(16),
        type_=sa.String(64),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "ai_summaries", "range_kind",
        existing_type=sa.String(64),
        type_=sa.String(16),
        existing_nullable=False,
    )
