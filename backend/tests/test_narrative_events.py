"""Narrative event cards: nap classification and stage-overlap clamping.

Both rules fail silently. A misclassified session shows the user "we
tracked a nap" about their night's sleep, and unclamped stage rows report
a longer sleep than actually happened — neither raises anything.
"""
from datetime import datetime, timedelta, timezone

import pytest

from myvitals.analytics.events import (
    NAP_MAX_SECONDS,
    _fmt_clock,
    _fmt_duration,
    clamp_stage_durations,
    classify_session,
)

CENTRAL = timezone(timedelta(hours=-5))


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 10, hour, minute, tzinfo=CENTRAL)


# ── nap vs night ──────────────────────────────────────────────────────

def test_a_short_afternoon_session_is_a_nap():
    # The real reading that motivated this: 12:45 PM local, 52 minutes.
    assert classify_session(at(12, 45), 52 * 60, is_longest_of_day=False) == "nap"


def test_a_full_night_is_never_a_nap():
    assert classify_session(at(22, 30), 8 * 3600, is_longest_of_day=True) == "sleep"


def test_an_early_morning_session_is_not_a_nap_even_if_short():
    """3am for 90 minutes is a fragmented night, not a nap.

    Duration alone would call this a nap and tell the user they napped at
    3am, which is both wrong and faintly insulting.
    """
    assert classify_session(at(3, 0), 90 * 60, is_longest_of_day=False) == "sleep"


def test_the_days_longest_session_is_always_the_night():
    """A badly-slept 2-hour night is still the night.

    If the user only managed 2 hours starting at noon, calling it a nap
    would leave the day with no sleep recorded at all.
    """
    assert classify_session(at(12, 0), 2 * 3600, is_longest_of_day=True) == "sleep"


@pytest.mark.parametrize("hour,expected", [
    (5, "sleep"),    # pre-dawn — night
    (6, "nap"),      # boundary: waking hours begin
    (19, "nap"),
    (20, "sleep"),   # boundary: evening reads as night
])
def test_nap_window_boundaries(hour, expected):
    assert classify_session(at(hour), 40 * 60, is_longest_of_day=False) == expected


def test_a_session_at_the_duration_threshold_is_a_night():
    assert classify_session(
        at(13), NAP_MAX_SECONDS, is_longest_of_day=False,
    ) == "sleep"


# ── stage overlap clamping ────────────────────────────────────────────

def test_overlapping_stage_rows_do_not_inflate_the_total():
    """sleep_stages has no source column, so re-imports leave overlaps.

    Two rows each claiming 30 minutes but starting 10 minutes apart
    describe 40 minutes of sleep, not 60.
    """
    base = at(12, 45).astimezone(timezone.utc)
    rows = [
        (base, "light", 1800),
        (base + timedelta(minutes=10), "deep", 1800),
    ]
    end = base + timedelta(minutes=40)
    segs = clamp_stage_durations(rows, end)
    assert sum(s["duration_s"] for s in segs) == 40 * 60
    assert segs[0]["duration_s"] == 600      # truncated by the next start
    assert segs[1]["duration_s"] == 1800     # runs to session end


def test_the_last_stage_is_clamped_to_the_session_end():
    base = at(12, 45).astimezone(timezone.utc)
    rows = [(base, "light", 99999)]
    segs = clamp_stage_durations(rows, base + timedelta(minutes=48))
    assert segs[0]["duration_s"] == 48 * 60


def test_a_single_synthetic_light_stage_survives():
    """The phone emits one 'light' stage spanning the session when Health
    Connect ships no breakdown. That is valid data, not an error."""
    base = at(12, 45).astimezone(timezone.utc)
    segs = clamp_stage_durations(
        [(base, "light", 2880)], base + timedelta(seconds=2880),
    )
    assert len(segs) == 1
    assert segs[0]["stage"] == "light"


def test_zero_length_rows_are_dropped_not_rendered():
    base = at(12, 45).astimezone(timezone.utc)
    rows = [(base, "light", 0), (base, "deep", 600)]
    segs = clamp_stage_durations(rows, base + timedelta(minutes=10))
    assert all(s["duration_s"] > 0 for s in segs)


def test_rows_arriving_out_of_order_are_sorted_before_clamping():
    base = at(12, 45).astimezone(timezone.utc)
    rows = [
        (base + timedelta(minutes=10), "deep", 600),
        (base, "light", 600),
    ]
    segs = clamp_stage_durations(rows, base + timedelta(minutes=20))
    assert [s["stage"] for s in segs] == ["light", "deep"]


# ── copy ──────────────────────────────────────────────────────────────

def test_clock_has_no_leading_zero():
    # "at 09:05 AM" reads like a timestamp; the reference says "9:05 AM".
    assert _fmt_clock(at(9, 5)) == "9:05 AM"
    assert _fmt_clock(at(12, 45)) == "12:45 PM"


@pytest.mark.parametrize("secs,expected", [
    (48 * 60, "48 min"),
    (3600, "1 hr"),
    (7 * 3600 + 20 * 60, "7 hr 20 min"),
])
def test_duration_phrasing(secs, expected):
    assert _fmt_duration(secs) == expected
