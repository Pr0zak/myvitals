"""Classifying an integration failure, and acting on the class (OG3-D1).

Every integration already recorded THAT a poll failed. None recorded what
sort of failure it was, and that distinction is the whole difference between
a retry worth making and one that cannot possibly succeed.

The cost is measured, not theoretical. The Google Health grant on this
install expired on 2026-09-08 and was retried every fifteen minutes for
eight days — roughly 770 pointless refresh attempts — while the dashboard
reported only that the stream was stale, which is exactly what a quiet week
looks like. The same thing had happened on 2026-08-28. Both times the cause
was an OAuth client left in *Testing* publishing status, whose refresh
tokens Google expires after seven days no matter how recently they were
used.

What this file pins is the behaviour that follows from the class, not the
class names themselves — a taxonomy nothing acts on is just a longer error
message.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from myvitals.analytics import data_health
from myvitals.integrations import errors
from myvitals.integrations.strava_web import CookieExpired
from myvitals.tasks import scheduled


class TestTheOAuthClassifier:
    def test_invalid_grant_is_auth_not_transient(self):
        """The case that actually happened, twice.

        A revoked or expired refresh token cannot be recovered by retrying.
        Classifying it as transient is what produced eight days of silent,
        futile polling.
        """
        body = '{"error": "invalid_grant", "error_description": "Token has been expired or revoked."}'
        assert errors.classify_oauth_response(400, body) == "auth"

    def test_a_5xx_from_the_auth_server_is_transient(self):
        """A failure that happens to be about auth is not an auth failure.

        Google returning 503 is an outage, and disabling the poll for it
        would turn a ten-minute blip into an integration the user has to
        notice and manually reconnect.
        """
        assert errors.classify_oauth_response(503, "invalid_grant") == "transient"

    def test_a_bad_client_registration_is_config_not_auth(self):
        """Different fault, different sentence.

        `auth` says "reconnect"; there is nothing to reconnect when the
        client itself is mis-registered, and following that advice would
        waste the user's time on a flow that cannot help.
        """
        assert errors.classify_oauth_response(400, "unauthorized_client") == "config"
        assert errors.classify_oauth_response(400, "invalid_scope") == "config"

    def test_a_rate_limit_is_upstream_and_therefore_not_blocking(self):
        kind = errors.classify_oauth_response(429, "slow down")
        assert kind == "upstream"
        assert kind not in errors.BLOCKING_KINDS

    def test_an_unrecognised_failure_stays_retryable(self):
        """The safe default.

        Treating an unknown failure as blocking would silently disable a
        working poll the first time an unfamiliar error appeared. Treating
        it as transient preserves exactly today's behaviour.
        """
        assert errors.IntegrationError("something odd").kind == "transient"
        assert not errors.IntegrationError("something odd").blocking


class TestTheKindDrivesBehaviour:
    def test_auth_and_config_block_config_only(self):
        assert errors.BLOCKING_KINDS == {"auth", "config"}
        assert errors.IntegrationError("x", kind="auth").blocking
        assert errors.IntegrationError("x", kind="config").blocking
        assert not errors.IntegrationError("x", kind="transient").blocking
        assert not errors.IntegrationError("x", kind="upstream").blocking

    def test_the_google_poll_skips_a_blocking_kind(self):
        """Pinned at the call site, because this is the fix.

        Classifying without acting on the classification is the version of
        this change that reads as done and fixes nothing.
        """
        src = inspect.getsource(scheduled._google_health_tick)
        assert "BLOCKING_KINDS" in src
        assert "last_error_kind" in src

    def test_a_dead_strava_cookie_is_an_auth_failure(self):
        """The archetype: a credential no retry can restore.

        The production row has no auto-login email or password, so once
        the session dies only a human can bring it back. v0.7.319 gave it a
        one-off reconnect banner; this generalises that.
        """
        assert CookieExpired.kind == "auth"
        assert CookieExpired("dead").blocking

    def test_every_kind_has_an_action_a_client_can_render(self):
        for kind in ("transient", "auth", "config", "upstream"):
            assert errors.KIND_ACTION[kind].strip()


class TestDataHealthReportsItWithoutRecolouringAnything:
    def test_the_entry_carries_kind_action_and_reconnect(self):
        src = inspect.getsource(data_health)
        for field in ('"last_error_kind"', '"action"', '"needs_reconnect"'):
            assert field in src

    def test_the_kind_never_feeds_status(self):
        """HEALTH-1's restraint, enforced the way HEALTH-1 enforces it.

        `data_health` already has an AST guard stopping `status` being
        derived from item age. The same rule applies here for the opposite
        reason: the kind is a fact about a fault that already set
        `status = "error"`, and letting it assign `status` would mean two
        rules competing over one field.
        """
        tree = ast.parse(Path(data_health.__file__).read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            targets = {getattr(t, "id", None) for t in node.targets}
            if "status" not in targets:
                continue
            used = {
                n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)
            }
            assert "kind" not in used, (
                "status must not be derived from the error kind — it is a "
                "fact reported beside the verdict, not a second verdict"
            )

    def test_an_unclassified_error_does_not_ask_for_a_reconnect(self):
        """Rows predating the classifier carry an error and no kind.

        Telling someone to reconnect when the real fault was a timeout is
        worse than saying nothing: they do the work, it does not help, and
        the next prompt means less.
        """
        src = inspect.getsource(data_health)
        assert 'kind == "auth"' in src, (
            "needs_reconnect must require the auth kind specifically"
        )
