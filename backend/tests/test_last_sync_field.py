"""`/summary/today`'s `last_sync` must mean sync freshness — SA-L6.

It used to be a bare `max(vitals_heartrate.time)`. That is the last watch HR
*sample*, not a sync, and the two only agree while the watch is actively
writing heart rate. Sampled over the last 719.2 hours of production data,
the field disagreed with the app's own `/query/last-sync` (which reads the
phone's `sync_heartbeat` row) for 158.4 of them — the chip amber-and-false
about 22% of wall-clock time, on the one screen the user opens first, and
pointing at the wrong fault (re-grant Health Connect / reinstall) when the
phone was syncing fine and the watch had simply stopped writing HR. Any
single "N hours stale" headline is an artefact of when you happen to look;
the ~22% figure is the durable claim, which is why nothing below asserts a
number of hours.

`_resolve_last_sync` gives the field the same three-rung answer
`/query/last-sync` already computes: the phone's last *successful* sync,
else its last *attempted* one, else — only with no `sync_heartbeat` row at
all — the last HR sample, so an install with none yet doesn't regress from
a wrong-but-present timestamp to "never synced" (the same failure in the
other direction; `SideNav.vue` keeps the identical `lastAttemptAt ??
lastSyncAt` fallback for the same reason).
"""
from __future__ import annotations

import inspect
from datetime import date, datetime, timezone
from types import SimpleNamespace

from myvitals.api import summary

T_SUCCESS = datetime(2026, 9, 18, 3, 51, 7, tzinfo=timezone.utc)
T_ATTEMPT = datetime(2026, 9, 18, 3, 50, 59, tzinfo=timezone.utc)
T_HR_SAMPLE = datetime(2026, 9, 15, 17, 30, 58, tzinfo=timezone.utc)


def _heartbeat(*, last_success_at=None, attempt_at=T_ATTEMPT):
    """A `sync_heartbeat` row shaped enough for `_resolve_last_sync`."""
    return SimpleNamespace(last_success_at=last_success_at, attempt_at=attempt_at)


class TestTheThreeRungs:
    def test_a_successful_sync_wins_even_with_a_stale_hr_sample(self):
        """The reported bug exactly: watch stopped writing HR 58h ago, phone
        synced 14 minutes ago. last_sync must be the phone's success, not
        the stale HR timestamp."""
        hb = _heartbeat(last_success_at=T_SUCCESS)
        assert summary._resolve_last_sync(hb, T_HR_SAMPLE) == T_SUCCESS

    def test_a_never_succeeded_attempt_beats_the_hr_sample(self):
        """Second rung: the phone has tried but never once succeeded (e.g.
        permissions revoked right after install) — still not "never
        synced", and still not the unrelated HR timestamp."""
        hb = _heartbeat(last_success_at=None, attempt_at=T_ATTEMPT)
        assert summary._resolve_last_sync(hb, T_HR_SAMPLE) == T_ATTEMPT

    def test_no_heartbeat_row_falls_back_to_the_hr_sample(self):
        """Third rung, added by the SA-L6 correction: an install with no
        `sync_heartbeat` rows yet (predates the table, or hasn't posted a
        single heartbeat) must not regress to "never synced" when a
        wrong-but-present HR timestamp is available instead."""
        assert summary._resolve_last_sync(None, T_HR_SAMPLE) == T_HR_SAMPLE

    def test_nothing_at_all_is_none_not_a_fabricated_time(self):
        """Null stays null all the way through — a brand-new install with
        no heartbeat and no HR sample must render "—", never a made-up
        instant."""
        assert summary._resolve_last_sync(None, None) is None


class TestTodayWiresItUp:
    def test_today_no_longer_reports_the_hr_sample_as_last_sync(self):
        """Regression guard for the original bug shape: `today()` must
        route `last_sync` through the sync-freshness resolver, not hand
        back the bare HR-table max under that name."""
        src = inspect.getsource(summary.today)
        # UI-3 moved the lookup into `_sync_signals` so `/summary/tiles`
        # shares it; the resolver call now lives there.
        assert "_sync_signals(db)" in src
        assert "_resolve_last_sync(hb, last_hr_sample_at)" in inspect.getsource(
            summary._sync_signals)
        assert "last_sync = last_sync_result.scalar()" not in src

    def test_the_hr_sample_instant_is_kept_under_its_own_name(self):
        """The proposal is explicit that nothing loses this value — it just
        stops being mislabelled as a sync."""
        src = inspect.getsource(summary.today)
        assert "last_hr_sample_at=last_hr_sample_at" in src


def test_schema_keeps_last_sync_and_last_hr_sample_at_distinct():
    """Both fields exist and are independently nullable — one client field
    name must not silently do double duty for two different meanings."""
    from myvitals.schemas import TodaySummary

    fields = TodaySummary.model_fields
    assert "last_sync" in fields
    assert "last_hr_sample_at" in fields
    empty = TodaySummary(date=date(2026, 9, 18))
    assert empty.last_sync is None
    assert empty.last_hr_sample_at is None
