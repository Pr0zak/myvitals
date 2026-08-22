"""Google Health backfill as a tracked job over a real date range.

The shipped "Backfill 90 days" button could not succeed until v0.12.5 —
a single pg_insert hit asyncpg's 32,767 bind-parameter ceiling — and even
once it could, it ran INLINE. A long range was one HTTP request that
could outlive its own timeout, with no way to tell a slow run from a dead
one.
"""

from __future__ import annotations

import inspect
from datetime import date

import pytest

from myvitals.api import google_health as gh_api


class TestRangeNotDays:
    def test_the_request_takes_explicit_dates(self):
        """"90 days" cannot express "the fortnight the phone was off",
        which is the shape a real gap has."""
        fields = gh_api.BackfillIn.model_fields
        assert set(fields) == {"since", "until"}
        assert fields["since"].annotation is date

    def test_an_inverted_range_is_rejected(self):
        src = inspect.getsource(gh_api.backfill)
        assert "until must be after since" in src

    def test_the_range_is_capped(self):
        """Beyond a year this stops being something to watch and becomes
        something to schedule, which is a different feature."""
        src = inspect.getsource(gh_api.backfill)
        assert "366" in src


class TestTracked:
    def test_it_returns_a_job_id_immediately(self):
        src = inspect.getsource(gh_api.backfill)
        assert "background.add_task" in src
        assert '"job_id": job_id' in src

    def test_it_reuses_the_existing_job_table(self):
        """A second progress mechanism beside import_jobs would be a
        second thing to keep correct, and the UI already polls that one."""
        src = inspect.getsource(gh_api.backfill)
        assert "_create_job" in src
        assert '"/imports/jobs/' in src

    def test_the_worker_uses_its_own_session(self):
        """A background task outlives the request, so the injected session
        is closed by the time it starts."""
        src = inspect.getsource(gh_api._run_backfill)
        assert "async with SessionLocal() as db" in src

    def test_progress_is_reported_between_windows(self):
        """Otherwise a long run is indistinguishable from a hung one."""
        src = inspect.getsource(gh_api._run_backfill)
        assert "_update_job_counts" in src
        assert "_windows_done" in src


class TestWindowing:
    def test_the_range_is_walked_in_windows(self):
        """Requested whole, one rate-limited call loses the entire range —
        and there would be nothing to report progress between."""
        assert 0 < gh_api._BACKFILL_WINDOW_D <= 14
        src = inspect.getsource(gh_api._run_backfill)
        assert "_BACKFILL_WINDOW_D" in src

    def test_a_failed_window_does_not_abandon_the_rest(self):
        """One bad window should not cost the other twelve. Ingest upserts,
        so re-running later repairs the gap without duplicating."""
        src = inspect.getsource(gh_api._run_backfill)
        assert "failures.append" in src
        # the loop continues rather than raising out
        assert "continue" not in src.split("failures.append")[1].split("windows += 1")[0]

    def test_partial_is_a_distinct_outcome(self):
        """"done" on a run where four windows failed would be a lie."""
        src = inspect.getsource(gh_api._run_backfill)
        assert '"partial"' in src

    def test_connection_is_checked_before_a_job_is_created(self):
        """Creating a job that instantly fails leaves a confusing row."""
        src = inspect.getsource(gh_api.backfill)
        assert src.index("not connected") < src.index("_create_job")
