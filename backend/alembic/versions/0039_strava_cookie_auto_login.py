"""strava_cookie_creds: add email + encrypted_password for auto-login

SCS-6 adds Playwright headless-Chromium-driven auto-login so the user
doesn't have to re-paste cookies every few months. Email is stored
plain (already on every API call's User-Agent anyway); password is
Fernet-encrypted with STRAVA_CREDS_KEY env var. Per existing
config.py pattern, the key lives in .env, never in code.

Revision ID: 0039
Revises: 0038
Create Date: 2026-06-05 12:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("strava_cookie_creds",
                  sa.Column("email", sa.String(255), nullable=True))
    op.add_column("strava_cookie_creds",
                  sa.Column("password_encrypted", sa.Text(), nullable=True))
    op.add_column("strava_cookie_creds",
                  sa.Column("auto_login_enabled", sa.Boolean(),
                            nullable=False, server_default=sa.text("false")))
    op.add_column("strava_cookie_creds",
                  sa.Column("last_auto_login_at", sa.DateTime(timezone=True),
                            nullable=True))
    # remember_token / sid_cookie were nullable=False in the prior
    # migration's add_column defaults. Relax remember_token to allow
    # an email+password-only row that lets the next sync auto-login.
    op.alter_column("strava_cookie_creds", "remember_token", nullable=True)


def downgrade() -> None:
    op.alter_column("strava_cookie_creds", "remember_token", nullable=False)
    op.drop_column("strava_cookie_creds", "last_auto_login_at")
    op.drop_column("strava_cookie_creds", "auto_login_enabled")
    op.drop_column("strava_cookie_creds", "password_encrypted")
    op.drop_column("strava_cookie_creds", "email")
