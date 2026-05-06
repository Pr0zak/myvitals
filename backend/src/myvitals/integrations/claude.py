"""Claude API integration — narrate aggregate health stats.

Privacy stance:
- The bounded payload built here is *aggregate*, not raw. We never send
  individual heart-rate samples, GPS tracks, exact sleep timestamps, or
  the user's profile PII (DOB → age range, no name/email).
- The user's API key lives in DB (ai_config), set via the Settings UI;
  empty key = feature off.
- Daily call limits enforced server-side so a stuck client can't run
  away with the bill.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from anthropic import AsyncAnthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import models


@dataclass
class AiResult:
    content: str
    model: str
    input_tokens: int
    output_tokens: int


SYSTEM_PROMPT = """You are a brief, friendly health coach narrating
aggregate self-tracked metrics for the user themselves. Your job:
- Translate numbers into a 2-4 paragraph plain-English read of how the
  user is doing this week / month.
- Call out what's notably better, what's flagging, and one or two
  practical takeaways grounded in the data.
- Be specific (cite numbers, deltas, correlations) but never alarmist.
  You are NOT a doctor and shouldn't pretend to diagnose.
- Tone: calm, supportive, plain English. Short sentences. No emoji.
- If the data is sparse or noisy, say so — don't fabricate trends.

Output: clean Markdown with at most one ## heading. No code blocks.
"""


def _bucket_age(dob: date | None) -> str | None:
    if dob is None:
        return None
    age = (date.today() - dob).days // 365
    if age < 25: return "<25"
    if age < 35: return "25-34"
    if age < 45: return "35-44"
    if age < 55: return "45-54"
    if age < 65: return "55-64"
    return "65+"


async def build_summary_payload(
    db: AsyncSession, range_kind: str
) -> dict[str, Any]:
    """Returns a *bounded* JSON payload — aggregate stats only, no raw rows.
    range_kind: 'week' (last 7d) or 'month' (last 30d)."""
    days = 30 if range_kind == "month" else 7
    today = datetime.now(timezone.utc).date()
    since = today - timedelta(days=days)

    # Daily summaries — already aggregated by the nightly job.
    rows = (await db.execute(
        select(models.DailySummary)
        .where(models.DailySummary.date >= since)
        .order_by(models.DailySummary.date)
    )).scalars().all()
    summaries = [
        {
            "date": str(r.date),
            "rhr": r.resting_hr,
            "hrv": r.hrv_avg,
            "recovery": r.recovery_score,
            "sleep_h": (r.sleep_duration_s / 3600.0) if r.sleep_duration_s else None,
            "sleep_score": r.sleep_score,
            "steps": r.steps_total,
            "readiness": r.readiness_score,
            "tsb": r.tsb,
        }
        for r in rows
    ]

    # Profile context — only safe fields, no DOB/name/email.
    profile = (await db.execute(
        select(models.UserProfile).limit(1)
    )).scalar_one_or_none() if hasattr(models, "UserProfile") else None
    profile_ctx: dict[str, Any] = {}
    if profile is not None:
        profile_ctx = {
            "age_range": _bucket_age(getattr(profile, "birth_date", None)),
            "sex": getattr(profile, "sex", None),
            "activity_level": getattr(profile, "activity_level", None),
            "rhr_baseline": getattr(profile, "resting_hr_baseline", None),
        }

    # Top correlations — already aggregated.
    discoveries: list[dict[str, Any]] = []
    try:
        from ..api.analytics import _DAILY_SUMMARY_METRICS, _daily_summary_metric, _pearson
        cache: dict[str, dict[date, float]] = {}
        until = today
        since_corr = today - timedelta(days=90)
        for m in _DAILY_SUMMARY_METRICS:
            cache[m] = await _daily_summary_metric(db, m, since_corr, until)
        keys = list(_DAILY_SUMMARY_METRICS)
        for i, x in enumerate(keys):
            for y in keys[i + 1:]:
                xs_d, ys_d = cache[x], cache[y]
                common = sorted(set(xs_d) & set(ys_d))
                if len(common) < 14:
                    continue
                r = _pearson([xs_d[d] for d in common], [ys_d[d] for d in common])
                if r is not None and abs(r) >= 0.4:
                    discoveries.append({"x": x, "y": y, "r": round(r, 2), "n": len(common)})
        discoveries.sort(key=lambda d: -abs(d["r"]))
        discoveries = discoveries[:5]
    except Exception:  # noqa: BLE001
        pass

    # Sober status — current days only, no history.
    current_streak: dict[str, Any] | None = None
    try:
        active = (await db.execute(
            select(models.SoberStreak)
            .where(models.SoberStreak.end_at.is_(None))
            .limit(1)
        )).scalar_one_or_none()
        if active is not None:
            secs = (datetime.now(timezone.utc) - active.start_at).total_seconds()
            current_streak = {
                "addiction": active.addiction,
                "days": round(secs / 86400.0, 1),
            }
    except Exception:  # noqa: BLE001
        pass

    return {
        "range": range_kind,
        "window_days": days,
        "today": str(today),
        "profile": profile_ctx,
        "daily": summaries,
        "discoveries": discoveries,
        "sober": current_streak,
    }


def hash_payload(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def explain(
    db: AsyncSession,
    range_kind: str,
    cfg: models.AiConfig,
) -> AiResult:
    """Build payload, send to Claude, return narrative."""
    if not cfg.enabled or not cfg.anthropic_api_key:
        raise RuntimeError("AI is disabled or no API key configured")

    payload = await build_summary_payload(db, range_kind)
    user_text = (
        f"Range: last {payload['window_days']} days as of {payload['today']}.\n\n"
        f"Profile: {json.dumps(payload['profile'], default=str)}\n\n"
        f"Daily aggregate ({len(payload['daily'])} rows):\n"
        f"{json.dumps(payload['daily'], default=str)}\n\n"
        f"Top correlations from the past 90 days "
        f"(|Pearson r| >= 0.4, n >= 14):\n"
        f"{json.dumps(payload['discoveries'], default=str)}\n\n"
        f"Sober streak (if tracked): {json.dumps(payload['sober'], default=str)}\n"
    )

    client = AsyncAnthropic(api_key=cfg.anthropic_api_key)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=900,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_text}],
    )
    text_parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
    content = "\n\n".join(text_parts).strip()
    return AiResult(
        content=content,
        model=resp.model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )
