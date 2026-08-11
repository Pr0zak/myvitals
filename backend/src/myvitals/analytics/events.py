"""Narrative event cards — "We tracked a nap", with its hypnogram.

Plain-language cards for what happened today, modelled on the reference's
sleep cards. Deterministic and free: NO LLM. The project has an opt-in
Claude layer, but a home-screen feed that bills per view is the wrong
place for it — statistical detection feeds the glanceable surfaces and
Claude only narrates pre-aggregated facts on demand.

Three things here are easy to get wrong and are handled deliberately:

  * **Local clock time.** "at 12:45 PM for 48 min" is a claim about the
    user's clock, and the CT runs TZ=UTC. Both the day boundary and the
    displayed hour resolve in `settings.tz`. This trap has shipped three
    times in this repo already.

  * **Overlapping stage rows.** `sleep_stages` is keyed (time, stage) with
    no source column, so importers can leave near-duplicate rows whose
    `duration_s` values overlap. Summing them raw inflates a night. Every
    duration is clamped to the gap before the next stage starts.

  * **A one-stage hypnogram is legitimate.** The phone's DataMapper emits
    a single synthetic `light` stage spanning the whole session when
    Health Connect ships no breakdown, so a valid nap can be one flat bar.
    That is data, not an error, and renders as-is.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import models

# Below this a sleep session is a nap candidate rather than a night.
NAP_MAX_SECONDS = 3 * 3600

# Local clock hours during which a session start reads as a daytime nap.
NAP_START_HOUR_MIN = 6
NAP_START_HOUR_MAX = 20

# Hard cap so a bad import can't turn the home screen into a wall of cards.
MAX_EVENTS = 12

STAGE_ORDER = ["awake", "rem", "light", "deep"]


def _fmt_clock(dt_local: datetime) -> str:
    """"12:45 PM" — no leading zero, matching the reference's phrasing."""
    return dt_local.strftime("%I:%M %p").lstrip("0")


def _fmt_duration(seconds: int) -> str:
    mins = int(round(seconds / 60))
    if mins < 60:
        return f"{mins} min"
    h, m = divmod(mins, 60)
    return f"{h} hr" if m == 0 else f"{h} hr {m} min"


def clamp_stage_durations(
    rows: list[tuple[datetime, str, int]], session_end: datetime,
) -> list[dict[str, Any]]:
    """Stage rows with each duration clamped to the next row's start.

    `sleep_stages` rows can overlap — the table has no source column and a
    re-import can leave near-duplicates. Trusting `duration_s` verbatim
    double-counts the overlap and reports a longer sleep than happened.
    Every other reader in this codebase clamps; so does this.
    """
    ordered = sorted(rows, key=lambda r: r[0])
    out: list[dict[str, Any]] = []
    for i, (start, stage, dur) in enumerate(ordered):
        boundary = ordered[i + 1][0] if i + 1 < len(ordered) else session_end
        available = int((boundary - start).total_seconds())
        clamped = max(0, min(int(dur or 0), max(0, available)))
        if clamped == 0:
            continue
        out.append({
            "start": start.isoformat(),
            "stage": (stage or "").lower(),
            "duration_s": clamped,
        })
    return out


def classify_session(start_local: datetime, duration_s: int) -> str:
    """`nap` or `sleep`, from duration and local start hour.

    Duration alone is not enough — a fragmented 90-minute night is still a
    night — so a session is a nap only when it is BOTH short and started
    during waking hours. The start-hour test is what protects the broken
    night: it begins at 3 AM, outside the nap window.

    An earlier version also forced the day's LONGEST session to be a night,
    meaning to protect a badly-slept short night. Live data showed that
    backfiring immediately: on a day whose only recorded sleep was 52
    minutes at 12:45 PM, the card read "Sleep tracked · you slept 52 min",
    asserting that lunchtime nap was the user's night. If the only sleep on
    record is a midday nap, the truthful reading is that the night is
    missing — not that the nap was it.
    """
    if duration_s >= NAP_MAX_SECONDS:
        return "sleep"
    if NAP_START_HOUR_MIN <= start_local.hour < NAP_START_HOUR_MAX:
        return "nap"
    return "sleep"


async def day_events(
    db: AsyncSession, day: date, tzinfo: Any,
) -> list[dict[str, Any]]:
    """Narrative cards for `day`, resolved in the user's timezone.

    `day` must already be the user's local day — see the local_tz block in
    api/summary.py.
    """
    day_start = datetime.combine(day, time.min, tzinfo=tzinfo)
    day_end = datetime.combine(day, time.max, tzinfo=tzinfo)
    # A night that ENDS today started yesterday evening, so the window
    # reaches back; without this the main sleep card never appears.
    window_start = day_start - timedelta(hours=18)

    sessions = (await db.execute(
        select(models.SleepSession)
        .where(models.SleepSession.end_at >= window_start)
        .where(models.SleepSession.start_at <= day_end)
        .order_by(models.SleepSession.start_at)
    )).scalars().all()

    if not sessions:
        return []

    events: list[dict[str, Any]] = []
    for s in sessions:
        duration_s = int((s.end_at - s.start_at).total_seconds())
        if duration_s <= 0:
            continue
        start_local = s.start_at.astimezone(tzinfo)
        kind = classify_session(start_local, duration_s)

        stage_rows = (await db.execute(
            select(
                models.SleepStage.time,
                models.SleepStage.stage,
                models.SleepStage.duration_s,
            )
            .where(models.SleepStage.time >= s.start_at)
            .where(models.SleepStage.time < s.end_at)
        )).all()
        segments = clamp_stage_durations(
            [(t, st, d) for t, st, d in stage_rows], s.end_at,
        )

        totals: dict[str, int] = {}
        for seg in segments:
            totals[seg["stage"]] = totals.get(seg["stage"], 0) + seg["duration_s"]
        stages = [
            {"stage": k, "duration_s": totals[k]}
            for k in STAGE_ORDER if k in totals
        ] + [
            {"stage": k, "duration_s": v}
            for k, v in sorted(totals.items()) if k not in STAGE_ORDER
        ]

        clock = _fmt_clock(start_local)
        dur_text = _fmt_duration(duration_s)
        if kind == "nap":
            headline = "We tracked a nap"
            detail = f"It looks like you took a nap at {clock} for {dur_text}"
        else:
            headline = "Sleep tracked"
            detail = f"You slept {dur_text}, starting at {clock}"

        events.append({
            "id": f"sleep:{s.start_at.isoformat()}",
            "kind": kind,
            "headline": headline,
            "detail": detail,
            "start": s.start_at.isoformat(),
            "end": s.end_at.isoformat(),
            "duration_s": duration_s,
            "title": s.title,
            "stages": stages,
            "segments": segments,
        })

    # Newest first, then capped — a bad import shouldn't fill the screen.
    events.sort(key=lambda e: e["start"], reverse=True)
    return events[:MAX_EVENTS]
