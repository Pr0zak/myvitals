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

def test_sample_points_use_their_physical_time():
    """The timestamp lives INSIDE the type body, not at the top level —
    which the first version of this parser assumed, so it found none."""
    ts = gh._point_time(
        {"dataSource": {}, "oxygenSaturation": {
            "sampleTime": {"physicalTime": "2026-08-21T12:17:50Z"}}},
        "oxygen-saturation",
    )
    assert ts == datetime(2026, 8, 21, 12, 17, 50, tzinfo=timezone.utc)


def test_interval_points_use_their_start_time():
    ts = gh._point_time(
        {"dataSource": {}, "steps": {"interval": {"startTime": "2026-08-18T03:14:00Z"}}},
        "steps",
    )
    assert ts == datetime(2026, 8, 18, 3, 14, tzinfo=timezone.utc)


def test_daily_points_are_stamped_at_midday_not_midnight():
    """Midnight is exactly the boundary this codebase keeps getting wrong.
    A daily aggregate parked there is ambiguous about which day it belongs
    to; midday is unambiguous in any timezone this user will be in."""
    ts = gh._point_time(
        {"dataSource": {}, "dailyRestingHeartRate": {
            "date": {"year": 2026, "month": 8, "day": 18}}},
        "daily-resting-heart-rate",
    )
    assert ts == datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)


def test_unparseable_points_yield_none_rather_than_raising():
    """One malformed point must not abort a whole sync."""
    assert gh._point_time({}, "steps") is None
    assert gh._point_time(
        {"dataSource": {}, "steps": {"interval": {"startTime": "not-a-date"}}}, "steps",
    ) is None
    assert gh._point_time(
        {"dataSource": {}, "dailyX": {"date": {"year": "banana"}}}, "daily-x",
    ) is None


def test_value_extraction_matches_the_real_payloads():
    """Shapes captured from the live account, Pixel Watch 3 via FITBIT.

    The first version of this guessed a dotted path
    (`dailySleepTemperatureDerivations.deltaCelsius`) that does not exist.
    Google reports two absolute temperatures and the delta is derived.
    """
    spo2 = {"dataSource": {}, "oxygenSaturation": {
        "sampleTime": {"physicalTime": "2026-08-21T12:17:50Z"},
        "percentage": 93.5,
    }}
    assert gh._spo2_percent(gh._body(spo2, "oxygen-saturation")) == 93.5

    skin = {"dataSource": {}, "dailySleepTemperatureDerivations": {
        "date": {"year": 2026, "month": 8, "day": 20},
        "nightlyTemperatureCelsius": 32.77371508379888,
        "baselineTemperatureCelsius": 33.223477684454096,
    }}
    body = gh._body(skin, "daily-sleep-temperature-derivations")
    assert gh._skin_temp_delta(body) == -0.45


def test_skin_temp_is_stored_as_a_deviation_not_an_absolute():
    """32.8 C at the wrist means nothing on its own; half a degree below
    your own baseline does. vitals_skin_temp.celsius_delta says delta."""
    assert gh._skin_temp_delta({"nightlyTemperatureCelsius": 33.0,
                                "baselineTemperatureCelsius": 33.0}) == 0.0
    assert gh._skin_temp_delta({"nightlyTemperatureCelsius": 33.0}) is None


def test_camel_case_key_derivation():
    assert gh._camel("oxygen-saturation") == "oxygenSaturation"
    assert gh._camel("daily-sleep-temperature-derivations") == "dailySleepTemperatureDerivations"


# ---------------------------------------------------------------------------
# The deliberately narrow ingest surface
# ---------------------------------------------------------------------------

def test_nothing_is_written_where_a_denser_writer_already_exists():
    """The double-counting guard, restated per target.

    Only three shapes of destination are allowed: a table with no competing
    writer, a table that carries a `source` column so two writers coexist,
    or the dedicated daily-aggregate table. Anything else risks a Google
    point replacing a phone measurement.
    """
    allowed_direct = {"spo2", "skin_temp", "steps", "weight", "body_fat"}
    for spec in gh.INGEST_TYPES:
        assert spec.target.startswith("daily:") or spec.target in allowed_direct, spec


def test_the_dense_streams_are_deliberately_skipped():
    """heart-rate, sleep and exercise are all served and all declined, each
    for a stated reason. The omission must read as a decision."""
    assert set(gh.SKIPPED_TYPES) == {"heart-rate", "sleep", "exercise"}
    ingested = {s.api_type for s in gh.INGEST_TYPES}
    for skipped in gh.SKIPPED_TYPES:
        assert skipped not in ingested
        assert gh.SKIPPED_TYPES[skipped], "a skip needs its reason recorded"


def test_daily_aggregates_go_to_their_own_table():
    """daily_summary is rewritten from raw samples on every lazy recompute,
    and vitals_hrv is per-sample — a single daily value dropped into either
    is clobbered or skews averages."""
    daily = {s.target for s in gh.INGEST_TYPES if s.target.startswith("daily:")}
    assert "daily:resting_hr" in daily
    assert "daily:hrv_avg_ms" in daily
    assert "daily:deep_sleep_rmssd_ms" in daily


def test_multi_source_tables_are_tagged_with_a_recognised_source():
    """vitals_steps coexists by source, and pick_canonical_steps_source has
    to recognise this one as a watch source or it will not be preferred."""
    from myvitals.analytics.jobs import _is_watch_source

    assert _is_watch_source(gh.SOURCE)


def test_every_ingest_type_is_also_probed():
    """The probe is how the user finds out whether a stream is available at
    all, so it must not omit one this integration depends on."""
    for spec in gh.INGEST_TYPES:
        assert spec.api_type in gh.PROBE_TYPES


def test_ingest_dedupes_within_a_batch():
    """Several of these tables key on `time` alone, so two points sharing an
    instant would make the insert conflict with itself."""
    src = inspect.getsource(gh.ingest_range)
    assert "by_key" in src
    assert "on_conflict_do_update" in src


def test_each_api_type_is_fetched_once_even_with_several_targets():
    """daily-heart-rate-variability feeds both an average and a deep-sleep
    RMSSD. Fetching it per target would double the request count against a
    rate limit this API applies readily."""
    src = inspect.getsource(gh.ingest_range)
    assert "dict.fromkeys(" in src
    assert "fetched.get(spec.api_type)" in src


def test_daily_upsert_merges_rather_than_replaces():
    """A day whose VO2 max is missing must not blank the resting HR written
    for it moments earlier."""
    src = inspect.getsource(gh.ingest_range)
    assert "func.coalesce" in src


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


# ---------------------------------------------------------------------------
# The loopback paste flow
# ---------------------------------------------------------------------------

def test_the_browser_navigation_login_route_is_gone():
    """It could never work and its failure was baffling.

    `require_query` reads the bearer token from an Authorization header, and
    this project has no cookie session. A GET the browser must navigate to
    therefore cannot authenticate — pressing Connect produced a raw FastAPI
    validation error about a missing header, which reads like a server fault
    rather than an impossible design. The consent URL is fetched over the
    authenticated XHR client now and opened with window.open.
    """
    assert "/auth/google-health/login" not in _routes()


def test_exchange_route_exists():
    """Google refuses a LAN hostname as a redirect URI — it demands a public
    top-level domain over HTTPS, with `localhost` its only exception. For a
    self-hosted install that leaves exposing the app, tunnelling the loopback
    port, or capturing the code by hand. This is the third, and the only one
    that requires no infrastructure and no exposure."""
    assert "POST" in _routes().get("/google-health/exchange", set())
    assert "POST" in _routes().get("/google-health/authorize-url", set())


def test_exchange_accepts_a_pasted_url_and_pulls_out_the_parameters():
    """People paste the whole address, not a dissected query string."""
    src = inspect.getsource(api.exchange)
    assert "urlparse" in src and "parse_qs" in src
    assert "redirected_url" in src


def test_exchange_still_enforces_the_state_handshake():
    """The paste flow must not become a way around CSRF. The state is still
    minted by this server and burned exactly once."""
    src = inspect.getsource(api.exchange)
    assert "_burn_state(state)" in src


def test_exchange_reports_a_google_side_error_rather_than_a_missing_code():
    """A denied consent comes back as ?error=access_denied with no code.
    Saying "no authorization code found" there would send the user hunting
    for a copy-paste mistake they did not make."""
    src = inspect.getsource(api.exchange)
    assert 'params.get("error")' in src


def test_exchange_reuses_the_registered_redirect_uri():
    """Google requires the redirect_uri in the token exchange to be
    byte-identical to the one in the authorize request."""
    src = inspect.getsource(api.exchange)
    assert "cfg.callback_url" in src


def test_expired_state_says_how_to_recover():
    src = inspect.getsource(api.exchange)
    assert "15 minutes" in src, "tell the user the window, not just that it closed"


# ---------------------------------------------------------------------------
# Config write semantics
# ---------------------------------------------------------------------------

def test_a_blank_secret_keeps_the_stored_one():
    """The UI never echoes the secret back and tells the user that leaving
    the field blank keeps it. This handler used to overwrite unconditionally,
    so the SECOND save — after the field had been cleared on the first —
    silently wiped the secret, leaving a config that reported a client_id and
    could not authorise. A promise the UI makes has to be kept here."""
    src = inspect.getsource(api.set_config)
    assert "if secret:" in src
    assert "cfg.client_secret = secret" in src


def test_the_first_save_still_requires_a_secret():
    """Blank-keeps-existing must not become blank-is-fine, or the config
    reports configured with nothing to authorise with."""
    src = inspect.getsource(api.set_config)
    assert "elif not cfg.client_secret:" in src
    assert "required the first time" in src


def test_configured_means_both_halves_are_present():
    """`configured` gates the consent button. If it could be true with only
    a client id, the button would enable and the flow would fail at Google."""
    src = inspect.getsource(api.get_config)
    assert "cfg.client_id and cfg.client_secret" in src


# ---------------------------------------------------------------------------
# Per-type filter strategy — established empirically against the live API
# ---------------------------------------------------------------------------

def test_daily_types_filter_on_a_civil_date():
    """The documentation describes the filter grammar but not which field
    each type exposes. Getting it wrong is a flat 400
    (INVALID_DATA_POINT_FILTER_DATA_TYPE_MEMBER), not an ignored parameter,
    so every one of these was confirmed against the real API."""
    from datetime import date as _date

    f = gh._filter_for("daily-sleep-temperature-derivations",
                       _date(2026, 8, 14), _date(2026, 8, 22))
    assert f is not None
    assert "daily_sleep_temperature_derivations.date" in f
    assert "2026-08-14" in f and "T00:00:00Z" not in f


def test_interval_types_filter_on_interval_start_time():
    from datetime import date as _date

    f = gh._filter_for("steps", _date(2026, 8, 14), _date(2026, 8, 22))
    assert f is not None and "steps.interval.start_time" in f and "T00:00:00Z" in f


def test_sample_and_session_types_accept_no_filter_at_all():
    """oxygen-saturation, heart-rate, sleep and weight rejected every filter
    field tried. They are fetched unfiltered and bounded in Python."""
    from datetime import date as _date

    for t in ("oxygen-saturation", "heart-rate", "sleep", "weight"):
        assert gh._filter_for(t, _date(2026, 8, 14), _date(2026, 8, 22)) is None


def test_unfiltered_fetches_are_bounded():
    """Without a server-side filter there is nothing to stop a paginated walk
    through years of samples if the newest-first ordering ever changes."""
    src = inspect.getsource(gh.fetch_data_points)
    assert "max_pages" in src
    assert "_within(" in src


def test_rate_limiting_is_retried_not_reported_as_absence():
    """A 429 surfaced as a hard failure makes an available stream look
    unavailable — the one thing the probe must not get wrong."""
    src = inspect.getsource(gh._get_with_retry)
    assert "429" in src and "Retry-After" in src


def test_the_probe_paces_itself():
    src = inspect.getsource(gh.probe_available_types)
    assert "asyncio.sleep" in src


# ---------------------------------------------------------------------------
# Poll cadence — GH-2
# ---------------------------------------------------------------------------

def test_the_tick_enforces_the_configured_interval():
    """The scheduler ticks on a fixed short cadence and the tick itself
    decides whether enough time has passed.

    Rescheduling the APScheduler job on every settings change would work too,
    and would not take effect until the next restart. Gating inside the tick
    means a changed interval applies on the next tick.
    """
    from myvitals.tasks import scheduled

    src = inspect.getsource(scheduled._google_health_tick)
    assert "poll_interval_min" in src
    assert "last_sync_at" in src
    assert "timedelta(minutes=interval)" in src


def test_the_interval_has_a_floor():
    """A poll fetches ten data types over a three-day window, and the API
    rate-limits readily enough that a dozen calls in a row trips a 429.
    Polling every couple of minutes spends quota to re-read overnight
    metrics that change once a night."""
    from myvitals.tasks import scheduled

    assert "max(15" in inspect.getsource(scheduled._google_health_tick)
    assert "max(15" in inspect.getsource(api.set_poll)


def test_the_interval_has_a_ceiling():
    """A day is the longest interval that still counts as polling."""
    assert "min(1440" in inspect.getsource(api.set_poll)


def test_enabling_the_poll_does_not_require_naming_an_interval():
    """interval_min is optional so a plain enable keeps the stored value
    rather than silently resetting it to a default."""
    assert api.PollToggle.model_fields["interval_min"].default is None


def test_daily_upsert_rows_all_carry_the_same_columns():
    """pg_insert(...).values(list_of_dicts) builds its column list from the
    FIRST dict and silently drops keys that only appear in later ones.

    That shipped: fifteen days had a resting heart rate and ten also had HRV
    and respiratory rate; the first row carried only resting_hr, so the other
    three columns were never written even though the sync counted them as
    extracted. The counts were right and the table was empty.
    """
    src = inspect.getsource(gh.ingest_range)
    assert "_DAILY_COLUMNS" in src
    assert "cols.get(col) for col in _DAILY_COLUMNS" in src


def test_every_daily_target_maps_to_a_real_column():
    """A target naming a column that does not exist would fail at insert
    time, inside a scheduled job, on whichever type happened to serve data."""
    from myvitals.db import models

    real = set(models.GoogleHealthDaily.__table__.columns.keys())
    for spec in gh.INGEST_TYPES:
        if spec.target.startswith("daily:"):
            column = spec.target.split(":", 1)[1]
            assert column in real, f"{spec.target} has no column"
            assert column in gh._DAILY_COLUMNS, f"{column} missing from _DAILY_COLUMNS"
