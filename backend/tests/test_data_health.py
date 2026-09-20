"""HEALTH-1 — the data-health card, and what it deliberately will not say.

The module's whole difficulty is that most of these streams are SUPPOSED
to be stale. Weight was last written 103 days ago and blood pressure 75;
neither is a fault, and a card that paints them red is wrong three times
over and trains the user to ignore it within a week — after which the one
time heart rate really does stop, the red means nothing.

So the tests here are mostly about restraint: which facts get reported,
and which conclusions the app refuses to draw from them.
"""
from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timedelta, timezone

from myvitals.analytics import data_health as DH

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "myvitals"


def _code_only(src: str) -> str:
    """Source with comments and docstrings removed.

    Assertions that match a module's own prose have produced several
    false failures in this project — this one matched the very sentence
    explaining why the forbidden thing is absent.
    """
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)



def test_only_continuous_streams_can_ever_be_stale():
    """An ad-hoc stream reports its age and is never red. This is the
    load-bearing rule of the module."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    long_ago = now - timedelta(days=103)
    for spec in DH.STREAMS:
        status, age = DH._classify(spec, long_ago, now)
        if spec.kind in ("continuous", "nightly"):
            assert status == "stale", f"{spec.key} should go stale"
        else:
            assert status != "stale", f"{spec.key} must never read as stale"
        assert age is not None


def test_a_never_written_optional_stream_is_off_not_broken():
    """Home Assistant may simply not be configured. "Never" and "not set
    up" call for different responses."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    optional = next(s for s in DH.STREAMS if s.kind == "optional")
    continuous = next(s for s in DH.STREAMS if s.kind == "continuous")
    assert DH._classify(optional, None, now)[0] == "not_configured"
    assert DH._classify(continuous, None, now)[0] == "never"


def test_stream_tables_and_columns_are_real():
    """Interpolated straight into SQL from the STREAMS constant, so a
    typo here is a 500 at request time, not an import error."""
    from myvitals.db import models

    tables = {m.__tablename__: m for m in models.Base.__subclasses__()}
    for spec in DH.STREAMS:
        model = tables.get(spec.table)
        assert model is not None, f"{spec.key}: no model for {spec.table!r}"
        cols = {c.key for c in model.__table__.columns}
        assert spec.time_col in cols, f"{spec.key}: {spec.table}.{spec.time_col} missing"


def test_no_count_star_without_a_time_predicate():
    """`vitals_heartrate` holds ~23.6M rows and the nav polls this on
    page load. An unbounded count is the one query that would make this
    card an outage."""
    code = _code_only((SRC / "analytics" / "data_health.py").read_text())
    assert "count(*)" not in code.lower()

# ------------------------------------- imported-vs-polled (v0.26.10)


def test_item_probes_are_reported_but_never_become_a_status():
    """The gap this closed: `last_sync_at` alone cannot distinguish a
    poll that succeeded and brought back nothing from a poll that
    succeeded when there was nothing to bring.

    That first case is exactly how Strava fails here — the cookie
    expires, the request 401s, the sync completes, and zero rides
    arrive. It went unnoticed until a reconnect banner was added, and on
    this database Concept2 currently reports `ok` with no error while its
    newest imported session is three months old.

    But a three-month gap in erg sessions is also a perfectly ordinary
    thing for a person to do, so inferring breakage from it would
    manufacture the false alarm this module is otherwise careful to
    avoid. The numbers are shown; the conclusion is the user's.
    """
    src = (SRC / "analytics" / "data_health.py").read_text()
    tree = ast.parse(src)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "integration_health"
    )
    body = ast.unparse(fn)
    # It is reported...
    assert "importing_nothing" in body
    assert "last_item_at" in body

    # ...and it never feeds `status`. Checked structurally rather than by
    # matching text: `ast.unparse` collapses the whole return dict onto
    # one line, so any line-based heuristic sees `status` and
    # `item_age_h` together and fires on correct code.
    for node in ast.walk(fn):
        if not isinstance(node, (ast.Assign, ast.AugAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(
            isinstance(t, ast.Name) and t.id == "status" for t in targets
        ):
            continue
        names = {
            n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)
        }
        assert "item_age_h" not in names, (
            "item age must not determine the status: " + ast.unparse(node)
        )


def test_every_item_probe_names_a_real_table_and_column():
    """Interpolated straight into SQL from the constant, so a typo is a
    500 at request time rather than an import error."""
    from myvitals.db import models

    tables = {m.__tablename__: m for m in models.Base.__subclasses__()}
    for key, (table, col, _pred) in DH._ITEM_PROBES.items():
        model = tables.get(table)
        assert model is not None, f"{key}: no model for table {table!r}"
        cols = {c.key for c in model.__table__.columns}
        assert col in cols, f"{key}: {table}.{col} missing (has {sorted(cols)[:8]})"


def test_a_never_used_integration_reports_null_not_a_zero_age():
    """"Imported nothing ever" and "imported nothing lately" are
    different facts, and collapsing them is the flattening this codebase
    treats as a bug elsewhere."""
    code = _code_only((SRC / "analytics" / "data_health.py").read_text())
    assert "last_item_at" in code and "item.isoformat() if item else None" in code
    assert "item_age_hours" in code
    assert "if item_age_h is not None else None" in code


def test_the_probes_run_as_one_statement():
    """The nav polls this on page load and the streams query already
    went to some trouble to be a single round trip. Three more serial
    round trips would undo that."""
    code = _code_only((SRC / "analytics" / "data_health.py").read_text())
    fn = code[code.index("async def _last_items"):code.index("async def integration_health")]
    assert fn.count("db.execute") == 1


def test_the_heart_rate_threshold_clears_the_measured_worst_gap():
    """6 hours was the original value and it fires on healthy data.

    Measured over 30 days on the production database, the longest real
    gap between heart-rate samples is 16.4 hours: the watch comes off to
    charge and is not worn every night. A threshold inside that window
    turns the card red most weeks, and a card that has been wrong three
    times is one nobody reads — which costs exactly the alert this whole
    module exists to deliver.
    """
    hr = next(s for s in DH.STREAMS if s.key == "heart_rate")
    assert hr.stale_after_h >= 20.0, (
        "must clear the 16.4 h observed maximum with margin"
    )


def test_steps_are_judged_on_the_canonical_writer_not_the_table():
    """Seven sources write steps and `source` is part of the primary key,
    so they coexist. A whole-table MAX stays green while ANY of them is
    active — including a phone pedometer keeping the badge fresh after
    the watch feed has died, which is the one case worth catching.
    """
    assert "steps" in DH._MULTI_SOURCE_STREAMS
    code = _code_only((SRC / "analytics" / "data_health.py").read_text())
    assert "_canonical_steps_last" in code


# ------------------------------------- SA-C11: bounded canonical-steps MAX


class _Row:
    def __init__(self, source: str, newest: datetime | None):
        self.source = source
        self.newest = newest


class _Result:
    def __init__(self, rows: list[_Row]):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDb:
    """Hands back queued `.execute(...)` results in order, one per SQL
    round trip. `_canonical_steps_last` issues at most two — a bounded
    query, then (only when needed) the unbounded fallback — so ordering
    is enough to stand in for the real statements."""

    def __init__(self, *results: _Result):
        self._queue = list(results)
        self.calls = 0

    async def execute(self, _stmt):
        self.calls += 1
        assert self._queue, "more queries were issued than the test queued"
        return self._queue.pop(0)


WATCH = "com.fitbit.FitbitMobile"
PHONE = "android"

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
RECENT = NOW - timedelta(hours=2)
STALE = NOW - timedelta(days=10)  # older than _STEPS_RECENT_WINDOW (3 days)


async def test_recent_watch_row_short_circuits_on_the_bounded_query():
    """The ordinary case: the watch wrote today. One round trip, and the
    unbounded fallback is never touched."""
    db = _FakeDb(_Result([_Row(WATCH, RECENT)]))
    result = await DH._canonical_steps_last(db)
    assert result == RECENT
    assert db.calls == 1


async def test_a_watch_gone_stale_beyond_the_window_still_reports_its_own_time():
    """The bound must not change the answer. The watch stopped 10 days
    ago; the phone pedometer is still writing today. The bounded query
    (first result) only sees the phone, because the watch's own rows are
    outside the window -- if the function stopped there it would report
    the phone's fresh timestamp and silently hide a dead watch, which is
    the exact false-green HEALTH-1 exists to catch. It must fall through
    to the unbounded query (second result) and report the watch's true,
    stale time instead."""
    bounded = _Result([_Row(PHONE, RECENT)])
    unbounded = _Result([_Row(PHONE, RECENT), _Row(WATCH, STALE)])
    db = _FakeDb(bounded, unbounded)
    result = await DH._canonical_steps_last(db)
    assert result == STALE
    assert db.calls == 2


async def test_an_empty_window_still_falls_through_to_find_a_stale_watch():
    """No source wrote in the last 3 days at all (a longer sync gap than
    usual). The window being empty must not be read as "nothing was ever
    written" when the unbounded query can still find the watch's last
    real value."""
    db = _FakeDb(_Result([]), _Result([_Row(WATCH, STALE)]))
    result = await DH._canonical_steps_last(db)
    assert result == STALE
    assert db.calls == 2


async def test_nothing_ever_written_is_still_none_not_a_crash():
    db = _FakeDb(_Result([]), _Result([]))
    assert await DH._canonical_steps_last(db) is None
    assert db.calls == 2


async def test_no_watch_source_ever_falls_back_to_the_freshest_other_source():
    """Matches the pre-SA-C11 behaviour exactly: with no watch at all,
    the freshest of whatever is there wins, regardless of which query
    found it."""
    db = _FakeDb(_Result([_Row(PHONE, RECENT)]), _Result([_Row(PHONE, RECENT)]))
    result = await DH._canonical_steps_last(db)
    assert result == RECENT


def test_the_bound_is_a_module_constant_not_user_input():
    """Interpolated into raw SQL text, so it must be a fixed literal this
    module owns -- never anything that could originate from a request."""
    assert isinstance(DH._STEPS_RECENT_WINDOW, str)
    code = _code_only((SRC / "analytics" / "data_health.py").read_text())
    assert "_STEPS_RECENT_WINDOW" in code
    # Two grouped-MAX statements now: the bounded fast path and the
    # unbounded fallback, sharing one query builder.
    assert code.count("GROUP BY source") == 1  # built once, called twice


def test_the_watch_source_keyword_list_is_not_duplicated():
    """It has already been extended twice — for the Fitbit rename and the
    Google Health rebrand. A second copy in this module would drift, and
    the drift would be silent."""
    src = (SRC / "analytics" / "data_health.py").read_text()
    assert "_is_watch_source" in src, "must reuse the shared helper"

    # Check STRING LITERALS, not raw text. `models.GoogleHealthCredentials`
    # contains "googlehealth" as a substring of a class name, which a
    # naive search reads as a re-listed keyword — a false positive on
    # correct code, which is the failure mode these source-matching tests
    # keep producing in this repo.
    literals = {
        n.value.lower() for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    for keyword in ("fitbit", "wearable", "googlehealth", "fit.wearable"):
        assert keyword not in literals, (
            f"{keyword!r} is a re-listed source keyword; import "
            "_is_watch_source instead"
        )
