"""last_error_kind on the integration credentials — OG3-D1

Both credential tables already recorded THAT a poll failed. Neither
recorded what sort of failure it was, and that is the difference between a
retry worth making and one that cannot possibly succeed: a network timeout
will likely work in fifteen minutes; a revoked OAuth grant will not work
ever, without a person.

The cost of not knowing is measured rather than theoretical. The Google
Health grant on this install expired on 2026-09-08 and was retried every
fifteen minutes for eight days, while the dashboard reported only that the
stream was stale — which is exactly what a quiet week looks like. It had
happened once before, on 2026-08-28.

Nullable with no default and no backfill. Every existing row's error, if it
has one, predates the classifier, and inventing a kind for it would be
guessing at a failure nobody observed. Absent means "unclassified", which
the readers treat as retryable — preserving today's behaviour rather than
silently disabling a poll on the strength of a made-up value.

`String(16)` rather than a native enum: the four values are a Literal in
`integrations/errors.py`, and a database enum would mean a second migration
every time that list changes, in exchange for a constraint the application
already enforces.

Revision ID: 0067
Revises: 0066
"""
from alembic import op
import sqlalchemy as sa

revision = "0067"
down_revision = "0066"
branch_labels = None
depends_on = None

_TABLES = ("google_health_credentials", "strava_cookie_creds")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table, sa.Column("last_error_kind", sa.String(16), nullable=True),
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "last_error_kind")
