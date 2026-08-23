"""ai_config.cli_oauth_token — subscription OAuth for the headless CLI provider

Additive nullable column for the `claude_cli` provider, which shells out
to `claude -p` on the machine's Claude subscription instead of calling
the Messages API. Real spend on that path is $0; calls draw on the
subscription's rate-limit budget rather than per-token billing.

The token comes from `claude setup-token` and is stored here rather than
only in the environment so it can be replaced from the Settings UI
without editing `.env` and restarting the stack — the same reason the
Anthropic API key lives in this table instead of an env var.

Deliberately a SEPARATE column from `anthropic_api_key` rather than a
reuse of it. The two are not interchangeable: an `ANTHROPIC_API_KEY`
present in the CLI's environment makes it authenticate as an API key and
bill per token, which defeats the entire point — so the provider strips
that variable from the child environment and passes this one instead.
Storing both in one field would make that distinction impossible.

Revision ID: 0061
Revises: 0060
Create Date: 2026-08-22 21:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0061"
down_revision: str | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_config", sa.Column("cli_oauth_token", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_config", "cli_oauth_token")
