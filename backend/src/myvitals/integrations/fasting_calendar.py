"""Religious-calendar fasting dates.

Static 5-year tables for the major traditions; the scheduled tick
consults these when profile.extra.fasting_prefs.religious_calendar
is set. Sunrise / sunset are approximated to local 5:00 / 19:00 —
solar-aware lookups would require lat/long + a fairly heavy
ephemeris dep; the simplification is documented for the user.

Ramadan dates from the Umm al-Qura calendar (Saudi standard);
Yom Kippur dates from the Hebrew calendar. Lent is omitted because
the tradition is abstinence-based, not a single fasting window.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

# 1st of Ramadan → last day (inclusive). The fast is sunrise-to-sunset
# each day in this range.
RAMADAN_RANGES: list[tuple[date, date]] = [
    (date(2026, 2, 17), date(2026, 3, 19)),
    (date(2027, 2, 6),  date(2027, 3, 8)),
    (date(2028, 1, 26), date(2028, 2, 24)),
    (date(2029, 1, 14), date(2029, 2, 13)),
    (date(2030, 1, 4),  date(2030, 2, 2)),
]

# Yom Kippur — single ~25h fast each year. Begins at sundown the
# preceding day and ends at nightfall on the named day.
YOM_KIPPUR_DATES: list[date] = [
    date(2026, 9, 21),
    date(2027, 10, 11),
    date(2028, 9, 30),
    date(2029, 9, 19),
    date(2030, 10, 7),
]

# Local-clock approximations for Ramadan dawn / dusk. Real practice
# follows the user's lat/long; this is a reasonable default for
# temperate latitudes that the user can override by starting fasts
# manually if precision matters.
RAMADAN_DAWN_H = 5.0
RAMADAN_DUSK_H = 19.0

# Yom Kippur window in local hours, anchored to the prior calendar
# day. Sundown approx 19:30 the night before → nightfall ~20:30 day-of.
YK_START_HOUR = 19.5  # preceding day, local
YK_DURATION_H = 25.0


def is_ramadan_day(d: date) -> bool:
    return any(start <= d <= end for start, end in RAMADAN_RANGES)


def is_yom_kippur_window(now_utc: datetime, tz: ZoneInfo) -> tuple[bool, datetime | None]:
    """Returns (in_window, start_utc_if_in_window).

    The window straddles two calendar days locally; the "name" date in
    YOM_KIPPUR_DATES is the day the fast *ends* on, with the start
    19:30 the prior evening.
    """
    now_local = now_utc.astimezone(tz)
    today = now_local.date()
    yesterday = today - timedelta(days=1)
    candidates: list[date] = []
    if today in YOM_KIPPUR_DATES:
        candidates.append(today)
    if (today + timedelta(days=1)) in YOM_KIPPUR_DATES:
        # Pre-fast evening — start window opens at 19:30 today.
        candidates.append(today + timedelta(days=1))
    if yesterday in YOM_KIPPUR_DATES:
        # The fast set started yesterday — still inside the 25h window.
        candidates.append(yesterday)
    for end_day in candidates:
        start_local = datetime.combine(
            end_day - timedelta(days=1),
            time(int(YK_START_HOUR), int((YK_START_HOUR % 1) * 60)),
            tzinfo=tz,
        )
        end_local = start_local + timedelta(hours=YK_DURATION_H)
        if start_local <= now_local <= end_local:
            return True, start_local.astimezone(timezone.utc)
    return False, None


def ramadan_today_window(
    now_utc: datetime, tz: ZoneInfo,
) -> tuple[bool, datetime | None, datetime | None]:
    """If today is a Ramadan day in `tz`, returns
    (True, dawn_utc, dusk_utc); else (False, None, None)."""
    now_local = now_utc.astimezone(tz)
    if not is_ramadan_day(now_local.date()):
        return False, None, None
    dawn_local = datetime.combine(
        now_local.date(),
        time(int(RAMADAN_DAWN_H), int((RAMADAN_DAWN_H % 1) * 60)),
        tzinfo=tz,
    )
    dusk_local = datetime.combine(
        now_local.date(),
        time(int(RAMADAN_DUSK_H), int((RAMADAN_DUSK_H % 1) * 60)),
        tzinfo=tz,
    )
    return True, dawn_local.astimezone(timezone.utc), dusk_local.astimezone(timezone.utc)
