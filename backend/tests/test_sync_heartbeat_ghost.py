"""SA-O2 — a second install poisons the only sync-health signal the web reads.

`sync_heartbeat` has no device identity (unlike its sibling `device_status`,
which has carried `device_id` since day one), and both `/query/last-sync`
and `/query/data-health` used to select the single newest row with no
filter at all. A locally-built debug APK — `versionName` falls back to
"0.1.0" in android/app/build.gradle.kts whenever `BUILD_VERSION_NAME` is
unset, which only happens outside CI — posted 222 heartbeats against
production between 2026-08-25 and 2026-09-03, interleaved with the real
phone's, and intermittently defined "the phone" for the web dashboard.
Confirmed against production (`sync_heartbeat` grouped by `app_version`):
every one of those 222 rows carries `permissions_lost=true,
perms_granted=0, perms_required=13` and the exact string "0.1.0"; every
other row across 230 distinct `app_version` values, from 0.5.1 through the
current 0.39.1, is a real CI-tagged release. That makes the two installs
distinguishable in the EXISTING data with no schema change: `app_version`
already is the discriminator (this is also what the correction on SA-O2
concludes — the over-reaching part of the original proposal was a new
`device_id` column, which would also require widening ingest.py's
`on_conflict_do_nothing` target, a change outside this lane).

The fix is `models.real_install_heartbeat_filter()`, applied at both
`/query/last-sync` and `/query/data-health`'s "most recent heartbeat"
queries: exclude rows whose `app_version` is exactly the local-build
sentinel, and nothing else — a real release can never carry that string,
so the filter can never suppress a genuine permissions-lost report. NULL
`app_version` (pre-field-existing rows, or a future client that omits it)
is deliberately let through rather than treated as suspect.
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import re
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from myvitals.api import query as q
from myvitals.db import models

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "myvitals"


def _heartbeat(when: datetime, version: str | None, *, granted=13, required=13,
               lost=False) -> models.SyncHeartbeat:
    return models.SyncHeartbeat(
        attempt_at=when,
        success=not lost,
        permissions_lost=lost,
        perms_granted=granted,
        perms_required=required,
        app_version=version,
    )


def _sqlite_session() -> Session:
    """A bare sqlite engine holding only `sync_heartbeat`.

    Just this one table (not the whole `Base.metadata`) so a
    Postgres-only column type elsewhere in the schema can't get in the
    way of what is otherwise a pure ORM-filter test.
    """
    engine = create_engine("sqlite:///:memory:")
    models.SyncHeartbeat.__table__.create(engine)
    return Session(engine)


def test_the_sentinel_matches_the_android_fallback_it_is_named_for():
    """This constant is only correct while it tracks the literal in
    build.gradle.kts. If that fallback ever changes, this test — not a
    production banner nine days later — is what should notice."""
    gradle = (REPO_ROOT / "android" / "app" / "build.gradle.kts").read_text()
    m = re.search(
        r'versionName\s*=\s*System\.getenv\("BUILD_VERSION_NAME"\)\s*\?:\s*"([^"]+)"',
        gradle,
    )
    assert m, "could not find the versionName fallback in build.gradle.kts"
    assert m.group(1) == models.LOCAL_BUILD_APP_VERSION


def test_filter_excludes_only_the_exact_sentinel():
    """A ghost row, a real release, and a null-version row (predates the
    column) all coexist. Only the ghost is dropped."""
    with _sqlite_session() as session:
        session.add_all([
            _heartbeat(datetime(2026, 8, 27, 14, 20, tzinfo=timezone.utc),
                       "0.1.0", granted=0, lost=True),
            _heartbeat(datetime(2026, 8, 27, 14, 19, tzinfo=timezone.utc),
                       "0.29.3", granted=13, lost=False),
            _heartbeat(datetime(2026, 8, 27, 14, 18, tzinfo=timezone.utc),
                       None, granted=13, lost=False),
        ])
        session.commit()

        kept = session.scalars(
            select(models.SyncHeartbeat).where(models.real_install_heartbeat_filter())
        ).all()
        versions = {row.app_version for row in kept}

    assert "0.1.0" not in versions, "the local-build ghost must be excluded"
    assert "0.29.3" in versions, "a real release must never be filtered out"
    assert None in versions, (
        "a null app_version is unknown, not proven to be the ghost — "
        "null is not zero applies here too"
    )


def test_the_ghost_no_longer_wins_newest_row_even_when_it_posts_last():
    """The reported failure mode exactly: reproduces the 2026-08-27 14:19
    -> 14:20 flip from the evidence, where the ghost's heartbeat is
    chronologically newer than the real phone's. Unfiltered, `ORDER BY
    attempt_at DESC LIMIT 1` picks the ghost and the real phone's 13/13
    status disappears from the response."""
    real = _heartbeat(datetime(2026, 8, 27, 14, 19, tzinfo=timezone.utc),
                       "0.29.3", granted=13, lost=False)
    ghost = _heartbeat(datetime(2026, 8, 27, 14, 20, tzinfo=timezone.utc),
                        "0.1.0", granted=0, required=13, lost=True)

    with _sqlite_session() as session:
        session.add_all([real, ghost])
        session.commit()

        newest = session.scalars(
            select(models.SyncHeartbeat)
            .where(models.real_install_heartbeat_filter())
            .order_by(models.SyncHeartbeat.attempt_at.desc())
            .limit(1)
        ).first()

    assert newest is not None
    assert newest.app_version == "0.29.3"
    assert newest.permissions_lost is False


def test_both_endpoints_apply_the_filter():
    """Regression guard for the two call sites in api/query.py. Written
    as a source check (matching this file's sibling tests) rather than
    hitting a live endpoint, since this suite has no DB-backed request
    fixture — the filter's actual behaviour is covered directly above."""
    for fn in (q.data_health, q.get_last_sync):
        src = inspect.getsource(fn)
        assert "real_install_heartbeat_filter()" in src, (
            f"{fn.__name__} no longer filters its SyncHeartbeat query — "
            "the local-build ghost can win 'most recent heartbeat' again"
        )


def test_the_filter_logic_is_not_duplicated():
    """`real_install_heartbeat_filter` must be the only place the
    sentinel comparison is written — a second hand-rolled copy in
    api/query.py would be free to drift, the same trap the watch-source
    keyword list already hit once in analytics/jobs.py."""
    src = (BACKEND_SRC / "api" / "query.py").read_text()
    assert "LOCAL_BUILD_APP_VERSION" not in src, (
        "api/query.py should call models.real_install_heartbeat_filter() "
        "rather than compare against the sentinel itself"
    )
    assert src.count("SyncHeartbeat.app_version !=") == 0


def test_null_is_not_treated_as_zero_in_the_docstring_and_the_code():
    """AST-level check that the OR-null-safety is real code, not just
    the accompanying comment — a `_code_only`-style false pass is exactly
    the failure mode this project has hit with prose-matching asserts."""
    src = inspect.getsource(models.real_install_heartbeat_filter)
    tree = ast.parse(src)
    fn = tree.body[0]
    assert isinstance(fn, ast.FunctionDef)
    body_src = ast.unparse(fn)
    assert "is_(None)" in body_src
    assert "!=" in body_src
