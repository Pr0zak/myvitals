"""PUT /profile applies only the fields a client SENT (D1, D2 — 2026-09-24).

Every field on ProfileIn defaults to None and the handler used to assign all
of them, so a client that did not model a field erased it on each save:
every web profile save nulled `fasting_target_hours_per_week`, the phone's
reminder toggle nulled the home location, and the goal sync then blanked
the target of every active sleep and fast_streak goal. Separately, both
clients write `extra.sleep_goal_h` while analytics read the
`sleep_target_h` column, which only `extra.sleep_target_h` fed.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from myvitals.api import profile as prof


class _Rows:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items


class _Db:
    def __init__(self, p, goals):
        self.p = p
        self.goals = goals

    async def get(self, _model, _pk):
        return self.p

    async def execute(self, stmt):
        kind = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        return _Rows([g for g in self.goals if f"'{g.kind}'" in kind])

    def add(self, _obj):
        pass

    async def commit(self):
        pass

    async def refresh(self, _obj):
        pass


def _profile(**kw):
    base = dict(
        id=1, birth_date=None, sex="male", height_cm=180.0, weight_goal_kg=90.0,
        fasting_target_hours_per_week=100.0, resting_hr_baseline=55.0, max_hr=185.0,
        activity_level="moderate", extra={"steps_goal": 8000, "display": {"units": "imperial"}},
        home_latitude=43.0, home_longitude=-89.4, sleep_target_h=8.0, updated_at=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _put(p, goals, **body):
    db = _Db(p, goals)

    async def _dict(_db, _p):
        return {}
    orig = prof._profile_dict
    prof._profile_dict = _dict
    try:
        asyncio.run(prof.put_profile(prof.ProfileIn(**body), db=db))
    finally:
        prof._profile_dict = orig


def test_a_partial_save_leaves_unsent_fields_alone():
    p = _profile()
    _put(p, [], extra={"steps_goal": 9000})
    assert p.fasting_target_hours_per_week == 100.0
    assert (p.home_latitude, p.home_longitude) == (43.0, -89.4)
    assert p.max_hr == 185.0 and p.weight_goal_kg == 90.0 and p.sex == "male"
    assert p.extra["steps_goal"] == 9000
    assert p.extra["display"] == {"units": "imperial"}


def test_an_explicit_null_still_clears():
    p = _profile()
    _put(p, [], max_hr=None)
    assert p.max_hr is None


def test_goals_are_only_synced_for_fields_that_were_sent():
    sleep = SimpleNamespace(kind="sleep", target_value=7.5)
    fast = SimpleNamespace(kind="fast_streak", target_value=100.0)
    p = _profile()
    _put(p, [sleep, fast], extra={"steps_goal": 9000})
    assert sleep.target_value == 7.5, "a save that never mentioned sleep blanked its goal"
    assert fast.target_value == 100.0, "a save that never mentioned fasting blanked its goal"


def test_the_sleep_goal_key_the_clients_actually_write_sets_the_column():
    sleep = SimpleNamespace(kind="sleep", target_value=8.0)
    p = _profile()
    _put(p, [sleep], extra={"sleep_goal_h": 7.25})
    assert p.sleep_target_h == 7.25
    assert sleep.target_value == 7.25


# ── data-health overview (settings home hero) ────────────────────────────

from myvitals.analytics.data_health import overview  # noqa: E402


def _s(key, label, status, age=None):
    return {"key": key, "label": label, "status": status, "age_hours": age}


def test_overview_is_positive_when_nothing_is_wrong():
    o = overview([_s("hr", "Heart rate", "ok", 1)],
                 [{"key": "strava", "label": "Strava", "configured": True, "status": "ok"}],
                 {"permissions_lost": False, "last_success": "t"}, [])
    assert (o["tone"], o["headline"]) == ("positive", "Everything is arriving")
    assert (o["integrations_ok"], o["integrations_total"]) == (1, 1)


def test_overview_names_the_first_problem_in_amber():
    streams = [_s("hr", "Heart rate", "stale", 26.4), _s("steps", "Steps", "stale", 30)]
    o = overview(streams, [], {"permissions_lost": False}, ["hr", "steps"])
    assert o["tone"] == "caution"
    assert o["headline"] == "Heart rate not updated for 26h (+1 more)"


def test_health_connect_denial_outranks_everything():
    o = overview([_s("hr", "Heart rate", "stale", 26)], [], {"permissions_lost": True}, ["hr"])
    assert o["headline"].startswith("Health Connect")
    assert o["problem_count"] == 2


# ── a stream fed only by a failing integration is its symptom ─────────────

from myvitals.analytics.data_health import downstream_of  # noqa: E402


def test_spo2_behind_a_dead_google_grant_is_not_a_second_problem():
    streams = [dict(_s("spo2", "Blood oxygen", "stale", 428), via_integration="google_health"),
               dict(_s("hr", "Heart rate", "ok", 1), via_integration=None)]
    integ = [{"key": "google_health", "label": "Google Health", "configured": True,
              "status": "error", "last_error_kind": "auth"}]
    blocked = downstream_of(streams, integ)
    assert blocked == {"spo2": "google_health"}
    problems = [s["key"] for s in streams if s["status"] == "stale" and s["key"] not in blocked]
    problems += ["google_health"]
    o = overview(streams, integ, {"permissions_lost": False}, problems)
    assert o["headline"] == "Google Health needs reconnecting"
    assert o["problem_count"] == 1


def test_a_stale_stream_whose_integration_is_fine_is_still_a_problem():
    streams = [dict(_s("spo2", "Blood oxygen", "stale", 60), via_integration="google_health")]
    integ = [{"key": "google_health", "label": "Google Health", "configured": True, "status": "ok"}]
    assert downstream_of(streams, integ) == {}
