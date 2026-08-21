"""Training streaks and true frequency (CONS-1).

The version this replaces lived inline in ``api/strava.py:activities_stats``
and had three defects, each of which quietly reported a number lower or
higher than the truth:

1. **The streak was computed from the displayed window.** ``active_days``
   was built from rows already filtered to the last ``days``, so a streak
   that began before the window boundary was truncated at it. Switching
   the page from "last 30 days" to "last 7 days" changed the length of a
   streak that had not changed at all.

2. **The anchor was the UTC date.** ``d = datetime.now(timezone.utc).date()``
   rolls at 7pm Central, so for five hours every evening the walk-back
   started from tomorrow — a day with no activity yet — and reported a
   streak of zero to a user in the middle of one.

3. **Activity dates were UTC dates.** ``a.start_at.date()`` on a 20:00
   Central workout yields the *following* calendar day. A person training
   at the same time every evening produced a set of active days each
   shifted forward by one, which is invisible in aggregate but creates
   phantom gaps whenever a session lands either side of the boundary.

Frequency had a subtler problem: deriving sessions-per-week as
``count / range_days * 7`` makes the number move when the user changes
the date picker, which is not a property of their training. Here it is
always measured over a fixed trailing window.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Streaks:
    """Consecutive-day training streaks, measured over full history."""

    current_days: int
    longest_days: int
    current_start: date | None
    longest_start: date | None
    longest_end: date | None
    last_active: date | None
    #: True when the current streak is being carried by yesterday because
    #: today has not been trained yet. Lets a client say "keep it alive"
    #: rather than implying the day is already banked.
    today_pending: bool


def compute_streaks(active_days: Iterable[date], today: date) -> Streaks:
    """Current and longest consecutive-day streaks.

    ``active_days`` must be LOCAL dates and should be the user's whole
    history, not a display window — see the module docstring.

    A day that has not ended does not break a streak. If today has no
    session but yesterday does, the streak is reported as still running
    with ``today_pending=True``. The alternative — resetting to zero at
    midnight and only reappearing once the user trains — shows a broken
    streak to someone who has not broken it, every single morning.
    """
    days = set(active_days)
    if not days:
        return Streaks(0, 0, None, None, None, None, False)

    last_active = max(days)

    # ── current ──────────────────────────────────────────────────────
    # Anchor on today if trained, else yesterday (the day is not over).
    # Anything older means the streak has genuinely lapsed.
    if today in days:
        anchor, pending = today, False
    elif (today - timedelta(days=1)) in days:
        anchor, pending = today - timedelta(days=1), True
    else:
        anchor, pending = None, False

    current = 0
    current_start: date | None = None
    if anchor is not None:
        d = anchor
        while d in days:
            current += 1
            current_start = d
            d -= timedelta(days=1)

    # ── longest ──────────────────────────────────────────────────────
    # One pass over sorted days; a run continues while each date is
    # exactly one day after the last.
    longest = 0
    longest_start: date | None = None
    longest_end: date | None = None
    run = 0
    run_start: date | None = None
    prev: date | None = None
    for d in sorted(days):
        if prev is not None and d - prev == timedelta(days=1):
            run += 1
        else:
            run = 1
            run_start = d
        if run > longest:
            longest = run
            longest_start = run_start
            longest_end = d
        prev = d

    return Streaks(
        current_days=current,
        longest_days=longest,
        current_start=current_start,
        longest_start=longest_start,
        longest_end=longest_end,
        last_active=last_active,
        today_pending=pending,
    )


def sessions_per_week(
    active_days: Iterable[date], today: date, window_days: int = 28,
) -> float:
    """Sessions per week over a FIXED trailing window.

    Fixed on purpose. Deriving this from whatever range the user has
    selected means the headline "3.2 sessions/week" changes when they
    switch the picker from 30 days to 90, which reads as the app
    disagreeing with itself about something it should simply know.

    28 days rather than 7: a single missed session swings a 7-day figure
    by a whole session per week, so the number would be dominated by
    which day of the week you happened to look at it.
    """
    if window_days <= 0:
        return 0.0
    since = today - timedelta(days=window_days - 1)
    n = sum(1 for d in set(active_days) if since <= d <= today)
    return round(n / window_days * 7.0, 2)


def count_in_window(
    active_days: Iterable[date], today: date, window_days: int,
) -> int:
    """Active days within a trailing window, inclusive of today."""
    since = today - timedelta(days=window_days - 1)
    return sum(1 for d in set(active_days) if since <= d <= today)
