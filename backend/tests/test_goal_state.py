"""GOAL-STATE — a goal that has gone backwards must say so.

A 0% progress bar carried three different meanings: "no data yet", "on
the starting line", and "you have moved AWAY from the target". The third
is the one that matters and the one the bar could not express — a user
5 lb heavier than when they set a weight-loss goal saw an empty bar,
which reads as "just getting started".

That conflation is the same one this codebase refuses everywhere else:
an absent value is not a zero, and a verdict the app cannot reach must
not borrow the appearance of one it can.

`progress_pct` is deliberately unchanged — same 0..100 clamp, same null
behaviour. Clients reading only that field must keep working, and one of
them fails dangerously if it stops: `YouScreen.kt` falls back to
`current / target` when the pct is null, which for 253.9 lb against a
200 lb goal is 1.27, clamped to a FULL bar. Signalling "no progress" by
nulling the pct would paint the most emphatic possible success on the
goal that has gone backwards.
"""
from __future__ import annotations

from types import SimpleNamespace

from myvitals.api.ai import WEIGHT_NOISE_BAND_KG, _goal_progress

LOSS = SimpleNamespace(kind="weight", target_value=200.0, target_unit="lb")
GAIN = SimpleNamespace(kind="weight", target_value=176.0, target_unit="lb")
STEPS = SimpleNamespace(kind="steps", target_value=10000.0, target_unit="steps")
SOBER = SimpleNamespace(kind="sober", target_value=30.0, target_unit="days")


def test_the_reported_case_reads_as_moved_away() -> None:
    """Baseline 112.9 kg, now 115.33 kg, target 200 lb. Five pounds the
    wrong way."""
    r = _goal_progress(LOSS, 115.33, 112.9)
    assert r["progress_state"] == "moved_away"
    assert r["state_tone"] == "caution"
    assert r["delta_value"] > 0
    assert r["progress_pct"] == 0.0


def test_moved_away_and_at_start_and_no_data_are_three_things() -> None:
    """The whole point. All three used to render as an empty bar."""
    moved = _goal_progress(LOSS, 115.33, 112.9)["progress_state"]
    start = _goal_progress(LOSS, 112.9, 112.9)["progress_state"]
    none_ = _goal_progress(LOSS, None, 112.9)["progress_state"]
    assert len({moved, start, none_}) == 3, (moved, start, none_)
    assert none_ == "no_data"


def test_a_goal_with_no_baseline_is_no_data_not_zero_progress() -> None:
    """No weigh-in since the goal started is not "no progress"; it is no
    answer, and the app says so rather than drawing an empty bar."""
    r = _goal_progress(LOSS, 115.33, None)
    assert r["progress_state"] == "no_data"
    assert r["state_tone"] == "unknown"
    assert r["baseline_value"] is None and r["delta_value"] is None


def test_progress_pct_keeps_its_old_contract() -> None:
    """Byte-for-byte: 0..100, and null only when there is no current
    value. A client that reads nothing else must be no worse off."""
    for cur, base in ((115.33, 112.9), (108.0, 112.9), (90.0, 112.9), (112.9, 112.9)):
        pct = _goal_progress(LOSS, cur, base)["progress_pct"]
        assert pct is not None and 0.0 <= pct <= 100.0
    assert _goal_progress(LOSS, None, 112.9)["progress_pct"] is None


def test_delta_is_exactly_current_minus_baseline() -> None:
    """The subtraction a user can do on the screen must agree with the
    state shown, so the state is judged on the same numbers displayed —
    not on a smoothed figure they cannot see."""
    r = _goal_progress(LOSS, 115.33, 112.9)
    assert abs(r["delta_value"] - (r["current_value"] - r["baseline_value"])) < 0.01


def test_the_baseline_is_reported_in_the_goals_unit() -> None:
    """It used to be emitted by the CALLER as raw kilograms beside a
    pounds target — the third unit bug in this area, and outside the
    reach of the test guarding the conversion because that test walks
    this function and the emission was one line later."""
    r = _goal_progress(LOSS, 115.33, 112.9)
    assert abs(r["baseline_value"] - 248.9) < 0.2, r["baseline_value"]


def test_a_small_drift_is_not_called_a_direction() -> None:
    """Firing amber on water weight is the HEALTH-1 failure: a card wrong
    most weeks is one you have stopped reading by the week it matters."""
    inside = _goal_progress(LOSS, 112.9 + WEIGHT_NOISE_BAND_KG * 0.5, 112.9)
    assert inside["progress_state"] == "at_start"
    outside = _goal_progress(LOSS, 112.9 + WEIGHT_NOISE_BAND_KG * 2, 112.9)
    assert outside["progress_state"] == "moved_away"


def test_the_noise_band_errs_toward_saying_nothing() -> None:
    """A real small regression reading as "at the starting line" is the
    tolerable error. The reverse — crying wolf — is not."""
    assert 0.3 <= WEIGHT_NOISE_BAND_KG <= 2.0


def test_a_weight_gain_goal_is_not_complete_at_halfway() -> None:
    """The old `denom <= 0` special case made a bulk goal read 100% at
    the midpoint: baseline 70 kg, target 80 kg, at 75 kg `current <=
    target` held and the bar filled. The signed formula was always
    general; the guard was the bug."""
    r = _goal_progress(GAIN, 75.0, 70.0)
    assert 45.0 <= r["progress_pct"] <= 55.0, r["progress_pct"]
    assert r["progress_state"] == "advancing"


def test_a_weight_gain_goal_still_completes() -> None:
    r = _goal_progress(GAIN, 80.0, 70.0)
    assert r["progress_state"] == "achieved"
    assert r["progress_pct"] == 100.0


def test_gain_oriented_kinds_get_a_state_too() -> None:
    assert _goal_progress(STEPS, 12000, None)["progress_state"] == "achieved"
    assert _goal_progress(STEPS, 4000, None)["progress_state"] == "advancing"


def test_a_broken_sober_streak_is_never_coloured_as_a_warning() -> None:
    """A reset streak reads as zero. It is a regression by any arithmetic
    and it is the one thing in this app that must not be scolded — the
    tone is decided on the server precisely so no client can get this
    wrong."""
    r = _goal_progress(SOBER, 0.0, None)
    assert r["state_tone"] == "neutral"
    assert r["state_tone"] != "caution"


def test_moved_away_is_caution_never_the_crisis_colour() -> None:
    """Rose is reserved for the crisis surfaces. Spending it on a body
    weight that drifted over a quarter is how it comes to mean nothing
    when it fires for something that does matter."""
    tones = {
        _goal_progress(LOSS, 115.33, 112.9)["state_tone"],
        _goal_progress(LOSS, 108.0, 112.9)["state_tone"],
        _goal_progress(LOSS, 112.9, 112.9)["state_tone"],
        _goal_progress(LOSS, None, 112.9)["state_tone"],
    }
    assert tones <= {"positive", "neutral", "caution", "unknown"}
    assert "critical" not in tones and "bad" not in tones


def test_every_branch_returns_the_full_field_set() -> None:
    """A surface branching on `progress_state` must never meet a response
    that lacks it."""
    keys = {"current_value", "baseline_value", "delta_value",
            "progress_pct", "progress_state", "state_tone"}
    for g, cur, base in ((LOSS, 115.33, 112.9), (LOSS, None, None),
                         (STEPS, 4000, None), (SOBER, 0.0, None),
                         (GAIN, 75.0, 70.0)):
        assert keys <= set(_goal_progress(g, cur, base)), (g.kind, cur)


def test_goal_progress_includes_all_goal_state_fields_for_projection() -> None:
    """The _goal_progress function must return all GOAL-STATE fields plus
    projection so the client can render complete goal cards. This was failing
    in SA-L2 because You.vue re-mapped and dropped projection.
    """
    r = _goal_progress(LOSS, 115.33, 112.9)
    # Verify the function includes all fields the endpoint needs to return
    assert "current_value" in r
    assert "baseline_value" in r
    assert "delta_value" in r
    assert "progress_pct" in r
    assert "progress_state" in r
    assert "state_tone" in r
    # The projection field is added by the endpoint, not by _goal_progress,
    # but we verify no_data case also gets the full set
    r_no_data = _goal_progress(LOSS, None, 112.9)
    assert "progress_state" in r_no_data and r_no_data["progress_state"] == "no_data"
    assert "state_tone" in r_no_data and r_no_data["state_tone"] == "unknown"


# ── Auto-completion uses the same rule the card does (UX-D1) ────────────
#
# `_check_goals_for_completion` runs inside GET /ai/alerts, which every page
# load calls. It carried its own `latest <= target` for weight goals long
# after `_goal_progress` learned about gain goals, so a bulk goal was closed
# as "reached" — and a goal_reached alert fired — on the very next load.


class _Rows:
    def __init__(self, items=None, scalar=None):
        self._items = items or []
        self._scalar = scalar

    def scalars(self):
        return self

    def all(self):
        return self._items

    def scalar_one(self):
        return self._scalar


class _Db:
    def __init__(self, goals):
        self.goals = goals
        self.added: list = []
        self.committed = False
        self._first = True

    async def execute(self, _stmt):
        if self._first:
            self._first = False
            return _Rows(self.goals)
        return _Rows(scalar=0)   # no existing alert with this dedup_key

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True


async def _run_completion(monkeypatch, goal, current_kg, baseline_kg):
    from myvitals.api import ai

    async def _currents(_db, _kinds):
        return {"weight": current_kg}

    async def _baseline(_db, _started):
        return baseline_kg

    monkeypatch.setattr(ai, "_current_values_for_goals", _currents)
    monkeypatch.setattr(ai, "_baseline_weight_kg_for_goal", _baseline)
    db = _Db([goal])
    await ai._check_goals_for_completion(db)
    return db


def _weight_goal(target_kg):
    return SimpleNamespace(
        id=7, kind="weight", title="Bulk", target_value=target_kg,
        target_unit="kg", started_at=None, ended_at=None,
    )


async def test_a_gain_goal_below_its_target_is_not_auto_closed(monkeypatch) -> None:
    goal = _weight_goal(80.0)
    db = await _run_completion(monkeypatch, goal, current_kg=72.0, baseline_kg=70.0)
    assert goal.ended_at is None
    assert db.added == []


async def test_a_gain_goal_that_reaches_its_target_is_closed(monkeypatch) -> None:
    goal = _weight_goal(80.0)
    db = await _run_completion(monkeypatch, goal, current_kg=80.4, baseline_kg=70.0)
    assert goal.ended_at is not None
    assert [a.kind for a in db.added] == ["goal_reached"]


async def test_a_loss_goal_still_closes_when_reached(monkeypatch) -> None:
    goal = _weight_goal(90.0)
    await _run_completion(monkeypatch, goal, current_kg=89.8, baseline_kg=100.0)
    assert goal.ended_at is not None
