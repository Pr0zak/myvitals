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
