"""The fasting streak counts LOCAL days over the whole history (UX-D2).

It used to count back from the UTC date over UTC-dated `ended_at` inside the
stats window, so it read 0 every morning until that day's fast ended, a fast
ending after 7pm Central was filed under tomorrow, and a streak older than the
window was cut at its edge.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

from myvitals.api import fasting


class _Res:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items


class _Db:
    """First query: sessions in the window. Second: every ended_at."""

    def __init__(self, sessions, ended):
        self._queue = [_Res(sessions), _Res(ended)]

    async def execute(self, _stmt):
        return self._queue.pop(0)


def _utc(y, m, d, h):
    return datetime(y, m, d, h, tzinfo=timezone.utc)


async def test_evening_fasts_count_on_their_local_day_and_today_is_pending(monkeypatch):
    from myvitals.config import settings
    monkeypatch.setattr(settings, "tz", "America/Chicago")
    monkeypatch.setattr(fasting, "local_today", lambda: date(2026, 9, 22))
    # Fasts ending at 8pm Central on the 19th, 20th and 21st, stored as
    # 01:00 UTC the following day. Nothing has ended yet today (the 22nd).
    ended = [_utc(2026, 9, 20, 1), _utc(2026, 9, 21, 1), _utc(2026, 9, 22, 1)]
    sessions = [SimpleNamespace(started_at=e.replace(hour=0), ended_at=e) for e in ended]
    out = await fasting.stats(days=90, db=_Db(sessions, ended))
    # Three consecutive local days, still running because today is not over.
    assert out["current_streak_days"] == 3


async def test_a_streak_longer_than_the_window_is_not_cut_off(monkeypatch):
    from myvitals.config import settings
    monkeypatch.setattr(settings, "tz", "America/Chicago")
    monkeypatch.setattr(fasting, "local_today", lambda: date(2026, 9, 22))
    from datetime import timedelta
    # 120 daily fasts ending at noon Central; the stats window is 90 days.
    ended = [_utc(2026, 9, 22, 17) - timedelta(days=i) for i in range(120)]
    window = ended[:90]
    sessions = [SimpleNamespace(started_at=e - timedelta(hours=16), ended_at=e) for e in window]
    out = await fasting.stats(days=90, db=_Db(sessions, ended))
    assert out["current_streak_days"] == 120
