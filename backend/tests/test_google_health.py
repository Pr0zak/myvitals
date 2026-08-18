"""Google Health API integration — GH-1.

A second, phone-independent route to the user's own watch data. Today the
Android companion app is the only path for every stream this app records,
which makes the phone a single point of failure for all of them — and two
streams are currently dead through it: SpO2 and skin temperature have been
silent on the Pixel Watch 3/4 since a Fitbit firmware update, and
`vitals_spo2` has never had a writer at all.

These tests cover the parts that can be exercised without a live Google
account: OAuth request shape, the CSRF state handshake, payload parsing, and
the deliberately narrow ingest surface. Whether this particular account's
Fitbit-sourced data actually populates the API is a question only
/google-health/probe can answer, which is why that endpoint exists.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

import pytest

from myvitals.api import google_health as api
from myvitals.integrations import google_health as gh


# ---------------------------------------------------------------------------
# OAuth request shape
# ---------------------------------------------------------------------------

def test_authorize_url_requests_offline_access_and_forces_consent():
    """Google issues a refresh token only on first consent unless asked
    again. Without one the connection works for exactly an hour and then
    fails in a way that looks like a server problem."""
    url = gh.authorize_url("cid", "https://example.test/cb", "st4te")
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=st4te" in url
    assert url.startswith(gh.AUTH_URL)


def test_only_readonly_scopes_are_requested():
    """This app consumes watch data. Nothing here should ever be able to
    write back into the user's Google Health record."""
    for scope in gh.SCOPES:
        assert scope.endswith(".readonly"), scope
    assert not any("writeonly" in s for s in gh.SCOPES)


def test_scopes_cover_the_streams_actually_ingested():
    """SpO2 and skin temperature live under different scopes — health
    metrics and sleep respectively — so requesting one and not the other
    would silently lose half the point of this integration."""
    joined = " ".join(gh.SCOPES)
    assert "health_metrics_and_measurements.readonly" in joined
    assert "sleep.readonly" in joined


def test_a_missing_refresh_token_is_a_loud_failure():
    src = inspect.getsource(gh.exchange_code)
    assert "refresh_token" in src
    assert "myaccount.google.com/permissions" in src, (
        "the error should tell the user how to recover, not just that it failed"
    )


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------

def test_state_round_trips_once_and_only_once():
    """Google redirects a browser to the callback and cannot carry our auth
    token, so `state` is the only thing preventing someone from binding
    THEIR Google account to this install."""
    state = api._mint_state()
    assert api._burn_state(state) is True
    assert api._burn_state(state) is False, "a state must not be reusable"


def test_an_unknown_state_is_rejected():
    assert api._burn_state("never-issued") is False


def test_expired_states_are_rejected():
    state = api._mint_state()
    api._PENDING_STATES[state] = datetime.now(timezone.utc) - timedelta(hours=2)
    assert api._burn_state(state) is False


# ---------------------------------------------------------------------------
# Payload parsing
# ---------------------------------------------------------------------------

def test_interval_points_use_their_start_time():
    ts = gh._point_time({"interval": {"startTime": "2026-08-18T03:14:00Z"}})
    assert ts == datetime(2026, 8, 18, 3, 14, tzinfo=timezone.utc)


def test_daily_points_are_stamped_at_midday_not_midnight():
    """Midnight is exactly the boundary this codebase keeps getting wrong.
    A daily aggregate parked there is ambiguous about which day it belongs
    to; midday is unambiguous in any timezone this user will be in."""
    ts = gh._point_time({"date": {"year": 2026, "month": 8, "day": 18}})
    assert ts == datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)


def test_unparseable_points_yield_none_rather_than_raising():
    """One malformed point must not abort a whole sync."""
    assert gh._point_time({}) is None
    assert gh._point_time({"interval": {"startTime": "not-a-date"}}) is None
    assert gh._point_time({"date": {"year": "banana"}}) is None


def test_value_extraction_walks_the_nested_payload():
    point = {"oxygenSaturation": {"percentage": 96.5}}
    assert gh._dig(point, "oxygenSaturation.percentage") == 96.5
    assert gh._dig(point, "oxygenSaturation.missing") is None
    assert gh._dig({}, "a.b.c") is None


# ---------------------------------------------------------------------------
# The deliberately narrow ingest surface
# ---------------------------------------------------------------------------

def test_only_streams_without_a_competing_writer_are_ingested():
    """The double-counting guard, and the reason this first cut is small.

    HeartRate, Steps, SleepSession and BodyMetric are already written by the
    phone. vitals_hrv, vitals_spo2 and vitals_skin_temp key on `time` alone
    with no source column, so a second writer at a different granularity
    would overwrite rather than coexist — and Google's HRV is a DAILY
    aggregate, which written into a per-sample table would be actively wrong.

    SpO2 and skin temperature have no competing writer at all, so they carry
    zero conflict risk and are exactly the two streams the firmware bug
    killed.
    """
    targets = {spec.target for spec in gh.INGEST_TYPES}
    assert targets == {"spo2", "skin_temp"}
    api_types = {spec.api_type for spec in gh.INGEST_TYPES}
    assert api_types == {"oxygen-saturation", "daily-sleep-temperature-derivations"}


def test_hrv_is_probed_but_not_ingested():
    """Google serves HRV as a daily aggregate; vitals_hrv stores per-sample
    RMSSD. Reporting it in the probe is useful; writing it would corrupt."""
    assert "daily-heart-rate-variability" in gh.PROBE_TYPES
    assert all(s.api_type != "daily-heart-rate-variability" for s in gh.INGEST_TYPES)


def test_every_ingest_type_is_also_probed():
    """The probe is how the user finds out whether a stream is available at
    all, so it must not omit one this integration depends on."""
    for spec in gh.INGEST_TYPES:
        assert spec.api_type in gh.PROBE_TYPES


def test_ingest_dedupes_within_a_batch():
    """These tables key on `time` alone, so two points sharing an instant
    would make the insert conflict with itself."""
    src = inspect.getsource(gh.ingest_range)
    assert "by_time" in src
    assert "on_conflict_do_update" in src


def test_a_failing_stream_does_not_abort_the_others():
    """A scope the user did not grant should cost that one stream, not the
    whole sync."""
    src = inspect.getsource(gh.ingest_range)
    assert "continue" in src
    assert "errors.append" in src


def test_partial_failure_is_persisted_not_just_logged():
    """An integration that fails silently reads as "no data" for weeks."""
    src = inspect.getsource(gh.ingest_range)
    assert "creds.last_error" in src


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _routes() -> dict[str, set[str]]:
    from fastapi.routing import APIRoute
    out: dict[str, set[str]] = {}
    for r in api.router.routes:
        if isinstance(r, APIRoute):
            out.setdefault(r.path, set()).update(r.methods)
    return out


@pytest.mark.parametrize("path,method", [
    ("/google-health/config", "GET"),
    ("/google-health/config", "POST"),
    ("/auth/google-health/login", "GET"),
    ("/auth/google-health/callback", "GET"),
    ("/google-health/status", "GET"),
    ("/google-health/probe", "POST"),
    ("/google-health/sync", "POST"),
    ("/google-health", "DELETE"),
])
def test_route_exists(path, method):
    assert method in _routes().get(path, set())


def test_status_is_readable_with_the_ingest_token():
    """CLAUDE.md's recurring trap: endpoints the phone needs must use
    require_any, not require_query, or the dashboard works and the phone
    401s."""
    src = inspect.getsource(api)
    status_src = src[src.index("async def status("):]
    decorator = src[:src.index("async def status(")].rsplit("@router.get", 1)[-1]
    assert "require_any" in decorator, "status must be reachable from the phone"


def test_the_client_secret_is_never_echoed_back():
    src = inspect.getsource(api.get_config)
    assert "client_secret_set" in src
    assert '"client_secret": cfg.client_secret' not in src


def test_disconnect_keeps_the_ingested_readings():
    """The readings are the user's own history, not Google's copy of it."""
    src = inspect.getsource(api.disconnect)
    assert "Spo2" not in src and "SkinTemp" not in src
