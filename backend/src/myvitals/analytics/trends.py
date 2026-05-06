"""Trend-badge engine — pure stats, no LLM.

Computes a small set of structured signals from daily_summary that the
dashboard surfaces as chips on Today. Cheap (one DB query + numpy-style
list math), deterministic, runs every page load.

Each badge has:
- key      : machine identifier
- label    : metric the badge is about (e.g. "Recovery")
- value    : the numeric headline (e.g. "+8")
- subtitle : one short phrase ("3-day decline")
- tone     : "good" | "warn" | "bad" | "neutral" — drives color
- direction: "up" | "down" | "flat" | "spike" | "streak" — drives icon
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import models


@dataclass
class TrendBadge:
    key: str
    label: str
    value: str
    subtitle: str
    tone: str        # good | warn | bad | neutral
    direction: str   # up | down | flat | spike | streak

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# Metric → (column, "lower-is-better"?, unit)
_METRICS: dict[str, tuple[str, bool, str]] = {
    "recovery_score": ("recovery", False, ""),
    "hrv_avg": ("HRV", False, " ms"),
    "resting_hr": ("RHR", True, " bpm"),
    "sleep_duration_s": ("Sleep", False, "h"),
    "sleep_score": ("Sleep score", False, ""),
    "readiness_score": ("Readiness", False, ""),
    "steps_total": ("Steps", False, ""),
}


def _slope(xs: list[float]) -> float:
    """Linear OLS slope on equally-spaced points (1 unit = 1 day)."""
    n = len(xs)
    if n < 2:
        return 0.0
    mx = (n - 1) / 2
    my = sum(xs) / n
    num = sum((i - mx) * (v - my) for i, v in enumerate(xs))
    den = sum((i - mx) ** 2 for i in range(n))
    return 0.0 if den == 0 else num / den


def _trend_badge_for(
    metric: str, recent: list[float], baseline: list[float],
) -> TrendBadge | None:
    """One badge per metric — picks the most striking signal among
    delta/slope/anomaly/streak. Returns None if not enough data."""
    label, lower_better, unit = _METRICS[metric]
    if len(recent) < 3:
        return None

    avg7 = sum(recent[-7:]) / min(7, len(recent))
    avg_baseline = sum(baseline) / len(baseline) if baseline else avg7
    delta = avg7 - avg_baseline
    delta_pct = (delta / avg_baseline * 100) if avg_baseline != 0 else 0.0

    slope = _slope(recent[-7:] if len(recent) >= 7 else recent)
    direction = "up" if slope > 0 else "down" if slope < 0 else "flat"

    # tone: lower-is-better metrics flip the polarity
    if abs(delta_pct) < 3:
        tone = "neutral"
    elif (delta > 0) == (not lower_better):
        tone = "good"
    else:
        tone = "warn" if abs(delta_pct) < 10 else "bad"

    # Format value
    if metric == "sleep_duration_s":
        recent_h = avg7 / 3600
        value_str = f"{recent_h:.1f}h"
        subtitle = (
            f"{('+' if delta >= 0 else '')}{delta / 3600:.1f}h vs baseline"
        )
    elif metric == "steps_total":
        value_str = f"{int(round(avg7)):,}"
        subtitle = f"{('+' if delta >= 0 else '')}{int(round(delta)):,} vs baseline"
    elif unit == "":
        value_str = f"{avg7:.0f}"
        subtitle = f"{('+' if delta >= 0 else '')}{delta:.0f} vs baseline"
    else:
        value_str = f"{avg7:.0f}{unit}"
        subtitle = f"{('+' if delta >= 0 else '')}{delta:.0f}{unit} vs baseline"

    # If recent slope is more dramatic than the delta, mention it
    if abs(slope) > abs(delta) / 7 + 1e-6 and abs(slope) > 0.5:
        if metric == "sleep_duration_s":
            subtitle = f"{direction} {slope / 3600:+.1f}h/d trend"
        elif unit == "":
            subtitle = f"{direction} {slope:+.1f}/d trend"
        else:
            subtitle = f"{direction} {slope:+.1f}{unit}/d trend"

    return TrendBadge(
        key=metric,
        label=label,
        value=value_str,
        subtitle=subtitle,
        tone=tone,
        direction=direction,
    )


def _spike_badge(metric: str, recent: list[float], baseline: list[float]) -> TrendBadge | None:
    """Z-score-flavoured anomaly check on the most recent value."""
    if len(baseline) < 7 or len(recent) < 1:
        return None
    label, lower_better, unit = _METRICS[metric]
    mu = sum(baseline) / len(baseline)
    var = sum((x - mu) ** 2 for x in baseline) / max(1, len(baseline) - 1)
    if var <= 0:
        return None
    sigma = var ** 0.5
    last = recent[-1]
    z = (last - mu) / sigma if sigma else 0
    if abs(z) < 1.8:
        return None
    is_bad = (z > 0) == lower_better
    if metric == "sleep_duration_s":
        value_str = f"{last / 3600:.1f}h"
        subtitle = f"{abs(z):.1f}σ {('above' if z > 0 else 'below')} baseline"
    elif unit == "":
        value_str = f"{last:.0f}"
        subtitle = f"{abs(z):.1f}σ {('above' if z > 0 else 'below')} baseline"
    else:
        value_str = f"{last:.0f}{unit}"
        subtitle = f"{abs(z):.1f}σ {('above' if z > 0 else 'below')} baseline"
    return TrendBadge(
        key=f"{metric}_anomaly",
        label=label,
        value=value_str,
        subtitle=subtitle,
        tone="bad" if is_bad else "good",
        direction="spike",
    )


def _streak_badge(metric: str, recent: list[float], threshold: float, label_phrase: str) -> TrendBadge | None:
    """Count trailing days that meet a threshold — surfaces "4 nights ≥ 7h" etc."""
    if not recent:
        return None
    streak = 0
    for v in reversed(recent):
        if v >= threshold:
            streak += 1
        else:
            break
    if streak < 3:
        return None
    return TrendBadge(
        key=f"{metric}_streak",
        label=label_phrase,
        value=f"{streak}d",
        subtitle="active streak",
        tone="good",
        direction="streak",
    )


async def _sober_badge(db: AsyncSession) -> TrendBadge | None:
    active = (await db.execute(
        select(models.SoberStreak)
        .where(models.SoberStreak.end_at.is_(None))
        .limit(1)
    )).scalar_one_or_none()
    if active is None:
        return None
    days = (datetime.now(timezone.utc) - active.start_at).total_seconds() / 86400.0
    return TrendBadge(
        key="sober",
        label="Sober",
        value=f"{int(days)}d",
        subtitle=f"streak active ({active.addiction})",
        tone="good",
        direction="streak",
    )


async def compute_badges(db: AsyncSession, max_badges: int = 5) -> list[dict[str, Any]]:
    """Pulls last 30d of daily_summary; produces a ranked list of trend badges."""
    today = datetime.now(timezone.utc).date()
    since = today - timedelta(days=30)
    rows = (await db.execute(
        select(models.DailySummary)
        .where(models.DailySummary.date >= since)
        .order_by(models.DailySummary.date)
    )).scalars().all()

    by_metric: dict[str, list[float]] = {m: [] for m in _METRICS}
    for r in rows:
        for metric in _METRICS:
            v = getattr(r, metric, None)
            if v is not None:
                by_metric[metric].append(float(v))

    badges: list[TrendBadge] = []

    for metric, series in by_metric.items():
        if len(series) < 7:
            continue
        recent = series[-7:]
        baseline = series[:-7] if len(series) > 7 else series
        spike = _spike_badge(metric, series, baseline)
        if spike is not None:
            badges.append(spike)
        else:
            tb = _trend_badge_for(metric, series, baseline)
            if tb is not None and tb.tone != "neutral":
                badges.append(tb)

    # Streak detections — sleep ≥ 7h
    sleep = by_metric["sleep_duration_s"]
    if sleep:
        sb = _streak_badge("sleep", sleep, 7 * 3600, "Sleep ≥ 7h")
        if sb is not None:
            badges.append(sb)

    # Sober streak
    sob = await _sober_badge(db)
    if sob is not None:
        badges.append(sob)

    # Rank: bad first (action), then good (motivation), then neutral
    tone_order = {"bad": 0, "warn": 1, "good": 2, "neutral": 3}
    badges.sort(key=lambda b: tone_order.get(b.tone, 3))
    return [b.as_dict() for b in badges[:max_badges]]
