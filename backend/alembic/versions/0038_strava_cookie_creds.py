"""strava_cookie_creds — singleton row for cookie-session Strava sync

Strava's June 2026 policy puts the OAuth API behind a paid Strava
subscription. To stay on free tier we let the user paste their
strava_remember_token (and optional _strava4_session) and pull rides
via the authenticated browser session. Each ride's original FIT file
carries the chest-strap HR stream — the part that actually matters
for the cardio coach + HR detail charts.

Singleton (id=1), same pattern as ai_config / ha_config / strava_credentials.

Revision ID: 0038
Revises: 0037
Create Date: 2026-06-04 18:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "strava_cookie_creds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("remember_token", sa.Text(), nullable=False),
        sa.Column("sid_cookie", sa.Text(), nullable=True),
        sa.Column("athlete_id_cached", sa.BigInteger(), nullable=True),
        sa.Column("athlete_name_cached", sa.String(255), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def downgrade() -> None:
    op.drop_table("strava_cookie_creds")
