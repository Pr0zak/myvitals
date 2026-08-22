"""AI daily-call quota guard — the server-side billing guardrail.

Locks `_check_and_bump_quota`: the disabled/no-key gates (400), the daily
limit (429), and the day-rollover reset (which v0.7.292 made commit eagerly so
a cache-hit request can't roll it back).
"""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from myvitals.api.ai import _check_and_bump_quota, _local_today_ai


class _FakeDB:
    """Records commits; _check_and_bump_quota commits the rollover reset."""

    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


def _cfg(**kw):
    base = dict(
        enabled=True, anthropic_api_key="k", calls_today=0,
        calls_today_date=_local_today_ai(), daily_call_limit=30,
    )
    base.update(kw)
    return SimpleNamespace(**base)


async def test_quota_day_is_the_users_local_day():
    """The reason these tests use _local_today_ai rather than date.today().

    The quota rolls over on the user's LOCAL day (v0.11.0). These tests
    previously asserted against `date.today()`, which reads the process
    timezone — UTC in the container. That agrees with the code for
    two-thirds of the day and disagrees for the rest, so the suite passed
    every run before ~7pm Central and failed after it. A time-dependent
    test is worse than no test: it teaches you to distrust the suite.
    """
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    from myvitals.config import settings

    tz = ZoneInfo(settings.tz) if settings.tz != "UTC" else timezone.utc
    assert _local_today_ai() == datetime.now(tz).date()


async def test_under_limit_passes():
    await _check_and_bump_quota(_FakeDB(), _cfg(calls_today=5))  # no raise


async def test_at_limit_raises_429():
    with pytest.raises(HTTPException) as ei:
        await _check_and_bump_quota(_FakeDB(), _cfg(calls_today=30))
    assert ei.value.status_code == 429


async def test_disabled_raises_400():
    with pytest.raises(HTTPException) as ei:
        await _check_and_bump_quota(_FakeDB(), _cfg(enabled=False))
    assert ei.value.status_code == 400


async def test_missing_key_raises_400():
    with pytest.raises(HTTPException) as ei:
        await _check_and_bump_quota(_FakeDB(), _cfg(anthropic_api_key=""))
    assert ei.value.status_code == 400


async def test_new_day_resets_and_commits():
    db = _FakeDB()
    # Yesterday's counter was maxed; today it must roll over to 0 and persist.
    cfg = _cfg(calls_today=30, calls_today_date=_local_today_ai() - timedelta(days=1))
    await _check_and_bump_quota(db, cfg)  # 0 < 30 after reset → no raise
    assert cfg.calls_today == 0
    assert cfg.calls_today_date == _local_today_ai()
    assert db.commits == 1  # the rollover was committed eagerly
