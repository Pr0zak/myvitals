"""Three bugs found while verifying backlog claims (v0.12.5).

None was a backlog item. Each was found by checking whether a backlog
entry was true, which is the argument for verifying before building.
"""

from __future__ import annotations

import inspect
from datetime import date, datetime, timedelta, timezone

import pytest

from myvitals.analytics import advanced
from myvitals.api import export
from myvitals.integrations import google_health


class TestExportIsStreamed:
    """`/export/{table}.{fmt}` was an OOM kill, not a slow download.

    It did `result.scalars().all()` and then built the entire body as one
    string before wrapping it in `iter([...])` — a StreamingResponse that
    streams a single pre-built blob, double-buffered. `vitals_heartrate`
    holds ~23.6M rows and the container has no mem_limit on an 8 GB CT.

    That ceiling is also why the date range could never safely be made
    user-selectable: the export feature was blocked on this.
    """

    @staticmethod
    def _code_only(src: str) -> str:
        """Source with comment lines stripped — the comments quote the old
        code to explain the fix, so a plain substring search matches the
        prose rather than the implementation."""
        return "\n".join(
            line for line in src.splitlines()
            if not line.lstrip().startswith("#")
        )

    def test_no_full_materialisation(self):
        code = self._code_only(inspect.getsource(export.export_table))
        assert "scalars().all()" not in code
        assert "iter([" not in code

    def test_uses_a_server_side_cursor(self):
        for fn in (export._stream_csv, export._stream_json):
            src = inspect.getsource(fn)
            assert "stream_scalars" in src, f"{fn.__name__} does not stream"
            assert "yield_per" in src
            assert "partitions(" in src

    def test_the_stream_owns_its_own_session(self):
        """A StreamingResponse body is consumed AFTER the endpoint returns.

        The request-scoped session may already be closed by the time the
        first row is pulled, and that failure looks like a truncated
        download rather than an error.
        """
        for fn in (export._stream_csv, export._stream_json):
            src = inspect.getsource(fn)
            assert "async with SessionLocal() as own_db" in src

    def test_json_is_assembled_incrementally(self):
        """json.dumps over the whole list would defeat the point.

        Each row is still serialised with json.dumps, so escaping stays
        correct — only the array assembly is manual.
        """
        src = inspect.getsource(export._stream_json)
        assert 'yield "["' in src and 'yield "]"' in src
        assert "json.dumps(obj" in src

    def test_batch_size_is_bounded(self):
        assert 0 < export._STREAM_BATCH <= 10_000


class TestGoogleHealthChunking:
    """The shipped "Backfill 90 days" button could not succeed.

    asyncpg refuses a statement carrying more than 32,767 bind parameters,
    and a multi-row INSERT binds one per column per row — so a single
    `pg_insert(...).values(list)` caps at ~16k rows for two-column
    `vitals_spo2`. At ~500 SpO2 readings a day, 90 days is ~45,000 rows.

    It fails as an asyncpg error at execute time, not a truncation, so the
    whole sync aborts.
    """

    def test_the_upsert_is_chunked(self):
        assert hasattr(google_health, "_chunked_upsert")

    def test_chunk_size_is_derived_from_the_column_count(self):
        """A fixed row count would silently go back over the ceiling the
        moment a table gained a column."""
        src = inspect.getsource(google_health._chunked_upsert)
        assert "len(rows[0])" in src
        assert "_MAX_BIND_PARAMS // n_cols" in src

    def test_the_limit_leaves_headroom(self):
        assert google_health._MAX_BIND_PARAMS < 32_767

    @pytest.mark.parametrize("n_cols,expected_max", [(2, 15_000), (3, 10_000)])
    def test_chunks_stay_under_the_asyncpg_ceiling(self, n_cols, expected_max):
        chunk = google_health._MAX_BIND_PARAMS // n_cols
        assert chunk * n_cols <= 32_767
        assert chunk >= expected_max

    def test_empty_input_is_a_no_op(self):
        src = inspect.getsource(google_health._chunked_upsert)
        assert "if not rows:" in src


class TestSleepConsistencyIsNotDead:
    """The metric returned 0.0 on 86 of the last 89 days in production.

    Sessions are clustered by splitting on any gap over 2h, so an
    afternoon nap became its own "night" with a mid-afternoon bed and wake
    time. Fed into a circular standard deviation those push sigma far past
    the 120-minute floor, and the score clamps to zero.

    A number that is almost always zero reads as "you are terrible at
    this" rather than as a broken metric, which is worse than showing
    nothing at all.
    """

    def test_short_sessions_are_excluded(self):
        src = inspect.getsource(advanced.sleep_consistency_score)
        assert "MIN_NIGHT_H" in src

    def test_one_night_per_local_date(self):
        src = inspect.getsource(advanced.sleep_consistency_score)
        assert "by_date" in src
        assert "end.astimezone(_tz).date()" in src, (
            "the night must be keyed on the date it ENDS in local time — a "
            "night beginning 23:40 belongs to the morning it ends on"
        )

    def test_the_longest_session_wins_a_date(self):
        """If two qualify on one date, the longer is the night."""
        src = inspect.getsource(advanced.sleep_consistency_score)
        assert "(end - start) > (prev[1] - prev[0])" in src

    def test_still_refuses_below_five_nights(self):
        """A stddev over four points is not a consistency score."""
        src = inspect.getsource(advanced.sleep_consistency_score)
        assert "len(sessions) < 5" in src

    def test_the_window_is_resolved_locally(self):
        src = inspect.getsource(advanced.sleep_consistency_score)
        assert "_local_tz()" in src
        assert "datetime.now(timezone.utc).date()" not in src
