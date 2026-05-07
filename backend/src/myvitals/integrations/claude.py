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


_TONE_FLAVORS = {
    "supportive": (
        "Tone: warm, encouraging, plain-English. Acknowledge wins, frame "
        "setbacks with a path forward. Never preachy."
    ),
    "blunt": (
        "Tone: direct, no-nonsense. Skip pleasantries. State the data, "
        "the most likely cause, and the most useful action. Never rude."
    ),
    "data-only": (
        "Tone: neutral, clinical, factual. State only what the numbers "
        "show — no encouragement or qualitative judgment. Cite figures."
    ),
}


def _tone_line(tone: str) -> str:
    return _TONE_FLAVORS.get(tone, _TONE_FLAVORS["supportive"])


def system_prompt(tone: str) -> str:
    return f"""You are a brief health coach narrating aggregate self-tracked
metrics for the user themselves.

{_tone_line(tone)}

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


def structured_system(tone: str) -> str:
    return f"""You are a brief health coach. The user gives you pre-aggregated
metric data and asks for an analysis on a specific topic.

{_tone_line(tone)}

Use the `give_analysis` tool to return your response. Schema:
- headline: ONE sentence, ≤ 14 words, the most important takeaway
- tone: "good" | "warn" | "bad" | "neutral"
- evidence: 2-4 short bullets (≤ 22 words each), each citing a number
  or date from the data
- suggestion: ONE concrete actionable lever, ≤ 22 words

Be specific. Never alarmist. If data is sparse, say so in the headline.
"""


VERDICT_SYSTEM = """You are a brief health coach. Read the user's most
recent stats and produce ONE headline sentence (≤ 12 words) summarising
how their body is doing right now. Plain English. No emoji.
Examples:
- "Recovery day — HRV still suppressed, prioritise sleep tonight."
- "Strong morning — readiness 86 after 7.4h sleep."
- "Watch your RHR — running 5bpm above baseline for 3 days."
Output ONLY the sentence. No bullets, no markdown."""


ASK_SYSTEM = """You are a brief health coach. The user has aggregate
data and a specific question. Answer in ≤ 80 words. Be concrete: cite
numbers and dates. Use bullets if listing > 1 cause. If the data
doesn't support an answer, say so honestly. No emoji."""

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
    """Workout details enriched: type, duration, distance, avg+max HR,
    elevation, power, kcal, suffer score, HR recovery — gives Claude
    real workout context instead of just step counts."""
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
    out: list[dict[str, Any]] = []
    for r in rows:
        d: dict[str, Any] = {
            "date": str(r.start_at.date()),
            "type": r.type,
            "duration_min": int((r.duration_s or 0) / 60),
        }
        if r.distance_m: d["distance_km"] = round(r.distance_m / 1000, 1)
        if r.elevation_gain_m: d["elev_m"] = int(r.elevation_gain_m)
        if r.avg_hr: d["avg_hr"] = int(r.avg_hr)
        if r.max_hr: d["max_hr"] = int(r.max_hr)
        if getattr(r, "avg_power_w", None): d["avg_power_w"] = int(r.avg_power_w)
        if r.kcal: d["kcal"] = int(r.kcal)
        if getattr(r, "suffer_score", None): d["suffer"] = int(r.suffer_score)
        if getattr(r, "hr_recovery_60s", None): d["hr_rec_60s"] = int(r.hr_recovery_60s)
        # Pace: only meaningful for distance activities
        if r.distance_m and r.duration_s and r.distance_m > 100:
            pace_s_per_km = (r.duration_s / (r.distance_m / 1000.0))
            d["pace_min_per_km"] = round(pace_s_per_km / 60.0, 2)
        out.append(d)
    return out


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


def _cached_system(text: str) -> list[dict]:
    """Wrap the system prompt for Anthropic's prompt cache so the fixed
    template doesn't get re-billed at full input rate on every call.
    Saves ~50% on repeated topical reads."""
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


async def explain_legacy(db: AsyncSession, range_kind: str, cfg: models.AiConfig) -> AiResult:
    """Backwards-compat narrative output (markdown). Used by /ai/explain."""
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
        system=_cached_system(system_prompt(cfg.tone)),
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
        system=_cached_system(structured_system(cfg.tone)),
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


# ─────────────── Verdict (one-line summary) ───────────────

async def build_verdict_payload(db: AsyncSession) -> dict[str, Any]:
    rows = await _daily_rows(db, 7)
    return {
        "today": rows[-1] if rows else None,
        "last_7_days": rows,
        "trend_badges": await compute_badges(db, max_badges=4),
        "sober": await _sober_status(db),
    }


async def verdict(db: AsyncSession, cfg: models.AiConfig) -> AiResult:
    if not cfg.enabled or not cfg.anthropic_api_key:
        raise RuntimeError("AI is disabled or no API key configured")
    payload = await build_verdict_payload(db)
    user_text = f"Aggregate snapshot:\n{json.dumps(payload, indent=2, default=str)}\n"
    client = AsyncAnthropic(api_key=cfg.anthropic_api_key)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=80,
        system=_cached_system(VERDICT_SYSTEM),
        messages=[{"role": "user", "content": user_text}],
    )
    text_parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
    return AiResult(
        content="\n".join(text_parts).strip().strip('"').strip(),
        model=resp.model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )


# ─────────────── Free-form Q&A ───────────────

async def ask(db: AsyncSession, cfg: models.AiConfig, question: str) -> AiResult:
    if not cfg.enabled or not cfg.anthropic_api_key:
        raise RuntimeError("AI is disabled or no API key configured")
    if len(question) > 500:
        question = question[:500]
    payload = await build_summary_payload(db, "week")
    user_text = (
        f"Question: {question}\n\n"
        f"Aggregate context (last 7 days + correlations + sober):\n"
        f"{json.dumps(payload, indent=2, default=str)}\n"
    )
    client = AsyncAnthropic(api_key=cfg.anthropic_api_key)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=400,
        system=_cached_system(ASK_SYSTEM),
        messages=[{"role": "user", "content": user_text}],
    )
    text_parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
    return AiResult(
        content="\n\n".join(text_parts).strip(),
        model=resp.model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )


# ─────────────── Discovery explainer ───────────────

async def explain_discovery(
    db: AsyncSession, cfg: models.AiConfig,
    x_metric: str, y_metric: str,
) -> AiResult:
    if not cfg.enabled or not cfg.anthropic_api_key:
        raise RuntimeError("AI is disabled or no API key configured")
    discoveries = await _correlations(db, days=90, top_n=20)
    target = next(
        (d for d in discoveries if (d["x"] == x_metric and d["y"] == y_metric)
         or (d["x"] == y_metric and d["y"] == x_metric)),
        None,
    )
    if target is None:
        return AiResult(
            content=f"No statistically meaningful correlation between {x_metric} and {y_metric} "
                    f"in the last 90 days (need n≥14 with |r|≥0.4).",
            model=cfg.model, input_tokens=0, output_tokens=0,
        )
    context_days = await _daily_rows(db, 30)
    user_text = (
        f"The user found a correlation in their data:\n{json.dumps(target)}\n\n"
        f"Context (last 30 days of daily summaries):\n"
        f"{json.dumps(context_days, default=str)}\n\n"
        f"In ≤ 70 words: explain in plain English what this correlation likely "
        f"means in their day-to-day. Cite the direction (negative r = more X "
        f"means less Y). Suggest one practical takeaway."
    )
    client = AsyncAnthropic(api_key=cfg.anthropic_api_key)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=300,
        system=_cached_system(ASK_SYSTEM),
        messages=[{"role": "user", "content": user_text}],
    )
    text_parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
    return AiResult(
        content="\n\n".join(text_parts).strip(),
        model=resp.model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )


# ─────────────── Pre-workout recommendation ───────────────

async def pre_workout(db: AsyncSession, cfg: models.AiConfig) -> AiResult:
    if not cfg.enabled or not cfg.anthropic_api_key:
        raise RuntimeError("AI is disabled or no API key configured")
    rows = await _daily_rows(db, 7)
    today = rows[-1] if rows else None
    payload = {
        "today": today,
        "last_7_days": rows,
        "trend_badges": await compute_badges(db, max_badges=3),
    }
    user_text = (
        f"User wants a one-line training recommendation for today.\n\n"
        f"Aggregate context:\n{json.dumps(payload, indent=2, default=str)}\n\n"
        f"Output: ONE verdict (Go hard / Moderate / Easy / Rest) with a "
        f"one-sentence justification citing the most important number. "
        f"≤ 25 words total. No markdown."
    )
    client = AsyncAnthropic(api_key=cfg.anthropic_api_key)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=80,
        system=_cached_system(VERDICT_SYSTEM),
        messages=[{"role": "user", "content": user_text}],
    )
    text_parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
    return AiResult(
        content="\n".join(text_parts).strip(),
        model=resp.model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )


# ─────────────── Activity summary ───────────────

async def activity_summary(
    db: AsyncSession, cfg: models.AiConfig, act: "models.Activity",
) -> AiResult:
    """Two-line context for a just-finished workout."""
    if not cfg.enabled or not cfg.anthropic_api_key:
        raise RuntimeError("AI is disabled or no API key configured")

    # Recent metric context — what's the user's recovery state going in
    rows = await _daily_rows(db, 7)
    payload = {
        "activity": {
            "date": str(act.start_at.date()),
            "type": act.type,
            "name": act.name,
            "duration_min": int((act.duration_s or 0) / 60),
            "distance_km": round((act.distance_m or 0) / 1000, 1) if act.distance_m else None,
            "elev_m": int(act.elevation_gain_m) if act.elevation_gain_m else None,
            "avg_hr": int(act.avg_hr) if act.avg_hr else None,
            "max_hr": int(act.max_hr) if act.max_hr else None,
            "kcal": int(act.kcal) if act.kcal else None,
            "suffer": int(act.suffer_score) if getattr(act, "suffer_score", None) else None,
            "hr_recovery_60s": int(act.hr_recovery_60s) if getattr(act, "hr_recovery_60s", None) else None,
        },
        "context_last_7_days": rows,
    }
    user_text = (
        f"User just finished a workout. Two-sentence context for it.\n\n"
        f"{json.dumps(payload, indent=2, default=str)}\n\n"
        f"Sentence 1: characterise the session (zone / intensity / "
        f"effort) using the data. Sentence 2: what to expect or do "
        f"tomorrow (HRV impact, recovery focus). ≤ 50 words total."
    )
    client = AsyncAnthropic(api_key=cfg.anthropic_api_key)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=200,
        system=_cached_system(ASK_SYSTEM),
        messages=[{"role": "user", "content": user_text}],
    )
    text_parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
    return AiResult(
        content="\n\n".join(text_parts).strip(),
        model=resp.model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )


# ─────────────── Goal check ───────────────

async def goal_check(
    db: AsyncSession, cfg: models.AiConfig, goal: "models.AiGoal",
) -> AiResult:
    """Coaching read on a goal — trajectory + leverage + ETA."""
    if not cfg.enabled or not cfg.anthropic_api_key:
        raise RuntimeError("AI is disabled or no API key configured")

    # 30-day context, plus any goal-relevant metric
    rows = await _daily_rows(db, 30)

    relevant: list[dict[str, Any]] = []
    if goal.kind == "weight":
        # Pull recent weight readings
        try:
            wts = (await db.execute(
                select(models.BodyMetric)
                .where(models.BodyMetric.weight_kg.is_not(None))
                .order_by(models.BodyMetric.time.desc())
                .limit(60)
            )).scalars().all()
            relevant = [
                {"date": str(w.time.date()), "weight_kg": w.weight_kg,
                 "body_fat_pct": w.body_fat_pct}
                for w in wts
            ]
        except Exception:  # noqa: BLE001
            relevant = []
    elif goal.kind == "sober":
        s = await _sober_status(db)
        if s: relevant = [s]
    elif goal.kind == "sleep":
        relevant = [{"date": r["date"], "sleep_h": r["sleep_h"], "score": r["sleep_score"]}
                    for r in rows]
    elif goal.kind == "steps":
        relevant = [{"date": r["date"], "steps": r["steps"]} for r in rows]

    payload = {
        "goal": {
            "kind": goal.kind, "title": goal.title,
            "target_value": goal.target_value, "target_unit": goal.target_unit,
            "target_date": str(goal.target_date) if goal.target_date else None,
            "started_at": str(goal.started_at),
            "notes": goal.notes,
        },
        "relevant_data": relevant,
        "context_last_30_days": rows,
    }
    user_text = (
        f"Coach the user on this goal. Cite numbers / dates from the data.\n\n"
        f"{json.dumps(payload, indent=2, default=str)}\n\n"
        f"In ≤ 80 words: trajectory (on track / behind / wrong direction), "
        f"the most useful next-step lever, and an honest ETA if the data "
        f"supports one. No false optimism."
    )
    client = AsyncAnthropic(api_key=cfg.anthropic_api_key)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=300,
        system=_cached_system(ASK_SYSTEM),
        messages=[{"role": "user", "content": user_text}],
    )
    text_parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
    return AiResult(
        content="\n\n".join(text_parts).strip(),
        model=resp.model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )


# ─────────────── Batch mode (all topics in one call) ───────────────

ALL_TOPICS_TOOL = {
    "name": "give_all_topics",
    "description": "Return one analysis per topic in a single call.",
    "input_schema": {
        "type": "object",
        "properties": {
            "week":     {"$ref": "#/definitions/topic"},
            "sleep":    {"$ref": "#/definitions/topic"},
            "recovery": {"$ref": "#/definitions/topic"},
            "sober":    {"$ref": "#/definitions/topic"},
            "anomaly":  {"$ref": "#/definitions/topic"},
        },
        "required": ["week", "sleep", "recovery", "sober", "anomaly"],
        "definitions": {
            "topic": {
                "type": "object",
                "properties": {
                    "headline":   {"type": "string"},
                    "tone":       {"type": "string", "enum": ["good", "warn", "bad", "neutral"]},
                    "evidence":   {"type": "array", "items": {"type": "string"}},
                    "suggestion": {"type": "string"},
                },
                "required": ["headline", "tone", "evidence", "suggestion"],
            },
        },
    },
}


async def explain_all(db: AsyncSession, cfg: models.AiConfig) -> AiResult:
    if not cfg.enabled or not cfg.anthropic_api_key:
        raise RuntimeError("AI is disabled or no API key configured")
    payload = await build_summary_payload(db, "week")
    user_text = (
        "Run analyses on each of week / sleep / recovery / sober / anomaly. "
        "Each topic gets its own headline + evidence + suggestion. Use the "
        "give_all_topics tool — one call, all topics.\n\n"
        f"Aggregate data:\n{json.dumps(payload, indent=2, default=str)}\n"
    )
    client = AsyncAnthropic(api_key=cfg.anthropic_api_key)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=1500,
        system=_cached_system(structured_system(cfg.tone)),
        tools=[ALL_TOPICS_TOOL],
        tool_choice={"type": "tool", "name": "give_all_topics"},
        messages=[{"role": "user", "content": user_text}],
    )
    tool_input: dict[str, Any] = {}
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use" and block.name == "give_all_topics":
            tool_input = block.input  # type: ignore[assignment]
            break
    return AiResult(
        content=json.dumps(tool_input),
        model=resp.model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )


# ─────────────── Anomaly detection (no LLM, then optional LLM phrasing) ───────────────

async def detect_anomalies(db: AsyncSession, z_threshold: float = 2.0) -> list[dict[str, Any]]:
    """Statistical scan: find metric values today that are >z_threshold
    away from the user's 30-day baseline. Returns list of structured
    anomaly dicts. The Claude phrasing layer runs on top of this."""
    rows = await _daily_rows(db, 30)
    if len(rows) < 7:
        return []
    today_row = rows[-1] if rows else None
    if today_row is None:
        return []
    out: list[dict[str, Any]] = []
    for metric in ("rhr", "hrv", "recovery", "sleep_h", "readiness"):
        baseline = [r[metric] for r in rows[:-1] if r.get(metric) is not None]
        last = today_row.get(metric)
        if last is None or len(baseline) < 7:
            continue
        mu = sum(baseline) / len(baseline)
        var = sum((v - mu) ** 2 for v in baseline) / max(1, len(baseline) - 1)
        if var <= 0:
            continue
        sigma = var ** 0.5
        z = (last - mu) / sigma if sigma else 0
        if abs(z) >= z_threshold:
            # Lower-is-better metrics: a high z is bad (RHR up = warning).
            lower_better = metric == "rhr"
            is_bad = (z > 0) == lower_better
            out.append({
                "date": today_row["date"],
                "metric": metric,
                "value": last,
                "baseline_mean": round(mu, 2),
                "z_score": round(z, 2),
                "severity": "bad" if is_bad else "good",
            })
    return out


STRENGTH_REVIEW_TOOL = {
    "name": "give_strength_review",
    "description": "Return a structured post-workout review for a single strength session.",
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {
                "type": "string",
                "description": "≤16 words. The single most important takeaway from this session.",
            },
            "tone": {"type": "string", "enum": ["good", "warn", "bad", "neutral"]},
            "highlights": {
                "type": "array", "items": {"type": "string"},
                "description": "1-3 short bullets, ≤22 words each. What went well — cite specifics "
                               "(weight × reps, rating, vs trailing 4w avg).",
            },
            "concerns": {
                "type": "array", "items": {"type": "string"},
                "description": "0-2 short bullets, ≤22 words each. Drift in rep quality, "
                               "missed sets, recovery context worth flagging.",
            },
            "next_session_suggestion": {
                "type": "string",
                "description": "≤30 words. ONE concrete lever for the next session — "
                               "e.g. 'add 2.5 lb to bench, keep RDL flat'.",
            },
        },
        "required": ["headline", "tone", "highlights", "next_session_suggestion"],
    },
}


def _strength_review_system(tone: str) -> str:
    return f"""You are a brief strength coach reviewing a completed
workout. The user logs sets in a self-hosted home-gym app and trains
mostly with dumbbells + an adjustable bench.

{_tone_line(tone)}

Use the `give_strength_review` tool to return your response. Schema:
- headline: ONE sentence, ≤ 16 words, the single most important read
- tone: "good" | "warn" | "bad" | "neutral"
- highlights: 1-3 bullets — cite weight × reps, RPE, vs prior session
- concerns: 0-2 bullets — only include if there's something real
- next_session_suggestion: ONE concrete lever (e.g. "add 2.5 lb to bench")

Be specific. Reference actual numbers from the data. Never alarmist.
If the session was unremarkable, say so honestly in the headline.
Never make up exercises that aren't in the data.
"""


async def build_strength_review_payload(
    db: AsyncSession, workout_id: int,
) -> dict[str, Any]:
    """Bounded payload for a single workout's review.

    Includes the workout's exercises with target/actual sets/reps/rating,
    the user's recovery context (already on the workout row), and a
    trailing 4-week comparison (avg rating per exercise, frequency,
    tonnage by primary muscle). NO raw set timestamps or per-second data.
    """
    workout = await db.get(models.StrengthWorkout, workout_id)
    if workout is None:
        return {}

    # Hydrate exercises + sets
    wex_rows = (await db.execute(
        select(models.StrengthWorkoutExercise)
        .where(models.StrengthWorkoutExercise.workout_id == workout_id)
        .order_by(models.StrengthWorkoutExercise.order_index)
    )).scalars().all()
    wex_ids = [w.id for w in wex_rows]
    sets_by_wex: dict[int, list[models.StrengthSet]] = {}
    if wex_ids:
        sets_rows = (await db.execute(
            select(models.StrengthSet)
            .where(models.StrengthSet.workout_exercise_id.in_(wex_ids))
        )).scalars().all()
        for s in sets_rows:
            sets_by_wex.setdefault(s.workout_exercise_id, []).append(s)

    # Catalog lookup so the payload uses human-readable names, not slugs
    from ..analytics.strength import CATALOG_BY_ID

    exercises_payload: list[dict[str, Any]] = []
    for wex in wex_rows:
        sets = sorted(sets_by_wex.get(wex.id, []), key=lambda s: s.set_number)
        logged = [s for s in sets if s.actual_reps is not None and not s.skipped]
        avg_rating = (
            sum(s.rating for s in logged if s.rating is not None) /
            max(1, sum(1 for s in logged if s.rating is not None))
            if any(s.rating is not None for s in logged) else None
        )
        cat = CATALOG_BY_ID.get(wex.exercise_id)
        exercises_payload.append({
            "name": cat["name"] if cat else wex.exercise_id,
            "primary_muscle": cat["primary_muscle"] if cat else None,
            "is_compound": cat["is_compound"] if cat else False,
            "target": f"{wex.target_sets}x{wex.target_reps_low}"
                      f"{('-' + str(wex.target_reps_high)) if wex.target_reps_high != wex.target_reps_low else ''}"
                      f"{(' @ ' + str(wex.target_weight_lb) + 'lb') if wex.target_weight_lb else ''}",
            "logged_sets": [
                {
                    "set": s.set_number,
                    "weight_lb": s.actual_weight_lb,
                    "reps": s.actual_reps,
                    "rating": s.rating,
                }
                for s in logged
            ],
            "avg_rating": round(avg_rating, 2) if avg_rating is not None else None,
            "skipped_sets": sum(1 for s in sets if s.skipped),
            "missed_sets": wex.target_sets - len(logged) - sum(1 for s in sets if s.skipped),
        })

    # Trailing 4-week comparison: per-exercise avg rating + tonnage by muscle
    cutoff = workout.date - timedelta(days=28)
    prior_workouts = (await db.execute(
        select(models.StrengthWorkout)
        .where(models.StrengthWorkout.date >= cutoff)
        .where(models.StrengthWorkout.date < workout.date)
        .where(models.StrengthWorkout.status == "completed")
    )).scalars().all()
    prior_wex_ids: list[int] = []
    if prior_workouts:
        prior_wex_rows = (await db.execute(
            select(models.StrengthWorkoutExercise)
            .where(models.StrengthWorkoutExercise.workout_id.in_(
                [w.id for w in prior_workouts]
            ))
        )).scalars().all()
        prior_wex_by_id = {w.id: w for w in prior_wex_rows}
        prior_wex_ids = list(prior_wex_by_id.keys())

    tonnage_by_muscle: dict[str, float] = {}
    rating_by_exercise: dict[str, list[float]] = {}
    if prior_wex_ids:
        prior_sets = (await db.execute(
            select(models.StrengthSet)
            .where(models.StrengthSet.workout_exercise_id.in_(prior_wex_ids))
            .where(models.StrengthSet.skipped.is_(False))
        )).scalars().all()
        for s in prior_sets:
            wex = prior_wex_by_id.get(s.workout_exercise_id)
            if wex is None:
                continue
            cat = CATALOG_BY_ID.get(wex.exercise_id)
            primary = cat["primary_muscle"] if cat else "unknown"
            if s.actual_weight_lb and s.actual_reps:
                tonnage_by_muscle[primary] = round(
                    tonnage_by_muscle.get(primary, 0.0)
                    + s.actual_weight_lb * s.actual_reps, 1,
                )
            if s.rating is not None:
                rating_by_exercise.setdefault(wex.exercise_id, []).append(s.rating)

    avg_rating_by_exercise = {
        eid: round(sum(rs) / len(rs), 2) for eid, rs in rating_by_exercise.items()
    }

    return {
        "today": {
            "date": str(workout.date),
            "split": workout.split_focus,
            "recovery_score": workout.recovery_score_used,
            "readiness_score": workout.readiness_score_used,
            "sleep_h": (round(workout.sleep_h_used, 1)
                        if workout.sleep_h_used is not None else None),
            "duration_min": (
                int((workout.completed_at - workout.started_at).total_seconds() / 60)
                if workout.completed_at and workout.started_at else None
            ),
            "exercises": exercises_payload,
        },
        "trailing_4w": {
            "n_workouts": len(prior_workouts),
            "tonnage_by_muscle_lb": tonnage_by_muscle,
            "avg_rating_by_exercise": avg_rating_by_exercise,
        },
    }


async def strength_review(
    db: AsyncSession, workout_id: int, cfg: models.AiConfig,
) -> AiResult:
    """Generate a structured strength review for a completed workout."""
    if not cfg.enabled or not cfg.anthropic_api_key:
        raise RuntimeError("AI is disabled or no API key configured")
    payload = await build_strength_review_payload(db, workout_id)
    if not payload:
        raise RuntimeError("workout not found")
    user_text = (
        f"Review this completed strength session, comparing it against "
        f"the trailing 4 weeks of the user's history.\n\n"
        f"Aggregate data:\n{json.dumps(payload, indent=2, default=str)}\n"
    )
    client = AsyncAnthropic(api_key=cfg.anthropic_api_key)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=600,
        system=_cached_system(_strength_review_system(cfg.tone)),
        tools=[STRENGTH_REVIEW_TOOL],
        tool_choice={"type": "tool", "name": "give_strength_review"},
        messages=[{"role": "user", "content": user_text}],
    )
    tool_input: dict[str, Any] = {}
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use" and block.name == "give_strength_review":
            tool_input = block.input  # type: ignore[assignment]
            break
    if not tool_input:
        text_parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
        tool_input = {
            "headline": "Could not generate structured review",
            "tone": "neutral",
            "highlights": ["\n".join(text_parts).strip()[:300]],
            "concerns": [],
            "next_session_suggestion": "Try again or check the model picker in Settings.",
        }
    return AiResult(
        content=json.dumps(tool_input),
        model=resp.model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )


async def phrase_anomaly(cfg: models.AiConfig, anomaly: dict[str, Any]) -> str:
    """Single-sentence push notification body for an anomaly. ~$0.0005/call."""
    if not cfg.enabled or not cfg.anthropic_api_key:
        raise RuntimeError("AI is disabled or no API key configured")
    user_text = (
        f"Statistical anomaly detected:\n{json.dumps(anomaly)}\n\n"
        f"Write ONE sentence (≤ 18 words) for a phone notification. Plain "
        f"English. Mention the metric, the magnitude, and a one-word read "
        f"(spike / dip / etc). No emoji."
    )
    client = AsyncAnthropic(api_key=cfg.anthropic_api_key)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=60,
        system=_cached_system(VERDICT_SYSTEM),
        messages=[{"role": "user", "content": user_text}],
    )
    text_parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
    return "\n".join(text_parts).strip().strip('"').strip()
