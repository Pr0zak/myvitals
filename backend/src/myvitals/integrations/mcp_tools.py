"""Read-only MCP tools over the existing bounded payload builders (MCP-1).

## Why this exists

Every AI surface in this app bills the app's own Anthropic key. This
publishes the *same* aggregates as MCP tools so the user's own Claude
subscription can read their health data directly — no chat UI to build,
no agent loop to supervise, no daily-quota risk, and no second copy of
the aggregation logic to keep in step with the first.

## Why it is read-only, permanently

There is no write path here and there should not be one. The value is
"let a model read my data"; the risk of a model *writing* to a health
record it partly misunderstands is not worth any convenience it buys. The
tools below map onto SELECT queries only, and `test_mcp_server.py` asserts
that no tool name suggests mutation.

## Privacy

These reuse the payload builders that `test_ai_privacy.py` already locks
down, so the two leaks that test exists to prevent — the user's real name
(which can live in the sober `addiction` column) and Strava activity
titles (which routinely embed home and workplace locations) — cannot
reappear here without failing that test.

The one place this module goes beyond those builders is activities, so
that tool omits `name` explicitly rather than relying on inheritance.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..analytics import compare as compare_mod
from ..analytics import consistency as consistency_mod
from ..config import settings
from ..db import models

ToolFn = Callable[[AsyncSession, dict[str, Any]], Awaitable[Any]]


def _local_today() -> date:
    """Today in the user's timezone. Same rule as everywhere else here."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(settings.tz) if settings.tz != "UTC" else timezone.utc
    except Exception:
        tz = timezone.utc
    return datetime.now(tz).date()


def _clamp_days(raw: Any, default: int, maximum: int) -> int:
    """Bound a caller-supplied window.

    An MCP client is a language model deciding its own arguments, so
    `days` will occasionally arrive as 100000. Clamping rather than
    erroring keeps a reasonable question answerable instead of failing on
    an implementation detail the model cannot see.
    """
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(maximum, n))


# ── tools ────────────────────────────────────────────────────────────

async def _daily_summary(db: AsyncSession, args: dict[str, Any]) -> Any:
    days = _clamp_days(args.get("days"), 30, 365)
    since = _local_today() - timedelta(days=days - 1)
    rows = (await db.execute(
        select(models.DailySummary)
        .where(models.DailySummary.date >= since)
        .order_by(models.DailySummary.date)
    )).scalars().all()
    return [
        {
            "date": str(r.date),
            "resting_hr": r.resting_hr,
            "hrv_ms": r.hrv_avg,
            "recovery": r.recovery_score,
            "readiness": r.readiness_score,
            "sleep_h": round(r.sleep_duration_s / 3600.0, 2) if r.sleep_duration_s else None,
            "sleep_score": r.sleep_score,
            "steps": r.steps_total,
            "weight_kg": r.weight_kg,
            "ctl": r.ctl, "atl": r.atl, "tsb": r.tsb,
        }
        for r in rows
    ]


async def _compare_periods(db: AsyncSession, args: dict[str, Any]) -> Any:
    days = _clamp_days(args.get("days"), 7, 365)
    vs = args.get("vs") if args.get("vs") in ("previous", "last_year") else "previous"
    end = _local_today()
    since = end - timedelta(days=days - 1)
    base_since, base_end = compare_mod.baseline_window(since, end, vs)

    rows = (await db.execute(
        select(models.DailySummary)
        .where(models.DailySummary.date >= base_since)
        .where(models.DailySummary.date <= end)
        .order_by(models.DailySummary.date)
    )).scalars().all()

    def shape(subset):
        return [
            {
                "date": str(r.date), "rhr": r.resting_hr, "hrv": r.hrv_avg,
                "recovery": r.recovery_score, "readiness": r.readiness_score,
                "sleep_h": (r.sleep_duration_s / 3600.0) if r.sleep_duration_s else None,
                "sleep_score": r.sleep_score,
                "sleep_consistency": r.sleep_consistency_score,
                "sleep_debt_h": r.sleep_debt_h, "steps": r.steps_total,
                "tsb": r.tsb, "ctl": r.ctl, "atl": r.atl,
                "weight_kg": r.weight_kg, "body_fat_pct": r.body_fat_pct,
            }
            for r in subset
        ]

    return {
        "current": {"since": since.isoformat(), "until": end.isoformat()},
        "baseline": {"since": base_since.isoformat(), "until": base_end.isoformat()},
        "metrics": compare_mod.compare_windows(
            shape([r for r in rows if since <= r.date <= end]),
            shape([r for r in rows if base_since <= r.date <= base_end]),
            window_days=days,
        ),
    }


async def _sleep(db: AsyncSession, args: dict[str, Any]) -> Any:
    days = _clamp_days(args.get("days"), 14, 180)
    since = _local_today() - timedelta(days=days - 1)
    rows = (await db.execute(
        select(models.DailySummary)
        .where(models.DailySummary.date >= since)
        .where(models.DailySummary.sleep_duration_s.is_not(None))
        .order_by(models.DailySummary.date)
    )).scalars().all()
    return [
        {
            "date": str(r.date),
            "hours": round(r.sleep_duration_s / 3600.0, 2),
            "score": r.sleep_score,
            "consistency": r.sleep_consistency_score,
            "debt_h": r.sleep_debt_h,
        }
        for r in rows
    ]


async def _activities(db: AsyncSession, args: dict[str, Any]) -> Any:
    """Recent cardio activities.

    `name` is deliberately omitted. Strava titles routinely embed home,
    workplace and gym locations ("Morning ride from <street>"), which is
    exactly what `test_ai_privacy.py` exists to keep out of a model's
    context. Type, duration and distance answer every training question
    the title would, without the address.
    """
    days = _clamp_days(args.get("days"), 30, 365)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await db.execute(
        select(models.Activity)
        .where(models.Activity.start_at >= since)
        .order_by(models.Activity.start_at.desc())
        .limit(200)
    )).scalars().all()
    return [
        {
            "date": a.start_at.date().isoformat(),
            "type": a.type,
            "duration_s": a.duration_s,
            "distance_m": a.distance_m,
            "elevation_gain_m": a.elevation_gain_m,
            "avg_hr": a.avg_hr,
            "kcal": a.kcal,
        }
        for a in rows
    ]


async def _strength_sessions(db: AsyncSession, args: dict[str, Any]) -> Any:
    days = _clamp_days(args.get("days"), 30, 365)
    since = _local_today() - timedelta(days=days - 1)
    rows = (await db.execute(
        select(models.StrengthWorkout)
        .where(models.StrengthWorkout.date >= since)
        .where(models.StrengthWorkout.status != "regenerated")
        .order_by(models.StrengthWorkout.date.desc())
    )).scalars().all()
    return [
        {
            "date": w.date.isoformat(),
            "status": w.status,
            "focus": w.split_focus,
        }
        for w in rows
    ]


async def _consistency(db: AsyncSession, args: dict[str, Any]) -> Any:
    today = _local_today()
    act = (await db.execute(select(models.Activity.start_at))).scalars().all()
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(settings.tz) if settings.tz != "UTC" else timezone.utc
    except Exception:
        tz = timezone.utc
    act_days = {
        (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(tz).date()
        for t in act
    }
    lift_days = set((await db.execute(
        select(models.StrengthWorkout.date)
        .where(models.StrengthWorkout.status == "completed")
    )).scalars().all())

    def block(days_set):
        s = consistency_mod.compute_streaks(days_set, today)
        return {
            "current_streak_days": s.current_days,
            "longest_streak_days": s.longest_days,
            "longest_streak_end": s.longest_end.isoformat() if s.longest_end else None,
            "last_active": s.last_active.isoformat() if s.last_active else None,
            "sessions_per_week": consistency_mod.sessions_per_week(days_set, today, 28),
            "sessions_last_28d": consistency_mod.count_in_window(days_set, today, 28),
        }

    return {"cardio": block(act_days), "strength": block(lift_days)}


async def _muscle_volume(db: AsyncSession, args: dict[str, Any]) -> Any:
    from ..analytics import strength as strength_algo
    days = _clamp_days(args.get("days"), 7, 90)
    return await strength_algo.weekly_muscle_volume(db, days=days)


async def _goals(db: AsyncSession, args: dict[str, Any]) -> Any:
    rows = (await db.execute(
        select(models.AiGoal).where(models.AiGoal.ended_at.is_(None))
    )).scalars().all()
    return [
        {
            "kind": g.kind,
            "title": g.title,
            "target_value": g.target_value,
            "target_unit": g.target_unit,
            "started_at": g.started_at.isoformat() if g.started_at else None,
        }
        for g in rows
    ]


def _days_schema(default: int, maximum: int, what: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": (
                    f"Trailing window in days (default {default}, "
                    f"clamped to {maximum})."
                ),
                "minimum": 1,
                "maximum": maximum,
            },
        },
        "additionalProperties": False,
        "description": what,
    }


#: name → (description, input schema, handler). Read-only, all of them.
TOOLS: dict[str, tuple[str, dict[str, Any], ToolFn]] = {
    "get_daily_summary": (
        "Daily health summary rows: resting HR, HRV, recovery, readiness, "
        "sleep hours and score, steps, weight, and training load (CTL/ATL/TSB).",
        _days_schema(30, 365, "Daily summary rows."),
        _daily_summary,
    ),
    "compare_periods": (
        "Period-over-period comparison of every daily metric. Returns mean, "
        "delta, percent change, and a direction that already accounts for "
        "whether higher or lower is better for each metric. Also reports how "
        "many days of each window actually had data.",
        {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "minimum": 1, "maximum": 365,
                         "description": "Window length (default 7)."},
                "vs": {"type": "string", "enum": ["previous", "last_year"],
                       "description": "Baseline: the preceding block, or the "
                                      "same window shifted back 364 days."},
            },
            "additionalProperties": False,
        },
        _compare_periods,
    ),
    "get_sleep": (
        "Per-night sleep: duration, score, consistency and accumulated debt.",
        _days_schema(14, 180, "Sleep nights."),
        _sleep,
    ),
    "get_activities": (
        "Cardio activities: type, duration, distance, elevation, average HR "
        "and calories. Titles are omitted deliberately — they embed locations.",
        _days_schema(30, 365, "Cardio activities."),
        _activities,
    ),
    "get_strength_sessions": (
        "Strength training sessions with their date, status and split focus.",
        _days_schema(30, 365, "Strength sessions."),
        _strength_sessions,
    ),
    "get_consistency": (
        "Training streaks and true frequency for both cardio and strength, "
        "computed over full history in the user's local timezone.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        _consistency,
    ),
    "get_muscle_volume": (
        "Weekly working-set volume per muscle group against research-backed "
        "MEV/MAV targets.",
        _days_schema(7, 90, "Muscle volume audit."),
        _muscle_volume,
    ),
    "get_goals": (
        "Active health goals with their targets.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        _goals,
    ),
}


def tool_list() -> list[dict[str, Any]]:
    """The `tools/list` payload."""
    return [
        {
            "name": name,
            "description": desc,
            "inputSchema": schema,
            # Advertised so a client can reason about safety without
            # calling anything. Every tool here is a SELECT.
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
        }
        for name, (desc, schema, _fn) in TOOLS.items()
    ]


async def call_tool(
    db: AsyncSession, name: str, arguments: dict[str, Any] | None,
) -> Any:
    entry = TOOLS.get(name)
    if entry is None:
        raise KeyError(name)
    return await entry[2](db, arguments or {})
