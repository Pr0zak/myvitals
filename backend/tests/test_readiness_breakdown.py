"""READY-1 — readiness banding + driver exposure.

`readiness_score` was refactored to delegate to `readiness_breakdown`. The
load-bearing property is that the SCORE IS UNCHANGED — the drivers were
always computed internally and thrown away; only the discarding changed.
"""
import datetime

import pytest

from myvitals.analytics.advanced import readiness_band, readiness_breakdown, readiness_score


class FakeResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class FakeDb:
    """Stands in for the 28-day baseline query.

    `row` is (hrv_mu, hrv_sd, hrv_n, rhr_mu, rhr_sd, rhr_n) — the exact
    tuple shape the real aggregate returns.
    """
    def __init__(self, row):
        self.row = row

    async def execute(self, _stmt):
        return FakeResult(self.row)


BASELINE = (60.0, 10.0, 28, 55.0, 5.0, 28)   # healthy 28-day baseline
DAY = datetime.date(2026, 8, 9)


# ── banding ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("score,expected", [
    (0.0, "low"), (29.0, "low"),
    (29.1, "moderate"), (50.0, "moderate"), (64.0, "moderate"),
    (64.1, "high"), (100.0, "high"),
])
def test_bands_match_the_documented_thresholds(score, expected):
    assert readiness_band(score) == expected


def test_band_of_none_is_none():
    # No score must not silently become "low" — that reads as a health
    # warning the data doesn't support.
    assert readiness_band(None) is None


# ── the refactor invariant ────────────────────────────────────────────

@pytest.mark.parametrize("hrv,rhr,ss,sd", [
    (72.0, 52.0, 80.0, 27000),
    (48.0, 61.0, 40.0, 18000),
    (60.0, 55.0, None, None),
    (None, 55.0, 70.0, 25200),
    (72.0, None, None, 28800),
])
async def test_score_equals_breakdown_score(hrv, rhr, ss, sd):
    """readiness_score is now a thin wrapper — the two must never diverge."""
    db = FakeDb(BASELINE)
    a = await readiness_score(db, DAY, hrv, rhr, ss, sd)
    b = await readiness_breakdown(db, DAY, hrv, rhr, ss, sd)
    assert a == b["score"]


# ── drivers ───────────────────────────────────────────────────────────

async def test_drivers_carry_z_and_weight():
    db = FakeDb(BASELINE)
    out = await readiness_breakdown(db, DAY, 72.0, 52.0, 80.0, 27000)
    keys = {d["key"] for d in out["drivers"]}
    assert keys == {"hrv", "rhr", "sleep_score", "sleep_duration"}
    hrv = next(d for d in out["drivers"] if d["key"] == "hrv")
    # 72 against mean 60, sd 10 → +1.2σ
    assert hrv["z"] == pytest.approx(1.2, abs=0.01)
    assert hrv["weight"] == 0.40
    assert hrv["higher_is_better"] is True
    rhr = next(d for d in out["drivers"] if d["key"] == "rhr")
    # Lower RHR is better, so a NEGATIVE z must raise the sub-score.
    assert rhr["z"] < 0
    assert rhr["sub_score"] > 50
    assert rhr["higher_is_better"] is False


async def test_thin_inputs_return_none_with_a_reason_not_a_number():
    db = FakeDb(BASELINE)
    # Sleep score alone is 0.15 weight — below the 0.45 floor.
    out = await readiness_breakdown(db, DAY, None, None, 80.0, None)
    assert out["score"] is None
    assert out["band"] is None
    assert out["reason"]
    # Drivers are still reported so the UI can say WHAT it had.
    assert [d["key"] for d in out["drivers"]] == ["sleep_score"]


async def test_thin_baseline_drops_the_zscored_branches():
    # Only 3 days of baseline — below MIN_BASELINE_DAYS.
    db = FakeDb((60.0, 10.0, 3, 55.0, 5.0, 3))
    out = await readiness_breakdown(db, DAY, 72.0, 52.0, 80.0, 27000)
    keys = {d["key"] for d in out["drivers"]}
    assert "hrv" not in keys and "rhr" not in keys
    # Sleep alone is 0.30 — still under the floor, so no score.
    assert out["score"] is None


async def test_no_baseline_row_is_handled():
    out = await readiness_breakdown(FakeDb(None), DAY, 60.0, 55.0, 80.0, 27000)
    assert out["score"] is None
    assert out["drivers"] == []


async def test_a_good_day_bands_high_and_a_bad_day_bands_low():
    db = FakeDb(BASELINE)
    good = await readiness_breakdown(db, DAY, 85.0, 47.0, 95.0, 30600)
    bad = await readiness_breakdown(db, DAY, 38.0, 68.0, 25.0, 16200)
    assert good["band"] == "high"
    assert bad["band"] == "low"
    assert good["score"] > bad["score"]
