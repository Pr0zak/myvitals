"""strava_cookie_creds: add creds_key_b64 to move Fernet key into the DB

SCS-7 drops the STRAVA_CREDS_KEY env-var requirement. The key is now
auto-generated on first password save and stored in this same row,
which keeps the entire Strava auto-login config setup-able from the
Settings UI without shelling into the CT.

Honest trade-off: a DB-only dump would now carry both the encrypted
password and the key, so backups are no longer defense-in-depth.
Realistic for a single-user self-hosted app on a private network;
the env-var path is preserved as a fallback (key in env wins when
both are present).

Revision ID: 0040
Revises: 0039
Create Date: 2026-06-05 13:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("strava_cookie_creds",
                  sa.Column("creds_key_b64", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("strava_cookie_creds", "creds_key_b64")
