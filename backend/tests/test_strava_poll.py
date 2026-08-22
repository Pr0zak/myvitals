"""Scheduled Strava poll: backoff and hard stop (STRAVA-1).

The cookie sync has been manual since the OAuth poll was disabled in
v0.7.275, so rides only arrive when the user remembers to press a button.
Nothing in the scheduler touched Strava.

The reason this needed backoff and a hard stop rather than a plain timer
is specific to this credential: unlike Google Health, whose access token
is refreshed from a stored refresh token, the Strava cookie **cannot
self-heal**. The production credentials row has no auto-login email or
password, so once the session dies only a human can restore it. A timer
that keeps hitting a third party with a credential that can never come
back on its own is how an IP gets rate-limited or flagged.
"""

from __future__ import annotations

import inspect

from myvitals.api import strava as strava_api
from myvitals.tasks import scheduled


class TestDefaultsOff:
    def test_poll_is_disabled_by_default_in_the_model(self):
        """A migration must not switch on something that phones out."""
        from myvitals.db import models

        col = models.StravaCookieCreds.__table__.columns["poll_enabled"]
        assert col.server_default.arg.lower() == "false"
        assert col.nullable is False

    def test_the_tick_returns_early_when_disabled(self):
        src = inspect.getsource(scheduled._strava_cookie_tick)
        assert "if row is None or not row.poll_enabled:" in src

    def test_the_tick_returns_early_without_a_cookie(self):
        src = inspect.getsource(scheduled._strava_cookie_tick)
        assert "if not (row.remember_token or row.sid_cookie):" in src


class TestBackoff:
    def test_the_wait_doubles_per_consecutive_failure(self):
        src = inspect.getsource(scheduled._strava_cookie_tick)
        assert "2 ** row.poll_consecutive_failures" in src

    def test_the_backoff_is_capped(self):
        """Uncapped doubling reaches weeks after a handful of failures,
        which is indistinguishable from the hard stop but without saying
        so — the user would just see silence."""
        src = inspect.getsource(scheduled._strava_cookie_tick)
        assert "min(MAX_BACKOFF_MULT" in src

    def test_success_resets_the_counter(self):
        """A transient network blip must cost one longer gap, not
        permanent silence."""
        src = inspect.getsource(scheduled._strava_cookie_tick)
        assert "row.poll_consecutive_failures = 0" in src

    def test_a_returned_error_counts_as_a_failure(self):
        """_run_cookie_sync reports a dead cookie by RETURNING an error,
        not by raising — counting only exceptions would miss the exact
        failure this feature exists for."""
        src = inspect.getsource(scheduled._strava_cookie_tick)
        assert "if result.error:" in src
        assert "row.poll_consecutive_failures += 1" in src

    def test_a_raised_exception_also_counts(self):
        src = inspect.getsource(scheduled._strava_cookie_tick)
        assert "except Exception" in src
        assert "row.last_error =" in src


class TestHardStop:
    def test_polling_stops_after_the_threshold(self):
        src = inspect.getsource(scheduled._strava_cookie_tick)
        assert "if row.poll_consecutive_failures >= MAX_FAILURES:" in src

    def test_the_threshold_is_shared_with_the_api(self):
        """Two places deciding "has polling stopped?" would eventually
        disagree, and the UI would say one thing while the scheduler did
        another."""
        tick_src = inspect.getsource(scheduled._strava_cookie_tick)
        assert "STRAVA_POLL_MAX_FAILURES as MAX_FAILURES" in tick_src
        assert isinstance(strava_api.STRAVA_POLL_MAX_FAILURES, int)

    def test_the_stop_is_visible_rather_than_silent(self):
        """`last_error` stays set and `poll_stopped` is reported, so the
        reconnect banner explains the silence instead of the user having
        to notice missing rides."""
        assert "poll_stopped" in strava_api.StravaCookieStatus.model_fields

    def test_enabling_clears_the_failure_counter(self):
        """The reconnect gesture: paste a fresh cookie, turn the poll back
        on. It must start trying again rather than staying stopped because
        of failures that belonged to the previous credential."""
        src = inspect.getsource(strava_api.set_cookie_poll)
        assert "row.poll_consecutive_failures = 0" in src


class TestInterval:
    def test_the_interval_has_a_floor(self):
        """Strava is not a live feed — a ride appears minutes to hours
        after it ends — so a tight cadence spends request budget against a
        third party for no new data."""
        src = inspect.getsource(strava_api.set_cookie_poll)
        assert "max(15," in src

    def test_the_interval_has_a_ceiling(self):
        src = inspect.getsource(strava_api.set_cookie_poll)
        assert "24 * 60" in src

    def test_the_gate_lives_inside_the_tick(self):
        """A short fixed tick with the gate inside means a changed
        interval takes effect immediately rather than on the next
        restart — the same shape as the Google Health poll."""
        src = inspect.getsource(scheduled._strava_cookie_tick)
        assert "elapsed_min < wait_min" in src


class TestFitIngestSafety:
    """Two defects in the FIT path, both fixed alongside the poll because
    enabling a timer over a broken importer would multiply the damage."""

    def test_the_hr_insert_is_chunked(self):
        """asyncpg refuses over 32,767 bind parameters and these rows bind
        three each, so one statement caps at ~10,900 samples — about three
        hours at 1 Hz. The longest ride in this database is 2h22m, so a
        longer one would have failed the whole import."""
        from myvitals.integrations import strava_web

        src = inspect.getsource(strava_web)
        assert "chunk_size = 10_000" in src

    def test_a_sparse_fit_stream_does_not_wipe_watch_data(self):
        """The window delete removes EVERY heart-rate row in the ride
        window regardless of source, so the chest strap wins over the
        wrist. But a truncated or corrupt FIT can span two hours with a
        handful of samples, and the delete would then destroy two hours of
        good watch data to install five points."""
        from myvitals.integrations import strava_web

        src = inspect.getsource(strava_web)
        assert "dense_enough" in src
        assert "if dense_enough:" in src
