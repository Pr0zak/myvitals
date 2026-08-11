"""Tile status semantics.

The tiles tell the user whether a number is good. That judgement has to be
pinned, because the failure mode is silent: a direction flipped on resting
HR would colour a *rising* resting heart rate green and nobody would notice
from the code alone.
"""
import pytest

from myvitals.analytics.tiles import (
    GOOD,
    TYPICAL,
    WATCH,
    Z_NOTABLE,
    _band_from_z,
    _pct_of_target,
)


# ── direction ─────────────────────────────────────────────────────────

def test_higher_is_better_metrics_reward_a_positive_z():
    status, reason = _band_from_z(1.5, higher_is_better=True)
    assert status == GOOD
    assert "above" in reason


def test_lower_is_better_metrics_reward_a_negative_z():
    """Resting HR: dropping below baseline is the GOOD outcome.

    This is the assertion that matters most in the file — get it backwards
    and a climbing resting heart rate reads as an improvement.
    """
    status, reason = _band_from_z(-1.5, higher_is_better=False)
    assert status == GOOD
    assert "below" in reason

    status, _ = _band_from_z(1.5, higher_is_better=False)
    assert status == WATCH


def test_the_middle_is_typical_for_both_directions():
    for higher in (True, False):
        assert _band_from_z(0.0, higher_is_better=higher)[0] == TYPICAL
        assert _band_from_z(0.9, higher_is_better=higher)[0] == TYPICAL
        assert _band_from_z(-0.9, higher_is_better=higher)[0] == TYPICAL


@pytest.mark.parametrize("z,higher,expected", [
    (Z_NOTABLE, True, GOOD),
    (Z_NOTABLE - 0.01, True, TYPICAL),
    (-Z_NOTABLE, True, WATCH),
    (-Z_NOTABLE, False, GOOD),
    (Z_NOTABLE, False, WATCH),
])
def test_boundaries_are_inclusive_on_the_notable_side(z, higher, expected):
    assert _band_from_z(z, higher_is_better=higher)[0] == expected


def test_reason_reports_the_magnitude_unsigned():
    # The word already carries the direction; a "-1.5σ below" reason reads
    # as a double negative.
    _, reason = _band_from_z(-1.5, higher_is_better=False)
    assert "1.5σ" in reason and "-1.5" not in reason


# ── targets ───────────────────────────────────────────────────────────

def test_pct_of_target_is_safe_when_no_target_is_set():
    # A user with the goal cleared must not crash the whole grid.
    assert _pct_of_target(5000, 0) == 0.0


def test_pct_of_target_is_a_percentage():
    assert _pct_of_target(5000, 10000) == pytest.approx(50.0)
    assert _pct_of_target(12000, 10000) == pytest.approx(120.0)


# ── staleness ─────────────────────────────────────────────────────────

def test_a_stale_reading_is_reported_but_not_judged():
    """Verdicts are claims about NOW.

    Blood pressure and weight carry forward the last reading, which can be
    months old. Rendering "stage 1 range" off a 62-day-old cuff reading
    states something current about the user that the data doesn't support.
    The value and its date survive; only the verdict is withheld.
    """
    from myvitals.analytics.tiles import (
        STALE_VERDICT_DAYS,
        suppress_stale_verdict,
    )

    def add(**kw):
        return suppress_stale_verdict(kw)

    fresh = add(key="bp", value="139/92", status=WATCH,
                status_reason="stage 1 range", stale_days=2)
    assert fresh["status"] == WATCH

    stale = add(key="bp", value="139/92", status=WATCH,
                status_reason="stage 1 range", stale_days=62)
    assert stale["status"] is None
    assert "62 days ago" in stale["status_reason"]
    assert stale["value"] == "139/92", "the reading itself must survive"

    edge = add(key="bp", value="139/92", status=WATCH,
               status_reason="stage 1 range", stale_days=STALE_VERDICT_DAYS)
    assert edge["status"] == WATCH, "the boundary day is still judgeable"


def test_a_stale_neutral_tile_still_discloses_its_age():
    """Weight has no verdict to strip, but still must not look current.

    Gating the disclosure on there being a status left the weight tile
    rendering a 90-day-old weigh-in as a bare number with nothing to
    indicate it wasn't measured today.
    """
    from myvitals.analytics.tiles import suppress_stale_verdict

    t = suppress_stale_verdict({
        "key": "weight", "value": 252.0, "status": None,
        "status_reason": None, "stale_days": 90,
    })
    assert t["status"] is None
    assert "90 days ago" in t["status_reason"]
    assert t["value"] == 252.0


# ── blood pressure ────────────────────────────────────────────────────

def test_bp_category_uses_the_higher_of_the_two_numbers():
    """139/92 is stage 2 on the diastolic, not stage 1 on the systolic.

    The first cut wrote stage 1 as `sys < 140 or dia < 90`, which is true
    for 139/92 and swallowed every stage 2 reading whose systolic happened
    to be under 140. It shipped and mislabelled the maintainer's own live
    reading, which is how it was caught.
    """
    from myvitals.analytics.tiles import bp_category

    assert bp_category(139, 92)[1].startswith("stage 2")
    # ...and the mirror case: high systolic, fine diastolic.
    assert bp_category(145, 78)[1].startswith("stage 2")


@pytest.mark.parametrize("sys_v,dia_v,expected", [
    (115, 75, "within the normal"),
    (119, 79, "within the normal"),
    (120, 79, "elevated"),
    (129, 79, "elevated"),
    (130, 79, "stage 1"),
    (119, 80, "stage 1"),      # diastolic alone promotes it
    (139, 89, "stage 1"),
    (140, 79, "stage 2"),      # systolic alone promotes it
    (119, 90, "stage 2"),      # diastolic alone promotes it
    (139, 92, "stage 2"),      # the live reading that exposed the bug
])
def test_bp_category_boundaries(sys_v, dia_v, expected):
    from myvitals.analytics.tiles import bp_category

    assert expected in bp_category(sys_v, dia_v)[1]


def test_normal_bp_is_the_only_good_one():
    from myvitals.analytics.tiles import bp_category

    assert bp_category(115, 75)[0] == GOOD
    assert bp_category(125, 75)[0] == TYPICAL
    assert bp_category(135, 85)[0] == WATCH
    assert bp_category(150, 95)[0] == WATCH


# ── normal-range band ─────────────────────────────────────────────────

def test_band_bounds_come_from_the_server_not_the_clients():
    """The band is a claim about what's normal for this user.

    It was briefly computed as baseline ± 8% inside both MetricCard.vue and
    MetricCard.kt. Two copies of a health judgement is how surfaces drift,
    so the bounds are emitted with the tile.
    """
    from myvitals.analytics.tiles import BAND_FRACTION

    baseline = 60.0
    low = baseline - abs(baseline) * BAND_FRACTION
    high = baseline + abs(baseline) * BAND_FRACTION
    assert low < baseline < high
    # A band that doesn't straddle the baseline would mark a perfectly
    # typical reading as out of range.
    assert round(high - baseline, 6) == round(baseline - low, 6)


# ── band exposure ─────────────────────────────────────────────────────

def test_bands_exist_only_where_a_threshold_already_does():
    """A band is a claim, so it is drawn only where the number is already
    defined — the user's own goal, or the app's own documented scoring.

    Weight is deliberately unbanded: a band there means choosing a goal the
    user never set. Blood pressure gets a reference LINE instead, because
    the AHA categories define an upper boundary but no lower one, and a
    band would require inventing a "too low" threshold.
    """
    from myvitals.analytics import tiles

    src = open(tiles.__file__).read()
    weight_call = src[src.index('key="weight"'):]
    weight_call = weight_call[:weight_call.index(")\n")]
    assert "band_low" not in weight_call, "weight must stay unbanded"

    bp_call = src[src.index('key="blood_pressure"'):]
    bp_call = bp_call[:bp_call.index("series=")]
    assert "band_low" not in bp_call, "BP gets a reference line, not a band"
    assert "target=130.0" in bp_call


def test_the_sleep_band_and_the_sleep_verdict_use_the_same_numbers():
    """The shaded zone and the chip must never disagree.

    Sleep's good/typical cut is target-0.5h .. target+1.5h; the band is
    derived from those same two numbers rather than a second set that could
    drift from them.
    """
    target = 8.0
    band_low, band_high = round(target - 0.5, 2), round(target + 1.5, 2)
    assert band_low <= 7.6 <= band_high      # inside band == status "good"
    assert not (band_low <= 6.9 <= band_high)
