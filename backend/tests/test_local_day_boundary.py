"""A user-facing "today" must be the user's local day, never the UTC one.

This bug has now landed twice. `/summary/today` had it first: with TZ=UTC
on Central time the UTC day rolls at 7pm CDT, so five hours of the previous
evening leaked into today's step count. `/summary/readiness` reintroduced
it in v0.7.369 — it asked for tomorrow's `daily_summary`, got nothing, and
rendered "not enough data" every night from 7pm to midnight.

The failure is invisible in unit tests and invisible to anyone developing
in UTC, which is exactly why it keeps coming back. This test reads the
source and fails on the specific expression that causes it.
"""
import ast
import pathlib

API = pathlib.Path(__file__).resolve().parents[1] / "src" / "myvitals" / "api"

# Modules whose endpoints resolve a calendar day the user actually sees.
DAY_FACING_MODULES = ["summary.py"]


def _utc_today_calls(tree: ast.AST) -> list[int]:
    """Line numbers of `datetime.now(timezone.utc).date()`-shaped calls.

    Matches the whole chain, so `datetime.now(timezone.utc)` on its own —
    a legitimate way to get an instant — is left alone. Only converting
    that instant straight to a DATE is the bug.
    """
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "date"):
            continue
        inner = fn.value
        if not (isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == "now"):
            continue
        # ...now(timezone.utc).date()
        for arg in inner.args:
            if isinstance(arg, ast.Attribute) and arg.attr == "utc":
                hits.append(node.lineno)
            elif isinstance(arg, ast.Name) and arg.id == "utc":
                hits.append(node.lineno)
    return hits


def test_day_facing_endpoints_do_not_derive_today_from_utc():
    offenders = []
    for name in DAY_FACING_MODULES:
        path = API / name
        tree = ast.parse(path.read_text())
        offenders += [f"{name}:{ln}" for ln in _utc_today_calls(tree)]
    assert not offenders, (
        "These derive a calendar day from UTC. On a negative UTC offset the "
        "day rolls over in the evening and the endpoint starts answering for "
        "tomorrow. Resolve the day in `settings.tz` instead — see the "
        "`local_tz` block in summary.py:today.\n  " + "\n  ".join(offenders)
    )


def test_the_guard_actually_catches_the_pattern():
    """A guard that can't fail is worse than no guard."""
    bad = ast.parse(
        "import datetime\n"
        "from datetime import timezone\n"
        "d = datetime.datetime.now(timezone.utc).date()\n"
    )
    assert _utc_today_calls(bad) == [3]

    good = ast.parse(
        "from zoneinfo import ZoneInfo\n"
        "d = datetime.now(ZoneInfo('America/Chicago')).date()\n"
        "instant = datetime.now(timezone.utc)\n"   # fine — not a date
    )
    assert _utc_today_calls(good) == []
