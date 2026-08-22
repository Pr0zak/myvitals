"""strava_cookie_creds: scheduled poll with backoff and a hard stop

The cookie-mode Strava sync has been manual since the OAuth poll was
disabled in v0.7.275, so rides only arrive when the user remembers to
press a button. Nothing in the scheduler touches Strava today.

Three columns, mirroring the Google Health poll that already works this
way (`poll_enabled` / `poll_interval_min`, with each tick gating on
elapsed time rather than rescheduling the job):

- `poll_enabled` — defaults FALSE, deliberately. This reaches a third
  party on a timer, and unlike Google Health the credential cannot
  self-heal: the production row has no stored auto-login email or
  password, so once the cookie expires only a human can restore it.
  Something that phones out on a schedule should be switched on by a
  person, not by a migration.

- `poll_interval_min` — defaults to 6 hours. Strava is not a live feed;
  a ride uploaded from a head unit appears minutes to hours after it
  ends, and nothing downstream reads activities more often than daily.

- `poll_consecutive_failures` — the counter behind both the backoff and
  the hard stop. Without it a dead cookie is retried forever at full
  cadence, which is exactly the pattern that gets an IP rate-limited or
  flagged. The scheduler doubles the wait per failure and stops entirely
  after a threshold, leaving `last_error` set so the reconnect banner
  added in v0.7.319 explains why.

Revision ID: 0055
Revises: 0054
Create Date: 2026-08-22 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0055"
down_revision: str | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "strava_cookie_creds",
        sa.Column(
            "poll_enabled", sa.Boolean(),
            nullable=False, server_default="false",
        ),
    )
    op.add_column(
        "strava_cookie_creds",
        sa.Column(
            "poll_interval_min", sa.Integer(),
            nullable=False, server_default="360",
        ),
    )
    op.add_column(
        "strava_cookie_creds",
        sa.Column(
            "poll_consecutive_failures", sa.Integer(),
            nullable=False, server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("strava_cookie_creds", "poll_consecutive_failures")
    op.drop_column("strava_cookie_creds", "poll_interval_min")
    op.drop_column("strava_cookie_creds", "poll_enabled")
