"""Weekly training load: the band must be derived, and strength must count.

Things this guards:

1. Strength sessions contribute load. `daily_training_stress` only ever
   queried the `activities` table, so a week of lifting produced a training
   load of exactly zero and CTL/ATL decayed as though training had stopped —
   while TYPE_INTENSITY had carried a "strength" entry the whole time.
2. SA-L3: a day with a completed lift and NO Strava activity must still
   carry real load. `daily_training_stress` used to early-return `None`
   the instant its `activities` query came back empty — three lines above
   the point where the strength contribution was added — so exactly the
   days strength-session counting was meant to fix kept reading as zero.
   It now delegates to `training_load_by_day` (a single-day window),
   which has no such early return.
3. SA-L3: `update_training_load` must not seed the EWMA chain at a
   fabricated 0.0 just because yesterday's `daily_summary` row is missing
   or null — that reset the whole chain going forward, permanently, off
   one bad day. It should walk back to the most recent real (ctl, atl)
   and decay forward across the gap, or refuse (None, None, None) when
   there is truly no prior history at all.
4. The target band is the acute:chronic sweet spot expressed in load units,
   not a number someone picked.
"""
import ast
import inspect
import pathlib
from datetime import date, datetime, timedelta, timezone

from myvitals.analytics import advanced

SRC = pathlib.Path(advanced.__file__).read_text()


class _FakeResult:
    """Stands in for a SQLAlchemy `Result` — just `.all()` / `.first()`."""

    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _QueueSession:
    """Hands back canned results in call order, one per `db.execute()`.

    The real query construction (local-day windows, table joins) is
    exercised against Postgres in the deployed app — what these tests pin
    is the arithmetic and control flow once rows come back.
    """

    def __init__(self, results):
        self._results = list(results)

    async def execute(self, _stmt):
        return self._results.pop(0)


def test_strength_sessions_feed_daily_load():
    """daily_training_stress must consult the strength table, not just
    activities — via delegation to training_load_by_day, so the per-day
    and weekly-window figures can never diverge."""
    fn = inspect.getsource(advanced.daily_training_stress)
    assert "training_load_by_day" in fn
    helper = inspect.getsource(advanced.training_load_by_day)
    assert "StrengthWorkout" in helper
    # Only completed sessions, and net of paused time.
    assert '"completed"' in helper, "counts planned/skipped sessions as load"
    assert "total_paused_s" in helper, (
        "counts paused time as training, so a session left open reads as hours"
    )


async def test_lifting_only_day_is_not_zero_or_none():
    """A day with a completed strength session and no Strava ride must
    carry its real load — reproduces the production case from the audit
    (2026-09-14: strength_component 41.8, daily_training_stress None)."""
    day = date(2026, 9, 14)
    started = datetime(2026, 9, 14, 18, 0, tzinfo=timezone.utc)
    completed = started + timedelta(minutes=45)
    db = _QueueSession([
        _FakeResult([]),  # activities: none that day
        _FakeResult([(day, started, completed, 0, "push")]),  # strength
    ])
    result = await advanced.daily_training_stress(db, day)
    assert result is not None and result > 0, (
        "a lifting-only day must not read as zero/None training load"
    )


async def test_a_true_rest_day_is_still_none():
    """No activity and no completed strength session really is nothing —
    the fix must not turn every day non-None."""
    day = date(2026, 9, 15)
    db = _QueueSession([_FakeResult([]), _FakeResult([])])
    result = await advanced.daily_training_stress(db, day)
    assert result is None


async def test_update_training_load_unchanged_when_yesterday_is_present():
    """The common path — yesterday's row exists and is non-null — must
    produce exactly the same numbers as before this fix. Pins the
    arithmetic so the seeding change above can't quietly perturb it."""
    target = date(2026, 9, 7)
    yesterday = date(2026, 9, 6)
    db = _QueueSession([_FakeResult([(yesterday, 2.0, 5.9)])])
    ctl, atl, tsb = await advanced.update_training_load(db, target, 40.9)
    assert (ctl, atl, tsb) == (2.9, 10.9, -3.9)


async def test_missing_yesterday_decays_from_older_history_not_zero():
    """SA-L3(b): yesterday's `daily_summary` row is missing (never
    computed, or the SA-L3(a) bug left it null). Seeding from 0.0 here is
    what turned one bad day into a permanent reset, because every later
    day seeds off the one before it. The chain must instead walk back to
    the most recent real (ctl, atl) — here 3 days back at (2.0, 5.9) — and
    decay it forward across the 2-day gap before folding in today.

    A 0.0 seed would give (1.0, 5.8, 0.0) for this same input (verified
    against the pre-fix formula) — visibly different from the correct
    decayed-forward answer, which is the point: the old seed wasn't decay,
    it was a hard reset.
    """
    target = date(2026, 9, 9)
    three_days_back = date(2026, 9, 6)
    db = _QueueSession([_FakeResult([(three_days_back, 2.0, 5.9)])])
    ctl, atl, tsb = await advanced.update_training_load(db, target, 40.9)
    assert (ctl, atl, tsb) == (2.8, 9.6, -2.4)
    assert (ctl, atl, tsb) != (1.0, 5.8, 0.0), (
        "this is what a fabricated 0.0 seed would have produced instead"
    )


async def test_no_prior_history_refuses_rather_than_fabricating_zero():
    """A genuine first day of tracking: nothing in the lookback window at
    all. There is no "yesterday" to have gotten wrong, so this is the one
    case where 0.0 would not be a fabrication -- and the function still
    refuses (None, None, None) rather than assert one, per the project's
    null-is-not-zero rule. The caller stores it as a null `ctl`/`atl`/`tsb`,
    which every client already renders as "--"."""
    target = date(2026, 9, 9)
    db = _QueueSession([_FakeResult([])])
    result = await advanced.update_training_load(db, target, 40.9)
    assert result == (None, None, None)


def test_yoga_is_not_scored_as_strength():
    helper = inspect.getsource(advanced.training_load_by_day)
    assert "yoga" in helper, (
        "yoga days are generated into the same table but are not the same "
        "stimulus; scoring them at strength intensity inflates load"
    )


def test_band_is_the_acute_chronic_ratio():
    """0.8-1.3 x (CTL x 7) — the standard ACWR sweet spot in load units."""
    api = (pathlib.Path(advanced.__file__).parents[1]
           / "api" / "summary.py").read_text()
    tree = ast.parse(api)
    fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
         and n.name == "training_load"),
        None,
    )
    assert fn is not None, "training_load endpoint missing"
    src = ast.get_source_segment(api, fn) or ""
    assert "0.8" in src and "1.3" in src, "band is not the ACWR sweet spot"
    # No chronic load → no target, rather than a fabricated one.
    assert "target_low = target_high = acwr = None" in src, (
        "endpoint should return null bounds when there is no chronic load to "
        "compare against, not guess a target for a first week of training"
    )


async def test_backfill_computes_oldest_day_first(monkeypatch):
    """SA-L3: `update_training_load` seeds each day off *yesterday's
    stored row*, so a backfill that computes newest-first asks for today
    before yesterday has been recomputed in this same pass -- every day
    but the very last one seeds from stale or missing history, and only
    the single oldest day actually heals. Oldest-first means each day's
    yesterday is already correct by the time it's used, so one call heals
    the whole requested range."""
    from myvitals.api import analytics as analytics_api

    seen: list[date] = []

    async def fake_compute(target_date):
        seen.append(target_date)

    monkeypatch.setattr(analytics_api, "compute_daily_summary", fake_compute)
    await analytics_api.backfill_analytics(days=5)

    assert len(seen) == 5
    assert seen == sorted(seen), (
        "backfill must compute oldest-to-newest, or update_training_load "
        "seeds each day off a yesterday this same call hasn't fixed yet"
    )


def test_week_is_computed_from_source_not_the_summary_column():
    """daily_summary.training_stress_score is only rewritten when a summary is
    recomputed, and staleness watches sleep/HRV — so a change to how load is
    derived never reaches historical days."""
    api = (pathlib.Path(advanced.__file__).parents[1]
           / "api" / "summary.py").read_text()
    tree = ast.parse(api)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "training_load"
    )
    src = ast.get_source_segment(api, fn) or ""
    assert "training_load_by_day" in src, (
        "weekly load reads the stored summary column, so it will report zero "
        "for weeks that predate any change to how load is derived"
    )
