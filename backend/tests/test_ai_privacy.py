"""Privacy regression tests for the Claude payload builders.

These lock the v0.7.292 fixes: the user's real name (which can live in the
sober `addiction` column) and Strava activity titles (which routinely embed
home/locations) must never be serialized into a Claude payload. A future edit
that re-adds either field should fail here rather than ship a silent leak.

No DB / network — a minimal AsyncSession stand-in feeds queued query results
and the Anthropic client is monkeypatched to capture what would be sent.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from myvitals.db import models
from myvitals.integrations import claude

REAL_NAME = "Jane Q. Public"


class _Result:
    """Stands in for a SQLAlchemy Result for the two access shapes the
    payload builders use: .scalar_one_or_none() and .scalars().all()."""

    def __init__(self, one=None, many=None):
        self._one = one
        self._many = many if many is not None else []

    def scalar_one_or_none(self):
        return self._one

    def scalars(self):
        return self

    def all(self):
        return self._many


class _FakeDB:
    """Minimal AsyncSession: returns queued results in execute() call order."""

    def __init__(self, results):
        self._results = list(results)
        self._i = 0

    async def execute(self, *args, **kwargs):
        r = self._results[self._i]
        self._i += 1
        return r


async def test_sober_status_never_sends_addiction_or_real_name():
    now = datetime.now(timezone.utc)
    active = models.SoberStreak(
        addiction=REAL_NAME, start_at=now - timedelta(days=30), end_at=None,
    )
    past = models.SoberStreak(
        addiction=REAL_NAME, start_at=now - timedelta(days=90),
        end_at=now - timedelta(days=60),
    )
    db = _FakeDB([
        _Result(one=active),           # active-streak lookup
        _Result(many=[active, past]),  # all-streaks duration aggregate
    ])

    out = await claude._sober_status(db)

    assert out is not None
    assert "addiction" not in out
    assert REAL_NAME not in json.dumps(out)
    # Still returns the useful, non-identifying duration stats.
    assert out["current_days"] >= 29
    assert out["total_resets"] == 1


class _FakeAnthropic:
    """Captures the kwargs passed to messages.create so the test can inspect
    exactly what bytes would have left the box."""

    captured: list = []

    def __init__(self, *a, **k):
        pass

    class _Messages:
        async def create(self, **kwargs):
            _FakeAnthropic.captured.append(kwargs)
            block = SimpleNamespace(type="text", text="ok")
            usage = SimpleNamespace(input_tokens=1, output_tokens=1)
            return SimpleNamespace(content=[block], model="test", usage=usage)

    @property
    def messages(self):
        return _FakeAnthropic._Messages()


async def test_activity_summary_never_sends_strava_title(monkeypatch):
    monkeypatch.setattr(claude, "AsyncAnthropic", _FakeAnthropic)
    _FakeAnthropic.captured.clear()

    db = _FakeDB([_Result(many=[])])  # _daily_rows → no summaries
    secret_title = "Evening Ride from 123 Secret Lane"
    act = models.Activity(
        start_at=datetime.now(timezone.utc), type="ride", name=secret_title,
        duration_s=3600, distance_m=20000,
    )
    cfg = SimpleNamespace(enabled=True, anthropic_api_key="x", model="m")

    await claude.activity_summary(db, cfg, act)

    sent = json.dumps(_FakeAnthropic.captured)
    assert secret_title not in sent          # title (location) must not leak
    assert "Secret Lane" not in sent
    assert "ride" in sent                    # the activity type IS sent
