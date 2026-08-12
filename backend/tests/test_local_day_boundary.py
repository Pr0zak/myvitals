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

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "myvitals"
API = SRC / "api"
ANALYTICS = SRC / "analytics"

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


# ── Second shape of the same bug ────────────────────────────────────────
#
# The first guard catches `datetime.now(timezone.utc).date()` in the API layer.
# It did not catch the ANALYTICS layer combining a calendar date with UTC to
# build a day window:
#
#     day_start = datetime.combine(target, time.min, tzinfo=timezone.utc)
#
# For a Central user that window runs 7pm-7pm, so an evening workout is
# attributed to the following day — which put a Tuesday session on Wednesday's
# bar in the weekly-load card, and at a week boundary in the following week.
#
# Windows anchored to a CLOCK HOUR rather than midnight (a "night" of
# 22:00→09:00) are a different question and deliberately not flagged here;
# they are listed in KNOWN_CLOCK_WINDOWS so this test states what it does not
# cover instead of implying the whole layer is clean.

KNOWN_CLOCK_WINDOWS = {
    # module: why it is exempt
    "sleep.py": "18:00→14:00 night window, not a midnight-to-midnight day",
    "baselines.py": "22:00→09:00 night window for nightly RHR",
}


def _utc_day_windows(tree: ast.AST) -> list[int]:
    """`datetime.combine(<date>, time.min|max, tzinfo=timezone.utc)` lines."""
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "combine"):
            continue
        # Second arg is a midnight/end-of-day sentinel?
        if len(node.args) < 2:
            continue
        a1 = node.args[1]
        is_midnight = (
            isinstance(a1, ast.Attribute) and a1.attr in {"min", "max"}
            and isinstance(a1.value, ast.Name) and a1.value.id == "time"
        )
        if not is_midnight:
            continue
        for kw in node.keywords:
            if kw.arg != "tzinfo":
                continue
            v = kw.value
            if isinstance(v, ast.Attribute) and v.attr == "utc":
                hits.append(node.lineno)
    return hits


def test_analytics_day_windows_are_local():
    offenders = []
    for path in sorted(ANALYTICS.glob("*.py")):
        if path.name in KNOWN_CLOCK_WINDOWS:
            continue
        tree = ast.parse(path.read_text())
        offenders += [f"{path.name}:{ln}" for ln in _utc_day_windows(tree)]
    assert not offenders, (
        "calendar day combined with UTC to build a day window: "
        + ", ".join(offenders)
        + " — for a Central user this runs 7pm-7pm, so an evening activity is "
        "attributed to the following day. Use the configured local tz."
    )
