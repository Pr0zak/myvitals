"""Every stage the watch reports must survive to the client.

`sleep_stages` holds BOTH of Fitbit's vocabularies — "stages"
(light/deep/rem/wake) and the older classic "levels" (asleep/restless/awake).
A four-entry allow-list dropped `asleep`, `restless` and `wake`, which is
~39% of all stage rows, so a night recorded in classic levels rendered an
almost-empty hypnogram beneath a headline claiming a full night's sleep.
"""
from datetime import datetime, timedelta, timezone

from myvitals.analytics import events as ev
from myvitals.analytics.events import clamp_stage_durations

# Fetched lazily so a tree without the synonym table fails on the ASSERTION
# (showing the real defect) rather than on import.
STAGE_ORDER = getattr(ev, "STAGE_ORDER", [])
STAGE_SYNONYMS = getattr(ev, "STAGE_SYNONYMS", {})


def _rows(*stages: str):
    t0 = datetime(2026, 8, 11, 2, 0, tzinfo=timezone.utc)
    return [(t0 + timedelta(minutes=30 * i), s, 1800) for i, s in enumerate(stages)]


def test_wake_is_folded_into_awake():
    """Two spellings of one thing must not split the awake total."""
    end = datetime(2026, 8, 11, 4, 0, tzinfo=timezone.utc)
    out = clamp_stage_durations(_rows("wake", "light"), end)
    assert [o["stage"] for o in out] == ["awake", "light"], out
    assert "wake" not in {o["stage"] for o in out}


def test_classic_levels_are_not_dropped():
    """asleep / restless are real Fitbit levels, not junk."""
    end = datetime(2026, 8, 11, 5, 0, tzinfo=timezone.utc)
    out = clamp_stage_durations(_rows("asleep", "restless", "awake"), end)
    assert {o["stage"] for o in out} == {"asleep", "restless", "awake"}


def test_stage_order_covers_both_vocabularies():
    for s in ("awake", "rem", "light", "deep", "asleep", "restless"):
        assert s in STAGE_ORDER, f"{s} missing from STAGE_ORDER"
    assert STAGE_SYNONYMS.get("wake") == "awake"


def test_unknown_stage_passes_through_untouched():
    """A stage we have never seen should still reach the client."""
    end = datetime(2026, 8, 11, 3, 0, tzinfo=timezone.utc)
    out = clamp_stage_durations(_rows("brand_new_stage"), end)
    assert [o["stage"] for o in out] == ["brand_new_stage"]
