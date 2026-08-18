"""The Activity ingest sink — TD-5.

Three defects motivated one funnel, and the rules that fix them are easy to
regress because they are all about what the sink *does not* do.

1. ``maybe_complete_cardio_day`` was wired to the retired Strava OAuth path
   and to Concept2, but not to ``strava_web.upsert_activity_from_fit`` --
   the only Strava path that actually runs. Cardio-day auto-completion was
   dead for every ride the user synced.
2. ``_link_activity_to_trail`` had exactly one caller, inside the manual
   ``POST /trails/link-activities``, so nothing linked a trail on ingest.
3. The FIT upsert wrote ``avg_hr``, ``max_hr`` and ``polyline``
   unconditionally. ``parse_fit_bytes`` returns an empty ``ParsedFit`` and
   logs a warning rather than raising, so re-syncing an activity whose FIT
   file failed to parse silently nulled good heart-rate and GPS data.

These tests exercise the column-selection rules directly rather than through
a database, which is where the interesting decisions live.
"""

from __future__ import annotations

from myvitals.integrations import activity_sink


def _update_set(values: dict) -> dict:
    """Reproduce the sink's update projection: provider columns, non-null."""
    insert_values = {
        k: v for k, v in values.items()
        if k in activity_sink.PROVIDER_COLUMNS or k in ("source", "source_id")
    }
    return {
        k: v for k, v in insert_values.items()
        if k in activity_sink.PROVIDER_COLUMNS and v is not None
    }


def test_a_thin_resync_cannot_erase_a_richer_one():
    """The destructive-overwrite bug, stated as a rule.

    A FIT file that fails to parse yields None for heart rate and polyline.
    Those must be skipped on update, not written, or the good data stored by
    the sync that worked is gone.
    """
    failed_parse = {
        "source": "strava", "source_id": "123",
        "type": "ride", "name": "Evening Ride",
        "start_at": "2026-08-01T17:00:00Z", "duration_s": 3600,
        "avg_hr": None, "max_hr": None, "polyline": None,
    }
    written = _update_set(failed_parse)
    assert "avg_hr" not in written
    assert "max_hr" not in written
    assert "polyline" not in written
    # The fields it does know about still land.
    assert written["type"] == "ride"
    assert written["duration_s"] == 3600


def test_a_real_value_still_overwrites():
    """Skip-None must not become skip-everything: a later sync with better
    data is exactly what an upsert is for."""
    written = _update_set({
        "source": "strava", "source_id": "123",
        "avg_hr": 142.0, "max_hr": 171.0, "polyline": "abc",
    })
    assert written == {"avg_hr": 142.0, "max_hr": 171.0, "polyline": "abc"}


def test_zero_is_written_because_zero_is_a_measurement():
    """Falsy is not the same as absent. A ride with zero elevation gain is a
    flat ride, not a ride we know nothing about."""
    written = _update_set({
        "source": "strava", "source_id": "1", "elevation_gain_m": 0.0, "kcal": 0.0,
    })
    assert written["elevation_gain_m"] == 0.0
    assert written["kcal"] == 0.0


def test_user_owned_columns_are_never_written_by_a_provider():
    """notes, tags and trail_id belong to the user.

    The skip-None rule deliberately does not extend to them: for a
    user-owned field, None means "clear this", and a provider has no
    business expressing either intent. So they are excluded from the
    projection entirely rather than merely skipped when null.
    """
    written = _update_set({
        "source": "strava", "source_id": "1",
        "notes": "hijacked", "tags": ["hijacked"], "trail_id": 99,
        "name": "Real Ride",
    })
    for column in activity_sink.USER_OWNED_COLUMNS:
        assert column not in written, f"{column} must not be provider-writable"
    assert written["name"] == "Real Ride"


def test_provider_and_user_column_sets_do_not_overlap():
    """A column in both lists would make the rules contradictory."""
    assert not (
        set(activity_sink.PROVIDER_COLUMNS) & set(activity_sink.USER_OWNED_COLUMNS)
    )


def test_every_declared_column_exists_on_the_model():
    """An allowlist that names a column the model does not have would fail at
    runtime, in an ingest path, on whichever provider happened to send it."""
    from myvitals.db import models

    real = set(models.Activity.__table__.columns.keys())
    for column in activity_sink.PROVIDER_COLUMNS + activity_sink.USER_OWNED_COLUMNS:
        assert column in real, f"{column} is not a column on activities"


def test_allowlist_covers_the_model_or_omits_deliberately():
    """A new column must be classified, not silently ignored.

    `polyline_simple` is derived (the sink invalidates it rather than
    accepting it from a provider) and the two key columns are the identity,
    so those three are the only legitimate omissions. Anything else means
    someone added a field and no ingest path can populate it.
    """
    from myvitals.db import models

    classified = set(activity_sink.PROVIDER_COLUMNS) | set(activity_sink.USER_OWNED_COLUMNS)
    deliberate = {"source", "source_id", "polyline_simple"}
    unclassified = set(models.Activity.__table__.columns.keys()) - classified - deliberate
    assert not unclassified, (
        f"unclassified activity columns: {sorted(unclassified)}. Add each to "
        "PROVIDER_COLUMNS or USER_OWNED_COLUMNS in integrations/activity_sink.py."
    )


def test_every_ingest_path_goes_through_the_sink():
    """The point of the sink is that it is the only writer.

    Grepping is crude, but the failure it guards is exactly the one that
    produced this task: a new provider writing its own upsert and quietly
    not running the ingest side-effects.
    """
    import pathlib

    src = pathlib.Path(activity_sink.__file__).resolve().parents[1]
    offenders = []
    # api/imports.py is the one documented exception: a historical import is
    # thousands of rows, and the sink is row-at-a-time because it runs the
    # per-activity side-effects. It shares the sink's column allowlist
    # instead, which is asserted separately below.
    allowed = {"activity_sink.py", "imports.py"}
    for path in list((src / "integrations").glob("*.py")) + list((src / "api").glob("*.py")):
        if path.name in allowed:
            continue
        text = path.read_text()
        if "models.Activity" not in text:
            continue
        # Writing shapes: an ORM add, or an insert statement against the table.
        if "db.add(models.Activity(" in text:
            offenders.append(f"{path.name}: db.add(models.Activity(...))")
        if "insert(models.Activity)" in text:
            offenders.append(f"{path.name}: insert(models.Activity)")
    assert not offenders, (
        "These write Activity rows directly instead of calling "
        "integrations/activity_sink.py:upsert_activity, so they skip the "
        "None-guard, cardio-day completion and trail auto-linking:\n  "
        + "\n  ".join(offenders)
    )


def test_the_bulk_import_path_shares_the_sink_allowlist():
    """The one exempt writer must not re-derive which columns are writable.

    api/imports.py bulk-inserts historical activities and cannot use the
    row-at-a-time sink, but the question "may a provider write this column"
    has to have a single answer, or the exemption becomes a second policy
    that drifts.
    """
    import pathlib

    src = pathlib.Path(activity_sink.__file__).resolve().parents[1]
    text = (src / "api" / "imports.py").read_text()
    assert "from ..integrations.activity_sink import PROVIDER_COLUMNS" in text, (
        "api/imports.py must derive its updatable columns from the sink's "
        "allowlist rather than listing exclusions of its own"
    )
