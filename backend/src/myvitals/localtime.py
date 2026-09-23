"""The user's calendar day, in one place.

A user-facing "today" is the LOCAL day, never the UTC one. The container runs
TZ=UTC while the user is on Central time, so the UTC date rolls over at 7pm
CDT and anything deriving a calendar day from UTC starts answering for
tomorrow every evening. That has shipped at least six times, and each time the
code involved had its own private copy of the timezone lookup — eleven of
them at the last count — so the next endpoint written from scratch reached for
`datetime.now(timezone.utc).date()` because nothing shared was closer to hand.

New code imports from here. The older private copies behave identically and
are being folded in as their modules are touched (UX-D11).
"""
from __future__ import annotations

from datetime import date, datetime, timezone, tzinfo

from .config import settings


def local_tz() -> tzinfo:
    """The user's timezone, falling back to UTC when it will not resolve."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(settings.tz) if settings.tz != "UTC" else timezone.utc
    except Exception:
        return timezone.utc


def local_today() -> date:
    """Today's date where the user is."""
    return datetime.now(local_tz()).date()


def local_date(ts: datetime) -> date:
    """The user's calendar day that an instant falls on.

    A naive timestamp is treated as UTC, which is how every timestamp column
    in this schema is written.
    """
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(local_tz()).date()


def local_midnight(day: date) -> datetime:
    """The instant the user's day begins, as an aware datetime."""
    return datetime.combine(day, datetime.min.time(), tzinfo=local_tz())
