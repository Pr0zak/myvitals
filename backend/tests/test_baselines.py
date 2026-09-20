"""SA-N1 — the nightly RHR/HRV window resolves in `settings.tz`, not UTC.

`baselines.py:_night_window` hard-coded `tzinfo=timezone.utc` for its
22:00->09:00 "night". On this deployment (`settings.tz` = "America/Chicago")
that ran 17:00->04:00 local: ~5h40m of evening wakefulness folded in, the
last ~2h20m of real sleep cut off. Measured against the canonical
Health-Connect sleep session as ground truth, this was not a systematic bias
(the ratios/z-scores downstream of `nightly_rhr` and `nightly_hrv` cancel a
*proportional* window bias exactly) but real per-night noise: >=2 bpm on
roughly half of nights.

The fix mirrors `sleep.py:_stages_for_night` — prefer the canonical
SleepSession boundary when one exists (`_resolve_night_bounds`), and fall
back to the clock window only when there isn't one (`_night_window`),
resolved in `settings.tz` rather than UTC.

`_night_window(day)` itself stays a PURE, SYNCHRONOUS function of `day` alone
— not an implementation detail, a contract. A day-attribution bisector like
`api/summary.py:_owning_days` (SA-N2) needs a plain function it can call in a
tight loop over a whole date range with no database round-trip. The
canonical-session preference lives in the separate `_resolve_night_bounds`,
which only `nightly_rhr`/`nightly_hrv` call.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from myvitals.analytics import baselines
from myvitals.db import models


class _SessionLookup:
    """Just enough AsyncSession to drive `_resolve_night_bounds`.

    `execute` always answers the one query it issues (a SleepSession
    lookup) with whatever row was queued; nothing else is exercised here.
    Matches the `_FakeSession` convention already used in e.g.
    `test_hr_zones.py` — the real query is exercised against Postgres in
    the deployed app, what's worth pinning is the boundary arithmetic.
    """

    def __init__(self, session_row: models.SleepSession | None = None):
        self._row = session_row

    async def execute(self, _stmt):
        row = self._row

        class _Result:
            def scalar_one_or_none(_self):
                return row

        return _Result()


def test_night_window_is_a_pure_sync_function_of_day_alone():
    """SA-N2 contract: `api/summary.py:_owning_days` calls
    `night_window(day) -> (start, end)` synchronously in a tight bisect
    loop over an entire date range, with no database and no await. If
    `_night_window` ever grows a `db` parameter or an `async def` again,
    that caller breaks outright (TypeError / an un-awaited coroutine
    substituted for a tuple) rather than merely computing a wrong answer.
    """
    import inspect

    assert not inspect.iscoroutinefunction(baselines._night_window)
    sig = inspect.signature(baselines._night_window)
    assert list(sig.parameters) == ["day"]


def test_night_window_fallback_resolves_in_settings_tz(monkeypatch):
    """Before SA-N1 this was hard-coded UTC, so on a Central deployment the
    window ran 17:00->04:00 local — this test fails against that code (see
    the reviewer note below) and passes now.
    """
    from myvitals.config import settings
    monkeypatch.setattr(settings, "tz", "America/Chicago")

    day = date(2026, 9, 10)
    start, end = baselines._night_window(day)

    chicago = ZoneInfo("America/Chicago")
    assert start == datetime(2026, 9, 9, 22, 0, tzinfo=chicago)
    assert end == datetime(2026, 9, 10, 9, 0, tzinfo=chicago)

    # The crux of the bug: the pre-fix window was 22:00/09:00 **UTC**. In
    # Chicago (UTC-5 in September, CDT) that is 17:00/04:00 local. Converted
    # back to UTC, the fixed window must NOT land on the old UTC clock hours.
    assert start.astimezone(timezone.utc).hour != 22
    assert end.astimezone(timezone.utc).hour != 9


def test_night_window_stays_utc_when_settings_tz_is_utc(monkeypatch):
    """A deployment that genuinely runs UTC (`settings.tz` unset/"UTC")
    must keep behaving exactly as before — this is a local-vs-UTC fix, not
    a behaviour change for a UTC deployment.
    """
    from myvitals.config import settings
    monkeypatch.setattr(settings, "tz", "UTC")

    day = date(2026, 9, 10)
    start, end = baselines._night_window(day)

    assert start == datetime(2026, 9, 9, 22, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc)


async def test_resolve_night_bounds_falls_back_to_night_window(monkeypatch):
    """No canonical session for the night -> `_resolve_night_bounds` must
    hand back exactly `_night_window(day)`'s local-tz fallback, not a
    UTC-anchored window.
    """
    from myvitals.config import settings
    monkeypatch.setattr(settings, "tz", "America/Chicago")

    db = _SessionLookup(session_row=None)
    day = date(2026, 9, 10)
    start, end = await baselines._resolve_night_bounds(db, day)

    assert (start, end) == baselines._night_window(day)
    assert start == datetime(2026, 9, 9, 22, 0, tzinfo=ZoneInfo("America/Chicago"))


async def test_resolve_night_bounds_prefers_the_canonical_sleep_session(monkeypatch):
    """When a canonical SleepSession exists for the night, its own
    start_at/end_at win over the clock-window fallback entirely — matching
    `sleep.py:_stages_for_night`'s pattern and the ground truth the SA-N1
    measurement used. A real session that runs later than 22:00 local (e.g.
    a 23:10 bedtime) must not be truncated to the fallback's earlier start.
    """
    from myvitals.config import settings
    monkeypatch.setattr(settings, "tz", "America/Chicago")

    sess = models.SleepSession(
        start_at=datetime(2026, 9, 9, 23, 10, tzinfo=timezone.utc),
        end_at=datetime(2026, 9, 10, 6, 45, tzinfo=timezone.utc),
        source="watch",
    )
    db = _SessionLookup(session_row=sess)
    day = date(2026, 9, 10)
    start, end = await baselines._resolve_night_bounds(db, day)

    assert start == sess.start_at
    assert end == sess.end_at
    # Not the fallback clock window — the session ran later than 22:00 and
    # the fix must not clip it back to the fallback's boundary.
    assert start != datetime(2026, 9, 9, 22, 0, tzinfo=ZoneInfo("America/Chicago"))
