"""A user-facing "today" must be the user's local day, never the UTC one.

This bug has now landed three times. `/summary/today` had it first: with TZ=UTC
on Central time the UTC day rolls at 7pm CDT, so five hours of the previous
evening leaked into today's step count. `/summary/readiness` reintroduced
it in v0.7.369 — it asked for tomorrow's `daily_summary`, got nothing, and
rendered "not enough data" every night from 7pm to midnight. TD-3 then found
`today_snapshot` still carrying a bare `date.today()`, which the original
guard did not match because it only looked for the
`datetime.now(timezone.utc).date()` shape -- `date.today()` reads the
container clock, and the container runs TZ=UTC, so it is the same bug wearing
a different hat.

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
    """Line numbers of every expression that derives a DATE from UTC.

    Two shapes, both of which have shipped:

    ``datetime.now(timezone.utc).date()``
        Matched as a whole chain, so ``datetime.now(timezone.utc)`` on its
        own — a legitimate way to get an instant — is left alone. Only
        converting that instant straight to a date is the bug.

    ``date.today()`` / ``datetime.today()``
        Reads the process timezone. That is harmless on a developer laptop
        set to the user's own zone and wrong in production, where the
        container runs TZ=UTC. This is the shape that slipped past the first
        version of this guard.
    """
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        # `date.today()` / `datetime.today()` / `datetime.date.today()`.
        # Deliberately anchored on the receiver rather than the method name:
        # this module has an endpoint handler called `today()`, and matching
        # a bare `today(...)` call flagged every call to it.
        if isinstance(fn, ast.Attribute) and fn.attr == "today":
            recv = fn.value
            recv_name = (
                recv.id if isinstance(recv, ast.Name)
                else recv.attr if isinstance(recv, ast.Attribute)
                else None
            )
            if recv_name in {"date", "datetime"}:
                hits.append(node.lineno)
            continue
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
        "These derive a calendar day from UTC or from the process timezone. "
        "On a negative UTC offset the day rolls over in the evening and the "
        "endpoint starts answering for tomorrow. Call "
        "`summary.resolve_day()` instead — it resolves the day in "
        "`settings.tz` and also tells you whether it is actually today, "
        "which matters for the endpoints that repair a stale row.\n  "
        + "\n  ".join(offenders)
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

    # The shape that slipped through the first version of this guard, and
    # sat in today_snapshot until TD-3.
    process_tz = ast.parse(
        "from datetime import date\n"
        "d = date.today()\n"
    )
    assert _utc_today_calls(process_tz) == [2]


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


# --------------------------------------------------------------------------
# resolve_day — TD-3
# --------------------------------------------------------------------------

def test_resolve_day_defaults_to_the_local_today():
    from myvitals.api.summary import resolve_day

    day, tz, is_today = resolve_day()
    from datetime import datetime as _dt
    assert day == _dt.now(tz).date()
    assert is_today is True


def test_resolve_day_reports_a_past_date_as_not_today():
    """`is_today` is what keeps the day-scoped endpoints honest.

    /summary/tiles and /summary/readiness repair a stale daily_summary row
    and splice in a live step count before answering. Both are correct only
    for the current day: doing either while looking at last Tuesday would
    rebuild a finished historical row out of samples taken today.
    """
    from datetime import date as _date, timedelta as _td

    from myvitals.api.summary import resolve_day

    past = _date.today() - _td(days=30)
    day, _tz, is_today = resolve_day(past)
    assert day == past
    assert is_today is False


def test_day_scoped_endpoints_accept_a_date_parameter():
    """The analytics were always day-parameterised; only the routes were not.

    analytics/tiles.py:tile_stats and analytics/events.py:day_events have
    both taken an explicit day since they were written, while the endpoints
    on top of them hardcoded today — so the phone had day navigation on four
    screens and the web had none, with nothing able to serve it.
    """
    from fastapi.routing import APIRoute

    from myvitals.api import summary

    wanted = {"/tiles", "/events", "/readiness"}
    seen = {}
    for route in summary.router.routes:
        if isinstance(route, APIRoute) and route.path in wanted:
            seen[route.path] = {
                p.field_info.alias or p.name for p in route.dependant.query_params
            }
    assert set(seen) == wanted, f"missing routes: {wanted - set(seen)}"
    for path, params in seen.items():
        assert "date" in params, f"{path} still hardcodes today"
