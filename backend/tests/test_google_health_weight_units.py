"""Five weight points in the account, zero written, and no error anywhere.

`_weight_kg` tried `weightKilograms`, `kilograms` and `value`. Google Health
serves the field as `weightGrams`, so every extraction returned None, every
point was skipped by the `if value is None: continue` guard in
`ingest_range`, and the run logged `'weight': 0` beside counts that were
plainly working — `'spo2': 808`, `'steps': 1065`, `'body_fat': 1`.

Nothing failed. A zero from a type that genuinely has no data and a zero
from a type whose parser cannot read the payload are the same number, and
the source comment had concluded the former ("Both return nothing on this
account today"). The probe endpoint was the only thing that ever saw the
difference — it reported `weight: points=5, ok=True` against the ingest's
`0` — and no code compares the two.

The real reading it was dropping came from a Garmin Index scale, exported
into Health Connect by `com.garmin.android.apps.connectmobile` and mirrored
to the Google Health API: 115330 g at 2026-08-24T20:53:03Z, alongside a
manually-entered duplicate of the same weigh-in.
"""
from __future__ import annotations

import inspect

from myvitals.integrations.google_health import _body, _weight_kg

#: One real point, trimmed to the parts the extractor reads.
GARMIN_POINT = {
    "name": "users/…/dataTypes/weight/dataPoints/781358263232693160",
    "dataSource": {
        "recordingMethod": "PASSIVELY_MEASURED",
        "device": {"formFactor": "SCALE"},
        "application": {"packageName": "com.garmin.android.apps.connectmobile"},
        "platform": "HEALTH_CONNECT",
    },
    "weight": {
        "sampleTime": {"physicalTime": "2026-08-24T20:53:03Z"},
        "weightGrams": 115330,
    },
}


def test_the_real_payload_yields_kilograms() -> None:
    assert _weight_kg(_body(GARMIN_POINT, "weight")) == 115.33


def test_grams_are_converted_not_passed_through() -> None:
    """115330 must never reach `weight_kg`. The column is kilograms, and a
    gram figure in it is a 1000x error that every downstream target,
    projection and BMI would quietly consume."""
    kg = _weight_kg({"weightGrams": 115330})
    assert kg is not None and 20 < kg < 400, f"implausible body mass: {kg} kg"


def test_the_documented_shapes_still_work() -> None:
    """The original keys stay supported — they cost nothing and the API
    surface was never confirmed to be grams-only for all time."""
    assert _weight_kg({"weightKilograms": 80.5}) == 80.5
    assert _weight_kg({"kilograms": 80.5}) == 80.5
    assert _weight_kg({"value": 80.5}) == 80.5


def test_grams_win_when_both_are_present() -> None:
    """`weightGrams` is what the API actually sends, so it is authoritative."""
    assert _weight_kg({"weightGrams": 115330, "value": 999}) == 115.33


def test_absent_is_none_not_zero() -> None:
    """A point with no readable weight must not be recorded as weighing
    nothing — the whole `null is not zero` discipline depends on it."""
    assert _weight_kg({}) is None
    assert _weight_kg({"weightGrams": None}) is None
    assert _weight_kg({"weightGrams": ""}) is None


def test_zero_grams_is_not_treated_as_missing() -> None:
    """Distinct from absent: 0 is a readable value. It is nonsense as a body
    mass, but inventing a None for it would hide a real bad reading."""
    assert _weight_kg({"weightGrams": 0}) == 0.0


def test_extractor_documents_the_unit_it_returns() -> None:
    """The next person to add a body measurement will copy this function."""
    doc = inspect.getdoc(_weight_kg) or ""
    assert "gram" in doc.lower() and "kilogram" in doc.lower(), (
        "say which unit comes in and which goes out"
    )
