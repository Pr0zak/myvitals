"""Claude API integration — narrate aggregate health stats.

Privacy stance:
- The bounded payloads built here are *aggregate*, not raw. We never
  send individual heart-rate samples, GPS tracks, exact sleep
  timestamps, the user's name/email, or sober-streak history dates.
- The user's API key lives in DB (ai_config), set via the Settings UI;
  empty key = feature off.
- Daily call limits enforced server-side so a stuck client can't run
  away with the bill.

Output shape:
- Targeted endpoints (sleep / recovery / sober / week / anomaly) use
  Claude's tool-use to enforce a JSON schema:
    { headline, evidence: [str], suggestion, tone }
- Result rendered as a structured card on the dashboard, not a wall of
  prose. Way less wordy than the original "2-4 paragraph" template.
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

from ..analytics.trends import compute_badges
from ..db import models


@dataclass
class AiResult:
    content: str            # markdown for legacy /ai/explain; JSON string for structured
    model: str
    input_tokens: int
    output_tokens: int


SYSTEM_PROMPT = """You are a brief, friendly health coach narrating
aggregate self-tracked metrics for the user themselves.

OUTPUT FORMAT — strict:
- Headline: one sentence, ≤ 12 words.
- Then 3 bullet points, each ≤ 18 words, each citing a specific number
  or date.
- Then ONE "Try this:" line — one concrete actionable lever.
- Total under 90 words. No paragraphs.

Rules:
- Be specific. Cite numbers, dates, and named correlations.
- Never alarmist; you are NOT a doctor.
- If data is sparse, say so — do not fabricate trends.
- No emoji. Markdown bullets only.
"""

STRUCTURED_SYSTEM = """You are a brief health coach. The user gives you
pre-aggregated metric data and asks for an analysis on a specific topic.

Use the `give_analysis` tool to return your response. The schema is:
- headline: ONE sentence, ≤ 14 words, the most important takeaway
- tone: "good" | "warn" | "bad" | "neutral"
- evidence: 2-4 short bullets (≤ 22 words each), each citing a number
  or date from the data
- suggestion: ONE concrete actionable lever, ≤ 22 words

Be specific. Never alarmist. If data is sparse, say so in the headline.
"""

ANALYSIS_TOOL = {
    "name": "give_analysis",
    "description": "Return your analysis as structured fields.",
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {"type": "string", "description": "≤14 words, most important takeaway"},
            "tone": {"type": "string", "enum": ["good", "warn", "bad", "neutral"]},
            "evidence": {
                "type": "array", "items": {"type": "string"},
                "description": "2-4 short bullets, each citing a specific number or date",
            },
            "suggestion": {"type": "string", "description": "≤22 words, one concrete actionable lever"},
        },
        "required": ["headline", "tone", "evidence", "suggestion"],
    },
}


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


async def _profile_ctx(db: AsyncSession) -> dict[str, Any]:
    if not hasattr(models, "UserProfile"):
        return {}
    profile = (await db.execute(select(models.UserProfile).limit(1))).scalar_one_or_none()
    if profile is None:
        return {}
    return {
        "age_range": _bucket_age(getattr(profile, "birth_date", None)),
        "sex": getattr(profile, "sex", None),
        "activity_level": getattr(profile, "activity_level", None),
        "rhr_baseline": getattr(profile, "resting_hr_baseline", None),
    }


async def _daily_rows(db: AsyncSession, days: int) -> list[dict[str, Any]]:
    today = datetime.now(timezone.utc).date()
    since = today - timedelta(days=days)
    rows = (await db.execute(
        select(models.DailySummary)
        .where(models.DailySummary.date >= since)
        .order_by(models.DailySummary.date)
    )).scalars().all()
    return [
        {
            "date": str(r.date),
            "rhr": r.resting_hr,
            "hrv": r.hrv_avg,
            "recovery": r.recovery_score,
            "sleep_h": (r.sleep_duration_s / 3600.0) if r.sleep_duration_s else None,
            "sleep_score": r.sleep_score,
            "sleep_consistency": r.sleep_consistency_score,
            "sleep_debt_h": r.sleep_debt_h,
            "steps": r.steps_total,
            "readiness": r.readiness_score,
            "tsb": r.tsb,
            "ctl": r.ctl,
            "atl": r.atl,
        }
        for r in rows
    ]


async def _activities(db: AsyncSession, days: int) -> list[dict[str, Any]]:
    if not hasattr(models, "Activity"):
        return []
    today = datetime.now(timezone.utc)
    since = today - timedelta(days=days)
    try:
        rows = (await db.execute(
            select(models.Activity)
            .where(models.Activity.start_at >= since)
            .order_by(models.Activity.start_at.desc())
            .limit(40)
        )).scalars().all()
    except Exception:  # noqa: BLE001
        return []
    return [
        {
            "date": str(r.start_at.date()),
            "type": r.type,
            "duration_min": int((r.duration_s or 0) / 60),
            "distance_km": round((r.distance_m or 0) / 1000, 1) if r.distance_m else None,
            "avg_hr": int(r.avg_hr) if r.avg_hr else None,
            "kcal": int(r.kcal) if r.kcal else None,
        }
        for r in rows
    ]


async def _annotations(db: AsyncSession, days: int) -> list[dict[str, Any]]:
    today = datetime.now(timezone.utc)
    since = today - timedelta(days=days)
    rows = (await db.execute(
        select(models.Annotation)
        .where(models.Annotation.ts >= since)
        .order_by(models.Annotation.ts)
        .limit(200)
    )).scalars().all()
    out: list[dict[str, Any]] = []
    for r in rows:
        # Filter to the high-signal types and drop free-form notes for privacy
        if r.type in ("caffeine", "alcohol", "mood", "meds"):
            out.append({
                "date": r.ts.date().isoformat(),
                "type": r.type,
                "payload": r.payload,
            })
    return out


async def _correlations(db: AsyncSession, days: int = 90, top_n: int = 5) -> list[dict[str, Any]]:
    try:
        from ..api.analytics import _DAILY_SUMMARY_METRICS, _daily_summary_metric, _pearson
    except Exception:  # noqa: BLE001
        return []
    today = datetime.now(timezone.utc).date()
    since = today - timedelta(days=days)
    cache: dict[str, dict[date, float]] = {}
    for m in _DAILY_SUMMARY_METRICS:
        cache[m] = await _daily_summary_metric(db, m, since, today)
    out: list[dict[str, Any]] = []
    keys = list(_DAILY_SUMMARY_METRICS)
    for i, x in enumerate(keys):
        for y in keys[i + 1:]:
            xs_d, ys_d = cache[x], cache[y]
            common = sorted(set(xs_d) & set(ys_d))
            if len(common) < 14:
                continue
            r = _pearson([xs_d[d] for d in common], [ys_d[d] for d in common])
            if r is not None and abs(r) >= 0.4:
                out.append({"x": x, "y": y, "r": round(r, 2), "n": len(common)})
    out.sort(key=lambda d: -abs(d["r"]))
    return out[:top_n]


async def _sober_status(db: AsyncSession) -> dict[str, Any] | None:
    try:
        active = (await db.execute(
            select(models.SoberStreak)
            .where(models.SoberStreak.end_at.is_(None))
            .limit(1)
        )).scalar_one_or_none()
        if active is None:
            return None
        secs = (datetime.now(timezone.utc) - active.start_at).total_seconds()
        # Aggregate stats across past streaks (durations only, no dates)
        all_streaks = (await db.execute(
            select(models.SoberStreak)
        )).scalars().all()
        durations = [
            (s.end_at - s.start_at).total_seconds() / 86400.0
            for s in all_streaks if s.end_at is not None
        ]
        return {
            "addiction": active.addiction,
            "current_days": round(secs / 86400.0, 1),
            "total_resets": len(durations),
            "longest_days": round(max(durations), 1) if durations else None,
            "avg_days": round(sum(durations) / len(durations), 1) if durations else None,
        }
    except Exception:  # noqa: BLE001
        return None


async def build_summary_payload(db: AsyncSession, range_kind: str) -> dict[str, Any]:
    """Bounded JSON payload for a multi-topic weekly/monthly read.
    range_kind: 'week' (7d) | 'month' (30d). Now richer — includes
    activities + annotations + WoW deltas computed server-side."""
    days = 30 if range_kind == "month" else 7
    today = datetime.now(timezone.utc).date()
    daily = await _daily_rows(db, days * 2)  # pull 2× window for WoW deltas

    # Split current vs prior window for delta calc
    current = [r for r in daily if r["date"] >= str(today - timedelta(days=days))]
    prior = [r for r in daily if r["date"] < str(today - timedelta(days=days))]

    def _mean(rows: list[dict[str, Any]], key: str) -> float | None:
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    deltas: dict[str, dict[str, Any]] = {}
    for k in ("rhr", "hrv", "recovery", "sleep_h", "sleep_score", "steps", "readiness"):
        cur = _mean(current, k)
        prv = _mean(prior, k)
        deltas[k] = {"current": cur, "prior": prv,
                     "delta": round(cur - prv, 2) if cur is not None and prv is not None else None}

    return {
        "range": range_kind,
        "window_days": days,
        "today": str(today),
        "profile": await _profile_ctx(db),
        "daily": current,
        "deltas": deltas,
        "discoveries": await _correlations(db, 90, top_n=5),
        "activities": await _activities(db, days),
        "annotations": await _annotations(db, days),
        "sober": await _sober_status(db),
        "trend_badges": await compute_badges(db),
    }


async def build_topic_payload(db: AsyncSession, topic: str, days: int = 14) -> dict[str, Any]:
    """Slim payload for a focused single-topic read (sleep / recovery / sober)."""
    today = datetime.now(timezone.utc).date()
    rows = await _daily_rows(db, days)
    activities = await _activities(db, days) if topic == "recovery" else []
    annotations = await _annotations(db, days) if topic in ("sleep", "recovery", "sober") else []
    sober = await _sober_status(db) if topic == "sober" else None
    return {
        "topic": topic,
        "today": str(today),
        "window_days": days,
        "profile": await _profile_ctx(db),
        "daily": rows,
        "discoveries": await _correlations(db, 90, top_n=3),
        "activities": activities,
        "annotations": annotations,
        "sober": sober,
    }


def hash_payload(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def explain_legacy(db: AsyncSession, range_kind: str, cfg: models.AiConfig) -> AiResult:
    """Backwards-compat narrative output (markdown). Used by the original
    /ai/explain endpoint."""
    if not cfg.enabled or not cfg.anthropic_api_key:
        raise RuntimeError("AI is disabled or no API key configured")
    payload = await build_summary_payload(db, range_kind)
    user_text = (
        f"Range: last {payload['window_days']} days as of {payload['today']}.\n\n"
        f"{json.dumps(payload, indent=2, default=str)}\n"
    )
    client = AsyncAnthropic(api_key=cfg.anthropic_api_key)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=600,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_text}],
    )
    text_parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
    return AiResult(
        content="\n\n".join(text_parts).strip(),
        model=resp.model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )


async def explain_topic(
    db: AsyncSession,
    topic: str,
    cfg: models.AiConfig,
    days: int = 14,
) -> AiResult:
    """Targeted explain — calls Claude with the analysis tool so the
    response comes back as a typed JSON blob, not free prose."""
    if not cfg.enabled or not cfg.anthropic_api_key:
        raise RuntimeError("AI is disabled or no API key configured")

    if topic == "week":
        payload = await build_summary_payload(db, "week")
    elif topic == "month":
        payload = await build_summary_payload(db, "month")
    else:
        payload = await build_topic_payload(db, topic, days=days)

    topic_intent = {
        "sleep":     "Analyze sleep duration, consistency, and impact on recovery.",
        "recovery":  "Analyze recovery trend, what's helping vs hurting (sleep, training load, alcohol).",
        "sober":     "Analyze the sobriety streak — progress, risk factors, and physiological signals.",
        "anomaly":   "Identify the most anomalous metric this week and explain it.",
        "week":      "Read the user's last 7 days — what's working, what's flagging.",
        "month":     "Read the user's last 30 days — broader trends and inflection points.",
    }.get(topic, "Provide a focused analysis on the topic in the data.")

    user_text = (
        f"Topic: {topic_intent}\n\n"
        f"Aggregate data:\n{json.dumps(payload, indent=2, default=str)}\n"
    )
    client = AsyncAnthropic(api_key=cfg.anthropic_api_key)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=600,
        system=STRUCTURED_SYSTEM,
        tools=[ANALYSIS_TOOL],
        tool_choice={"type": "tool", "name": "give_analysis"},
        messages=[{"role": "user", "content": user_text}],
    )
    # Pull the tool_use block
    tool_input: dict[str, Any] = {}
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use" and block.name == "give_analysis":
            tool_input = block.input  # type: ignore[assignment]
            break
    if not tool_input:
        # Defensive fallback — no tool call happened
        text_parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
        tool_input = {
            "headline": "Could not generate structured analysis",
            "tone": "neutral",
            "evidence": ["\n\n".join(text_parts).strip()[:500]],
            "suggestion": "Try again or check the model picker in Settings.",
        }
    return AiResult(
        content=json.dumps(tool_input),
        model=resp.model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )
