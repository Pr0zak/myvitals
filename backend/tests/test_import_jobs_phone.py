"""SETTINGS-C: the phone can read recent import jobs.

`/import/jobs` requires the query token, which the phone does not hold, so
the phone's Data & imports page had no way to show a job's status. The
`/query/import-jobs` twin reuses the import router's serialiser and sits on
the `require_any` query router.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from myvitals.api import query


class _Rows:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items


class _Db:
    def __init__(self, jobs):
        self.jobs = jobs
        self.stmt = None

    async def execute(self, stmt):
        self.stmt = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        return _Rows(self.jobs)


def _job(**kw):
    start = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
    base = dict(
        id=7, kind="google_takeout", filename="takeout.zip", size_bytes=1024,
        status="done", started_at=start, finished_at=start + timedelta(seconds=90),
        counts={"heartrate": 100, "steps": 20}, error=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_serialises_like_the_import_router():
    db = _Db([_job()])
    out = asyncio.run(query.recent_import_jobs(limit=5, db=db))
    assert out == [{
        "id": 7, "kind": "google_takeout", "filename": "takeout.zip",
        "size_bytes": 1024, "status": "done",
        "started_at": "2026-01-05T12:00:00+00:00",
        "finished_at": "2026-01-05T12:01:30+00:00",
        "elapsed_s": 90.0, "counts": {"heartrate": 100, "steps": 20},
        "total_rows": 120, "error": None,
    }]
    assert "ORDER BY" in db.stmt and "DESC" in db.stmt and "LIMIT 5" in db.stmt


def test_phone_token_is_accepted():
    """The route sits on the query router, whose dependency is require_any —
    the ingest token the phone holds is enough."""
    from myvitals.auth import require_any
    deps = [d.dependency for d in query.router.dependencies]
    assert require_any in deps
    assert "/import-jobs" in {r.path for r in query.router.routes}
