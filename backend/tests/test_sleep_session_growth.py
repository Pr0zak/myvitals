"""A broken night is one night, and a session may grow after it is synced.

Two defects, found together on 2026-11-18 while checking why HRV had gone
quiet:

1. The watch writes a sleep session while the night is still going and
   later rewrites it with a later end, same start. Ingest upserted on
   `start_at` with DO NOTHING, so the first, shorter version won forever:
   on 2026-11-15 the session stayed 03:17-04:58 UTC while its stages ran to
   13:09, and the night read 1.5 h. 37 nights from May to November 2026
   were cut short this way.
2. A night split into several sessions counted only the LONGEST. The night
   ending 2026-11-17 had 04:06-08:51 and 10:46-13:30 UTC and read 4.7 h.

Since Google started writing one HRV reading per night, stamped at the
night's end, both defects also blanked HRV: the reading fell outside the
window and the night had no HRV at all.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.dialects import postgresql

from myvitals.analytics.sleep import chain_night, merge_intervals, sum_stages_in
from myvitals.api.ingest import sleep_session_upsert


def _t(h: int, m: int = 0, day: int = 17) -> datetime:
    return datetime(2026, 11, day, h, m, tzinfo=timezone.utc)


def test_split_night_counts_both_sessions() -> None:
    spans = merge_intervals([(_t(10, 46), _t(13, 30)), (_t(4, 6), _t(8, 51))])
    assert spans == [(_t(4, 6), _t(8, 51)), (_t(10, 46), _t(13, 30))]
    rows = [
        (_t(4, 6), "light", 4 * 3600 + 45 * 60),
        (_t(10, 46), "light", 2 * 3600 + 44 * 60),
    ]
    by_stage = sum_stages_in(rows, spans)
    assert by_stage["light"] == (4 * 3600 + 45 * 60) + (2 * 3600 + 44 * 60)


def test_stage_in_the_gap_between_sessions_is_not_counted() -> None:
    spans = [(_t(4), _t(5)), (_t(7), _t(8))]
    rows = [(_t(4), "deep", 3600), (_t(6), "light", 3600), (_t(7), "rem", 3600)]
    assert sum_stages_in(rows, spans) == {"deep": 3600, "rem": 3600}


def test_stage_is_clamped_to_its_span_end_and_the_next_stage() -> None:
    spans = [(_t(4), _t(5))]
    # Runs 2 h but the session ends after 1 h.
    assert sum_stages_in([(_t(4), "light", 7200)], spans) == {"light": 3600}
    # Overlapping writers: the first row is cut at the second's start.
    rows = [(_t(4), "light", 1800), (_t(4, 10), "light", 600)]
    assert sum_stages_in(rows, spans) == {"light": 600 + 600}


def test_overlapping_sessions_merge_rather_than_double_count() -> None:
    spans = merge_intervals([(_t(3), _t(6)), (_t(5), _t(9)), (_t(9), _t(10))])
    assert spans == [(_t(3), _t(10))]


def _sql(rows) -> str:
    return str(sleep_session_upsert(rows).compile(dialect=postgresql.dialect()))


def test_a_later_sync_can_extend_a_session() -> None:
    sql = _sql([{"start_at": _t(3, 17, 15), "end_at": _t(13, 9, 15),
                 "source": "watch", "title": None}])
    assert "ON CONFLICT (start_at) DO UPDATE" in sql
    assert "greatest(sleep_sessions.end_at, excluded.end_at)" in sql


def test_a_replayed_older_snapshot_cannot_shrink_a_session() -> None:
    """The phone replays its Room buffer oldest-first, so the short version
    can arrive after the long one. The update only fires when the incoming
    end is later, and GREATEST would keep the longer end regardless."""
    sql = _sql([{"start_at": _t(3, 17, 15), "end_at": _t(4, 58, 15),
                 "source": "watch", "title": None}])
    assert "WHERE excluded.end_at > sleep_sessions.end_at" in sql


def test_only_inserted_or_grown_sessions_come_back() -> None:
    """RETURNING drives the summary recompute; a no-op conflict (same or
    shorter end) is filtered by the WHERE and returns nothing."""
    assert "RETURNING sleep_sessions.end_at" in _sql(
        [{"start_at": _t(3), "end_at": _t(4), "source": "watch", "title": None}])


def test_in_batch_duplicates_keep_the_latest_end() -> None:
    import asyncio

    from myvitals.api import ingest

    seen: list = []

    class _DB:
        async def execute(self, stmt):
            seen.append(stmt.compile(dialect=postgresql.dialect()).params)

            class _R:
                def scalars(self):
                    class _S:
                        def all(self):
                            return []
                    return _S()
            return _R()

    rows = [
        {"start_at": _t(3), "end_at": _t(9), "source": "watch", "title": None},
        {"start_at": _t(3), "end_at": _t(5), "source": "watch", "title": None},
    ]
    asyncio.run(ingest._upsert_sleep_sessions(_DB(), rows))
    ends = [v for k, v in seen[0].items() if k.startswith("end_at")]
    assert ends == [_t(9)]


def test_hrv_wake_grace_is_short() -> None:
    """The grace exists for a reading stamped just after the session row we
    hold. Anything long would start pulling in daytime readings."""
    from myvitals.analytics.baselines import HRV_WAKE_GRACE

    assert timedelta(0) < HRV_WAKE_GRACE <= timedelta(hours=1)


def _repair():
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).parents[1] / "scripts" / "repair_sleep_sessions.py"
    spec = importlib.util.spec_from_file_location("repair_sleep_sessions", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_repair_extends_to_the_last_stage_end() -> None:
    """2026-11-15: stored 03:17-04:58, an awake stage running past the
    stored end, and stages on to 13:04 + 300 s."""
    plan, orphans = _repair().plan_extensions(
        [(_t(3, 17, 15), _t(4, 58, 15))],
        [
            (_t(3, 17, 15), "awake", 360),
            (_t(4, 51, 15), "awake", 5580),
            (_t(6, 24, 15), "light", 1620),
            (_t(6, 51, 15), "light", 6 * 3600),
            (_t(12, 51, 15), "light", 780),
            (_t(13, 4, 15), "awake", 300),
        ],
    )
    assert plan == {_t(3, 17, 15): _t(13, 9, 15)}
    assert orphans == []


def test_repair_does_not_bridge_a_long_gap_or_cross_the_next_session() -> None:
    plan, orphans = _repair().plan_extensions(
        [(_t(3), _t(5)), (_t(9), _t(11))],
        [(_t(8), "light", 7200)],   # 3 h after the first session ends
    )
    assert plan == {}
    assert orphans == [(_t(8), "light", 7200)]

    plan, _ = _repair().plan_extensions(
        [(_t(3), _t(5)), (_t(9), _t(11))],
        [(_t(6), "light", 4 * 3600)],   # would run into the 09:00 session
    )
    assert plan == {_t(3): _t(9)}


def test_back_to_sleep_joins_the_night_but_a_nap_does_not() -> None:
    d16 = lambda h, m=0: _t(h, m, day=16)  # noqa: E731
    # Evening nap 17:12-18:10 CST the day before (3.6 h before bedtime),
    # main sleep, then back to sleep 2.7 h after waking.
    spans = chain_night([
        (d16(23, 12), _t(0, 10)),
        (_t(3, 45), _t(8, 51)),
        (_t(10, 46), _t(13, 30)),
    ])
    assert spans == [(_t(3, 45), _t(8, 51)), (_t(10, 46), _t(13, 30))]


def test_chain_night_empty() -> None:
    assert chain_night([]) == []


def test_a_day_without_a_session_does_not_borrow_yesterdays_night(monkeypatch) -> None:
    """2026-11-08 had no session; the fallback found 11-07's (ending 07:15
    local on the 7th) and copied its RHR and HRV."""
    from datetime import date

    from myvitals.analytics import baselines
    from myvitals.config import settings

    monkeypatch.setattr(settings, "tz", "America/Chicago")
    start, _end = baselines._fallback_search(date(2026, 11, 8))
    assert _t(13, 15, day=7) < start
