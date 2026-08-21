"""Server-persisted display preferences (DISP-1).

Units, time format and theme were localStorage-only on the web and did
not exist at all on the phone, which hardcoded `/ 1609.34` in twelve
places across eight files — using two different values for the same
constant (1609.34 and 1609.344).

The tests that matter here are about the *merge*: a partial write from
one surface must not erase a preference set on the other.
"""

from __future__ import annotations

import pytest

from myvitals.api import profile as prof


class TestDefaults:
    def test_every_key_has_a_default(self):
        """The payload always carries every key.

        A client should never have to know the default for a preference it
        has not seen — that is how the web and the phone end up disagreeing
        about what "unset" means.
        """
        out = prof._display_payload({})
        assert set(out) == set(prof.DISPLAY_DEFAULTS)
        assert out == prof.DISPLAY_DEFAULTS

    def test_defaults_are_all_valid_values(self):
        for k, v in prof.DISPLAY_DEFAULTS.items():
            assert v in prof.DISPLAY_ALLOWED[k]

    def test_missing_profile_yields_defaults_not_an_error(self):
        assert prof._display_payload({}) == prof.DISPLAY_DEFAULTS
        assert prof._display_payload({"display": {}}) == prof.DISPLAY_DEFAULTS


class TestValidation:
    def test_stored_garbage_falls_back_to_the_default(self):
        """A bad stored value must not propagate to the clients.

        Both surfaces branch on these strings; an unrecognised one would
        silently take the else branch on each, and the two else branches
        are not necessarily the same.
        """
        out = prof._display_payload({"display": {"units": "furlongs"}})
        assert out["units"] == prof.DISPLAY_DEFAULTS["units"]

    def test_wrong_type_falls_back(self):
        out = prof._display_payload({"display": {"units": 42}})
        assert out["units"] == prof.DISPLAY_DEFAULTS["units"]

    def test_retired_theme_value_is_folded_not_rejected(self):
        """"refined" was retired in v0.7.366 but may still be cached.

        Rejecting it would 400 on every save for anyone whose localStorage
        still holds it, which turns a cosmetic legacy value into a broken
        Settings page.
        """
        assert "refined" in prof.DISPLAY_ALLOWED["theme"]
        out = prof._display_payload({"display": {"theme": "refined"}})
        assert out["theme"] == "neon"

    @pytest.mark.parametrize("units", ["metric", "imperial"])
    def test_valid_units_round_trip(self, units):
        assert prof._display_payload({"display": {"units": units}})["units"] == units

    @pytest.mark.parametrize("tf", ["auto", "12h", "24h"])
    def test_valid_time_formats_round_trip(self, tf):
        out = prof._display_payload({"display": {"time_format": tf}})
        assert out["time_format"] == tf


class TestScoping:
    def test_display_lives_under_its_own_key(self):
        """Namespaced so it cannot collide with goal or tile keys.

        `extra` also holds steps_goal, sleep_target_h, vitals_order and
        vitals_hidden. Flat keys would eventually collide.
        """
        out = prof._display_payload({
            "display": {"units": "metric"},
            "steps_goal": 12000,
            "vitals_order": ["hrv"],
        })
        assert out["units"] == "metric"
        assert "steps_goal" not in out

    def test_reading_ignores_unrelated_extra_keys(self):
        out = prof._display_payload({"steps_goal": 12000})
        assert out == prof.DISPLAY_DEFAULTS

    def test_the_write_is_partial_by_construction(self):
        """A patch omitting a field must leave it alone.

        This is the whole reason the endpoint exists separately from
        PUT /profile, which assigns `p.extra = body.extra` wholesale. If
        this write replaced the display block instead of updating it, the
        phone saving `units` would wipe a `theme` set on the web.
        """
        import inspect
        src = inspect.getsource(prof.put_display_prefs)
        assert "display.update(incoming)" in src, (
            "the write must merge into the stored block, not replace it"
        )
        assert "if v is not None" in src, (
            "omitted fields must be dropped from the patch, not sent as None"
        )

    def test_the_write_reassigns_extra_rather_than_mutating(self):
        """SQLAlchemy does not track in-place mutation of a JSON column.

        Mutating `p.extra` directly commits nothing at all — the save
        appears to succeed and the value is gone on the next read.
        """
        import inspect
        src = inspect.getsource(prof.put_display_prefs)
        assert "dict(p.extra or {})" in src
        assert "p.extra = extra" in src
