"""Trail-snapshot write dedup (SA-C5) + the dead history endpoint (SA-C4).

The RainoutLine poller used to insert a `trail_status_snapshots` row every
15 minutes unconditionally: 35 trails at 96 ticks/day accumulated 463,314
rows in 4.5 months, 99.62% byte-identical to the previous row for that
trail — 76 MB storing 1,746 actual facts. `_snapshot_changed` is the new
gate: write only when (status, comment, source_ts) differs from the
trail's last-persisted snapshot. `trails.last_seen_at` keeps being touched
on every poll regardless (`_ensure_trail`), so "last checked" stays exact
even on a tick that writes no snapshot.

SA-C4's `/trails/{id}/history` route and the `trailHistory` client method
were removed rather than kept: zero callers on either client (no Vue view,
no Compose screen, and the client wrapper itself had no callers) and zero
production hits. See the SA-C4 correction in docs/sa-findings.json for
what a defensible history/reliability surface would need if one is ever
built — this fix does not attempt that.
"""
from __future__ import annotations

import inspect
from datetime import datetime, timezone

from myvitals.integrations import rainoutline
from myvitals.integrations.rainoutline import TrailReading, _snapshot_changed


def _reading(
    status: str = "open",
    comment: str | None = "all clear",
    source_ts: datetime | None = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc),
) -> TrailReading:
    return TrailReading(
        extension=101, name="Test Trail", status=status,
        comment=comment, source_ts=source_ts,
    )


class TestSnapshotChanged:
    def test_first_sighting_always_writes(self):
        """A trail with no prior snapshot has nothing to compare against —
        the first reading is itself a fact worth keeping."""
        assert _snapshot_changed(None, _reading()) is True

    def test_identical_reading_does_not_write(self):
        prev = ("open", "all clear", datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc))
        assert _snapshot_changed(prev, _reading()) is False

    def test_status_change_writes(self):
        prev = ("closed", "all clear", datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc))
        assert _snapshot_changed(prev, _reading(status="open")) is True

    def test_comment_change_alone_writes(self):
        """Status can hold while the message changes ("wet spots" ->
        "dried out") — that is still new information."""
        prev = ("open", "wet spots", datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc))
        assert _snapshot_changed(prev, _reading(comment="dried out")) is True

    def test_source_ts_change_alone_writes(self):
        """The upstream site re-publishing the same status/comment at a
        new source timestamp is a new statement, not a repeat."""
        prev = ("open", "all clear", datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc))
        assert _snapshot_changed(prev, _reading()) is True

    def test_both_comments_none_is_not_a_change(self):
        prev = ("open", None, datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc))
        reading = _reading(comment=None)
        assert _snapshot_changed(prev, reading) is False


class TestWritePathWiring:
    def test_the_insert_is_gated_on_snapshot_changed(self):
        """Guards against the fix landing as a comment-only no-op — the
        actual `db.add(TrailStatusSnapshot(...))` call must sit behind
        `_snapshot_changed`."""
        src = inspect.getsource(rainoutline.poll_and_persist)
        assert "if _snapshot_changed(prev, r):" in src
        gate_idx = src.index("if _snapshot_changed(prev, r):")
        add_idx = src.index("db.add(models.TrailStatusSnapshot(")
        assert gate_idx < add_idx

    def test_last_seen_at_is_touched_unconditionally(self):
        """`_ensure_trail` (which sets last_seen_at) must run before, and
        independently of, the dedup gate — a poll that writes no snapshot
        must still record that the trail was checked."""
        src = inspect.getsource(rainoutline.poll_and_persist)
        ensure_idx = src.index("await _ensure_trail(")
        gate_idx = src.index("if _snapshot_changed(prev, r):")
        assert ensure_idx < gate_idx
        ensure_src = inspect.getsource(rainoutline._ensure_trail)
        assert "row.last_seen_at = now" in ensure_src
        assert "last_seen_at=now" in ensure_src  # the find-or-create branch

    def test_alerting_still_compares_status_only_not_the_full_tuple(self):
        """The dedup fix must not change alert semantics: a comment-only
        edit with the same status must not fire an open/close alert."""
        src = inspect.getsource(rainoutline.poll_and_persist)
        assert "prev_status = prev[0] if prev else None" in src
        assert "_should_alert(notify_by_id[trail.id], prev_status, r.status)" in src


class TestHistoryEndpointRemoved:
    def test_no_history_route_on_the_trails_router(self):
        from myvitals.api import trails as trails_api

        paths = {r.path for r in trails_api.router.routes}
        assert not any(p.endswith("/history") for p in paths)

    def test_no_trail_history_client_method(self):
        import pathlib

        client_ts = pathlib.Path(__file__).parents[2] / "frontend" / "src" / "api" / "client.ts"
        assert "trailHistory" not in client_ts.read_text()
