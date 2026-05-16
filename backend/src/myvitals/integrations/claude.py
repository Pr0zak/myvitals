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


_RELIGIOUS_PROTOCOLS = ("ramadan", "lent", "yom_kippur")


async def _fasting_status(db: AsyncSession) -> dict[str, Any] | None:
    """Active fast + last-7-day fasting summary, as a bounded dict
    for AI payloads. Returns None on empty history so the AI doesn't
    waste tokens on a "no fasts" placeholder.

    Shape (FAST-19):
      - weekly_fasting_hours: float  (sum of daily_summary.fasting_hours)
      - last_7d_fast_count: int      (completed fasts in trailing 7d)
      - last_7d_longest_h: float     (longest completed fast in 7d)
      - is_religious: bool           (any fast row this week is religious)
      - active_fast: {...} | absent  (when a fast is in progress)
          - protocol, elapsed_h, target_h, current_stage, is_religious

    KEEP BOUNDED — single ints/floats + the active dict only, no
    per-session rows. The Claude payload budget matters; ballooning
    this is how the cache-hash spreads + cost climbs."""
    try:
        from datetime import timedelta as _td
        from ..api.fasting import _stage_for

        active = (await db.execute(
            select(models.FastingSession)
            .where(models.FastingSession.ended_at.is_(None))
            .limit(1)
        )).scalar_one_or_none()

        today_d = datetime.now(timezone.utc).date()
        seven_ago = today_d - _td(days=6)

        rows = (await db.execute(
            select(models.DailySummary.fasting_hours)
            .where(models.DailySummary.date >= seven_ago)
            .where(models.DailySummary.date <= today_d)
        )).all()
        weekly_h = round(sum(r[0] or 0 for r in rows), 1)

        # Per-session aggregate over the trailing 7d for richer signal
        # (the daily_summary roll-up doesn't preserve per-fast length).
        seven_ago_dt = datetime.now(timezone.utc) - _td(days=7)
        sessions = (await db.execute(
            select(models.FastingSession)
            .where(models.FastingSession.ended_at.is_not(None))
            .where(models.FastingSession.started_at >= seven_ago_dt)
        )).scalars().all()
        completed_count = len(sessions)
        longest_h = 0.0
        religious_in_7d = False
        for s in sessions:
            if s.ended_at is not None:
                dur_h = (s.ended_at - s.started_at).total_seconds() / 3600.0
                longest_h = max(longest_h, dur_h)
            if (s.protocol or "").lower() in _RELIGIOUS_PROTOCOLS:
                religious_in_7d = True

        # Early-out only when there's truly nothing to say.
        if active is None and weekly_h == 0 and completed_count == 0:
            return None

        out: dict[str, Any] = {
            "weekly_fasting_hours": weekly_h,
            "last_7d_fast_count": completed_count,
            "last_7d_longest_h": round(longest_h, 1),
            "is_religious": religious_in_7d,
        }
        if active is not None:
            elapsed_h = (
                datetime.now(timezone.utc) - active.started_at
            ).total_seconds() / 3600.0
            stage, _next_at = _stage_for(elapsed_h)
            active_is_religious = (
                (active.protocol or "").lower() in _RELIGIOUS_PROTOCOLS
            )
            out["active_fast"] = {
                "protocol": active.protocol,
                "elapsed_h": round(elapsed_h, 1),
                "target_h": active.target_hours,
                "current_stage": stage,
                "is_religious": active_is_religious,
            }
            # An active religious fast trumps history for the top-level flag.
            if active_is_religious:
                out["is_religious"] = True
        return out
    except Exception:  # noqa: BLE001
        return None


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
        "fasting": await _fasting_status(db),
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
        "fasting": await _fasting_status(db),
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


STRENGTH_NUDGE_TOOL = {
    "name": "give_variety_nudge",
    "description": (
        "Return 0-2 exercise swaps that increase variety without changing "
        "the workout's intent. Each swap replaces a target exercise from "
        "today's plan with a different exercise of similar muscle / "
        "movement pattern that the user has done less recently. Return "
        "an empty `swaps` array if the plan already provides enough "
        "variety — better silence than a low-quality suggestion."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "swaps": {
                "type": "array",
                "maxItems": 2,
                "items": {
                    "type": "object",
                    "properties": {
                        "target_exercise_id": {
                            "type": "string",
                            "description": "exercise_id of one of today's "
                                           "exercises that should be swapped.",
                        },
                        "replacement_exercise_id": {
                            "type": "string",
                            "description": "exercise_id of the replacement, "
                                           "must come from `available_catalog`.",
                        },
                        "reason": {
                            "type": "string",
                            "description": "≤24 words. Why this swap is worth "
                                           "doing — cite recency, repetition, "
                                           "or a meaningful pattern shift.",
                        },
                    },
                    "required": ["target_exercise_id", "replacement_exercise_id", "reason"],
                },
            },
        },
        "required": ["swaps"],
    },
}


def _strength_nudge_system(tone: str) -> str:
    return f"""You are a strength coach reviewing a single planned workout
the deterministic generator just produced. The user trains mostly with
dumbbells + an adjustable bench at home.

{_tone_line(tone)}

Use the `give_variety_nudge` tool. Suggest 0-2 swaps. Rules:
- A swap MUST keep the SAME primary muscle group as the target exercise
  (look at `primary_muscle` in both lists).
- The replacement MUST come from `available_catalog`. Don't invent ids.
- Don't replace an exercise the user has logged in `recent_history`
  with one they've ALSO done a lot recently — pick something less worn.
- Return an empty `swaps` array if no swap is meaningfully better than
  the current plan. Quality > quantity.
- The `reason` cites concrete history (e.g. "Bulgarian Split Squat done
  3 of last 4 leg sessions; Cossack Squat untouched in 4 weeks") in
  ≤24 words.
"""


async def build_strength_nudge_payload(
    db: AsyncSession, workout_id: int, catalog_by_id: dict[str, dict],
) -> dict[str, Any]:
    """Bounded payload for variety nudge.

    Sends today's plan, last-4-week per-exercise frequency + last-seen
    date, and the catalog (id + name + primary_muscle + movement_pattern)
    of all exercises the user can do given current equipment + prefs."""
    workout = await db.get(models.StrengthWorkout, workout_id)
    if workout is None:
        return {}

    wex_rows = (await db.execute(
        select(models.StrengthWorkoutExercise)
        .where(models.StrengthWorkoutExercise.workout_id == workout_id)
        .order_by(models.StrengthWorkoutExercise.order_index)
    )).scalars().all()
    today_plan = []
    for wex in wex_rows:
        info = catalog_by_id.get(wex.exercise_id, {})
        today_plan.append({
            "exercise_id": wex.exercise_id,
            "name": info.get("name", wex.exercise_id),
            "primary_muscle": info.get("primary_muscle"),
            "movement_pattern": info.get("movement_pattern"),
            "target_sets": wex.target_sets,
            "target_reps_low": wex.target_reps_low,
            "target_reps_high": wex.target_reps_high,
        })

    # Last 4 weeks of completed/in-progress workouts on this user.
    cutoff = (workout.date - timedelta(days=28))
    prior_workouts = (await db.execute(
        select(models.StrengthWorkout)
        .where(models.StrengthWorkout.date >= cutoff)
        .where(models.StrengthWorkout.date < workout.date)
        .where(models.StrengthWorkout.status.in_(("completed", "in_progress")))
    )).scalars().all()
    prior_ids = [w.id for w in prior_workouts]

    recent_history: dict[str, dict[str, Any]] = {}
    if prior_ids:
        prior_wex = (await db.execute(
            select(models.StrengthWorkoutExercise.exercise_id,
                   models.StrengthWorkout.date)
            .join(models.StrengthWorkout,
                  models.StrengthWorkout.id ==
                  models.StrengthWorkoutExercise.workout_id)
            .where(models.StrengthWorkoutExercise.workout_id.in_(prior_ids))
        )).all()
        for ex_id, dt in prior_wex:
            entry = recent_history.setdefault(ex_id, {"count": 0, "last_seen": None})
            entry["count"] += 1
            iso = str(dt)
            if entry["last_seen"] is None or iso > entry["last_seen"]:
                entry["last_seen"] = iso

    # Catalog filtered by today's plan's primary-muscle universe + the
    # available equipment (already represented by what the generator
    # picked from). Cap at 60 entries to keep the payload small.
    today_muscles = {p["primary_muscle"] for p in today_plan if p.get("primary_muscle")}
    available_catalog = []
    for cid, info in catalog_by_id.items():
        if info.get("primary_muscle") in today_muscles:
            available_catalog.append({
                "exercise_id": cid,
                "name": info.get("name", cid),
                "primary_muscle": info.get("primary_muscle"),
                "movement_pattern": info.get("movement_pattern"),
            })
    available_catalog = available_catalog[:60]

    return {
        "today": {
            "date": str(workout.date),
            "split": workout.split_focus,
            "exercises": today_plan,
        },
        "recent_history": recent_history,  # exercise_id -> {count, last_seen}
        "available_catalog": available_catalog,
    }


async def strength_nudge(
    db: AsyncSession, workout_id: int, cfg: models.AiConfig,
    catalog_by_id: dict[str, dict],
) -> AiResult:
    """Generate up to 2 variety-swap suggestions for today's plan."""
    if not cfg.enabled or not cfg.anthropic_api_key:
        raise RuntimeError("AI is disabled or no API key configured")
    payload = await build_strength_nudge_payload(db, workout_id, catalog_by_id)
    if not payload:
        raise RuntimeError("workout not found")
    user_text = (
        f"Today's plan and the user's recent strength history:\n\n"
        f"{json.dumps(payload, indent=2, default=str)}\n"
    )
    client = AsyncAnthropic(api_key=cfg.anthropic_api_key)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=400,
        system=_cached_system(_strength_nudge_system(cfg.tone)),
        tools=[STRENGTH_NUDGE_TOOL],
        tool_choice={"type": "tool", "name": "give_variety_nudge"},
        messages=[{"role": "user", "content": user_text}],
    )
    tool_input: dict[str, Any] = {"swaps": []}
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use" and block.name == "give_variety_nudge":
            tool_input = block.input  # type: ignore[assignment]
            break
    return AiResult(
        content=json.dumps(tool_input),
        model=resp.model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )


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


DELOAD_TOOL = {
    "name": "give_deload_judgment",
    "description": (
        "Decide if the user needs a deload right now based on multi-signal "
        "recovery + training-load + strength-performance data. Return a "
        "structured judgment — only recommend a deload when signals "
        "converge. Better silence than a false alarm."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "should_deload": {
                "type": "boolean",
                "description": "Whether the user should deload this week.",
            },
            "severity": {
                "type": "string",
                "enum": ["none", "light", "moderate", "rest"],
                "description": (
                    "none = train as planned; "
                    "light = cut volume ~20% (one fewer set/exercise); "
                    "moderate = cut volume ~40% AND weight ~10%; "
                    "rest = skip today entirely, prioritise sleep."
                ),
            },
            "headline": {
                "type": "string",
                "description": "≤14 words. The single most important read on recovery state.",
            },
            "evidence": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "2-4 bullets, ≤22 words each, EACH citing a specific "
                    "number from the data (HRV trend, RHR delta, sleep "
                    "debt, TSB, avg rating, missed sets, etc)."
                ),
            },
            "recommendation": {
                "type": "string",
                "description": "≤30 words. Concrete action for today.",
            },
        },
        "required": ["should_deload", "severity", "headline", "evidence", "recommendation"],
    },
}


def _deload_system(tone: str) -> str:
    return f"""You are a brief strength coach reading the user's recovery
+ training-load + recent strength-performance signals to decide if they
need a deload right now.

{_tone_line(tone)}

Use the `give_deload_judgment` tool. Rules:
- Default to NO deload (severity=none) unless multiple signals converge.
- A single bad day is not enough — look for trends (HRV dropping AND
  RHR rising AND avg_rating falling, sleep_debt accumulating, TSB
  deeply negative, missed sets stacking up).
- "moderate" only for clear over-reaching (HRV ≥1σ below baseline for
  ≥4 days, AND avg_rating drifting ≥0.5 below baseline).
- "rest" only when recovery is severely impaired (sickness signals: RHR
  ≥10bpm above baseline + sleep debt + low HRV) — flag honestly.
- Every evidence bullet must cite an actual number from the data.
- Headline is the read, not the prescription.
"""


async def build_deload_payload(db: AsyncSession) -> dict[str, Any]:
    """Bounded signals payload for the deload-trigger AI judgment.

    Pulls 28 days of dailies (splits into trailing-7d vs 8-28d baseline
    for delta math, computed server-side) + last 14d of strength workout
    aggregates (avg rating, missed/skipped sets, weights).
    """
    today = datetime.now(timezone.utc).date()
    daily = await _daily_rows(db, 28)
    recent = [r for r in daily if r["date"] >= str(today - timedelta(days=7))]
    baseline = [r for r in daily if r["date"] < str(today - timedelta(days=7))]

    def _mean(rows: list[dict[str, Any]], key: str) -> float | None:
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    trends: dict[str, dict[str, Any]] = {}
    for k in ("rhr", "hrv", "recovery", "sleep_h", "sleep_debt_h",
              "readiness", "tsb", "ctl", "atl"):
        cur = _mean(recent, k)
        base = _mean(baseline, k)
        trends[k] = {
            "last_7d": cur,
            "baseline_8_28d": base,
            "delta": round(cur - base, 2) if cur is not None and base is not None else None,
        }

    # Strength performance over the last 14d
    since = today - timedelta(days=14)
    workouts = (await db.execute(
        select(models.StrengthWorkout)
        .where(models.StrengthWorkout.date >= since)
        .where(models.StrengthWorkout.status.in_(("completed", "in_progress")))
    )).scalars().all()
    wex_ids: list[int] = []
    if workouts:
        wex_rows = (await db.execute(
            select(models.StrengthWorkoutExercise.id)
            .where(models.StrengthWorkoutExercise.workout_id.in_(
                [w.id for w in workouts]
            ))
        )).all()
        wex_ids = [r[0] for r in wex_rows]
    strength_signal: dict[str, Any] = {
        "n_workouts": len(workouts),
        "avg_rating": None,
        "missed_or_skipped_sets": 0,
        "total_logged_sets": 0,
    }
    if wex_ids:
        sets_rows = (await db.execute(
            select(models.StrengthSet)
            .where(models.StrengthSet.workout_exercise_id.in_(wex_ids))
        )).scalars().all()
        ratings = [s.rating for s in sets_rows if s.rating is not None and not s.skipped]
        skipped = sum(1 for s in sets_rows if s.skipped)
        missed = sum(1 for s in sets_rows
                     if s.actual_reps is None and not s.skipped)
        logged = sum(1 for s in sets_rows
                     if s.actual_reps is not None and not s.skipped)
        strength_signal["avg_rating"] = (
            round(sum(ratings) / len(ratings), 2) if ratings else None
        )
        strength_signal["missed_or_skipped_sets"] = skipped + missed
        strength_signal["total_logged_sets"] = logged

    return {
        "today": str(today),
        "profile": await _profile_ctx(db),
        "trends": trends,
        "recent_dailies": recent,
        "strength_last_14d": strength_signal,
        "fasting": await _fasting_status(db),
        "trend_badges": await compute_badges(db, max_badges=4),
    }


async def deload_check(db: AsyncSession, cfg: models.AiConfig) -> AiResult:
    """Multi-signal AI judgment: should the user deload right now?"""
    if not cfg.enabled or not cfg.anthropic_api_key:
        raise RuntimeError("AI is disabled or no API key configured")
    payload = await build_deload_payload(db)
    user_text = (
        f"Decide if the user should deload right now. The data covers "
        f"their last 28 days of vitals + last 14 days of strength "
        f"performance:\n\n"
        f"{json.dumps(payload, indent=2, default=str)}\n"
    )
    client = AsyncAnthropic(api_key=cfg.anthropic_api_key)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=500,
        system=_cached_system(_deload_system(cfg.tone)),
        tools=[DELOAD_TOOL],
        tool_choice={"type": "tool", "name": "give_deload_judgment"},
        messages=[{"role": "user", "content": user_text}],
    )
    tool_input: dict[str, Any] = {}
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use" and block.name == "give_deload_judgment":
            tool_input = block.input  # type: ignore[assignment]
            break
    if not tool_input:
        tool_input = {
            "should_deload": False,
            "severity": "none",
            "headline": "Could not produce a deload judgment from the data",
            "evidence": [],
            "recommendation": "Train as planned; try again later.",
        }
    return AiResult(
        content=json.dumps(tool_input),
        model=resp.model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )


FOCUS_CUE_TOOL = {
    "name": "give_focus_cue",
    "description": (
        "Return a short, specific pre-workout coaching cue for the "
        "user's planned session. Tied to TODAY'S exercises + recent "
        "performance — not generic motivation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {
                "type": "string",
                "description": "≤10 words. The single thing to focus on this session.",
            },
            "tone": {"type": "string", "enum": ["good", "warn", "bad", "neutral"]},
            "cue": {
                "type": "string",
                "description": (
                    "≤45 words. Two sentences max. Sentence 1: form/technique "
                    "focus on a SPECIFIC exercise from today's plan. "
                    "Sentence 2: a load/volume warning or push, citing "
                    "recent history (avg rating, trend) when relevant."
                ),
            },
        },
        "required": ["headline", "tone", "cue"],
    },
}


def _focus_cue_system(tone: str) -> str:
    return f"""You are a brief strength coach giving a single pre-workout
focus cue for the user's planned session today.

{_tone_line(tone)}

Use the `give_focus_cue` tool. Rules:
- Reference SPECIFIC exercises from today's plan, not generic advice.
- If recent ratings on a specific lift have been creeping down, mention
  it and suggest conservative weight on that lift.
- If a lift hasn't been touched in 4+ weeks, mention it's fresh — be
  conservative on the first set.
- Cue must be actionable — "engage your lats" is not actionable;
  "pause 1s at the bottom of the Decline Push-Up" is.
- Don't editorialise about recovery state — that's the deload banner's
  job. Stay focused on form / load / pacing for the planned lifts.
"""


async def build_focus_cue_payload(
    db: AsyncSession, workout_id: int, catalog_by_id: dict[str, dict],
) -> dict[str, Any]:
    """Bounded payload for the per-workout focus cue.

    Slim: today's exercise list (id + name + target prescription) +
    per-exercise recent avg_rating + weeks-since-last-seen + the
    today recovery context already on the workout row.
    """
    workout = await db.get(models.StrengthWorkout, workout_id)
    if workout is None:
        return {}

    wex_rows = (await db.execute(
        select(models.StrengthWorkoutExercise)
        .where(models.StrengthWorkoutExercise.workout_id == workout_id)
        .order_by(models.StrengthWorkoutExercise.order_index)
    )).scalars().all()
    today_plan: list[dict[str, Any]] = []
    for wex in wex_rows:
        info = catalog_by_id.get(wex.exercise_id, {})
        today_plan.append({
            "exercise_id": wex.exercise_id,
            "name": info.get("name", wex.exercise_id),
            "primary_muscle": info.get("primary_muscle"),
            "is_compound": info.get("is_compound", False),
            "target": (
                f"{wex.target_sets}x{wex.target_reps_low}"
                f"{('-' + str(wex.target_reps_high)) if wex.target_reps_high != wex.target_reps_low else ''}"
                f"{(' @ ' + str(wex.target_weight_lb) + 'lb') if wex.target_weight_lb else ''}"
            ),
        })

    # Trailing 6w per-exercise history: avg rating, last seen.
    cutoff = workout.date - timedelta(days=42)
    prior_q = (await db.execute(
        select(
            models.StrengthWorkoutExercise.exercise_id,
            models.StrengthWorkout.date,
            models.StrengthSet.rating,
        )
        .join(
            models.StrengthSet,
            models.StrengthSet.workout_exercise_id == models.StrengthWorkoutExercise.id,
        )
        .join(
            models.StrengthWorkout,
            models.StrengthWorkout.id == models.StrengthWorkoutExercise.workout_id,
        )
        .where(models.StrengthWorkout.date >= cutoff)
        .where(models.StrengthWorkout.date < workout.date)
        .where(models.StrengthSet.skipped.is_(False))
    )).all()

    by_ex: dict[str, dict[str, Any]] = {}
    for ex_id, dt, rating in prior_q:
        entry = by_ex.setdefault(ex_id, {"ratings": [], "last_seen": None})
        if rating is not None:
            entry["ratings"].append(int(rating))
        iso = str(dt)
        if entry["last_seen"] is None or iso > entry["last_seen"]:
            entry["last_seen"] = iso
    today_iso = str(workout.date)
    history = {}
    for ex_id, e in by_ex.items():
        ratings = e["ratings"]
        ls = e["last_seen"]
        days_ago = None
        if ls is not None:
            try:
                days_ago = (workout.date - date.fromisoformat(ls)).days
            except Exception:  # noqa: BLE001
                days_ago = None
        history[ex_id] = {
            "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
            "samples": len(ratings),
            "days_since_last": days_ago,
        }

    return {
        "today": today_iso,
        "split": workout.split_focus,
        "recovery_score": workout.recovery_score_used,
        "readiness_score": workout.readiness_score_used,
        "sleep_h": (round(workout.sleep_h_used, 1)
                    if workout.sleep_h_used is not None else None),
        "plan": today_plan,
        "history_6w": history,
    }


async def strength_focus_cue(
    db: AsyncSession, workout_id: int, cfg: models.AiConfig,
    catalog_by_id: dict[str, dict],
) -> AiResult:
    """Pre-workout focus cue — short, plan-specific."""
    if not cfg.enabled or not cfg.anthropic_api_key:
        raise RuntimeError("AI is disabled or no API key configured")
    payload = await build_focus_cue_payload(db, workout_id, catalog_by_id)
    if not payload:
        raise RuntimeError("workout not found")
    user_text = (
        f"User is about to start their planned session. Give one "
        f"focus cue tied to today's exercises + recent history.\n\n"
        f"{json.dumps(payload, indent=2, default=str)}\n"
    )
    client = AsyncAnthropic(api_key=cfg.anthropic_api_key)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=300,
        system=_cached_system(_focus_cue_system(cfg.tone)),
        tools=[FOCUS_CUE_TOOL],
        tool_choice={"type": "tool", "name": "give_focus_cue"},
        messages=[{"role": "user", "content": user_text}],
    )
    tool_input: dict[str, Any] = {}
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use" and block.name == "give_focus_cue":
            tool_input = block.input  # type: ignore[assignment]
            break
    if not tool_input:
        tool_input = {
            "headline": "No cue generated", "tone": "neutral",
            "cue": "Train as planned.",
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


def _normalize_array_field(tool_input: dict[str, Any], key: str) -> None:
    """Claude tool-use occasionally returns array fields as a string
    containing `<parameter name="item">…</parameter>` blocks instead of
    a proper JSON array (a known model quirk on some prompts). Rewrites
    `tool_input[key]` in place so downstream consumers always see a list.

    Also folds in a stray top-level `item` key if the model lifted one
    of the array elements out of the array."""
    import re as _re
    val = tool_input.get(key)
    extra = tool_input.pop("item", None)
    if isinstance(val, list):
        if isinstance(extra, str) and extra:
            val.append(extra)
        tool_input[key] = val
        return
    if isinstance(val, str):
        # Extract <parameter name="item">…</parameter> blocks first.
        tags = _re.findall(r"<parameter[^>]*>([\s\S]*?)</parameter>", val)
        items = [s.strip() for s in tags if s.strip()]
        if not items:
            # Fallback: split on newlines.
            items = [s.strip() for s in val.splitlines() if s.strip()]
        if isinstance(extra, str) and extra.strip():
            items.append(extra.strip())
        tool_input[key] = items
        return
    tool_input[key] = []


# ─────────────── Cardio coach ───────────────

CARDIO_COACH_TOOL = {
    "name": "give_cardio_coach",
    "description": (
        "Return a structured analysis of the user's cardio pattern over the "
        "trailing window: zone distribution, weekly volume, polarization, "
        "concrete recommendation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {
                "type": "string",
                "description": "≤14 words. Single most important read on current cardio dose.",
            },
            "tone": {"type": "string", "enum": ["good", "warn", "bad", "neutral"]},
            "polarized_assessment": {
                "type": "string",
                "description": (
                    "≤30 words. Is the Z1/Z2 : Z3+ ratio healthy? Polarized "
                    "training research says ~80:20 easy:hard for endurance "
                    "athletes; recreational users land closer to 70:30."
                ),
            },
            "volume_assessment": {
                "type": "string",
                "description": "≤30 words. Is weekly volume appropriate (too much / too little / right)?",
            },
            "evidence": {
                "type": "array",
                "items": {"type": "string"},
                "description": "2-4 bullets, each citing specific numbers (Z2 min/week, polarized ratio, …).",
            },
            "recommendation": {
                "type": "string",
                "description": "≤30 words. Concrete lever (more Z2, cut grey zone, recovery week, etc).",
            },
        },
        "required": [
            "headline", "tone", "polarized_assessment",
            "volume_assessment", "evidence", "recommendation",
        ],
    },
}


def _cardio_coach_system(tone: str) -> str:
    return f"""You are a brief cardio coach reading the user's last 30
days of HR-zone training data. Use the `give_cardio_coach` tool.

{_tone_line(tone)}

Frame your assessment against widely-accepted training principles:
- Polarized training (Seiler) — ~80% time in Z1+Z2 ("easy"), ~20% in
  Z4+Z5 ("hard"), minimal Z3 ("grey zone") for best aerobic gains.
- Recreational adults benefit from 150 min/wk Z2-or-above; 300 min/wk
  is the target for cardiovascular fitness gains.
- Too much Z3 indicates time spent too hard for recovery, too easy
  for stimulus — biggest single fixable problem in most amateurs.

Cite specific numbers in evidence. Don't be vague."""


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Plain Pearson r. Returns None when fewer than 5 paired samples or
    when either series has zero variance. Kept dependency-light because
    we already do everything else in pure Python."""
    n = len(xs)
    if n < 5 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    return sxy / ((sxx ** 0.5) * (syy ** 0.5))


_CORR_METRICS = ("rhr", "hrv", "recovery", "sleep_h", "readiness", "steps", "tsb")


def _top_correlations(
    rows: list[dict[str, Any]], min_abs: float = 0.5, top_k: int = 3,
) -> list[dict[str, Any]]:
    """Pairwise Pearson between trailing-window vitals (ANALYTICS-4).

    Returns the strongest correlations across the input rows so the
    Coach AI can name-check real-data relationships ("your sleep_h
    and readiness ride at r=0.78") instead of speculating from a
    spotty individual-day view. Caps at top_k and filters out
    anything weaker than |r| ≥ min_abs to keep the payload terse."""
    if len(rows) < 7:
        return []
    out: list[tuple[str, str, float]] = []
    for i, a in enumerate(_CORR_METRICS):
        for b in _CORR_METRICS[i + 1:]:
            xs: list[float] = []
            ys: list[float] = []
            for r in rows:
                xa = r.get(a)
                xb = r.get(b)
                if xa is None or xb is None:
                    continue
                xs.append(float(xa))
                ys.append(float(xb))
            r_val = _pearson(xs, ys)
            if r_val is None:
                continue
            if abs(r_val) < min_abs:
                continue
            out.append((a, b, r_val))
    out.sort(key=lambda t: abs(t[2]), reverse=True)
    return [
        {"a": a, "b": b, "r": round(rv, 2), "n": sum(
            1 for r in rows if r.get(a) is not None and r.get(b) is not None
        )}
        for (a, b, rv) in out[:top_k]
    ]


def _wow_deltas(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Week-over-week deltas for the same metric set (ANALYTICS-4).

    Splits the trailing rows into the last 7 days and the prior 7 days
    and returns mean + absolute delta + percent change per metric. The
    AI uses this in evidence bullets ("HRV is up 8% vs last week").
    """
    if len(rows) < 7:
        return {}
    last = rows[-7:]
    prior = rows[-14:-7] if len(rows) >= 14 else []
    out: dict[str, dict[str, Any]] = {}
    for k in _CORR_METRICS:
        vs_last = [r[k] for r in last if r.get(k) is not None]
        vs_prior = [r[k] for r in prior if r.get(k) is not None]
        if not vs_last or not vs_prior:
            continue
        m_last = sum(vs_last) / len(vs_last)
        m_prior = sum(vs_prior) / len(vs_prior)
        delta = m_last - m_prior
        pct = (delta / m_prior * 100.0) if m_prior else None
        out[k] = {
            "last_7d": round(m_last, 2),
            "prior_7d": round(m_prior, 2),
            "delta": round(delta, 2),
            "pct_change": round(pct, 1) if pct is not None else None,
        }
    return out


async def _recent_alerts_ctx(
    db: AsyncSession, days: int = 14, limit: int = 6,
) -> list[dict[str, Any]]:
    """Compact ai_alerts feed for Coach payloads (ALERTS-2).

    Returns last N alerts in the trailing window, prefering severity ordering
    (bad > warn > info > good), then recency. Only the fields the AI actually
    benefits from — date, severity, kind, metric, title — so we don't blow up
    the cached-payload size or accidentally include body prose that already
    paraphrases the numbers the AI will see in its own metric blocks.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await db.execute(
        select(models.AiAlert)
        .where(models.AiAlert.created_at >= cutoff)
        .order_by(models.AiAlert.created_at.desc())
        .limit(limit * 4)  # over-fetch so the severity sort below has room
    )).scalars().all()
    sev_weight = {"bad": 3, "warn": 2, "info": 1, "good": 0}
    ranked = sorted(
        rows,
        key=lambda r: (
            sev_weight.get(r.severity, 0),
            int(r.created_at.timestamp()),
        ),
        reverse=True,
    )[:limit]
    return [
        {
            "date": r.created_at.date().isoformat(),
            "severity": r.severity,
            "kind": r.kind,
            "metric": r.metric,
            "title": r.title,
        }
        for r in ranked
    ]


async def build_cardio_coach_payload(db: AsyncSession) -> dict[str, Any]:
    """Bounded payload for the cardio coach AI card."""
    from ..analytics.cardio import cardio_summary
    summary = await cardio_summary(db, days=30)
    daily = await _daily_rows(db, 28)
    return {
        "today": datetime.now(timezone.utc).date().isoformat(),
        "profile": await _profile_ctx(db),
        "cardio_30d": summary,
        "recent_alerts": await _recent_alerts_ctx(db),
        "top_correlations": _top_correlations(daily),
        "wow_deltas": _wow_deltas(daily),
    }


async def cardio_coach(db: AsyncSession, cfg: models.AiConfig) -> AiResult:
    """Structured AI analysis of cardio zone distribution + dose."""
    if not cfg.enabled or not cfg.anthropic_api_key:
        raise RuntimeError("AI is disabled or no API key configured")
    payload = await build_cardio_coach_payload(db)
    user_text = (
        f"Analyze this user's cardio pattern over the last 30 days and "
        f"return structured advice via the `give_cardio_coach` tool:\n\n"
        f"{json.dumps(payload, indent=2, default=str)}\n"
    )
    client = AsyncAnthropic(api_key=cfg.anthropic_api_key)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=500,
        system=_cached_system(_cardio_coach_system(cfg.tone)),
        tools=[CARDIO_COACH_TOOL],
        tool_choice={"type": "tool", "name": "give_cardio_coach"},
        messages=[{"role": "user", "content": user_text}],
    )
    tool_input: dict[str, Any] = {}
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use" and block.name == "give_cardio_coach":
            tool_input = block.input  # type: ignore[assignment]
            break
    if not tool_input:
        tool_input = {
            "headline": "Not enough cardio data to coach on yet",
            "tone": "neutral",
            "polarized_assessment": "Need more sessions logged before zone math is meaningful.",
            "volume_assessment": "Unknown.",
            "evidence": [],
            "recommendation": "Log a few cardio sessions then retry.",
        }
    _normalize_array_field(tool_input, "evidence")
    return AiResult(
        content=json.dumps(tool_input),
        model=resp.model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )


# ─────────────── Workout coach (multi-signal) ───────────────

WORKOUT_COACH_TOOL = {
    "name": "give_workout_coach",
    "description": (
        "Multi-signal weekly coach. Synthesizes strength, cardio, sleep, "
        "HRV, and training load into a single guidance card."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {
                "type": "string",
                "description": "≤14 words. Top-level read on this week's training state.",
            },
            "tone": {"type": "string", "enum": ["good", "warn", "bad", "neutral"]},
            "what_is_working": {
                "type": "string",
                "description": "≤30 words. Specific behaviour worth keeping.",
            },
            "what_to_change": {
                "type": "string",
                "description": "≤30 words. Single most actionable adjustment.",
            },
            "evidence": {
                "type": "array",
                "items": {"type": "string"},
                "description": "2-4 bullets citing specific signals (HRV delta, sleep debt, missed sets, Z2 min, etc).",
            },
            "weekly_plan_hint": {
                "type": "string",
                "description": "≤40 words. How to balance strength + cardio + rest this week given the data.",
            },
        },
        "required": [
            "headline", "tone", "what_is_working", "what_to_change",
            "evidence", "weekly_plan_hint",
        ],
    },
}


def _workout_coach_system(tone: str) -> str:
    return f"""You are the user's weekly training coach. You see:
- Last 14 days of strength performance (avg rating, missed sets, muscle volume)
- Last 30 days of cardio (HR zones, polarization, volume by type)
- Last 28 days of vitals (HRV, RHR, sleep, readiness, training load CTL/ATL/TSB)
- Today's daily summary
- recent_alerts — anomaly alerts the system already flagged (high RHR,
  suppressed HRV, illness risk, broken streaks). Treat these as confirmed
  signals worth name-checking when they cluster around the week's pattern.
- top_correlations — pre-computed Pearson r between trailing-28d vitals
  (only |r| ≥ 0.5 kept, top 3). Use these to make causal-sounding
  observations defensible: "your sleep_h and readiness ride at r=0.78
  this month, so the bad readiness today follows from short sleep".
- wow_deltas — last-7d vs prior-7d mean + percent change per metric.
  Quote the pct_change figure in evidence ("HRV +8% vs last week")
  rather than hand-computing from the dailies.
- fasting — null when the user isn't doing intermittent fasting,
  otherwise weekly_fasting_hours / last_7d_fast_count /
  last_7d_longest_h / is_religious / optional active_fast block.
  IMPORTANT: long fasts compress HRV and lower RHR without indicating
  overtraining. If `fasting.weekly_fasting_hours` is ≥ 70 OR
  `last_7d_fast_count` ≥ 3, suppressed HRV / RHR readings are likely
  fasting-driven, not training-driven — do NOT recommend a deload on
  HRV grounds alone. Check sleep_debt and missed sets too.

{_tone_line(tone)}

Use the `give_workout_coach` tool. Rules:
- Synthesize across silos — don't just report strength OR cardio.
- The MOST common useful insight is the interaction: e.g. "your cardio
  volume is good but HRV is suppressed; pull back hard sessions this week"
  or "strength is plateauing because sleep debt is climbing".
- Be specific. Generic motivation is bad. Cite numbers in evidence.
- A single high-confidence change beats five vague ones.
- If recent_alerts cluster (e.g. two RHR anomalies in five days), weight
  the recommendation accordingly. Ignore stale or isolated ones.
- Prefer wow_deltas and top_correlations over re-deriving the same
  numbers from recent_dailies — they're already correct and bounded."""


# ─────────────── Sleep coach (COACH-5) ───────────────

SLEEP_COACH_TOOL = {
    "name": "give_sleep_coach",
    "description": (
        "Verdict on whether the user's sleep pattern is supporting "
        "recovery — pulls duration, consistency, stage breakdown, "
        "sleep debt, and HRV/RHR drift."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {
                "type": "string",
                "description": "≤14 words. One-line verdict.",
            },
            "tone": {"type": "string", "enum": ["good", "warn", "bad", "neutral"]},
            "supporting_recovery": {
                "type": "string",
                "enum": ["yes", "marginal", "no"],
                "description": "Bottom-line: is sleep currently a force-multiplier or a drag?",
            },
            "duration_assessment": {
                "type": "string",
                "description": "≤30 words. How does avg sleep_h vs target_h look, and how stable is it?",
            },
            "consistency_assessment": {
                "type": "string",
                "description": "≤30 words. Bedtime/wake variance picture — is the schedule shifting?",
            },
            "stage_assessment": {
                "type": "string",
                "description": "≤30 words. Deep/REM/light proportions — flag if deep is suppressed.",
            },
            "recovery_link": {
                "type": "string",
                "description": "≤30 words. Whether HRV/RHR/readiness drift tracks sleep changes.",
            },
            "evidence": {
                "type": "array",
                "items": {"type": "string"},
                "description": "2-4 bullets citing specific signals (sleep_debt_h, 7d avg sleep, HRV WoW, etc).",
            },
            "recommendation": {
                "type": "string",
                "description": "≤40 words. Single most actionable adjustment, with WHEN.",
            },
        },
        "required": [
            "headline", "tone", "supporting_recovery", "duration_assessment",
            "consistency_assessment", "stage_assessment", "recovery_link",
            "evidence", "recommendation",
        ],
    },
}


def _sleep_coach_system(tone: str) -> str:
    return f"""You are the user's sleep coach. You see a 28-day window of:
- per-night sleep_h, sleep_score, sleep_consistency_score, sleep_debt_h
- 7-day avg vs 28-day baseline for each
- stage breakdown (deep_h / rem_h / light_h / awake_h) summed over last 7 days
- HRV / RHR / readiness 7d-avg vs 28d-baseline so you can correlate
- overnight_env_7d — averaged sleep-window bedroom temp/humidity etc.
  from Home Assistant sensors (may be empty if HA isn't configured).
  Cite specific numbers when available: "bedroom temp avg 19.4 °C is
  well within the 16-19 °C sleep-quality sweet spot" or "humidity at
  62% is on the high side, can contribute to night sweats". Don't
  over-weight a single sensor pair — these are environmental hints,
  not the primary signal.
- profile.sleep_target_h and the user's tone preference
- top_correlations between sleep and downstream metrics
- recent_alerts the system already flagged (suppressed HRV, high RHR, illness risk)

{_tone_line(tone)}

Use the `give_sleep_coach` tool. Rules:
- The verdict (supporting_recovery yes / marginal / no) is the most
  important field — clients use it for the headline color.
- Be specific. Quote numbers in evidence. "Avg sleep 6.4 h vs 7.5 h
  target" beats "you're not sleeping enough".
- Distinguish DURATION (how long), CONSISTENCY (variance), and STAGES
  (composition). All three can independently be off.
- If stage data is mostly missing, say so in stage_assessment — don't
  hallucinate a deep-sleep estimate.
- The recovery_link should defend (or push back on) the supporting_recovery
  verdict using the HRV / RHR / readiness deltas. Don't just restate.
- The recommendation should pick the SINGLE biggest lever — earlier
  bedtime, more consistent wake, caffeine cutoff, etc. Not a list.
"""


async def _overnight_env_readings(
    db: AsyncSession, days: int = 7,
) -> dict[str, Any]:
    """Average bedroom temp / humidity / etc. across last N overnight
    windows (defined as 23:00-06:00 local each night). Returns empty
    dict if no env_readings rows match — caller should gracefully
    elide the section in payloads.

    Naive timezone — uses UTC for the 23:00-06:00 cutoff which is fine
    in practice because we're averaging and the user's bedtime is
    typically a stable offset; mis-bucketing one hour at the edges
    doesn't move the mean meaningfully."""
    from statistics import mean
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    since = _dt.now(_tz.utc) - _td(days=days)
    rows = (await db.execute(
        select(models.EnvReading)
        .where(models.EnvReading.time >= since)
    )).scalars().all()
    if not rows:
        return {"days": days, "sources": {}}
    # Bucket by (source, metric); only keep rows in the overnight
    # window 23:00-06:00 UTC. This filters out daytime spikes from
    # the bedroom sensor that would skew the "sleep environment" read.
    buckets: dict[tuple[str, str], list[float]] = {}
    for r in rows:
        h = r.time.hour
        if not (h >= 23 or h < 6):
            continue
        key = (r.source, r.metric)
        buckets.setdefault(key, []).append(r.value)
    if not buckets:
        return {"days": days, "sources": {}}
    sources: dict[str, dict[str, float]] = {}
    for (source, metric), vals in buckets.items():
        sources.setdefault(source, {})[metric] = round(mean(vals), 2)
    return {"days": days, "sources": sources}


async def _sleep_stage_breakdown(db: AsyncSession, days: int = 7) -> dict[str, Any]:
    """Sum stage seconds over a trailing window. Empty if no stage rows."""
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    from sqlalchemy import func as _func
    since = _dt.now(_tz.utc) - _td(days=days)
    rows = (await db.execute(
        select(
            models.SleepStage.stage,
            _func.sum(models.SleepStage.duration_s).label("total_s"),
        )
        .where(models.SleepStage.time >= since)
        .group_by(models.SleepStage.stage)
    )).all()
    if not rows:
        return {"days": days, "stages_seconds": {}}
    by_stage = {r.stage: int(r.total_s or 0) for r in rows}
    return {"days": days, "stages_seconds": by_stage}


async def build_sleep_coach_payload(db: AsyncSession) -> dict[str, Any]:
    """Bounded payload for the sleep coach card."""
    from statistics import mean
    daily = await _daily_rows(db, 28)
    last7 = daily[-7:] if len(daily) >= 7 else daily

    def _avg(rows: list[dict[str, Any]], key: str) -> float | None:
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(mean(vals), 2) if vals else None

    last7_summary = {
        "sleep_h": _avg(last7, "sleep_h"),
        "sleep_score": _avg(last7, "sleep_score"),
        "sleep_debt_h": _avg(last7, "sleep_debt_h"),
        "hrv": _avg(last7, "hrv"),
        "rhr": _avg(last7, "rhr"),
        "readiness": _avg(last7, "readiness"),
    }
    baseline_28d = {
        "sleep_h": _avg(daily, "sleep_h"),
        "sleep_score": _avg(daily, "sleep_score"),
        "sleep_debt_h": _avg(daily, "sleep_debt_h"),
        "hrv": _avg(daily, "hrv"),
        "rhr": _avg(daily, "rhr"),
        "readiness": _avg(daily, "readiness"),
    }
    return {
        "today": datetime.now(timezone.utc).date().isoformat(),
        "profile": await _profile_ctx(db),
        "last7_summary": last7_summary,
        "baseline_28d": baseline_28d,
        "recent_dailies": daily,
        "stage_breakdown_7d": await _sleep_stage_breakdown(db, days=7),
        "overnight_env_7d": await _overnight_env_readings(db, days=7),
        "fasting_status": await _fasting_status(db),
        "recent_alerts": await _recent_alerts_ctx(db),
        "top_correlations": _top_correlations(daily),
        "wow_deltas": _wow_deltas(daily),
    }


async def sleep_coach(db: AsyncSession, cfg: models.AiConfig) -> AiResult:
    """Structured AI verdict on whether sleep is currently supporting
    recovery."""
    if not cfg.enabled or not cfg.anthropic_api_key:
        raise RuntimeError("AI is disabled or no API key configured")
    payload = await build_sleep_coach_payload(db)
    user_text = (
        f"Read the user's last 28 days of sleep + recovery vitals and "
        f"return a structured verdict via the `give_sleep_coach` tool:\n\n"
        f"{json.dumps(payload, indent=2, default=str)}\n"
    )
    client = AsyncAnthropic(api_key=cfg.anthropic_api_key)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=600,
        system=_cached_system(_sleep_coach_system(cfg.tone)),
        tools=[SLEEP_COACH_TOOL],
        tool_choice={"type": "tool", "name": "give_sleep_coach"},
        messages=[{"role": "user", "content": user_text}],
    )
    tool_input: dict[str, Any] = {}
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use" and block.name == "give_sleep_coach":
            tool_input = block.input  # type: ignore[assignment]
            break
    if not tool_input:
        tool_input = {
            "headline": "Not enough sleep data to coach yet",
            "tone": "neutral",
            "supporting_recovery": "marginal",
            "duration_assessment": "Need a few more nights logged.",
            "consistency_assessment": "Need a few more nights logged.",
            "stage_assessment": "No stage data available yet.",
            "recovery_link": "Insufficient overlap with HRV/RHR data.",
            "evidence": [],
            "recommendation": "Keep wearing the watch overnight and re-check in a week.",
        }
    _normalize_array_field(tool_input, "evidence")
    return AiResult(
        content=json.dumps(tool_input),
        model=resp.model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )


# ─────────────── Recovery coach (COACH-6) ───────────────

RECOVERY_COACH_TOOL = {
    "name": "give_recovery_coach",
    "description": (
        "Multi-week recovery trend read: HRV + RHR + skin-temp Δ + "
        "readiness + recovery score. Broader than the per-workout "
        "deload check; surfaces directional momentum, not single-day "
        "anomalies."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {
                "type": "string",
                "description": "≤14 words. One-line directional read.",
            },
            "tone": {"type": "string", "enum": ["good", "warn", "bad", "neutral"]},
            "trend_direction": {
                "type": "string",
                "enum": ["improving", "flat", "declining"],
                "description": "Multi-week momentum across the core recovery signals.",
            },
            "hrv_assessment": {
                "type": "string",
                "description": "≤30 words. 7d vs 28d HRV picture and what that implies.",
            },
            "rhr_assessment": {
                "type": "string",
                "description": "≤30 words. 7d vs 28d RHR picture and what that implies.",
            },
            "skin_temp_assessment": {
                "type": "string",
                "description": "≤30 words. Skin-temp Δ trend — flag clustered positive deltas as illness risk.",
            },
            "readiness_assessment": {
                "type": "string",
                "description": "≤30 words. Daily-summary readiness/recovery score trajectory.",
            },
            "evidence": {
                "type": "array",
                "items": {"type": "string"},
                "description": "2-4 bullets with specific numbers (HRV -6% vs 28d, RHR +3bpm, 3 nights skin-temp Δ ≥ +0.3 °C, etc).",
            },
            "recommendation": {
                "type": "string",
                "description": "≤40 words. Single most actionable adjustment, accounting for trend direction.",
            },
        },
        "required": [
            "headline", "tone", "trend_direction", "hrv_assessment",
            "rhr_assessment", "skin_temp_assessment", "readiness_assessment",
            "evidence", "recommendation",
        ],
    },
}


def _recovery_coach_system(tone: str) -> str:
    return f"""You are the user's recovery coach. You see a 28-day window of:
- per-day HRV (rMSSD ms), resting HR, skin_temp_delta_avg (°C vs baseline),
  recovery_score, readiness_score, sleep_h, sleep_score
- 7-day vs 28-day averages so you can talk in deltas instead of raw numbers
- wow_deltas — pre-computed last-7d vs prior-7d pct changes per metric
- top_correlations — Pearson r≥0.5 between the core vitals (use these
  to make causal-sounding claims defensible)
- recent_alerts the anomaly scanner already raised (high RHR, suppressed
  HRV, skin-temp clusters, illness risk)
- fasting_status — null when not fasting, otherwise weekly_fasting_hours
  / last_7d_fast_count / last_7d_longest_h / is_religious / optional
  active_fast block. IMPORTANT: long fasts compress HRV and lower RHR
  WITHOUT being overtraining. If `fasting_status.weekly_fasting_hours`
  is ≥ 70 OR `last_7d_fast_count` ≥ 3, an HRV/RHR drift in the
  trailing 7d is most likely autonomic-fasting rather than declining
  recovery. Distinguish in `hrv_assessment` / `rhr_assessment` —
  don't call it a declining trend on autonomic data alone.
- profile.tone preference

{_tone_line(tone)}

Use the `give_recovery_coach` tool. Rules:
- The MAIN read is trend_direction (improving / flat / declining). Pick
  it from the 7d vs 28d direction across HRV + RHR + readiness — they
  usually align, but if they diverge call that out in evidence.
- Skin-temp delta is the SUBTLE one: positive deltas clustered over
  2-3+ days are the earliest illness signal. Quote the count and peak
  in skin_temp_assessment when present.
- Don't react to single-day anomalies — this is the multi-week view.
  Cite trend numbers (7d avg, pct delta) not yesterday's single reading.
- The recommendation should match trend_direction: improving → keep
  loading; flat → identify a leverage point; declining → back off,
  identify the suspected driver (sleep debt, training load, illness).
- If recent_alerts cluster (e.g. two suppressed-HRV alerts in five
  days), weight the verdict toward declining even if averages mask it.
"""


async def build_recovery_coach_payload(db: AsyncSession) -> dict[str, Any]:
    """Bounded payload for the recovery coach card. Adds skin-temp Δ
    rows beyond what _daily_rows ships by default."""
    from statistics import mean
    daily = await _daily_rows(db, 28)
    # Pull skin-temp deltas separately and join by date — they live in
    # DailySummary too but _daily_rows doesn't project that column.
    skin_rows = (await db.execute(
        select(models.DailySummary.date, models.DailySummary.skin_temp_delta_avg)
        .where(models.DailySummary.date >= (
            datetime.now(timezone.utc).date() - timedelta(days=28)
        ))
        .order_by(models.DailySummary.date)
    )).all()
    skin_by_date = {str(r.date): r.skin_temp_delta_avg for r in skin_rows}
    for row in daily:
        row["skin_temp_delta"] = skin_by_date.get(row["date"])

    last7 = daily[-7:] if len(daily) >= 7 else daily

    def _avg(rows: list[dict[str, Any]], key: str) -> float | None:
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(mean(vals), 2) if vals else None

    last7_summary = {
        "hrv": _avg(last7, "hrv"),
        "rhr": _avg(last7, "rhr"),
        "recovery": _avg(last7, "recovery"),
        "readiness": _avg(last7, "readiness"),
        "sleep_h": _avg(last7, "sleep_h"),
        "skin_temp_delta": _avg(last7, "skin_temp_delta"),
    }
    baseline_28d = {
        "hrv": _avg(daily, "hrv"),
        "rhr": _avg(daily, "rhr"),
        "recovery": _avg(daily, "recovery"),
        "readiness": _avg(daily, "readiness"),
        "sleep_h": _avg(daily, "sleep_h"),
        "skin_temp_delta": _avg(daily, "skin_temp_delta"),
    }
    skin_warm_count = sum(
        1 for r in last7 if (r.get("skin_temp_delta") or 0) >= 0.3
    )
    return {
        "today": datetime.now(timezone.utc).date().isoformat(),
        "profile": await _profile_ctx(db),
        "last7_summary": last7_summary,
        "baseline_28d": baseline_28d,
        "skin_temp_warm_days_7d": skin_warm_count,
        "overnight_env_7d": await _overnight_env_readings(db, days=7),
        "recent_dailies": daily,
        "recent_alerts": await _recent_alerts_ctx(db),
        "top_correlations": _top_correlations(daily),
        "wow_deltas": _wow_deltas(daily),
    }


async def recovery_coach(db: AsyncSession, cfg: models.AiConfig) -> AiResult:
    """Multi-week recovery trend verdict + recommendation."""
    if not cfg.enabled or not cfg.anthropic_api_key:
        raise RuntimeError("AI is disabled or no API key configured")
    payload = await build_recovery_coach_payload(db)
    user_text = (
        f"Read the user's last 28 days of recovery vitals and return a "
        f"structured trend verdict via the `give_recovery_coach` tool:\n\n"
        f"{json.dumps(payload, indent=2, default=str)}\n"
    )
    client = AsyncAnthropic(api_key=cfg.anthropic_api_key)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=600,
        system=_cached_system(_recovery_coach_system(cfg.tone)),
        tools=[RECOVERY_COACH_TOOL],
        tool_choice={"type": "tool", "name": "give_recovery_coach"},
        messages=[{"role": "user", "content": user_text}],
    )
    tool_input: dict[str, Any] = {}
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use" and block.name == "give_recovery_coach":
            tool_input = block.input  # type: ignore[assignment]
            break
    if not tool_input:
        tool_input = {
            "headline": "Not enough recovery data to read trend yet",
            "tone": "neutral",
            "trend_direction": "flat",
            "hrv_assessment": "Need more data.",
            "rhr_assessment": "Need more data.",
            "skin_temp_assessment": "Need more data.",
            "readiness_assessment": "Need more data.",
            "evidence": [],
            "recommendation": "Keep wearing the watch overnight and re-check in a week.",
        }
    _normalize_array_field(tool_input, "evidence")
    return AiResult(
        content=json.dumps(tool_input),
        model=resp.model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )


async def build_workout_coach_payload(db: AsyncSession) -> dict[str, Any]:
    """Multi-signal payload — reuses cardio + deload signals."""
    from ..analytics.cardio import cardio_summary
    # Reuse the deload payload's trend + strength signals, but rename
    # so the system prompt knows this is a broader weekly read.
    deload = await build_deload_payload(db)
    cardio = await cardio_summary(db, days=30)
    # Reuse the 28-day daily rows the deload payload already pulled
    # (held in deload["recent_dailies"] + the baseline window) by
    # re-fetching cheaply — _daily_rows is a single SELECT and falls
    # well inside the cache-keyed payload hash.
    daily = await _daily_rows(db, 28)
    return {
        "today": datetime.now(timezone.utc).date().isoformat(),
        "profile": await _profile_ctx(db),
        "vitals_trends": deload.get("trends"),
        "strength_last_14d": deload.get("strength_last_14d"),
        "cardio_30d": cardio,
        "fasting": await _fasting_status(db),
        "trend_badges": await compute_badges(db, max_badges=4),
        "recent_alerts": await _recent_alerts_ctx(db),
        "top_correlations": _top_correlations(daily),
        "wow_deltas": _wow_deltas(daily),
    }


async def workout_coach(db: AsyncSession, cfg: models.AiConfig) -> AiResult:
    """Synthesizing AI coach — weekly perspective, multi-signal."""
    if not cfg.enabled or not cfg.anthropic_api_key:
        raise RuntimeError("AI is disabled or no API key configured")
    payload = await build_workout_coach_payload(db)
    user_text = (
        f"Synthesize the user's strength + cardio + recovery picture "
        f"into a single weekly-perspective coaching card via the "
        f"`give_workout_coach` tool:\n\n"
        f"{json.dumps(payload, indent=2, default=str)}\n"
    )
    client = AsyncAnthropic(api_key=cfg.anthropic_api_key)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=600,
        system=_cached_system(_workout_coach_system(cfg.tone)),
        tools=[WORKOUT_COACH_TOOL],
        tool_choice={"type": "tool", "name": "give_workout_coach"},
        messages=[{"role": "user", "content": user_text}],
    )
    tool_input: dict[str, Any] = {}
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use" and block.name == "give_workout_coach":
            tool_input = block.input  # type: ignore[assignment]
            break
    if not tool_input:
        tool_input = {
            "headline": "Not enough cross-signal data yet",
            "tone": "neutral",
            "what_is_working": "Keep logging.",
            "what_to_change": "Nothing specific to suggest yet.",
            "evidence": [],
            "weekly_plan_hint": "Train as planned and re-check next week.",
        }
    _normalize_array_field(tool_input, "evidence")
    return AiResult(
        content=json.dumps(tool_input),
        model=resp.model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )
