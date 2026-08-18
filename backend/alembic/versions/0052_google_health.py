"""google_health_config + google_health_credentials

A second, phone-independent route to the user's own watch data.

Today the Android companion app is the only path for every stream this app
records. That is a single point of failure -- if the phone stops syncing,
Health Connect revokes a grant on upgrade, or a firmware bug silences a
sensor, the data simply stops. Two streams are in that state right now:
SpO2 and skin temperature have been dead on the Pixel Watch 3/4 since a
Fitbit firmware update, and `vitals_spo2` has never had a writer at all.

Google's Health API v4 serves the same data server-to-server, including
`oxygen-saturation` and `daily-sleep-temperature-derivations`. Verified
before building: no allowlist, no approval process, and app verification is
only required above 100 users -- a single-user self-hosted install stays in
the unverified tier indefinitely.

Two tables mirroring the Strava pattern: the app registration the user
creates in their own Google Cloud project, and the tokens that come out of
authorising it. Both single-row (id=1), because this is a single-user app.

Revision ID: 0052
Revises: 0051
Create Date: 2026-08-18 09:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0052"
down_revision: str | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "google_health_config",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("client_id", sa.String(255), nullable=True),
        sa.Column("client_secret", sa.String(255), nullable=True),
        sa.Column("callback_url", sa.String(512), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "google_health_credentials",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        # Surfaced in the UI rather than only logged. The one lesson the
        # Strava cookie taught: an integration that fails silently reads as
        # "no data" for weeks before anyone notices.
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("poll_enabled", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_table("google_health_credentials")
    op.drop_table("google_health_config")
