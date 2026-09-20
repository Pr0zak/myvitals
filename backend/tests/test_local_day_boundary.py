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
# CONS-1 added strava.py (activity streaks are calendar-day questions) and
# workout/strength.py (the week-ahead schedule, the stats window, and the
# training-load week boundary all resolve days). Adding a module here turns
# the suite red until every offending expression in it is fixed, which is
# the point — the guard is only worth anything if it is allowed to fail.
# SA-N7 added analytics.py: backfill_analytics and correlate both resolve
# window boundaries as calendar dates the user sees.
DAY_FACING_MODULES = ["analytics.py", "summary.py", "strava.py", "workout/strength.py", "meals.py"]

# OG2-C1 widened the FIRST guard to the analytics layer, because the bug
# reached production through the gap between the two guards in this file.
#
# `analytics/strength.py` anchored four windowed history readers on
# `datetime.now(timezone.utc).date()` — the exact shape guard one matches —
# but guard one walked only the API layer. Guard two DOES walk analytics, and
# looks for a different shape entirely (`datetime.combine(..., tzinfo=utc)`).
# Right shape with the wrong scope, and the right scope with the wrong shape,
# so the expression fell between them.
#
# The cost was not cosmetic: `weekly_muscle_volume(days=7)` returned zero
# credited sets for all fourteen muscles on a user who had trained seven days
# earlier, `muscle_need()` saturated identically for every muscle, and
# ADAPT-1's adaptive split selection degenerated to a tie.
#
# A module goes here only once it is clean. `consistency.py` is exempt by
# name: its occurrence is inside a docstring explaining this very bug.
#
# SA-L1 added `jobs.py`. `compute_daily_summary()` defaulted its target to
# `datetime.now(timezone.utc).date()`, and the one caller that takes the
# default is the startup job in `main.py` — so a backend restarted after 7pm
# Central wrote a daily_summary row for TOMORROW. The row is empty because
# the day has not happened, and an empty row is not the same as no row: the
# readers in front of it show the day as real and stepless.
DAY_FACING_ANALYTICS = ["strength.py", "jobs.py"]


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
# 22:00→09:00) used to be a different question and deliberately unflagged —
# they were only listed in KNOWN_CLOCK_WINDOWS so this test stated what it
# did not cover instead of implying the whole layer was clean.
#
# SA-N1: that carve-out is exactly how `baselines.py:_night_window` hard-coded
# its 22:00→09:00 "night" to `tzinfo=timezone.utc` and shipped invisibly — on
# this deployment (settings.tz=America/Chicago) that ran 17:00→04:00 local,
# folding in ~5h40m of evening wakefulness and cutting the last ~2h20m of real
# sleep, and neither this guard nor `KNOWN_CLOCK_WINDOWS` said a word about
# it, because `is_midnight` only matched the `.min`/`.max` attribute shape — a
# `time(hour=22)` call is neither. `_utc_day_windows` now also matches a
# `time(hour=N, ...)` CALL as the clock argument, so a UTC-anchored clock-hour
# window is caught the same way a UTC-anchored midnight window already was.
# `baselines.py` no longer needs an entry below because its window now
# resolves in `settings.tz` rather than a literal `timezone.utc` (see
# `analytics/baselines.py:_night_window`). `sleep.py`'s 18:00→14:00 window is
# a deliberately different (wider) fallback that SA-N1's correction explicitly
# said not to unify with baselines.py without evidence they should match —
# fixing ITS UTC anchoring is a separate, not-yet-made decision, so it keeps
# its exemption rather than turning this guard red for an out-of-scope module.

KNOWN_CLOCK_WINDOWS = {
    # module: why it is exempt
    "sleep.py": "18:00→14:00 UTC night window — a different, wider fallback "
                "than baselines.py's; SA-N1 fixed baselines.py's clock-hour "
                "window but deliberately left this one alone (see SA-N1's "
                "correction in docs/sa-findings.json).",
}


def _utc_day_windows(tree: ast.AST) -> list[int]:
    """`datetime.combine(<date>, <clock>, tzinfo=timezone.utc)` lines.

    ``<clock>`` covers two shapes:

    - ``time.min`` / ``time.max`` — a bare midnight-to-midnight calendar day.
    - ``time(hour=N, ...)`` — a fixed clock-hour window, e.g. the
      ``time(hour=22)`` this function could not see before SA-N1. Both are
      "a calendar day combined with UTC" in exactly the same sense: on a
      negative UTC offset the window runs some fixed number of hours earlier
      than the caller intended.
    """
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "combine"):
            continue
        # Second arg is a midnight/end-of-day sentinel, or a clock-hour call?
        if len(node.args) < 2:
            continue
        a1 = node.args[1]
        is_midnight = (
            isinstance(a1, ast.Attribute) and a1.attr in {"min", "max"}
            and isinstance(a1.value, ast.Name) and a1.value.id == "time"
        )
        is_clock_hour = (
            isinstance(a1, ast.Call)
            and (
                (isinstance(a1.func, ast.Name) and a1.func.id == "time")
                or (isinstance(a1.func, ast.Attribute) and a1.func.attr == "time")
            )
        )
        if not (is_midnight or is_clock_hour):
            continue
        for kw in node.keywords:
            if kw.arg != "tzinfo":
                continue
            v = kw.value
            if isinstance(v, ast.Attribute) and v.attr == "utc":
                hits.append(node.lineno)
    return hits


def test_the_guard_now_catches_a_clock_hour_window():
    """SA-N1: `is_midnight` alone let `_night_window`'s `time(hour=22)` /
    `time(hour=9)` UTC window ship invisibly. Pin the widened shape so the
    next fixed-clock-hour UTC window doesn't slip through the same gap.
    """
    bad = ast.parse(
        "from datetime import datetime, time, timezone\n"
        "d = datetime.combine(day, time(hour=22), tzinfo=timezone.utc)\n"
    )
    assert _utc_day_windows(bad) == [2]

    # A clock-hour window resolved against a local tz variable — exactly
    # what the SA-N1 fix produces — must stay clean; only a literal
    # `timezone.utc` is the bug.
    good = ast.parse(
        "from datetime import datetime, time\n"
        "d = datetime.combine(day, time(hour=22), tzinfo=local_tz)\n"
    )
    assert _utc_day_windows(good) == []


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


def test_day_facing_analytics_modules_use_the_local_day():
    """The same shape guard one forbids in the API layer, in analytics.

    Windowed history readers decide what the generator sees. A window that
    starts a day late for five hours every evening does not merely mislabel a
    chart — at the boundary it drops the most recent session out of the
    window, and a reader that returns "nothing" is indistinguishable from a
    user who has not trained.
    """
    offenders = []
    for name in DAY_FACING_ANALYTICS:
        path = ANALYTICS / name
        assert path.exists(), f"{name} is listed but does not exist"
        tree = ast.parse(path.read_text())
        offenders += [f"analytics/{name}:{ln}" for ln in _utc_today_calls(tree)]
    assert not offenders, (
        "UTC-derived calendar date in a day-facing analytics module: "
        + ", ".join(offenders)
        + " — the CT runs TZ=UTC while the user is Central, so this window "
        "starts a day late from 7pm local. Use the module's `_local_today()`."
    )
