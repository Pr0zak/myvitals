"""Server-owned ring facts for Sober and Fasting (UI-6).

Both clients used to carry their own milestone list / stage-label map and
derive "next milestone" and "next stage in" from a locally ticked clock.
These pin the fields that replaced that.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from myvitals.api import fasting, sober

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)


def test_no_active_streak_has_the_ladder_but_no_next():
    out = sober.milestone_fields(None, NOW)
    assert out["milestones"] == [7, 14, 30, 60, 90, 180, 365]
    assert out["milestones_reached"] == 0
    assert out["next_milestone_days"] is None
    assert out["next_milestone_at"] is None
    assert out["milestone_progress"] == 0.0


def test_mid_ladder_names_the_next_milestone_and_when():
    start = NOW - timedelta(days=42, hours=7, minutes=30)
    out = sober.milestone_fields(start, NOW)
    assert out["milestones_reached"] == 3          # 7, 14, 30
    assert out["next_milestone_days"] == 60
    assert out["next_milestone_at"] == start + timedelta(days=60)
    assert out["next_milestone_in_seconds"] == int(
        (start + timedelta(days=60) - NOW).total_seconds())
    # Three of seven dots passed, 12.3/30 of the way to the fourth.
    n = len(out["milestones"])
    assert 3 / n < out["milestone_progress"] < 4 / n


def test_fill_reaches_a_dot_exactly_when_that_milestone_passes():
    out = sober.milestone_fields(NOW - timedelta(days=30), NOW)
    assert out["milestones_reached"] == 3
    assert out["milestone_progress"] == round(3 / len(out["milestones"]), 4)


def test_past_a_year_the_ladder_grows_so_there_is_always_a_next():
    out = sober.milestone_fields(NOW - timedelta(days=800), NOW)
    assert out["milestones"][-2:] == [730, 1095]
    assert out["next_milestone_days"] == 1095
    assert out["milestone_progress"] < 1.0


def _row(hours_ago: float, target: float | None, ended: bool = False):
    started = NOW - timedelta(hours=hours_ago)
    return SimpleNamespace(
        id=1, started_at=started, ended_at=NOW if ended else None,
        protocol="16:8", mode="active", target_hours=target,
        target_eating_window_h=8.0, notes=None,
    )


def test_fasting_enrich_serves_stages_and_next_stage(monkeypatch):
    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(fasting, "datetime", _DT)
    out = fasting._enrich(_row(14.3, 16.0))
    assert out["current_stage"] == "glycogen_depleting"
    assert out["current_stage_label"] == "Glycogen depleting"
    assert out["next_stage"] == "ketosis"
    assert out["next_stage_label"] == "Ketosis"
    assert out["hours_to_next_stage"] == 1.7
    assert out["target_end_at"] == (
        NOW - timedelta(hours=14.3) + timedelta(hours=16)).isoformat()
    assert out["reached_target"] is False
    assert [s["at_h"] for s in out["stages"]] == [h for h, _ in fasting.FASTING_STAGES]
    fasting.FastingSessionOut(**out)  # still validates against the schema


def test_fasting_without_a_target_does_not_invent_one():
    out = fasting._enrich(_row(20.0, None, ended=True))
    assert out["target_end_at"] is None
    assert out["reached_target"] is None
    out2 = fasting._enrich(_row(17.0, 16.0, ended=True))
    assert out2["reached_target"] is True
