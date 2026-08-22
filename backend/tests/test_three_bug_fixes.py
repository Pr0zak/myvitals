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


class TestDataHealthModelNamesResolve:
    """The endpoint references three ORM models by attribute.

    A wrong name is an AttributeError at request time, not at import — the
    full suite passed green while `models.Concept2Creds` (the real class is
    `Concept2Credentials`) sat in the source, because nothing executed the
    endpoint. Same failure shape as the `Activity.id` bug in v0.12.1.
    """

    def test_every_referenced_model_exists(self):
        import re

        from myvitals.analytics import data_health
        from myvitals.db import models

        src = inspect.getsource(data_health)
        for name in sorted(set(re.findall(r"models\.(\w+)", src))):
            assert hasattr(models, name), f"models.{name} does not exist"

    def test_every_stream_table_and_column_exists(self):
        """A typo'd table name here is a runtime SQL error on a nav poll."""
        from myvitals.analytics import data_health
        from myvitals.db import models

        tables = models.Base.metadata.tables
        for spec in data_health.STREAMS:
            assert spec.table in tables, f"unknown table {spec.table}"
            cols = tables[spec.table].columns.keys()
            assert spec.time_col in cols, (
                f"{spec.table} has no column {spec.time_col}"
            )

    def test_ad_hoc_streams_can_never_report_stale(self):
        """The whole point: body metrics 103 days old is a fact about the
        user, not a fault. Painting it red trains you to ignore the card."""
        from datetime import datetime, timedelta, timezone

        from myvitals.analytics import data_health

        now = datetime.now(timezone.utc)
        for spec in data_health.STREAMS:
            if spec.kind != "ad_hoc":
                continue
            status, _age = data_health._classify(
                spec, now - timedelta(days=365), now,
            )
            assert status == "ad_hoc", f"{spec.key} went {status} at a year old"

    def test_an_unwritten_optional_stream_is_not_configured_not_broken(self):
        from datetime import datetime, timezone

        from myvitals.analytics import data_health

        spec = next(s for s in data_health.STREAMS if s.kind == "optional")
        status, _ = data_health._classify(spec, None, datetime.now(timezone.utc))
        assert status == "not_configured"

    def test_a_silent_continuous_stream_does_report_stale(self):
        """The one case that must still go red."""
        from datetime import datetime, timedelta, timezone

        from myvitals.analytics import data_health

        spec = next(s for s in data_health.STREAMS if s.kind == "continuous")
        now = datetime.now(timezone.utc)
        status, _ = data_health._classify(
            spec, now - timedelta(hours=spec.stale_after_h + 1), now,
        )
        assert status == "stale"


class TestIntegrationConfiguredChecks:
    """The `configured` flag must read the field that actually holds the
    credential, which is not always on the row you would expect.

    Google Health splits config (client id/secret) from credentials
    (refresh token) across two tables. Reading `refresh_token` off the
    config row reported a working, actively-polling integration as "not
    connected" — the single worst error this card can make, because it
    sends the user to re-authorise something that is fine.
    """

    def test_google_health_reads_the_credentials_table(self):
        from myvitals.analytics import data_health

        src = inspect.getsource(data_health.integration_health)
        assert "GoogleHealthCredentials" in src
        assert 'getattr(gh, "refresh_token"' not in src

    def test_it_matches_how_the_status_endpoint_decides(self):
        """Two places answering "is this connected?" must agree.

        /google-health/status uses `bool(creds and creds.refresh_token)`.
        If this card used a different test, Settings would contradict
        itself on the same screen.
        """
        from myvitals.analytics import data_health
        from myvitals.api import google_health as gh_api

        status_src = inspect.getsource(gh_api.status)
        health_src = inspect.getsource(data_health.integration_health)
        assert "creds.refresh_token" in status_src
        assert "gh_creds.refresh_token" in health_src


class TestStatusFieldsComeFromTheRightRow:
    """`configured`, `last_sync_at` and `last_error` must all be read from
    the row that actually carries them.

    For Google Health that is the CREDENTIALS row for all three; the
    config row holds only the client id and secret. Getting this half
    right produced `configured=True, status=never` on an integration that
    had synced minutes earlier — a subtler wrong answer than the original
    bug, and one the suite could not see because nothing executed it.
    """

    def test_google_health_status_reads_the_credentials_row(self):
        from myvitals.analytics import data_health

        src = inspect.getsource(data_health.integration_health)
        assert 'entry("google_health", "Google Health", gh_creds,' in src

    def test_the_row_passed_actually_has_the_status_fields(self):
        """Whatever row each integration passes must carry last_sync_at."""
        from myvitals.db import models

        for cls in (
            models.GoogleHealthCredentials,
            models.StravaCookieCreds,
            models.Concept2Credentials,
        ):
            assert hasattr(cls, "last_sync_at"), (
                f"{cls.__name__} has no last_sync_at, so its row cannot "
                "answer 'when did this last work?'"
            )
