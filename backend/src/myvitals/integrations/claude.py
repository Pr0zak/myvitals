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
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .llm import get_provider
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..analytics.trends import compute_badges
from ..config import settings
from ..db import models

log = logging.getLogger(__name__)


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


def _local_today() -> date:
    """Today's date in the user's timezone — not UTC, not the process zone.

    Every AI payload stamps a ``today`` and slices windows relative to it.
    The container runs TZ=UTC while the user is Central, so a UTC-derived
    date rolls at 7pm local: for five hours each evening the model was
    told today was tomorrow, and every trailing window it reasoned over
    was shifted a day forward. That produces confident, specific, wrong
    statements ("your HRV dropped yesterday") from correct data.

    It also poisons the cache in a way that looks like a cache bug rather
    than a date bug: ``today`` is part of the hashed payload, so the key
    changed at 7pm and again at midnight, re-billing the same question
    twice a day for an unchanged answer.
    """
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(settings.tz) if settings.tz != "UTC" else timezone.utc
    except Exception:
        tz = timezone.utc
    return datetime.now(tz).date()


ASK_SYSTEM = """You are a brief health coach. The user has aggregate
data and a specific question. Answer via the `give_answer` tool.

Rules:
- Cite specific numbers and dates from the context. A claim with no
  number behind it is not worth returning.
- If the context does not support an answer, say so in `caveat` and set
  confidence to "low". Do NOT infer beyond the data to seem helpful;
  a confident wrong answer about someone's health is the worst failure
  mode available to you.
- If the question is not about the user's health data, answer briefly
  that you only have their health context, rather than guessing.
- Never diagnose, and never contradict a clinician. Suggest seeing one
  when the data looks genuinely concerning.
- No emoji."""

ASK_TOOL = {
    "name": "give_answer",
    "description": "Answer the user's question as structured fields.",
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {
                "type": "string",
                "description": "≤14 words. The direct answer, not a restatement of the question.",
            },
            "answer_bullets": {
                "type": "array", "items": {"type": "string"},
                "description": "1-4 short bullets, each citing a specific number or date.",
            },
            "caveat": {
                "type": "string",
                "description": (
                    "What this answer cannot tell them — thin data, short window, "
                    "confounders. Empty string only if there genuinely is none."
                ),
            },
            "confidence": {
                "type": "string", "enum": ["high", "medium", "low"],
                "description": "How well the available data supports the answer.",
            },
        },
        "required": ["headline", "answer_bullets", "caveat", "confidence"],
    },
}

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
    age = (_local_today() - dob).days // 365
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
    today = _local_today()
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
    except Exception as e:  # noqa: BLE001
        log.warning("claude._activities query failed: %s", e)
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
        from ..api.analytics import all_daily_summary_metrics, _pearson
    except Exception as e:  # noqa: BLE001
        log.warning("claude._correlations: analytics import failed: %s", e)
        return []
    today = _local_today()
    since = today - timedelta(days=days)
    # One query for every metric series (was one query per metric).
    cache = await all_daily_summary_metrics(db, since, today)
    out: list[dict[str, Any]] = []
    keys = list(cache.keys())  # already sorted → deterministic pairing
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

        today_d = _local_today()
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
    except Exception as e:  # noqa: BLE001
        log.warning("claude._fasting_status failed: %s", e)
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
            # NOTE: `active.addiction` is deliberately NOT sent — the column can
            # hold the user's real name (see CLAUDE.md privacy notes). Durations
            # alone are enough for the model to narrate streak progress.
            "current_days": round(secs / 86400.0, 1),
            "total_resets": len(durations),
            "longest_days": round(max(durations), 1) if durations else None,
            "avg_days": round(sum(durations) / len(durations), 1) if durations else None,
        }
    except Exception as e:  # noqa: BLE001
        log.warning("claude._sober_status failed: %s", e)
        return None


async def build_summary_payload(db: AsyncSession, range_kind: str) -> dict[str, Any]:
    """Bounded JSON payload for a multi-topic weekly/monthly read.
    range_kind: 'week' (7d) | 'month' (30d). Now richer — includes
    activities + annotations + WoW deltas computed server-side."""
    days = 30 if range_kind == "month" else 7
    today = _local_today()
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
    today = _local_today()
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


# Hard cap on standing instructions. Long enough for a few real constraints,
# short enough that it cannot quietly inflate the cached prefix of every
# request -- and short enough to read before saving, which matters because
# this text is aimed at the model's own guardrails.
MAX_CUSTOM_INSTRUCTIONS = 1000


def personalise(text: str, cfg: "models.AiConfig | None") -> str:
    """Append the user's standing instructions to a system prompt.

    Appended, never prepended, and under a fixed heading: these instructions
    augment the base rules rather than replacing them, and putting them last
    means a prompt cannot be made to look like it starts with user text.

    Every system prompt in this module goes through here, which is the point.
    The tone flavour is threaded into twelve separate prompt builders and the
    thirteenth would have been forgotten; one chokepoint is how the same
    thing does not happen to this.
    """
    if cfg is None:
        return text
    # getattr rather than attribute access: during a rolling deploy the app
    # can briefly run against a database that has not taken migration 0049
    # yet, and a missing column must degrade to "no extra instructions"
    # rather than 500 every AI surface at once.
    extra = (getattr(cfg, "custom_instructions", None) or "").strip()
    if not extra:
        return text
    return (
        f"{text}\n\n## Additional instructions from the user\n"
        f"{extra[:MAX_CUSTOM_INSTRUCTIONS]}\n"
    )


def _credentials_missing(cfg: "models.AiConfig") -> bool:
    """True when this config cannot make a call.

    Every AI runner used to guard on `not cfg.anthropic_api_key`, which
    is right for the Anthropic path and wrong for every other provider:
    the CLI authenticates with the machine's subscription OAuth and has
    no API key at all, so that guard would refuse every surface while
    reporting "no API key configured". Ollama needs no key either.
    """
    provider = (getattr(cfg, "provider", None) or "anthropic").strip().lower()
    if provider == "claude_cli":
        # Auth lives in the CLI's own credentials (or a stored OAuth
        # token). A missing login fails loudly at call time with the
        # CLI's own message, which is more useful than a guess here.
        return False
    if provider in ("openai_compatible", "ollama"):
        # A local endpoint usually needs no key; the base URL is what
        # matters, and that is validated when it is saved.
        return not getattr(cfg, "base_url", None)
    return not cfg.anthropic_api_key


def _cached_system(text: str, cfg: "models.AiConfig | None" = None) -> list[dict]:
    """Wrap the system prompt for Anthropic's prompt cache so the fixed
    template doesn't get re-billed at full input rate on every call.
    Saves ~50% on repeated topical reads.

    `cfg` carries the user's standing instructions. They sit inside the
    cached prefix deliberately: the text is fixed between edits, so it is
    billed once per cache window rather than per call. Editing it invalidates
    the cache — and every stored summary — which is why the UI warns before
    saving."""
    return [{
        "type": "text",
        "text": personalise(text, cfg),
        "cache_control": {"type": "ephemeral"},
    }]


async def explain_legacy(db: AsyncSession, range_kind: str, cfg: models.AiConfig) -> AiResult:
    """Backwards-compat narrative output (markdown). Used by /ai/explain."""
    if not cfg.enabled or _credentials_missing(cfg):
        raise RuntimeError("AI is disabled or no credentials configured")
    payload = await build_summary_payload(db, range_kind)
    user_text = (
        f"Range: last {payload['window_days']} days as of {payload['today']}.\n\n"
        f"{json.dumps(payload, indent=2, default=str)}\n"
    )
    client = get_provider(cfg)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=600,
        system=_cached_system(system_prompt(cfg.tone), cfg),
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
    if not cfg.enabled or _credentials_missing(cfg):
        raise RuntimeError("AI is disabled or no credentials configured")

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
    client = get_provider(cfg)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=600,
        system=_cached_system(structured_system(cfg.tone), cfg),
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
    if not cfg.enabled or _credentials_missing(cfg):
        raise RuntimeError("AI is disabled or no credentials configured")
    payload = await build_verdict_payload(db)
    user_text = f"Aggregate snapshot:\n{json.dumps(payload, indent=2, default=str)}\n"
    client = get_provider(cfg)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=80,
        system=_cached_system(VERDICT_SYSTEM, cfg),
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

def _tool_result(resp: Any, tool_name: str) -> dict[str, Any]:
    """Extract a forced tool call's input, or {} if the model did not call it.

    Every structured surface in this module inlines this loop. This is the
    shared version; new surfaces should use it rather than adding a ninth
    copy. Returning {} rather than raising lets each caller decide what a
    missing tool call means for its own card — some can degrade, some
    cannot.

    `tool_choice={"type": "tool", ...}` makes the omission very unlikely,
    but "very unlikely" over an external API is not "impossible", and an
    IndexError in a health app is a worse outcome than an honest fallback.
    """
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use" and block.name == tool_name:
            return dict(block.input or {})
    return {}


MAX_QUESTION_CHARS = 500


async def build_ask_payload(db: AsyncSession, question: str) -> dict[str, Any]:
    """Bounded payload for a free-form question (ASK-1).

    The question is part of the payload rather than a separate argument so
    it lands inside the cache hash: asking the same question against
    unchanged data must return the cached answer instead of re-billing,
    and asking a *different* question against the same data must not.

    Truncated at MAX_QUESTION_CHARS. An unbounded question is both a cost
    lever and a prompt-injection surface, and 500 characters is more than
    any real question here needs.
    """
    return {
        "question": question.strip()[:MAX_QUESTION_CHARS],
        "context": await build_summary_payload(db, "week"),
    }


async def ask(db: AsyncSession, cfg: models.AiConfig, question: str) -> AiResult:
    """Structured answer to a free-form question (ASK-1).

    This was the last AI surface returning free prose. Everything else
    already went through forced tool-use, which is what lets the clients
    render cards instead of a paragraph, and what stops the model padding
    an answer to fill a text block.
    """
    if not cfg.enabled or _credentials_missing(cfg):
        raise RuntimeError("AI is disabled or no credentials configured")
    payload = await build_ask_payload(db, question)
    user_text = (
        f"Question: {payload['question']}\n\n"
        f"Aggregate context (last 7 days + correlations + sober):\n"
        f"{json.dumps(payload['context'], indent=2, default=str)}\n"
    )
    client = get_provider(cfg)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=600,
        system=_cached_system(ASK_SYSTEM, cfg),
        tools=[ASK_TOOL],
        tool_choice={"type": "tool", "name": "give_answer"},
        messages=[{"role": "user", "content": user_text}],
    )
    analysis = _tool_result(resp, "give_answer")
    if not analysis:
        # No tool call. Say so rather than inventing an answer — this is a
        # question about the user's health, and a fabricated response is
        # worse than an admitted failure.
        text_parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
        analysis = {
            "headline": "Could not produce a structured answer",
            "answer_bullets": [
                t for t in ["\n\n".join(text_parts).strip()[:400]] if t
            ] or ["The model returned no usable response."],
            "caveat": "Try again, or pick a different model in Settings → AI.",
            "confidence": "low",
        }
    return AiResult(
        content=json.dumps(analysis),
        model=resp.model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )


# ─────────────── Discovery explainer ───────────────

async def explain_discovery(
    db: AsyncSession, cfg: models.AiConfig,
    x_metric: str, y_metric: str,
) -> AiResult:
    if not cfg.enabled or _credentials_missing(cfg):
        raise RuntimeError("AI is disabled or no credentials configured")
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
    client = get_provider(cfg)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=300,
        system=_cached_system(ASK_SYSTEM, cfg),
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
    if not cfg.enabled or _credentials_missing(cfg):
        raise RuntimeError("AI is disabled or no credentials configured")
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
    client = get_provider(cfg)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=80,
        system=_cached_system(VERDICT_SYSTEM, cfg),
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
    if not cfg.enabled or _credentials_missing(cfg):
        raise RuntimeError("AI is disabled or no credentials configured")

    # Recent metric context — what's the user's recovery state going in
    rows = await _daily_rows(db, 7)
    payload = {
        "activity": {
            "date": str(act.start_at.date()),
            "type": act.type,
            # `act.name` (Strava free-text title) is omitted on purpose — titles
            # routinely embed locations ("Morning Ride from <home>"). type only.
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
    client = get_provider(cfg)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=200,
        system=_cached_system(ASK_SYSTEM, cfg),
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
    if not cfg.enabled or _credentials_missing(cfg):
        raise RuntimeError("AI is disabled or no credentials configured")

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
        except Exception as e:  # noqa: BLE001
            log.warning("claude goal-context weight fetch failed: %s", e)
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
    client = get_provider(cfg)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=300,
        system=_cached_system(ASK_SYSTEM, cfg),
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
    if not cfg.enabled or _credentials_missing(cfg):
        raise RuntimeError("AI is disabled or no credentials configured")
    payload = await build_summary_payload(db, "week")
    user_text = (
        "Run analyses on each of week / sleep / recovery / sober / anomaly. "
        "Each topic gets its own headline + evidence + suggestion. Use the "
        "give_all_topics tool — one call, all topics.\n\n"
        f"Aggregate data:\n{json.dumps(payload, indent=2, default=str)}\n"
    )
    client = get_provider(cfg)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=1500,
        system=_cached_system(structured_system(cfg.tone), cfg),
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

An exercise with `skipped_exercise: true` was deliberately declined by the
user — not forgotten, and not a failure. Do not treat it as missed work or
as a sign of poor adherence. Only `missed_sets` represents prescribed work
that went unaccounted for. Skipped cool-down or mobility slots in particular
are a scheduling choice and rarely worth a concern bullet.

An exercise with `added_ad_hoc: true` was appended by the user mid-session
and was not part of the generated plan. Treat it as extra work they chose to
do, not as a deviation to correct. It is worth a highlight when it filled a
real gap and worth a concern only if it pushed a muscle group well past its
weekly target.
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
            # SKIP-1: a slot the user explicitly declined reports as skipped,
            # not as missed. Before the flag existed, walking away from an
            # exercise was indistinguishable from forgetting it, and this
            # payload told the reviewer the user had missed the whole
            # prescription. `missed_sets` is now genuinely "prescribed work
            # that went unaccounted for".
            "skipped_exercise": bool(getattr(wex, "skipped", False)),
            # TD-10: the user appended this one themselves. Reading it as a
            # deviation from the plan would be exactly backwards — it is
            # extra work they chose to do.
            "added_ad_hoc": bool(getattr(wex, "added_ad_hoc", False)),
            "missed_sets": (
                0 if getattr(wex, "skipped", False)
                else wex.target_sets - len(logged) - sum(1 for s in sets if s.skipped)
            ),
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
                # Net of any paused intervals (WP-14).
                int((
                    (workout.completed_at - workout.started_at).total_seconds()
                    - (workout.total_paused_s or 0)
                ) / 60)
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
    selectable_ids: set[str] | None = None,
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

    # The pool the model may swap from. Two filters, both load-bearing.
    #
    # `selectable_ids` is the generator's own rule — equipment the user owns,
    # exercises they have not disabled, superseded duplicates removed. The
    # comment this replaces claimed equipment was "already represented by
    # what the generator picked from", but the pool was built from the WHOLE
    # catalog, so the model was free to suggest a barbell lift to someone who
    # owns dumbbells, or an exercise the user had explicitly turned off. That
    # reads as the coach not having read the settings, and it spends a call
    # to produce advice that cannot be taken.
    #
    # Already-in-today's-plan exercises are excluded too: suggesting a swap
    # to something already prescribed today is never a variety improvement.
    today_muscles = {p["primary_muscle"] for p in today_plan if p.get("primary_muscle")}
    in_plan = {p.get("exercise_id") for p in today_plan}
    candidates = []
    for cid, info in catalog_by_id.items():
        if info.get("primary_muscle") not in today_muscles:
            continue
        if cid in in_plan:
            continue
        if selectable_ids is not None and cid not in selectable_ids:
            continue
        candidates.append({
            "exercise_id": cid,
            "name": info.get("name", cid),
            "primary_muscle": info.get("primary_muscle"),
            "movement_pattern": info.get("movement_pattern"),
        })
    # Least-recently-used first rather than dict order, then capped. The old
    # [:60] slice took whatever the catalog happened to list first, which
    # biased every suggestion toward the same alphabetical head and worked
    # against the variety the feature exists to provide.
    candidates.sort(key=lambda c: (
        recent_history.get(c["exercise_id"], {}).get("count", 0),
        c["name"],
    ))
    available_catalog = candidates[:60]

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
    selectable_ids: set[str] | None = None,
) -> AiResult:
    """Generate up to 2 variety-swap suggestions for today's plan."""
    if not cfg.enabled or _credentials_missing(cfg):
        raise RuntimeError("AI is disabled or no credentials configured")
    payload = await build_strength_nudge_payload(
        db, workout_id, catalog_by_id, selectable_ids,
    )
    if not payload:
        raise RuntimeError("workout not found")
    user_text = (
        f"Today's plan and the user's recent strength history:\n\n"
        f"{json.dumps(payload, indent=2, default=str)}\n"
    )
    client = get_provider(cfg)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=400,
        system=_cached_system(_strength_nudge_system(cfg.tone), cfg),
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
    if not cfg.enabled or _credentials_missing(cfg):
        raise RuntimeError("AI is disabled or no credentials configured")
    payload = await build_strength_review_payload(db, workout_id)
    if not payload:
        raise RuntimeError("workout not found")
    user_text = (
        f"Review this completed strength session, comparing it against "
        f"the trailing 4 weeks of the user's history.\n\n"
        f"Aggregate data:\n{json.dumps(payload, indent=2, default=str)}\n"
    )
    client = get_provider(cfg)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=600,
        system=_cached_system(_strength_review_system(cfg.tone), cfg),
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
    today = _local_today()
    daily = await _daily_rows(db, 28)
    recent = [r for r in daily if r["date"] >= str(today - timedelta(days=7))]
    baseline = [r for r in daily if r["date"] < str(today - timedelta(days=7))]

    def _mean(rows: list[dict[str, Any]], key: str) -> float | None:
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    # sleep_h / sleep_debt_h intentionally absent — Pixel Watch sleep
    # duration is unreliable enough that we don't want the deload model
    # weighing it. v0.7.269.
    trends: dict[str, dict[str, Any]] = {}
    for k in ("rhr", "hrv", "recovery", "readiness", "tsb", "ctl", "atl"):
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
    if not cfg.enabled or _credentials_missing(cfg):
        raise RuntimeError("AI is disabled or no credentials configured")
    payload = await build_deload_payload(db)
    user_text = (
        f"Decide if the user should deload right now. The data covers "
        f"their last 28 days of vitals + last 14 days of strength "
        f"performance:\n\n"
        f"{json.dumps(payload, indent=2, default=str)}\n"
    )
    client = get_provider(cfg)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=500,
        system=_cached_system(_deload_system(cfg.tone), cfg),
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
            except Exception as e:  # noqa: BLE001
                log.debug("focus-cue last-seen parse failed for %r: %s", ls, e)
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
    if not cfg.enabled or _credentials_missing(cfg):
        raise RuntimeError("AI is disabled or no credentials configured")
    payload = await build_focus_cue_payload(db, workout_id, catalog_by_id)
    if not payload:
        raise RuntimeError("workout not found")
    user_text = (
        f"User is about to start their planned session. Give one "
        f"focus cue tied to today's exercises + recent history.\n\n"
        f"{json.dumps(payload, indent=2, default=str)}\n"
    )
    client = get_provider(cfg)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=300,
        system=_cached_system(_focus_cue_system(cfg.tone), cfg),
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
    if not cfg.enabled or _credentials_missing(cfg):
        raise RuntimeError("AI is disabled or no credentials configured")
    user_text = (
        f"Statistical anomaly detected:\n{json.dumps(anomaly)}\n\n"
        f"Write ONE sentence (≤ 18 words) for a phone notification. Plain "
        f"English. Mention the metric, the magnitude, and a one-word read "
        f"(spike / dip / etc). No emoji."
    )
    client = get_provider(cfg)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=60,
        system=_cached_system(VERDICT_SYSTEM, cfg),
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
        "today": _local_today().isoformat(),
        "profile": await _profile_ctx(db),
        "cardio_30d": summary,
        "recent_alerts": await _recent_alerts_ctx(db),
        "top_correlations": _top_correlations(daily),
        "wow_deltas": _wow_deltas(daily),
    }


async def cardio_coach(db: AsyncSession, cfg: models.AiConfig) -> AiResult:
    """Structured AI analysis of cardio zone distribution + dose."""
    if not cfg.enabled or _credentials_missing(cfg):
        raise RuntimeError("AI is disabled or no credentials configured")
    payload = await build_cardio_coach_payload(db)
    user_text = (
        f"Analyze this user's cardio pattern over the last 30 days and "
        f"return structured advice via the `give_cardio_coach` tool:\n\n"
        f"{json.dumps(payload, indent=2, default=str)}\n"
    )
    client = get_provider(cfg)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=500,
        system=_cached_system(_cardio_coach_system(cfg.tone), cfg),
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
        "today": _local_today().isoformat(),
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
    if not cfg.enabled or _credentials_missing(cfg):
        raise RuntimeError("AI is disabled or no credentials configured")
    payload = await build_sleep_coach_payload(db)
    user_text = (
        f"Read the user's last 28 days of sleep + recovery vitals and "
        f"return a structured verdict via the `give_sleep_coach` tool:\n\n"
        f"{json.dumps(payload, indent=2, default=str)}\n"
    )
    client = get_provider(cfg)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=600,
        system=_cached_system(_sleep_coach_system(cfg.tone), cfg),
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
            _local_today() - timedelta(days=28)
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
        "today": _local_today().isoformat(),
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
    if not cfg.enabled or _credentials_missing(cfg):
        raise RuntimeError("AI is disabled or no credentials configured")
    payload = await build_recovery_coach_payload(db)
    user_text = (
        f"Read the user's last 28 days of recovery vitals and return a "
        f"structured trend verdict via the `give_recovery_coach` tool:\n\n"
        f"{json.dumps(payload, indent=2, default=str)}\n"
    )
    client = get_provider(cfg)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=600,
        system=_cached_system(_recovery_coach_system(cfg.tone), cfg),
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


# ─────────────── Fasting coach (FAST-16) ───────────────

FASTING_COACH_TOOL = {
    "name": "give_fasting_coach",
    "description": (
        "Decide whether the user should fast today, what protocol, "
        "and how it fits their active weight / fasting goal. Returns "
        "a structured card the client renders as the Fasting hero."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "recommendation": {
                "type": "string",
                "enum": ["fast", "eat_normally", "light_fast", "break_now"],
                "description": (
                    "Verdict. break_now is reserved for an in-progress fast "
                    "that signals say to abort — and MUST NOT fire if "
                    "is_religious_active is true."
                ),
            },
            "tone": {"type": "string", "enum": ["good", "warn", "bad", "neutral"]},
            "protocol_suggestion": {
                "type": "string",
                "description": (
                    "When recommendation is `fast` or `light_fast`, the "
                    "protocol label: \"16:8\" / \"18:6\" / \"20:4\" / \"24h\" / "
                    "\"36h\". Empty string when not applicable."
                ),
            },
            "best_window": {
                "type": "string",
                "description": (
                    "Free-form when window. Empty string when not relevant. "
                    "Example: \"18:00 today → 12:00 tomorrow\"."
                ),
            },
            "goal_alignment": {
                "type": "string",
                "description": "≤ 30 words. How this verdict fits the active weight / fasting goal.",
            },
            "evidence": {
                "type": "array",
                "items": {"type": "string"},
                "description": "2-4 bullets citing specific signals.",
            },
            "caveats": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Safeguards: religious-fast preserved, hydration cue, "
                    "medication timing — empty array OK."
                ),
            },
        },
        "required": [
            "recommendation", "tone", "protocol_suggestion", "best_window",
            "goal_alignment", "evidence", "caveats",
        ],
    },
}


def _fasting_coach_system(tone: str) -> str:
    return f"""You are the user's fasting coach. You see:
- 28d daily summary trends (HRV, RHR, recovery, readiness, sleep_h,
  sleep_debt_h)
- 14d fasting history — per-fast started_at, duration_h, protocol
- 14d in-fast logs — hunger (1-5), mood (1-5), hydration_ml, notes
- Today's planned strength split + recovery_score (when there is one)
- Active weight goal — current_value, target_value, progress_pct,
  direction (loss-oriented)
- Active fasting goal — target_value (hours/week)
- recent_alerts the anomaly scanner already raised
- top_correlations, wow_deltas
- is_religious_active — true when an in-progress fast's protocol
  is religious (ramadan / lent / yom_kippur)

{_tone_line(tone)}

Use the `give_fasting_coach` tool. RULES (order matters):

1. If `is_religious_active` is true, `recommendation` MUST NOT be
   `break_now`. The user is observing a religious fast; coaching
   collapses to hydration + reframing benefits. Use caveats to
   acknowledge the religious context.
2. If today's planned strength split contains a `main_compound` 3-5
   rep range AND the user is approaching a planned long fast,
   recommend `eat_normally` — fasted heavy lifts are an injury risk
   the system rules against (see FAST-COACH plan, hard rule).
3. Active weight goal stalled ≥ 3 weeks → lean toward `fast` /
   `light_fast` matched to current cadence. Active weight goal
   on track → `eat_normally` is fine; don't push harder than the
   plan needs.
4. `break_now` requires a strong signal — HRV cliff ≥ 30 ms below
   28d baseline overnight, mood ≤ 2 with hunger ≥ 4 from the most
   recent log, OR alert kind `illness_risk`. Single anomalies aren't
   enough; pattern matters.
5. Cite numbers in evidence. "Down 0.4 kg in 3 weeks at 14:10" beats
   "weight progress is slow".
6. Single high-confidence call beats five hedges.
"""


async def _recent_fasting_log_summary(
    db: AsyncSession, days: int = 14,
) -> dict[str, Any]:
    """Per-log avg hunger / mood and total hydration over the trailing
    window. Bounded: returns 5-6 scalars regardless of log count."""
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    since = _dt.now(_tz.utc) - _td(days=days)
    rows = (await db.execute(
        select(models.FastingLog)
        .where(models.FastingLog.time >= since)
    )).scalars().all()
    if not rows:
        return {"days": days, "log_count": 0}
    from statistics import mean
    hungers = [r.hunger for r in rows if r.hunger is not None]
    moods = [r.mood for r in rows if r.mood is not None]
    hydrations = [r.hydration_ml for r in rows if r.hydration_ml is not None]
    return {
        "days": days,
        "log_count": len(rows),
        "avg_hunger": round(mean(hungers), 1) if hungers else None,
        "avg_mood": round(mean(moods), 1) if moods else None,
        "total_hydration_ml": sum(hydrations) if hydrations else 0,
    }


async def _active_weight_goal_ctx(db: AsyncSession) -> dict[str, Any] | None:
    """Pull the single active weight goal with current value + pct.
    Returns None when no active weight goal exists."""
    g = (await db.execute(
        select(models.AiGoal)
        .where(models.AiGoal.kind == "weight")
        .where(models.AiGoal.ended_at.is_(None))
        .limit(1)
    )).scalar_one_or_none()
    if g is None:
        return None
    latest_kg = (await db.execute(
        select(models.BodyMetric.weight_kg)
        .where(models.BodyMetric.weight_kg.is_not(None))
        .order_by(models.BodyMetric.time.desc())
        .limit(1)
    )).scalar_one_or_none()
    return {
        "title": g.title,
        "target_value": g.target_value,
        "target_unit": g.target_unit,
        "current_value": latest_kg,
        "started_at": g.started_at.isoformat() if g.started_at else None,
    }


async def _active_fasting_goal_target(db: AsyncSession) -> float | None:
    g = (await db.execute(
        select(models.AiGoal.target_value)
        .where(models.AiGoal.kind == "fast_streak")
        .where(models.AiGoal.ended_at.is_(None))
        .limit(1)
    )).scalar_one_or_none()
    return g


async def _planned_strength_today(db: AsyncSession) -> dict[str, Any] | None:
    """Pull today's strength_workout split_focus + the highest-rep-
    intensity slot — lets the fasting coach see whether today is a
    heavy day (no fasted lifting) or a yoga / cardio day (fasting is
    fine)."""
    from datetime import date as _date
    today_d = _local_today()
    w = (await db.execute(
        select(models.StrengthWorkout)
        .where(models.StrengthWorkout.date == today_d)
        .limit(1)
    )).scalar_one_or_none()
    if w is None:
        return None
    return {
        "split_focus": w.split_focus,
        "status": w.status,
        "recovery_score_used": w.recovery_score_used,
    }


async def build_fasting_coach_payload(db: AsyncSession) -> dict[str, Any]:
    """Bounded payload for the fasting coach card."""
    daily = await _daily_rows(db, 28)
    fasting = await _fasting_status(db)
    log_summary = await _recent_fasting_log_summary(db, days=14)
    weight_goal = await _active_weight_goal_ctx(db)
    fasting_goal_target = await _active_fasting_goal_target(db)
    planned_strength = await _planned_strength_today(db)
    is_religious_active = bool(
        fasting is not None
        and fasting.get("active_fast")
        and fasting["active_fast"].get("is_religious")
    )
    return {
        "today": _local_today().isoformat(),
        "profile": await _profile_ctx(db),
        "fasting_status": fasting,
        "is_religious_active": is_religious_active,
        "log_summary_14d": log_summary,
        "active_weight_goal": weight_goal,
        "active_fasting_goal_target_h_per_week": fasting_goal_target,
        "planned_strength_today": planned_strength,
        "recent_dailies": daily,
        "recent_alerts": await _recent_alerts_ctx(db),
        "top_correlations": _top_correlations(daily),
        "wow_deltas": _wow_deltas(daily),
    }


async def fasting_coach(db: AsyncSession, cfg: models.AiConfig) -> AiResult:
    """'Should I fast today?' structured card."""
    if not cfg.enabled or _credentials_missing(cfg):
        raise RuntimeError("AI is disabled or no credentials configured")
    payload = await build_fasting_coach_payload(db)
    user_text = (
        f"Read the user's vitals, goal, and fasting history and decide "
        f"whether they should fast today via the `give_fasting_coach` "
        f"tool:\n\n"
        f"{json.dumps(payload, indent=2, default=str)}\n"
    )
    client = get_provider(cfg)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=600,
        system=_cached_system(_fasting_coach_system(cfg.tone), cfg),
        tools=[FASTING_COACH_TOOL],
        tool_choice={"type": "tool", "name": "give_fasting_coach"},
        messages=[{"role": "user", "content": user_text}],
    )
    tool_input: dict[str, Any] = {}
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use" and block.name == "give_fasting_coach":
            tool_input = block.input  # type: ignore[assignment]
            break
    if not tool_input:
        tool_input = {
            "recommendation": "eat_normally",
            "tone": "neutral",
            "protocol_suggestion": "",
            "best_window": "",
            "goal_alignment": "Not enough data to recommend a fast yet.",
            "evidence": [],
            "caveats": [],
        }
    # Religious-fast safeguard at the application layer too — belt and
    # braces, in case the model ignores the prompt rule.
    if payload.get("is_religious_active") and tool_input.get("recommendation") == "break_now":
        tool_input["recommendation"] = "eat_normally"
        tool_input.setdefault("caveats", []).append(
            "Religious fast active — break_now suppressed by safeguard."
        )
    _normalize_array_field(tool_input, "evidence")
    _normalize_array_field(tool_input, "caveats")
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
        "today": _local_today().isoformat(),
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
    if not cfg.enabled or _credentials_missing(cfg):
        raise RuntimeError("AI is disabled or no credentials configured")
    payload = await build_workout_coach_payload(db)
    user_text = (
        f"Synthesize the user's strength + cardio + recovery picture "
        f"into a single weekly-perspective coaching card via the "
        f"`give_workout_coach` tool:\n\n"
        f"{json.dumps(payload, indent=2, default=str)}\n"
    )
    client = get_provider(cfg)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=600,
        system=_cached_system(_workout_coach_system(cfg.tone), cfg),
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


# ── Meal suggestions (MEAL-4) ────────────────────────────────────────
#
# The differentiator this codebase actually has: every other meal app
# starts cold, so "healthy" means whatever its editors decided. This one
# already knows the weight goal and its trend, training load, fasting
# state, the day's planned workout — and, uniquely here, a per-meal fat
# constraint from a cholecystectomy.
#
# Two rules the prompt cannot be trusted to enforce on its own, so both
# are ALSO enforced in code after the tool call (`meal_suggestions`):
#
#   1. Fat per meal. A prompt rule is a request, not a guarantee, and the
#      one number this user's condition makes matter is exactly the one a
#      model is most likely to be breezy about. Every returned suggestion
#      is re-judged by `analytics/nutrition.assess_meal_fat`, the same
#      deterministic function the rest of the app uses, and the model's
#      own opinion of it is discarded.
#   2. Recipes are compositions, never reproductions. The app does not
#      ship or scrape third-party recipe text, and a suggestion that
#      claims to be a known published recipe would be doing by proxy what
#      the scraper decision ruled out.

MEAL_SUGGEST_TOOL = {
    "name": "give_meal_suggestions",
    "description": (
        "Return 2-4 meal suggestions composed from what the user has, "
        "fitted to their training, fasting and health context."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {
                "type": "string",
                "description": "One sentence on what today calls for, and why.",
            },
            "suggestions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "slot": {
                            "type": "string",
                            "enum": ["breakfast", "lunch", "dinner", "snack"],
                        },
                        "why": {
                            "type": "string",
                            "description": (
                                "Why THIS meal today — tie it to training "
                                "load, fasting state, the weight goal or "
                                "recovery. Not generic nutrition advice."
                            ),
                        },
                        "uses_from_pantry": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Pantry items this uses up.",
                        },
                        "also_needs": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Anything not already in the pantry.",
                        },
                        "est_prep_min": {"type": "integer"},
                        "est_fat_g": {
                            "type": "number",
                            "description": (
                                "Estimated fat in grams for ONE serving. Be "
                                "honest and rather over- than under-estimate; "
                                "this is checked against a medical constraint."
                            ),
                        },
                        "est_kcal": {"type": "number"},
                        "based_on_saved_recipe": {
                            "type": "string",
                            "description": (
                                "Name of the user's own saved recipe this "
                                "comes from, or empty if newly composed."
                            ),
                        },
                    },
                    "required": ["name", "slot", "why", "est_fat_g"],
                },
            },
            "notes": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["headline", "suggestions"],
    },
}


def _meal_suggest_system(tone: str) -> str:
    return (
        "You suggest meals for a single self-hosted user, composing from "
        "what they already have.\n\n"
        f"Tone: {tone}.\n\n"
        "## What makes a good suggestion here\n"
        "Tie every suggestion to TODAY'S context — the training load, the "
        "planned workout, the fasting state, the weight goal, recovery. "
        '"Higher-carb the evening before a long ride" is a suggestion. '
        '"Eat more vegetables" is not; the user did not need an LLM for '
        "that. Prefer meals that use pantry items which expire soonest.\n\n"
        "## Fat per meal is a medical constraint, not a preference\n"
        "This user has had their gall bladder removed. Bile now drips "
        "continuously instead of arriving as a bolus, so what matters is "
        "how much fat lands in ONE sitting, not the daily total. If a "
        "per-meal fat target is given, keep every suggestion under it. If "
        "no target is given, do NOT invent one and do not claim a meal is "
        "safe — tolerance varies a lot between people. Estimate `est_fat_g` "
        "honestly per serving and err on the high side; it is checked "
        "against a deterministic rule after you answer.\n\n"
        "## Do not reproduce published recipes\n"
        "Compose from ingredients, or adapt one of the user's OWN saved "
        "recipes and name it in `based_on_saved_recipe`. Never reproduce "
        "the text of a published recipe from memory, and never present an "
        "invented dish as a known published one.\n\n"
        "## Honesty\n"
        "If the pantry is nearly empty, say so in `notes` and suggest few "
        "things rather than inventing a full week. Anything the user does "
        "not have goes in `also_needs` — do not quietly assume staples.\n\n"
        "Answer only via the `give_meal_suggestions` tool."
    )


async def build_meal_suggestion_payload(db: AsyncSession) -> dict[str, Any]:
    """Bounded payload for the meal-suggestion card.

    Bounded is the operative word — see the AI section of CLAUDE.md. The
    pantry and recipe lists are names and quantities only; no nutrition
    tables, no ingredient rows, no history. Everything numeric the model
    needs has already been aggregated server-side.
    """
    from sqlalchemy import select as _select

    from ..api.meals import DIET_KEY, _DIET_DEFAULTS

    # Pantry: name, amount, and how close it is to expiring. Soonest
    # first, capped — a long pantry should not balloon the cache key.
    pantry_rows = (await db.execute(_select(models.PantryItem))).scalars().all()
    food_ids = {p.food_id for p in pantry_rows if p.food_id is not None}
    names: dict[int, str] = {}
    if food_ids:
        for fid, name in (await db.execute(
            _select(models.Food.id, models.Food.name)
            .where(models.Food.id.in_(food_ids))
        )).all():
            names[fid] = name
    today = _local_today()
    pantry = []
    for p in pantry_rows:
        label = names.get(p.food_id) if p.food_id else p.label
        if not label:
            continue
        pantry.append({
            "item": label,
            "amount": (
                f"{p.quantity:g} {p.unit}".strip()
                if p.quantity is not None else (p.unit or "some")
            ),
            "days_to_expiry": (
                (p.expires_on - today).days if p.expires_on else None
            ),
        })
    pantry.sort(key=lambda x: (
        x["days_to_expiry"] if x["days_to_expiry"] is not None else 10**6
    ))
    pantry = pantry[:60]

    # The user's own recipes, by name and headline numbers only.
    recipes = (await db.execute(
        _select(models.Recipe)
        .where(models.Recipe.archived.is_(False))
        .order_by(models.Recipe.name)
        .limit(40)
    )).scalars().all()
    saved = [
        {
            "name": r.name,
            "servings": r.servings,
            "minutes": (r.prep_min or 0) + (r.cook_min or 0) or None,
        }
        for r in recipes
    ]

    profile = await db.get(models.UserProfile, 1)
    extra = (profile.extra if profile and profile.extra else {}) or {}
    diet = {**_DIET_DEFAULTS, **(extra.get(DIET_KEY) or {})}

    daily = await _daily_rows(db, 14)
    return {
        "today": today.isoformat(),
        "profile": await _profile_ctx(db),
        "pantry": pantry,
        "pantry_size": len(pantry_rows),
        "saved_recipes": saved,
        # The medical constraint, and explicitly whether one is set.
        # A null target is NOT permission to guess a limit.
        "fat_per_meal_target_g": diet.get("fat_per_meal_target_g"),
        "fat_target_source": diet.get("fat_target_source"),
        "daily_kcal_target": diet.get("daily_kcal_target"),
        "active_weight_goal": await _active_weight_goal_ctx(db),
        "planned_strength_today": await _planned_strength_today(db),
        "fasting_status": await _fasting_status(db),
        "recent_dailies": daily,
        "wow_deltas": _wow_deltas(daily),
    }


async def meal_suggestions(db: AsyncSession, cfg: models.AiConfig) -> AiResult:
    """Meal ideas from the pantry, fitted to today's training and health."""
    if not cfg.enabled or _credentials_missing(cfg):
        raise RuntimeError("AI is disabled or no credentials configured")

    from ..analytics.nutrition import assess_meal_fat

    payload = await build_meal_suggestion_payload(db)
    user_text = (
        "Suggest meals for this user via the `give_meal_suggestions` "
        "tool:\n\n"
        f"{json.dumps(payload, indent=2, default=str)}\n"
    )
    client = get_provider(cfg)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=1200,
        system=_cached_system(_meal_suggest_system(cfg.tone), cfg),
        tools=[MEAL_SUGGEST_TOOL],
        tool_choice={"type": "tool", "name": "give_meal_suggestions"},
        messages=[{"role": "user", "content": user_text}],
    )
    tool_input: dict[str, Any] = {}
    for block in resp.content:
        if (getattr(block, "type", "") == "tool_use"
                and block.name == "give_meal_suggestions"):
            tool_input = block.input  # type: ignore[assignment]
            break
    if not tool_input:
        tool_input = {
            "headline": "No suggestions could be generated.",
            "suggestions": [],
            "notes": [],
        }

    # ── Application-layer fat check ──────────────────────────────────
    #
    # Belt and braces over the prompt rule, in the same shape as the
    # religious-fast safeguard above. Each suggestion's fat estimate is
    # re-judged by the SAME deterministic function every other surface
    # uses, so the card cannot disagree with the recipe page, and a model
    # that quietly ignored the target cannot present a meal as fine.
    #
    # Nothing is removed — a suggestion over the target is FLAGGED, not
    # hidden. Silently dropping it would leave the user wondering why the
    # obvious meal was not offered.
    target = payload.get("fat_per_meal_target_g")
    flagged = 0
    for s in tool_input.get("suggestions") or []:
        if not isinstance(s, dict):
            continue
        est = s.get("est_fat_g")
        try:
            est = None if est is None else float(est)
        except (TypeError, ValueError):
            est = None
        verdict = assess_meal_fat(est, target_g=target, history_fat_g=[])
        s["fat_assessment"] = verdict
        if verdict["verdict"] in {"high", "very_high"}:
            flagged += 1
    if flagged and target is not None:
        tool_input.setdefault("notes", []).append(
            f"{flagged} suggestion{'' if flagged == 1 else 's'} came back "
            f"above your {target:g} g per-meal fat target and "
            f"{'is' if flagged == 1 else 'are'} marked — the estimates are "
            "the model's, so treat them as rough."
        )

    _normalize_array_field(tool_input, "notes")
    return AiResult(
        content=json.dumps(tool_input),
        model=resp.model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )


# ── Identify foods from a photo (MEAL-7) ─────────────────────────────
#
# Filling a pantry by hand is the friction that stops one being kept
# current — the whole reason MEAL-6b added a one-tap staples list. A
# photograph of a shelf or a receipt covers the rest in one action.
#
# Three rules this surface does not bend:
#
#   1. NOTHING IS EVER ADDED AUTOMATICALLY. The model proposes; the user
#      ticks. Vision misidentifies confidently, and a pantry that grows
#      items you did not put there stops being trustworthy — at which
#      point the shopping list built on it is worse than useless.
#   2. THE PHOTO IS NEVER STORED. It is forwarded once and discarded.
#      There is no image column, no cache, no log line containing it.
#   3. CONFIDENCE IS REPORTED, not hidden. A guess and a certainty must
#      not render identically when the user is about to accept in bulk.

IDENTIFY_TOOL = {
    "name": "give_identified_foods",
    "description": (
        "List the distinct food items visible in the photo, as things "
        "someone would put on a shopping list."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": (
                                "The plain name a person would write: "
                                '"chicken breast", "olive oil", "eggs". '
                                "Not a brand and not a description."
                            ),
                        },
                        "confidence": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                            "description": (
                                "How sure you are this item is present AND "
                                "correctly identified. Use low freely."
                            ),
                        },
                        "detail": {
                            "type": "string",
                            "description": (
                                "What you actually saw, briefly — a label "
                                "read, a shape recognised. Empty if none."
                            ),
                        },
                    },
                    "required": ["name", "confidence"],
                },
            },
            "notes": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Anything the user should know: a blurry photo, a "
                    "cropped label, items you could see but not name."
                ),
            },
        },
        "required": ["items"],
    },
}


def _identify_system(tone: str) -> str:
    return (
        "You identify food items in a photograph so they can be added to "
        "a kitchen pantry inventory.\n\n"
        f"Tone: {tone}.\n\n"
        "## What to return\n"
        "Plain shopping-list names — \"chicken breast\", \"olive oil\", "
        "\"eggs\" — not brands, not descriptions, not recipes. One entry "
        "per distinct item. If you see six eggs, that is one entry: "
        "\"eggs\".\n\n"
        "## Be honest about uncertainty\n"
        "Use `confidence: low` freely. A wrong item added to a pantry "
        "makes the shopping list tell someone they already have "
        "something they do not, and they find out while cooking. An "
        "item you are unsure of is still worth listing AS LOW — the user "
        "confirms every item before anything is added — but marking a "
        "guess as high confidence is the one thing that breaks this.\n\n"
        "If the photo is too blurry, too dark, or shows no food at all, "
        "return an empty `items` list and say why in `notes`. Do not "
        "invent a plausible pantry.\n\n"
        "Do not identify people, and do not describe anything in the "
        "photo that is not food.\n\n"
        "Answer only via the `give_identified_foods` tool."
    )


#: Anthropic accepts these; anything else is rejected before a call is
#: made rather than after it is billed.
ALLOWED_IMAGE_TYPES = frozenset({
    "image/jpeg", "image/png", "image/gif", "image/webp",
})

#: Bytes of DECODED image. Anthropic's own limit is 5 MB; this is lower
#: because a phone photo needs downscaling before upload anyway and a
#: 4 MB JPEG of a fridge shelf identifies no better than a 600 KB one.
MAX_IMAGE_BYTES = 3_500_000


async def identify_foods(
    db: AsyncSession,
    cfg: models.AiConfig,
    image_b64: str,
    media_type: str,
) -> AiResult:
    """Name the foods in one photo. Adds nothing; proposes only."""
    if not cfg.enabled or _credentials_missing(cfg):
        raise RuntimeError("AI is disabled or no credentials configured")
    if media_type not in ALLOWED_IMAGE_TYPES:
        raise ValueError(f"unsupported image type {media_type!r}")

    client = get_provider(cfg)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=1000,
        system=_cached_system(_identify_system(cfg.tone), cfg),
        tools=[IDENTIFY_TOOL],
        tool_choice={"type": "tool", "name": "give_identified_foods"},
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_b64,
                    },
                },
                {
                    "type": "text",
                    "text": (
                        "List the food items in this photo via the "
                        "`give_identified_foods` tool."
                    ),
                },
            ],
        }],
    )

    tool_input: dict[str, Any] = {}
    for block in resp.content:
        if (getattr(block, "type", "") == "tool_use"
                and block.name == "give_identified_foods"):
            tool_input = block.input  # type: ignore[assignment]
            break
    if not tool_input:
        tool_input = {
            "items": [],
            "notes": ["Nothing could be identified in that photo."],
        }

    _normalize_array_field(tool_input, "notes")
    return AiResult(
        content=json.dumps(tool_input),
        model=resp.model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )


# ── Read a nutrition-facts panel from a photo (MEAL-8) ───────────────
#
# Roughly half this user's diet is packaged, and the only nutrition
# source for a packaged item is the label on it. Typing thirteen numbers
# off a panel is the friction that stops a food ever being added; a photo
# of the panel is one action.
#
# Distinct from `identify_foods`, which names WHAT is in a picture. This
# one reads NUMBERS off a specific, highly structured document, so the
# rules differ: every field is optional and null means "not printed on
# this label", never zero. A label that omits fibre is not a food with no
# fibre, and quietly filling in 0 would corrupt a total this app's
# medical constraint depends on.

LABEL_TOOL = {
    "name": "give_nutrition_label",
    "description": (
        "Transcribe a nutrition-facts panel. Report only what is printed."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "Product name if visible on the packaging, else empty."
                ),
            },
            "serving_size_g": {
                "type": "number",
                "description": (
                    "Grams (or millilitres) in ONE serving, as printed. This "
                    "is what every other number below is per."
                ),
            },
            "serving_text": {
                "type": "string",
                "description": 'The serving as written, e.g. "2/3 cup (55g)".',
            },
            "basis": {
                "type": "string",
                "enum": ["per_serving", "per_100g", "unknown"],
                "description": (
                    "Which column you read. US labels are per serving; UK/EU "
                    "labels usually print both and per-100g is the reliable "
                    "one. Say which you used — the server converts."
                ),
            },
            "kcal": {"type": "number"},
            "protein_g": {"type": "number"},
            "carbs_g": {"type": "number"},
            "fat_g": {"type": "number"},
            "saturated_fat_g": {"type": "number"},
            "fiber_g": {"type": "number"},
            "sugar_g": {"type": "number"},
            "sodium_mg": {"type": "number"},
            "ingredients_text": {
                "type": "string",
                "description": (
                    "The ingredients list, transcribed verbatim from the "
                    "packaging if one of the photos shows it. Keep the "
                    "original order and wording — it is a legal ingredient "
                    "declaration, not prose to tidy up. Empty if no photo "
                    "shows one."
                ),
            },
            "unreadable": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Fields present on the label but too blurred or cropped "
                    "to read. Better here than guessed."
                ),
            },
            "notes": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["basis"],
    },
}


def _label_system(tone: str) -> str:
    return (
        "You transcribe nutrition-facts panels from photographs into "
        "structured data.\n\n"
        f"Tone: {tone}.\n\n"
        "## More than one photo may arrive\n"
        "They are the SAME product from different angles — typically the "
        "front of the pack, the Nutrition Facts panel, and sometimes the "
        "ingredients list. Take the product name from whichever photo "
        "shows it (the panel never carries one), the numbers from the "
        "panel, and the ingredients from whichever photo shows them. Do "
        "not treat them as different foods.\n\n"
        "Transcribe an ingredients list VERBATIM, in its original order "
        "and wording. It is a legal declaration, not prose to tidy up, "
        "and re-ordering or summarising it destroys the one thing it is "
        "good for.\n\n"
        "## Report only what is printed\n"
        "OMIT any field the label does not show. Do NOT infer, estimate, "
        "or fill a plausible value — a field you leave out is recorded as "
        "'not stated', which is correct and useful. A field you guess "
        "becomes a wrong number in a medical fat total that the user has "
        "no way to spot. If a value is on the label but you cannot read "
        "it, list the field name in `unreadable` rather than guessing.\n\n"
        "## Say which column you read\n"
        "US panels print per serving. UK and EU panels usually print both "
        "per-100g and per-serving. Set `basis` to whichever you actually "
        "read, and give `serving_size_g` when it is stated — the server "
        "converts to per-100g and needs to know which it is starting "
        "from. If you cannot tell, use `unknown` and the server will ask "
        "the user rather than assume.\n\n"
        "## Units\n"
        "Report sodium in MILLIGRAMS. Some labels print grams of salt "
        "instead — salt is about 2.5x sodium by weight, but do NOT do "
        "that conversion yourself; say so in `notes` and leave sodium "
        "out.\n\n"
        "If the photo is not a nutrition panel, return `basis: unknown` "
        "with nothing else and say so in `notes`.\n\n"
        "Answer only via the `give_nutrition_label` tool."
    )


async def read_nutrition_label(
    db: AsyncSession,
    cfg: models.AiConfig,
    images: list[tuple[str, str]],
) -> AiResult:
    """Transcribe a packaged food from one or more photos. Saves nothing.

    `images` is [(base64, media_type), ...]. Multiple photos are the
    normal case rather than a nicety: a Nutrition Facts panel carries no
    product name — that is on the FRONT of the pack — so transcribing a
    panel alone produces perfect numbers attached to nothing. Sending the
    front and the panel together is what actually adds a packaged food.
    """
    if not cfg.enabled or _credentials_missing(cfg):
        raise RuntimeError("AI is disabled or no credentials configured")
    if not images:
        raise ValueError("at least one image is required")
    for _b64, media_type in images:
        if media_type not in ALLOWED_IMAGE_TYPES:
            raise ValueError(f"unsupported image type {media_type!r}")

    content: list[dict[str, Any]] = [
        {
            "type": "image",
            "source": {
                "type": "base64", "media_type": media_type, "data": b64,
            },
        }
        for b64, media_type in images
    ]
    content.append({
        "type": "text",
        "text": (
            f"{len(images)} photo(s) of the same packaged food. Some may "
            "show the front of the pack (product name, brand, net weight) "
            "and some the Nutrition Facts panel (the numbers). Combine "
            "them and answer via the `give_nutrition_label` tool."
            if len(images) > 1 else
            "Transcribe this nutrition label via the "
            "`give_nutrition_label` tool."
        ),
    })

    client = get_provider(cfg)
    resp = await client.messages.create(
        model=cfg.model,
        max_tokens=900,
        system=_cached_system(_label_system(cfg.tone), cfg),
        tools=[LABEL_TOOL],
        tool_choice={"type": "tool", "name": "give_nutrition_label"},
        messages=[{"role": "user", "content": content}],
    )

    tool_input: dict[str, Any] = {}
    for block in resp.content:
        if (getattr(block, "type", "") == "tool_use"
                and block.name == "give_nutrition_label"):
            tool_input = block.input  # type: ignore[assignment]
            break
    if not tool_input:
        tool_input = {
            "basis": "unknown",
            "notes": ["Nothing could be read from that photo."],
        }

    _normalize_array_field(tool_input, "notes")
    _normalize_array_field(tool_input, "unreadable")
    return AiResult(
        content=json.dumps(tool_input),
        model=resp.model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )


# ── Weekly component prep plan (MEAL-9) ──────────────────────────────
#
# The one AI surface in this app that produces a WEEK of instructions
# rather than a card of observations, which changes what the model is
# allowed to be trusted with.
#
# It proposes *what to cook* and *how to combine it*. It does not produce
# a single number the user sees. Every gram, calorie, protein and fat
# figure on the finished plan is computed by `analytics/prep.py` from the
# food catalog after the tool call returns, against foods resolved from
# the catalog by search term. A meal plan is a wall of numbers, and a
# model-invented wall of numbers is worse than none at all — it looks
# exactly as authoritative as a real one.
#
# Two consequences of that split show up in the schema below:
#
#   * Components carry a `food_search` term, not a food id and not a
#     nutrition table. The server resolves the term against the same
#     catalog search the pickers use, so the plan's chicken is the same
#     chicken the food log costs.
#   * There is no `est_kcal` field anywhere. Earlier AI surfaces here do
#     accept model estimates (the meal-suggestion card asks for
#     `est_fat_g` and then re-judges it), but those describe a single
#     hypothetical meal. This describes a week of eating aimed at a
#     deficit, and an estimate that is 20% out compounds across fifteen
#     meals into a plan that does the opposite of what it claims.

PREP_PLAN_TOOL = {
    "name": "give_prep_plan",
    "description": (
        "Return one week of component batch cooking: a short list of "
        "things to cook in bulk on prep day, and the meals to assemble "
        "from them through the week."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {
                "type": "string",
                "description": (
                    "One sentence describing the week's theme, e.g. "
                    "'Roast chicken and rice bowls, four ways.'"
                ),
            },
            "components": {
                "type": "array",
                "description": (
                    "4-7 things to cook in bulk on prep day. Fewer, "
                    "bigger batches beat many small ones — the whole "
                    "point is one cooking session."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": (
                                "What it is once cooked, as you would "
                                "write it on the container lid, e.g. "
                                "'Roast chicken breast'."
                            ),
                        },
                        "kind": {
                            "type": "string",
                            "enum": [
                                "protein", "grain", "veg", "sauce", "other",
                            ],
                        },
                        "food_search": {
                            "type": "string",
                            "description": (
                                "Plain search term for the underlying "
                                "ingredient so the server can cost it "
                                "from the food catalog: 'chicken "
                                "breast', 'brown rice', 'broccoli'. Two "
                                "or three words, no brand, no cooking "
                                "method."
                            ),
                        },
                        "quantity": {
                            "type": "number",
                            "description": "Total raw amount to buy and cook.",
                        },
                        "unit": {
                            "type": "string",
                            "description": (
                                "Unit for quantity: g, kg, oz, lb, cup, "
                                "tbsp. Use weight for anything sold by "
                                "weight."
                            ),
                        },
                        "portions": {
                            "type": "integer",
                            "description": (
                                "How many meal-portions this batch "
                                "yields. Must equal the total portions "
                                "the meals below draw from it."
                            ),
                        },
                        "prep_note": {
                            "type": "string",
                            "description": (
                                "How to cook it, one line, with "
                                "temperature and time if it matters."
                            ),
                        },
                    },
                    "required": ["name", "kind", "food_search", "quantity",
                                 "unit", "portions"],
                },
            },
            "meals": {
                "type": "array",
                "description": (
                    "One entry per meal per day, for the slots and days "
                    "requested. Vary the assembly — the same three "
                    "components should not produce the same meal five "
                    "times."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "day_index": {
                            "type": "integer",
                            "description": "0 = the first day of the plan.",
                        },
                        "slot": {
                            "type": "string",
                            "enum": ["breakfast", "lunch", "dinner", "snack"],
                        },
                        "name": {
                            "type": "string",
                            "description": "What this assembles into, e.g. 'Chicken burrito bowl'.",
                        },
                        "uses": {
                            "type": "array",
                            "description": "Which components, and how many portions of each.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "component": {
                                        "type": "integer",
                                        "description": (
                                            "0-based index into the "
                                            "components array above."
                                        ),
                                    },
                                    "portions": {
                                        "type": "number",
                                        "description": (
                                            "Portions of that component, "
                                            "usually 1, 0.5 for a half."
                                        ),
                                    },
                                },
                                "required": ["component", "portions"],
                            },
                        },
                        "assembly_note": {
                            "type": "string",
                            "description": (
                                "How to put it together and anything "
                                "fresh to add on the day, one line."
                            ),
                        },
                    },
                    "required": ["day_index", "slot", "name", "uses"],
                },
            },
            "notes": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "0-3 short notes: swaps if a component runs out, "
                    "what to freeze, what to add fresh."
                ),
            },
        },
        "required": ["headline", "components", "meals"],
    },
}


def _prep_plan_system(tone: str) -> str:
    return (
        "You plan a week of COMPONENT BATCH COOKING for a single "
        "self-hosted user who cooks once at the weekend and eats from it "
        "through the week.\n\n"
        "## The model is components, not seven dinners\n"
        "Cook a small number of parts in bulk — a protein, a grain or "
        "starch, one or two vegetables, a sauce — and assemble them into "
        "DIFFERENT meals across the week. This is the entire point. A "
        "plan of seven separately-cooked dinners is not what was asked "
        "for and is not what gets cooked.\n\n"
        "Aim for 4-6 components. Fewer, larger batches beat many small "
        "ones: it is one cooking session, not seven.\n\n"
        "## Variety comes from assembly, not from more cooking\n"
        "The same chicken and rice becomes a burrito bowl, a stir-fry, a "
        "salad and a wrap depending on sauce, vegetable and what is "
        "added fresh on the day. Give each meal a distinct name and a "
        "distinct assembly note. Repeating the identical bowl five times "
        "is the failure this feature exists to avoid.\n\n"
        "## Cooked food does not keep forever\n"
        "Cooked chicken and fish keep about 4 days in a fridge; grains "
        "and roast vegetables about 5. Do not assign a component to a "
        "day beyond that unless you say to freeze that portion in its "
        "prep note.\n\n"
        "## Portions must balance\n"
        "Each component's `portions` must equal the total portions the "
        "meals draw from it. A batch that yields 4 portions cannot feed "
        "6 meals. Count before you answer.\n\n"
        "## Do not state calories, protein or grams anywhere\n"
        "You have no nutrition data and the server computes every number "
        "from its own food catalog. Size the batches from the per-meal "
        "energy budget you are given — that is what it is for — but do "
        "not write a calorie or macro figure into any text field. If you "
        "state one it will contradict the real number shown beside it.\n\n"
        "## Search terms are for a database, not a menu\n"
        "`food_search` must be a plain ingredient: 'chicken breast', "
        "'brown rice', 'sweet potato', 'olive oil'. Not 'organic "
        "free-range chicken', not 'perfectly roasted chicken breast'. "
        "Two or three words. If the term does not match a plain "
        "ingredient the component cannot be costed and the user sees a "
        "gap.\n\n"
        "## Use what is already in the house\n"
        "Pantry items are listed with how close they are to expiring. "
        "Building around what is about to go off is worth more than "
        "theoretical optimality, and it shortens the shopping list.\n\n"
        "## Training and fat constraints\n"
        "Strength days need more protein and carbohydrate than rest "
        "days; weight the larger portions onto them. If a per-meal fat "
        "target is given it is MEDICAL — keep every meal under it. If "
        "none is given, do not invent one.\n\n"
        f"{_tone_line(tone)}\n"
        "Answer only via the `give_prep_plan` tool."
    )


async def build_prep_plan_payload(
    db: AsyncSession,
    *,
    start_day: date,
    days: int,
    slots: list[str],
) -> dict[str, Any]:
    """Bounded payload for the weekly prep planner.

    Bounded in the same sense as every other surface here: names,
    amounts and a handful of derived numbers. No nutrition tables, no
    sample rows, no history beyond aggregates. The single largest thing
    in here is the pantry, and it is capped.
    """
    from sqlalchemy import select as _select

    from ..analytics.prep import slot_budgets
    from ..analytics.strength import schedule_day_type
    from ..analytics.targets import compute_targets
    from ..api.meals import DIET_KEY, _DIET_DEFAULTS

    profile = await db.get(models.UserProfile, 1)
    extra = (profile.extra if profile and profile.extra else {}) or {}
    diet = {**_DIET_DEFAULTS, **(extra.get(DIET_KEY) or {})}

    targets = await compute_targets_for_user(db)
    # An explicit diet target always wins over the equation — the user
    # typing a number is a decision, not an input to be averaged.
    target_kcal = diet.get("daily_kcal_target") or (
        targets.get("target_kcal") if targets.get("ok") else None
    )
    target_protein = (
        diet.get("daily_protein_target_g")
        or (targets.get("protein_g") if targets.get("ok") else None)
    )
    budgets = slot_budgets(target_kcal, target_protein, slots)

    # Pantry, soonest-to-expire first, capped. Same shape the suggestion
    # card uses so the two surfaces build around the same food.
    pantry_rows = (await db.execute(_select(models.PantryItem))).scalars().all()
    food_ids = {p.food_id for p in pantry_rows if p.food_id is not None}
    names: dict[int, str] = {}
    if food_ids:
        for fid, name in (await db.execute(
            _select(models.Food.id, models.Food.name)
            .where(models.Food.id.in_(food_ids))
        )).all():
            names[fid] = name
    pantry = []
    for p in pantry_rows:
        label = names.get(p.food_id) if p.food_id else p.label
        if not label:
            continue
        pantry.append({
            "item": label,
            "amount": (
                f"{p.quantity:g} {p.unit}".strip()
                if p.quantity is not None else (p.unit or "some")
            ),
            "days_to_expiry": (
                (p.expires_on - start_day).days if p.expires_on else None
            ),
        })
    pantry.sort(key=lambda x: (
        x["days_to_expiry"] if x["days_to_expiry"] is not None else 10**6
    ))
    pantry = pantry[:50]

    # The week's training, projected from the same deterministic
    # schedule the workout generator uses, so the plan's "strength day"
    # and the app's strength day are the same day.
    training = (extra.get("training") or {}) if extra else {}
    try:
        s_per_week = int(training.get("days_per_week", 3))
        c_per_week = int(training.get("cardio_days_per_week", 2))
    except (TypeError, ValueError):
        s_per_week, c_per_week = 3, 2
    week = []
    for i in range(days):
        d = start_day + timedelta(days=i)
        week.append({
            "day_index": i,
            "date": d.isoformat(),
            "weekday": d.strftime("%A"),
            "training": schedule_day_type(d, s_per_week, c_per_week),
        })

    # What was eaten recently, by name only — enough to avoid proposing
    # the exact thing they had three times last week, and nothing more.
    since = start_day - timedelta(days=14)
    recent_names = [
        n for (n,) in (await db.execute(
            _select(models.FoodLogEntry.label)
            .where(models.FoodLogEntry.label.isnot(None))
            .where(models.FoodLogEntry.eaten_on >= since)
            .distinct()
            .limit(40)
        )).all() if n
    ]

    return {
        "start_day": start_day.isoformat(),
        "days": days,
        "week": week,
        "profile": await _profile_ctx(db),
        "targets": {
            "daily_kcal": target_kcal,
            "daily_protein_g": target_protein,
            "basis": targets.get("basis") if targets.get("ok") else None,
            "goal": (
                "lose weight" if targets.get("ok")
                and targets.get("deficit_kcal") else "maintain"
            ),
        },
        "per_meal_budget": budgets,
        # The medical constraint. A null target is NOT permission to
        # guess a limit — same rule as the suggestion card.
        "fat_per_meal_target_g": diet.get("fat_per_meal_target_g"),
        "fat_target_source": diet.get("fat_target_source"),
        "diet_preferences": {
            k: v for k, v in diet.items()
            if k in ("style", "avoid", "dislikes", "allergies")
            and v
        },
        "pantry": pantry,
        "pantry_size": len(pantry_rows),
        "recently_eaten": recent_names,
        "fasting_status": await _fasting_status(db),
    }


async def compute_targets_for_user(db: AsyncSession) -> dict[str, Any]:
    """Run `analytics.targets.compute_targets` against the live profile.

    Lives here rather than in the targets module because that module is
    deliberately pure — it takes numbers and returns numbers, which is
    what makes it testable without a database.
    """
    from sqlalchemy import select as _select

    from ..analytics.targets import compute_targets, goal_target_kg

    profile = await db.get(models.UserProfile, 1)
    weight = (await db.execute(
        _select(models.BodyMetric.weight_kg)
        .where(models.BodyMetric.weight_kg.isnot(None))
        .order_by(models.BodyMetric.time.desc())
        .limit(1)
    )).scalar_one_or_none()

    extra = (profile.extra if profile and profile.extra else {}) or {}
    goal_kg = None
    goal_row = (await db.execute(
        _select(models.AiGoal)
        .where(models.AiGoal.kind == "weight")
        .where(models.AiGoal.ended_at.is_(None))
        .order_by(models.AiGoal.started_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if goal_row is not None:
        # The goal form stores the unit the user typed. Reading 200 lb as
        # 200 kg concludes they are trying to GAIN 86 kg and prescribes a
        # surplus, silently and plausibly.
        goal_kg = goal_target_kg(goal_row.target_value, goal_row.target_unit)

    return compute_targets(
        weight_kg=float(weight) if weight is not None else None,
        height_cm=float(profile.height_cm) if profile and profile.height_cm else None,
        birth_date=profile.birth_date if profile else None,
        sex=(profile.sex if profile else None),
        activity_level=extra.get("activity_level"),
        goal_weight_kg=goal_kg,
        today=_local_today(),
        training_load_band=None,
    )


async def prep_plan(
    db: AsyncSession,
    cfg: models.AiConfig,
    *,
    start_day: date,
    days: int,
    slots: list[str],
) -> AiResult:
    """Generate one week of component batch cooking."""
    if not cfg.enabled or _credentials_missing(cfg):
        raise RuntimeError("AI is disabled or no credentials configured")

    payload = await build_prep_plan_payload(
        db, start_day=start_day, days=days, slots=slots,
    )
    user_text = (
        "Plan this user's week of batch cooking via the `give_prep_plan` "
        "tool:\n\n"
        f"{json.dumps(payload, indent=2, default=str)}\n"
    )
    client = get_provider(cfg)
    resp = await client.messages.create(
        model=cfg.model,
        # A week of meals is the largest structured output in the app.
        max_tokens=4000,
        system=_cached_system(_prep_plan_system(cfg.tone), cfg),
        tools=[PREP_PLAN_TOOL],
        tool_choice={"type": "tool", "name": "give_prep_plan"},
        messages=[{"role": "user", "content": user_text}],
    )
    tool_input: dict[str, Any] = {}
    for block in resp.content:
        if (getattr(block, "type", "") == "tool_use"
                and block.name == "give_prep_plan"):
            tool_input = block.input  # type: ignore[assignment]
            break
    if not tool_input:
        tool_input = {"headline": "", "components": [], "meals": [], "notes": []}

    _normalize_array_field(tool_input, "notes")
    return AiResult(
        content=json.dumps(tool_input),
        model=resp.model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )
