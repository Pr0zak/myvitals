"""HR-zone arithmetic — TD-2.

Zones had three separate client-side implementations and one correct
server-side one that no HTTP route exposed. These tests pin the server's
behaviour so the clients can be thin, and they encode the two specific ways
the client versions were wrong:

1. They counted heart-rate *samples* per zone rather than seconds. A watch
   that samples irregularly — dense during hard efforts, sparse while
   coasting — then reports a distribution that is a function of its own
   sampling behaviour rather than of the training.
2. The web's zone-breakdown card divided by ``activity.max_hr``, the peak
   heart rate observed during that session, instead of the athlete's
   physiological maximum. An easy ride topping out at 140 bpm therefore
   reported time in Z4 and Z5, and the same ride reported different zones
   from the card immediately above it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from myvitals.analytics import cardio


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    """Just enough AsyncSession for the zone functions.

    ``execute`` always returns the HR rows; ``get`` returns the profile. The
    real query construction is exercised against Postgres in the deployed
    app — what is worth pinning here is the arithmetic on the rows.
    """

    def __init__(self, rows, profile=None):
        self._rows = rows
        self._profile = profile

    async def execute(self, _stmt):
        return _FakeResult(self._rows)

    async def get(self, _model, _pk):
        return self._profile


START = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)


def _activity(duration_s=600, avg_hr=None, max_hr=None):
    return SimpleNamespace(
        source="strava", source_id="1", start_at=START,
        duration_s=duration_s, avg_hr=avg_hr, max_hr=max_hr,
    )


# --------------------------------------------------------------------------
# Boundaries
# --------------------------------------------------------------------------

def test_zone_bounds_are_absolute_bpm_and_cover_the_range():
    bounds = cardio.zone_bounds(200.0)
    assert [b["zone"] for b in bounds] == ["Z1", "Z2", "Z3", "Z4", "Z5"]
    assert [b["lo_bpm"] for b in bounds] == [0, 120, 140, 160, 180]
    # The top zone is open-ended: there is no upper bound on effort.
    assert bounds[-1]["hi_bpm"] is None
    assert bounds[-1]["hi_pct"] is None
    # Each zone starts exactly where the previous one ended — no gaps, no
    # overlaps, so no reading can fall into two zones or none.
    for lower, upper in zip(bounds, bounds[1:]):
        assert lower["hi_bpm"] == upper["lo_bpm"]


def test_zone_labels_cover_every_bound():
    assert set(cardio.ZONE_LABELS) == {z for z, _, _ in cardio.ZONE_BOUNDS_PCT}


@pytest.mark.parametrize("bpm,expected", [
    (100, "Z1"), (119, "Z1"), (120, "Z2"), (139, "Z2"),
    (140, "Z3"), (160, "Z4"), (180, "Z5"), (250, "Z5"),
])
def test_zone_for_is_inclusive_at_the_lower_edge(bpm, expected):
    assert cardio.zone_for(bpm, 200.0) == expected


# --------------------------------------------------------------------------
# Max-HR provenance
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_measured_max_hr_beats_the_age_estimate():
    profile = SimpleNamespace(max_hr=186.0, birth_date=None)
    value, source, age = await cardio.resolve_max_hr(_FakeSession([], profile))
    assert (value, source, age) == (186.0, "profile", None)


@pytest.mark.asyncio
async def test_birth_date_produces_a_tanaka_estimate():
    born = datetime.now(timezone.utc).date().replace(year=1986)
    profile = SimpleNamespace(max_hr=None, birth_date=born)
    value, source, age = await cardio.resolve_max_hr(_FakeSession([], profile))
    assert source == "estimated"
    assert age is not None
    assert value == pytest.approx(208.0 - 0.7 * age)


@pytest.mark.asyncio
async def test_no_profile_data_is_reported_as_a_default_not_an_estimate():
    """The age-40 fallback must not masquerade as a personalised number.

    Without this distinction a chart built on nothing at all looks exactly
    like one built on the user's own birth date.
    """
    profile = SimpleNamespace(max_hr=None, birth_date=None)
    value, source, age = await cardio.resolve_max_hr(_FakeSession([], profile))
    assert source == "default"
    assert age is None
    assert value == pytest.approx(208.0 - 0.7 * 40)


# --------------------------------------------------------------------------
# The bug: seconds, not samples
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_time_in_zone_weights_by_elapsed_seconds_not_sample_count():
    """Nine dense samples in one zone must not outweigh one long stretch.

    This is the sampling-cadence bug in its purest form: a watch that fires
    every second through a 9-second hard effort and then once after a 30
    second easy stretch yields nine Z5 samples against one Z1 sample. By
    sample count that is 90% Z5. By time it is 23% Z5, which is what
    actually happened.
    """
    rows = [(START + timedelta(seconds=i), 190.0) for i in range(1, 10)]
    rows.append((START + timedelta(seconds=39), 100.0))
    tiz = await cardio.time_in_zone_for_activity(
        _FakeSession(rows), _activity(duration_s=60), max_hr=200.0,
    )
    assert tiz["Z5"] == 9
    assert tiz["Z1"] == 30
    # Sample-counting would have called this ~90% Z5.
    assert tiz["Z5"] / sum(tiz.values()) == pytest.approx(9 / 39)


@pytest.mark.asyncio
async def test_long_gaps_are_capped_so_missing_data_is_not_attributed():
    """A watch that dropped out for an hour did not spend that hour in the
    zone it happened to resume in."""
    rows = [(START + timedelta(seconds=3600), 190.0)]
    tiz = await cardio.time_in_zone_for_activity(
        _FakeSession(rows), _activity(duration_s=3600), max_hr=200.0,
    )
    assert tiz["Z5"] == 30


# --------------------------------------------------------------------------
# The assembled payload
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_detail_reports_percentages_that_sum_to_the_session():
    rows = [
        (START + timedelta(seconds=10), 100.0),   # Z1 for 10s
        (START + timedelta(seconds=30), 150.0),   # Z3 for 20s
        (START + timedelta(seconds=45), 190.0),   # Z5 for 15s
    ]
    profile = SimpleNamespace(max_hr=200.0, birth_date=None)
    out = await cardio.activity_zone_detail(
        _FakeSession(rows, profile), _activity(duration_s=60), buckets=0,
    )
    assert out["sampled"] is True
    assert out["max_hr_source"] == "profile"
    assert out["total_seconds"] == 45
    by_zone = {z["zone"]: z for z in out["zones"]}
    assert by_zone["Z1"]["seconds"] == 10
    assert by_zone["Z3"]["seconds"] == 20
    assert by_zone["Z5"]["seconds"] == 15
    assert sum(z["pct"] for z in out["zones"]) == pytest.approx(100.0, abs=0.2)
    # Boundaries travel with the numbers so no client re-derives them.
    assert by_zone["Z3"]["lo_bpm"] == 140


@pytest.mark.asyncio
async def test_detail_flags_the_avg_hr_fallback_as_unsampled():
    """A session with no HR series still produces a distribution, but the
    client has to be able to tell that it is one bar wide by construction
    rather than because the ride was genuinely steady."""
    profile = SimpleNamespace(max_hr=200.0, birth_date=None)
    out = await cardio.activity_zone_detail(
        _FakeSession([], profile), _activity(duration_s=600, avg_hr=150.0), buckets=0,
    )
    assert out["sampled"] is False
    by_zone = {z["zone"]: z["seconds"] for z in out["zones"]}
    assert by_zone["Z3"] == 600
    assert out["total_seconds"] == 600


@pytest.mark.asyncio
async def test_series_sums_back_to_the_zone_totals():
    """The stacked chart and the distribution must describe one session.

    They are computed in separate passes over the same rows, so it is worth
    asserting that the two passes agree rather than assuming it.
    """
    rows = [(START + timedelta(seconds=i * 5), 100.0 + i * 10) for i in range(1, 13)]
    profile = SimpleNamespace(max_hr=200.0, birth_date=None)
    out = await cardio.activity_zone_detail(
        _FakeSession(rows, profile), _activity(duration_s=60), buckets=10,
    )
    assert len(out["series"]) == 10
    for zone in out["zones"]:
        from_series = sum(bucket.get(zone["zone"], 0) for bucket in out["series"])
        assert from_series == zone["seconds"], zone["zone"]
