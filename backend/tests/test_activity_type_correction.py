"""Correcting an activity's type — migration 0069.

A watch auto-detects workouts and guesses: mowing a lawn arrived from Health
Connect as "cycling", 26 minutes and 62 metres. The user can now correct the
type on any source. Three rules keep that correction from being undone or
from lying about itself:

1. It is written to `type`, so every reader sees it without changing.
2. `recorded_type` keeps the device's word and marks the type as the user's,
   so neither the sink nor the bulk importer may overwrite it.
3. Only the type crosses the provider boundary. Start, duration and name
   still belong to the device and stay manual-only.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from myvitals.api import strava
from myvitals.db import models
from myvitals.integrations import activity_sink

T = datetime(2026, 9, 22, 17, 7, tzinfo=timezone.utc)


def _act(source="healthconnect", **kw):
    d = dict(source=source, source_id="sid", type="cycling", start_at=T,
             duration_s=1560, trail_id=None)
    d.update(kw)
    return models.Activity(**d)


class _Res:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class _Db:
    def __init__(self, act):
        self.act = act

    async def execute(self, _stmt):
        return _Res(self.act)

    async def commit(self):
        pass

    async def refresh(self, _obj):
        pass

    async def get(self, _model, _pk):
        return None


def _patch(act, **body):
    return asyncio.run(strava.edit_activity(
        act.source, act.source_id, strava.ActivityEditIn(**body), db=_Db(act),
    ))


# ── the PATCH ──────────────────────────────────────────────────────────

def test_correcting_a_watch_activity_keeps_what_the_watch_said():
    a = _act()
    out = _patch(a, type="yard_work")
    assert a.type == "yard_work"
    assert a.recorded_type == "cycling"
    assert out.type == "yard_work" and out.recorded_type == "cycling"


def test_a_second_correction_does_not_lose_the_original():
    a = _act()
    _patch(a, type="yard_work")
    _patch(a, type="walking")
    assert a.type == "walking"
    assert a.recorded_type == "cycling"


def test_choosing_the_recorded_type_is_an_undo():
    a = _act()
    _patch(a, type="yard_work")
    _patch(a, type="cycling")
    assert a.type == "cycling"
    assert a.recorded_type is None


def test_reset_type_puts_the_device_word_back():
    a = _act()
    _patch(a, type="yard_work")
    _patch(a, reset_type=True)
    assert (a.type, a.recorded_type) == ("cycling", None)


def test_the_label_is_normalised_to_a_type_key():
    a = _act()
    _patch(a, type="Yard Work")
    assert a.type == "yard_work"


def test_a_manual_activity_has_nothing_to_undo_to():
    a = _act(source="manual")
    _patch(a, type="yard_work")
    assert a.type == "yard_work"
    assert a.recorded_type is None


def test_only_the_type_crosses_the_provider_boundary():
    a = _act()
    with pytest.raises(HTTPException) as e:
        _patch(a, type="yard_work", duration_minutes=30)
    assert e.value.status_code == 403
    assert a.type == "cycling", "a rejected request must change nothing"


def test_the_choices_carry_labels_and_include_yard_work():
    choices = asyncio.run(strava.activity_type_choices())
    keys = [c.type for c in choices]
    assert "yard_work" in keys
    assert len(keys) == len(set(keys))


# ── re-sync cannot revert it ───────────────────────────────────────────

def _sql(expr) -> str:
    return str(expr.compile(dialect=postgresql.dialect()))


def test_the_write_rule_defers_to_a_correction():
    sql = _sql(activity_sink.protected_type("cycling"))
    assert "CASE WHEN" in sql
    assert "activities.recorded_type IS NULL" in sql
    assert "ELSE activities.type" in sql


def test_both_write_paths_apply_the_rule():
    import inspect
    from myvitals.api import imports
    assert "protected_type(" in inspect.getsource(activity_sink.upsert_activity)
    assert "protected_type(" in inspect.getsource(imports._upsert_activities_chunk)


# ── a dedupe carries the correction whole ──────────────────────────────

def test_retiring_a_corrected_duplicate_carries_both_columns():
    from sqlalchemy.sql.dml import Delete

    stale = _act(type="yard_work", recorded_type="cycling")
    winner = _act(source="strava", source_id="w", type="ride")

    class _Session:
        async def execute(self, stmt):
            return _Res(None if isinstance(stmt, Delete) else stale)

    retired = asyncio.run(activity_sink._retire_promotion(
        _Session(), "sid", "test", winner=winner))
    assert retired is True
    # The choice moves; the survivor's undo points at ITS device's word.
    assert (winner.type, winner.recorded_type) == ("yard_work", "ride")
