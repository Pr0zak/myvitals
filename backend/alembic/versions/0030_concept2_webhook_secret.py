"""concept2_credentials — add webhook_secret column.

Concept2 lets you register any URL as a webhook target but doesn't
publicly document its signature scheme. We embed a 32-byte random
secret in the URL path (/integrations/concept2/webhook/{secret}) so
random POST traffic can't be processed; secret is generated on the
first sync after this migration runs.

Revision ID: 0030
Revises: 0029
Create Date: 2026-05-08 14:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "concept2_credentials",
        sa.Column("webhook_secret", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("concept2_credentials", "webhook_secret")
