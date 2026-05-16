"""AI summary endpoints — config + targeted explain + weekly digest."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..analytics.trends import compute_badges
from ..auth import require_any
from ..db import models
from ..db.session import get_session
from ..integrations.claude import (
    ask,
    build_cardio_coach_payload,
    build_recovery_coach_payload,
    build_sleep_coach_payload,
    build_summary_payload,
    build_topic_payload,
    build_workout_coach_payload,
    cardio_coach,
    explain_discovery,
    explain_legacy,
    explain_topic,
    hash_payload,
    pre_workout,
    recovery_coach,
    sleep_coach,
    verdict,
    workout_coach,
)

router = APIRouter(prefix="/ai", dependencies=[Depends(require_any)])


def _mask_key(k: str | None) -> str | None:
    if not k:
        return None
    if len(k) <= 12:
        return "*" * len(k)
    return f"{k[:7]}…{k[-4:]}"


async def _get_config(db: AsyncSession) -> models.AiConfig:
    cfg = await db.get(models.AiConfig, 1)
    if cfg is None:
        cfg = models.AiConfig(id=1, enabled=False, model="claude-haiku-4-5-20251001")
        db.add(cfg)
        await db.commit()
        await db.refresh(cfg)
    return cfg


# ─────────────── Config ───────────────

@router.get("/config")
async def get_config(db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    cfg = await _get_config(db)
    return {
        "enabled": cfg.enabled,
        "api_key_set": bool(cfg.anthropic_api_key),
        "api_key_masked": _mask_key(cfg.anthropic_api_key),
        "model": cfg.model,
        "daily_call_limit": cfg.daily_call_limit,
        "calls_today": cfg.calls_today if cfg.calls_today_date == date.today() else 0,
        "weekly_digest_enabled": cfg.weekly_digest_enabled,
        "tone": cfg.tone,
    }


class ConfigUpdate(BaseModel):
    enabled: bool | None = None
    anthropic_api_key: str | None = None
    clear_key: bool = False
    model: str | None = None
    daily_call_limit: int | None = None
    weekly_digest_enabled: bool | None = None
    tone: str | None = None


@router.post("/config")
async def update_config(
    body: ConfigUpdate, db: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    cfg = await _get_config(db)
    if body.enabled is not None:
        cfg.enabled = body.enabled
    if body.clear_key:
        cfg.anthropic_api_key = None
    elif body.anthropic_api_key is not None and body.anthropic_api_key != "":
        cfg.anthropic_api_key = body.anthropic_api_key
    if body.model:
        cfg.model = body.model
    if body.daily_call_limit is not None:
        cfg.daily_call_limit = max(1, min(200, body.daily_call_limit))
    if body.weekly_digest_enabled is not None:
        cfg.weekly_digest_enabled = body.weekly_digest_enabled
    if body.tone is not None and body.tone in ("supportive", "blunt", "data-only"):
        cfg.tone = body.tone
    cfg.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return await get_config(db)


# ─────────────── Trend badges (no LLM) ───────────────

@router.get("/badges")
async def get_badges(db: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    """Pure-stats trend badges for the Today header. No external calls."""
    return await compute_badges(db, max_badges=5)


# ─────────────── Preview / debug ───────────────

@router.get("/preview-payload")
async def preview_payload(
    range: str = "week",
    topic: str | None = None,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Return the exact aggregate JSON we'd send to Claude — for the user
    to audit before flipping the feature on. No external calls."""
    if topic and topic in ("sleep", "recovery", "sober", "anomaly"):
        return await build_topic_payload(db, topic, days=14)
    if range not in ("week", "month"):
        raise HTTPException(status_code=400, detail="range must be week or month")
    return await build_summary_payload(db, range)


# ─────────────── Quota guard ───────────────

async def _check_and_bump_quota(db: AsyncSession, cfg: models.AiConfig) -> None:
    if not cfg.enabled:
        raise HTTPException(status_code=400, detail="AI summaries disabled in Settings")
    if not cfg.anthropic_api_key:
        raise HTTPException(status_code=400, detail="Anthropic API key not configured")
    today = date.today()
    if cfg.calls_today_date != today:
        cfg.calls_today = 0
        cfg.calls_today_date = today
    if cfg.calls_today >= cfg.daily_call_limit:
        raise HTTPException(
            status_code=429,
            detail=f"Daily call limit ({cfg.daily_call_limit}) reached",
        )


# ─────────────── Legacy free-form explain (markdown) ───────────────

@router.post("/explain")
async def explain_endpoint(
    range: str = "week", db: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    if range not in ("week", "month"):
        raise HTTPException(status_code=400, detail="range must be week or month")
    cfg = await _get_config(db)
    await _check_and_bump_quota(db, cfg)

    payload = await build_summary_payload(db, range)
    payload_hash = hash_payload(payload)
    cached = (await db.execute(
        select(models.AiSummary)
        .where(models.AiSummary.range_kind == range)
        .where(models.AiSummary.payload_hash == payload_hash)
        .order_by(models.AiSummary.generated_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if cached is not None:
        return {
            "content": cached.content, "generated_at": cached.generated_at,
            "model": cached.model, "cached": True,
            "input_tokens": cached.input_tokens, "output_tokens": cached.output_tokens,
        }

    result = await explain_legacy(db, range, cfg)
    cfg.calls_today += 1
    summary = models.AiSummary(
        generated_at=datetime.now(timezone.utc),
        range_kind=range,
        payload_hash=payload_hash,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        content=result.content,
    )
    db.add(summary)
    await db.commit()
    return {
        "content": result.content, "generated_at": summary.generated_at,
        "model": result.model, "cached": False,
        "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
    }


@router.get("/latest")
async def latest_summary(
    range: str = "week", db: AsyncSession = Depends(get_session)
) -> dict[str, Any] | None:
    if range not in ("week", "month"):
        raise HTTPException(status_code=400, detail="range must be week or month")
    row = (await db.execute(
        select(models.AiSummary)
        .where(models.AiSummary.range_kind == range)
        .order_by(models.AiSummary.generated_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if row is None:
        return None
    return {"content": row.content, "generated_at": row.generated_at, "model": row.model}


# ─────────────── Targeted explain (structured JSON) ───────────────

ALLOWED_TOPICS = {"week", "month", "sleep", "recovery", "sober", "anomaly"}


@router.post("/explain/{topic}")
async def explain_topic_endpoint(
    topic: str, db: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Targeted analysis with structured output. Returns:
        { headline, tone, evidence: [...], suggestion, generated_at, model }"""
    if topic not in ALLOWED_TOPICS:
        raise HTTPException(status_code=400, detail=f"topic must be one of {sorted(ALLOWED_TOPICS)}")
    cfg = await _get_config(db)
    await _check_and_bump_quota(db, cfg)

    if topic in ("week", "month"):
        payload = await build_summary_payload(db, topic)
    else:
        payload = await build_topic_payload(db, topic, days=14)
    payload_hash = hash_payload({"topic": topic, **payload})

    cached = (await db.execute(
        select(models.AiSummary)
        .where(models.AiSummary.range_kind == topic)
        .where(models.AiSummary.payload_hash == payload_hash)
        .order_by(models.AiSummary.generated_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if cached is not None:
        try:
            import json as _json
            data = _json.loads(cached.content)
        except Exception:  # noqa: BLE001
            data = {"headline": cached.content, "tone": "neutral", "evidence": [], "suggestion": ""}
        return {
            **data,
            "generated_at": cached.generated_at,
            "model": cached.model,
            "cached": True,
        }

    result = await explain_topic(db, topic, cfg)
    cfg.calls_today += 1
    summary = models.AiSummary(
        generated_at=datetime.now(timezone.utc),
        range_kind=topic,
        payload_hash=payload_hash,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        content=result.content,
    )
    db.add(summary)
    await db.commit()
    import json as _json
    try:
        data = _json.loads(result.content)
    except Exception:  # noqa: BLE001
        data = {"headline": result.content, "tone": "neutral", "evidence": [], "suggestion": ""}
    return {
        **data,
        "generated_at": summary.generated_at,
        "model": result.model,
        "cached": False,
    }


# ─────────────── Today's verdict ───────────────

@router.post("/verdict")
async def verdict_endpoint(db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """One-line headline summarising current state. Cached by the most
    recent vital timestamp, so the headline doesn't re-bill on every
    page load — it only refreshes when new data arrives."""
    cfg = await _get_config(db)
    await _check_and_bump_quota(db, cfg)
    payload = {
        "kind": "verdict",
        "tone": cfg.tone,
        # Use only the freshest day as cache key — stable across reloads
        # but flips when fresh data lands.
    }
    # Build the real payload to compute hash
    from ..integrations.claude import build_verdict_payload as _bvp
    real = await _bvp(db)
    payload_hash = hash_payload({**payload, "snapshot": real})

    cached = (await db.execute(
        select(models.AiSummary)
        .where(models.AiSummary.range_kind == "verdict")
        .where(models.AiSummary.payload_hash == payload_hash)
        .order_by(models.AiSummary.generated_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if cached is not None:
        return {
            "content": cached.content,
            "generated_at": cached.generated_at,
            "model": cached.model,
            "cached": True,
        }
    result = await verdict(db, cfg)
    cfg.calls_today += 1
    summary = models.AiSummary(
        generated_at=datetime.now(timezone.utc),
        range_kind="verdict",
        payload_hash=payload_hash,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        content=result.content,
    )
    db.add(summary)
    await db.commit()
    return {
        "content": result.content,
        "generated_at": summary.generated_at,
        "model": result.model,
        "cached": False,
    }


@router.get("/verdict/latest")
async def verdict_latest(db: AsyncSession = Depends(get_session)) -> dict[str, Any] | None:
    row = (await db.execute(
        select(models.AiSummary)
        .where(models.AiSummary.range_kind == "verdict")
        .order_by(models.AiSummary.generated_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if row is None:
        return None
    return {"content": row.content, "generated_at": row.generated_at, "model": row.model}


# ─────────────── Pre-workout ───────────────

@router.post("/pre-workout")
async def pre_workout_endpoint(db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    cfg = await _get_config(db)
    await _check_and_bump_quota(db, cfg)
    result = await pre_workout(db, cfg)
    cfg.calls_today += 1
    await db.commit()
    return {
        "content": result.content,
        "generated_at": datetime.now(timezone.utc),
        "model": result.model,
    }


# ─────────────── Free-form Q&A ───────────────

class AskBody(BaseModel):
    question: str


@router.post("/ask")
async def ask_endpoint(
    body: AskBody, db: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    if not body.question or not body.question.strip():
        raise HTTPException(status_code=400, detail="question is required")
    cfg = await _get_config(db)
    await _check_and_bump_quota(db, cfg)
    result = await ask(db, cfg, body.question.strip())
    cfg.calls_today += 1
    await db.commit()
    return {
        "content": result.content,
        "generated_at": datetime.now(timezone.utc),
        "model": result.model,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }


# ─────────────── Discovery explainer ───────────────

class DiscoveryBody(BaseModel):
    x_metric: str
    y_metric: str


@router.post("/explain-discovery")
async def explain_discovery_endpoint(
    body: DiscoveryBody, db: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    cfg = await _get_config(db)
    await _check_and_bump_quota(db, cfg)
    result = await explain_discovery(db, cfg, body.x_metric, body.y_metric)
    if result.input_tokens > 0:
        cfg.calls_today += 1
        await db.commit()
    return {
        "content": result.content,
        "generated_at": datetime.now(timezone.utc),
        "model": result.model,
    }


# ─────────────── Alerts (anomaly notifications) ───────────────

@router.get("/alerts")
async def list_alerts(
    unacked_only: bool = True, limit: int = 20,
    db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    # Lazy-trigger anomaly scan when the most recent run is &gt; 6h old.
    # Replaces the standalone APScheduler job — phone + web both poll
    # /ai/alerts, so the scan piggybacks on actual demand instead of
    # firing on a fixed cadence regardless of whether anyone's looking.
    await _maybe_run_anomaly_scan(db)
    await _check_goals_for_completion(db)

    stmt = (
        select(models.AiAlert)
        .order_by(models.AiAlert.created_at.desc())
        .limit(limit)
    )
    if unacked_only:
        stmt = stmt.where(models.AiAlert.acked_at.is_(None))
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {"id": r.id, "created_at": r.created_at, "kind": r.kind,
         "severity": r.severity, "title": r.title, "body": r.body,
         "metric": r.metric, "z_score": r.z_score, "acked_at": r.acked_at,
         "phone_notified_at": r.phone_notified_at}
        for r in rows
    ]


# Lock so concurrent /ai/alerts calls don't double-scan. asyncio Lock is
# sufficient since we're single-process (uvicorn worker count = 1 in
# the deployment).
_anomaly_scan_lock = __import__("asyncio").Lock()


async def _check_goals_for_completion(db: AsyncSession) -> None:
    """Auto-complete active AiGoals once their targets are crossed
    (GOALS-6). Hardcoded direction convention by kind — `weight` going
    down, the rest going up. Creates a 'good'-severity goal_reached
    AiAlert with a per-goal dedup_key so re-firing is structurally
    impossible.
    """
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    from sqlalchemy import func as _func
    now = _dt.now(_tz.utc)
    today = now.date()
    goals = (await db.execute(
        select(models.AiGoal)
        .where(models.AiGoal.ended_at.is_(None))
        .where(models.AiGoal.target_value.is_not(None))
    )).scalars().all()
    if not goals:
        return

    kinds = {g.kind for g in goals}

    latest_weight_kg: float | None = None
    if "weight" in kinds:
        latest_weight_kg = (await db.execute(
            select(models.BodyMetric.weight_kg)
            .where(models.BodyMetric.weight_kg.is_not(None))
            .order_by(models.BodyMetric.time.desc())
            .limit(1)
        )).scalar_one_or_none()

    avg_sleep_h: float | None = None
    if "sleep" in kinds:
        since = today - _td(days=7)
        rows = (await db.execute(
            select(models.DailySummary.sleep_duration_s)
            .where(models.DailySummary.date >= since)
            .where(models.DailySummary.sleep_duration_s.is_not(None))
        )).scalars().all()
        if rows:
            avg_sleep_h = sum(rows) / len(rows) / 3600.0

    today_steps: int | None = None
    if "steps" in kinds:
        today_steps = (await db.execute(
            select(models.DailySummary.steps_total)
            .where(models.DailySummary.date == today)
            .limit(1)
        )).scalar_one_or_none()

    sober_days: float | None = None
    if "sober" in kinds:
        s = (await db.execute(
            select(models.SoberStreak)
            .where(models.SoberStreak.end_at.is_(None))
            .limit(1)
        )).scalar_one_or_none()
        if s is not None:
            sober_days = (now - s.start_at).total_seconds() / 86400.0

    # FAST-17: fast_streak. Sum daily_summary.fasting_hours over the
    # trailing 7d and compare to the goal target value (interpreted as
    # weekly cumulative fasting hours).
    fast_streak_hours_7d: float | None = None
    if "fast_streak" in kinds:
        since = today - _td(days=6)
        rows = (await db.execute(
            select(models.DailySummary.fasting_hours)
            .where(models.DailySummary.date >= since)
            .where(models.DailySummary.date <= today)
        )).all()
        fast_streak_hours_7d = sum((r[0] or 0) for r in rows)

    def _target_kg(g: models.AiGoal) -> float:
        """Normalise a weight goal's target to kilograms regardless of
        the unit the user typed it in. The /goals form lets users pick
        either kg or lb; storing both unit + value lets us be robust
        without forcing a migration."""
        unit = (g.target_unit or "").strip().lower()
        if unit in ("lb", "lbs", "pound", "pounds"):
            return g.target_value / 2.20462
        return g.target_value

    new_alerts: list[models.AiAlert] = []
    for g in goals:
        reached = False
        evidence = "—"
        if g.kind == "weight" and latest_weight_kg is not None:
            target_kg = _target_kg(g)
            reached = latest_weight_kg <= target_kg
            evidence = f"{latest_weight_kg:.1f} kg vs target {target_kg:.1f} kg"
        elif g.kind == "sleep" and avg_sleep_h is not None:
            # target_unit on sleep goals is typically "h" or "h/night";
            # value is hours either way.
            reached = avg_sleep_h >= g.target_value
            evidence = f"{avg_sleep_h:.1f}h/night avg vs target {g.target_value:.1f}h"
        elif g.kind == "steps" and today_steps is not None:
            reached = float(today_steps) >= g.target_value
            evidence = f"{today_steps:,} steps today vs target {int(g.target_value):,}"
        elif g.kind == "sober" and sober_days is not None:
            reached = sober_days >= g.target_value
            evidence = f"{sober_days:.0f} sober days vs target {int(g.target_value)}"
        elif g.kind == "fast_streak" and fast_streak_hours_7d is not None:
            reached = fast_streak_hours_7d >= g.target_value
            evidence = (
                f"{fast_streak_hours_7d:.1f}h fasted in last 7d "
                f"vs target {g.target_value:.0f}h/week"
            )
        if not reached:
            continue
        g.ended_at = now
        dedup_key = f"goal_reached:{g.id}"
        # Dedup by dedup_key so a phantom re-create can't double-alert.
        # _anomaly_scan uses the same mechanism for the same reason.
        existing = (await db.execute(
            select(_func.count(models.AiAlert.id))
            .where(models.AiAlert.dedup_key == dedup_key)
        )).scalar_one()
        if existing == 0:
            new_alerts.append(models.AiAlert(
                created_at=now, kind="goal_reached", severity="good",
                title=f"Goal reached: {g.title}",
                body=f"{evidence} — automatically marked complete.",
                metric=g.kind, dedup_key=dedup_key,
            ))
    for a in new_alerts:
        db.add(a)
    if new_alerts or any(g.ended_at == now for g in goals):
        await db.commit()


async def _maybe_run_anomaly_scan(db: AsyncSession) -> None:
    """Run the anomaly scan if the latest persisted alert is &gt; 6h old.
    Idempotent — repeated calls within the cooldown are no-ops."""
    from datetime import datetime, timezone, timedelta
    from ..db import models as _models
    last = (await db.execute(
        select(_models.AiAlert.created_at)
        .order_by(_models.AiAlert.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
    if last is not None and last >= cutoff:
        return
    if _anomaly_scan_lock.locked():
        return  # another caller is already running it
    async with _anomaly_scan_lock:
        from ..main import _anomaly_scan
        try:
            await _anomaly_scan()
        except Exception:  # noqa: BLE001
            # Don't block /ai/alerts on scan failure
            pass


@router.post("/alerts/{alert_id}/ack")
async def ack_alert(alert_id: int, db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    row = await db.get(models.AiAlert, alert_id)
    if row is None:
        raise HTTPException(status_code=404, detail="alert not found")
    row.acked_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True}


@router.post("/alerts/ack-all")
async def ack_all_alerts(db: AsyncSession = Depends(get_session)) -> dict[str, int]:
    from sqlalchemy import update as _update
    res = await db.execute(
        _update(models.AiAlert)
        .where(models.AiAlert.acked_at.is_(None))
        .values(acked_at=datetime.now(timezone.utc))
    )
    await db.commit()
    return {"acked": res.rowcount or 0}


@router.post("/alerts/mark-notified")
async def mark_alerts_notified(
    ids: list[int], db: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    """Phone calls this after posting a system notification — prevents
    re-notifying for the same alert next sync."""
    if not ids:
        return {"marked": 0}
    from sqlalchemy import update as _update
    res = await db.execute(
        _update(models.AiAlert)
        .where(models.AiAlert.id.in_(ids))
        .values(phone_notified_at=datetime.now(timezone.utc))
    )
    await db.commit()
    return {"marked": res.rowcount or 0}


# ─────────────── Goals (CRUD + check-in) ───────────────


# Goal kinds whose target value lives ALSO in user_profile / .extra
# (single source of truth — see GOALS-1). When one of these changes
# on either side, the other side is brought along.
def _profile_target_for_kind(kind: str, prof: models.UserProfile | None) -> float | None:
    if prof is None:
        return None
    if kind == "weight":
        return prof.weight_goal_kg
    if kind == "sleep":
        return prof.sleep_target_h
    if kind == "steps":
        extra = prof.extra or {}
        v = extra.get("steps_goal")
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None
    if kind == "fast_streak":
        return prof.fasting_target_hours_per_week
    return None


async def _profile_set_target_for_kind(
    db: AsyncSession, kind: str, value: float | None,
) -> None:
    """Bidirectional sync: writing a goal target writes back to the
    matching profile field so a single source of truth is preserved."""
    prof = await db.get(models.UserProfile, 1)
    if prof is None:
        return
    if kind == "weight":
        prof.weight_goal_kg = value
    elif kind == "sleep":
        prof.sleep_target_h = value
    elif kind == "steps":
        extra = dict(prof.extra or {})
        if value is None:
            extra.pop("steps_goal", None)
        else:
            extra["steps_goal"] = int(value)
        prof.extra = extra
    elif kind == "fast_streak":
        prof.fasting_target_hours_per_week = value
    else:
        return
    prof.updated_at = datetime.now(timezone.utc)


class GoalCreate(BaseModel):
    kind: str
    title: str
    target_value: float | None = None
    target_unit: str | None = None
    target_date: date | None = None
    notes: str | None = None


class GoalUpdate(BaseModel):
    title: str | None = None
    target_value: float | None = None
    target_unit: str | None = None
    target_date: date | None = None
    ended_at: datetime | None = None
    notes: str | None = None


def _goal_to_dict(g: models.AiGoal) -> dict[str, Any]:
    return {
        "id": g.id, "kind": g.kind, "title": g.title,
        "target_value": g.target_value, "target_unit": g.target_unit,
        "target_date": g.target_date, "started_at": g.started_at,
        "ended_at": g.ended_at, "notes": g.notes,
    }


async def _baseline_weight_kg_for_goal(
    db: AsyncSession, started_at: datetime,
) -> float | None:
    """First body_metrics row at or after the goal's started_at, used
    as the progress denominator for weight goals so the progress bar
    measures "distance from where you began" rather than a heuristic
    baseline."""
    return (await db.execute(
        select(models.BodyMetric.weight_kg)
        .where(models.BodyMetric.weight_kg.is_not(None))
        .where(models.BodyMetric.time >= started_at)
        .order_by(models.BodyMetric.time.asc())
        .limit(1)
    )).scalar_one_or_none()


async def _current_values_for_goals(
    db: AsyncSession, kinds: set[str],
) -> dict[str, float | None]:
    """Pull the latest-progress value for each goal kind the caller cares
    about (GOALS-3 + GOALS-6 share this). Keys present in the returned
    dict correspond to AiGoal.kind values; entries may be None if no
    underlying data has landed yet."""
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    now = _dt.now(_tz.utc)
    today = now.date()
    out: dict[str, float | None] = {}
    if "weight" in kinds:
        out["weight"] = (await db.execute(
            select(models.BodyMetric.weight_kg)
            .where(models.BodyMetric.weight_kg.is_not(None))
            .order_by(models.BodyMetric.time.desc())
            .limit(1)
        )).scalar_one_or_none()
    if "sleep" in kinds:
        since = today - _td(days=7)
        rows = (await db.execute(
            select(models.DailySummary.sleep_duration_s)
            .where(models.DailySummary.date >= since)
            .where(models.DailySummary.sleep_duration_s.is_not(None))
        )).scalars().all()
        out["sleep"] = (sum(rows) / len(rows) / 3600.0) if rows else None
    if "steps" in kinds:
        v = (await db.execute(
            select(models.DailySummary.steps_total)
            .where(models.DailySummary.date == today)
            .limit(1)
        )).scalar_one_or_none()
        out["steps"] = float(v) if v is not None else None
    if "sober" in kinds:
        s = (await db.execute(
            select(models.SoberStreak)
            .where(models.SoberStreak.end_at.is_(None))
            .limit(1)
        )).scalar_one_or_none()
        out["sober"] = (
            (now - s.start_at).total_seconds() / 86400.0 if s is not None else None
        )
    if "fast_streak" in kinds:
        since = today - _td(days=6)
        rows = (await db.execute(
            select(models.DailySummary.fasting_hours)
            .where(models.DailySummary.date >= since)
            .where(models.DailySummary.date <= today)
        )).all()
        out["fast_streak"] = sum((r[0] or 0) for r in rows)
    return out


def _goal_progress(
    g: models.AiGoal, current: float | None, baseline: float | None = None,
) -> dict[str, Any]:
    """Direction-aware progress for a goal (GOALS-3).

    - weight: loss-oriented. Progress measured against `baseline` (the
      weight at goal-start). Falls back to `current + 1` so the bar
      shows ~0% until real progress is made, rather than a confusing
      negative pct.
    - sleep / steps / sober: gain-oriented. Progress = current / target.
    """
    if current is None or g.target_value is None:
        return {"current_value": None, "progress_pct": None}
    unit = (g.target_unit or "").strip().lower()
    target = g.target_value
    if g.kind == "weight":
        target_kg = (target / 2.20462) if unit in ("lb", "lbs", "pound", "pounds") else target
        start = baseline if baseline is not None else (current + 1.0)
        denom = start - target_kg
        if denom <= 0:
            pct = 100.0 if current <= target_kg else 0.0
        else:
            pct = (start - current) / denom * 100.0
        pct = max(0.0, min(100.0, pct))
        return {"current_value": round(current, 2), "progress_pct": round(pct, 1)}
    # Gain-oriented kinds
    pct = (current / target * 100.0) if target > 0 else 0.0
    pct = max(0.0, min(100.0, pct))
    return {"current_value": round(current, 2), "progress_pct": round(pct, 1)}


@router.get("/goals")
async def list_goals(
    active_only: bool = True, db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    stmt = select(models.AiGoal).order_by(models.AiGoal.started_at.desc())
    if active_only:
        stmt = stmt.where(models.AiGoal.ended_at.is_(None))
    goals = (await db.execute(stmt)).scalars().all()
    kinds = {g.kind for g in goals if g.ended_at is None}
    currents = await _current_values_for_goals(db, kinds) if kinds else {}
    out: list[dict[str, Any]] = []
    for g in goals:
        d = _goal_to_dict(g)
        if g.ended_at is None and g.kind in currents:
            baseline = None
            if g.kind == "weight":
                baseline = await _baseline_weight_kg_for_goal(db, g.started_at)
            d.update(_goal_progress(g, currents[g.kind], baseline))
            d["baseline_value"] = round(baseline, 2) if baseline is not None else None
        else:
            d["current_value"] = None
            d["progress_pct"] = None
            d["baseline_value"] = None
        out.append(d)
    return out


@router.post("/goals")
async def create_goal(
    body: GoalCreate, db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    # GOALS-1 sync: if target_value was omitted and the kind has a
    # matching profile field, prefill from the profile so the goal +
    # profile don't diverge. If target_value was provided, write it
    # back to the profile.
    target = body.target_value
    if target is None:
        prof = await db.get(models.UserProfile, 1)
        target = _profile_target_for_kind(body.kind, prof)
    else:
        await _profile_set_target_for_kind(db, body.kind, target)
    g = models.AiGoal(
        kind=body.kind, title=body.title,
        target_value=target, target_unit=body.target_unit,
        target_date=body.target_date, started_at=datetime.now(timezone.utc),
        notes=body.notes,
    )
    db.add(g)
    await db.commit()
    await db.refresh(g)
    return _goal_to_dict(g)


@router.patch("/goals/{goal_id}")
async def update_goal(
    goal_id: int, body: GoalUpdate, db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    g = await db.get(models.AiGoal, goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="goal not found")
    patch = body.model_dump(exclude_unset=True)
    for k, v in patch.items():
        setattr(g, k, v)
    # GOALS-1 sync: when target_value was patched and this goal's
    # kind has a matching profile field, push the change to the profile.
    if "target_value" in patch:
        await _profile_set_target_for_kind(db, g.kind, g.target_value)
    await db.commit()
    await db.refresh(g)
    return _goal_to_dict(g)


@router.delete("/goals/{goal_id}", status_code=204)
async def delete_goal(goal_id: int, db: AsyncSession = Depends(get_session)) -> None:
    g = await db.get(models.AiGoal, goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="goal not found")
    await db.delete(g)
    await db.commit()


@router.post("/goals/{goal_id}/check")
async def goal_check_endpoint(
    goal_id: int, db: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    cfg = await _get_config(db)
    await _check_and_bump_quota(db, cfg)
    g = await db.get(models.AiGoal, goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="goal not found")
    from ..integrations.claude import goal_check
    result = await goal_check(db, cfg, g)
    cfg.calls_today += 1
    await db.commit()
    return {"content": result.content, "model": result.model,
            "generated_at": datetime.now(timezone.utc)}


# ─────────────── Post-activity summary ───────────────

@router.post("/activity/{source}/{source_id}/summary")
async def activity_summary_endpoint(
    source: str, source_id: str, db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    cfg = await _get_config(db)
    await _check_and_bump_quota(db, cfg)
    act = (await db.execute(
        select(models.Activity).where(
            (models.Activity.source == source) & (models.Activity.source_id == source_id)
        )
    )).scalar_one_or_none()
    if act is None:
        raise HTTPException(status_code=404, detail="activity not found")
    from ..integrations.claude import activity_summary
    result = await activity_summary(db, cfg, act)
    cfg.calls_today += 1
    await db.commit()
    return {"content": result.content, "model": result.model,
            "generated_at": datetime.now(timezone.utc)}


# ─────────────── Strength workout review ───────────────

@router.post("/strength/review/{workout_id}")
async def strength_review_endpoint(
    workout_id: int, db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Structured post-workout review for a completed strength session.

    Cached by payload_hash via the existing ai_summaries table — re-running
    after the user logs another set updates the hash and re-bills; running
    twice on the same finished workout is free."""
    workout = await db.get(models.StrengthWorkout, workout_id)
    if workout is None:
        raise HTTPException(status_code=404, detail="workout not found")

    cfg = await _get_config(db)
    await _check_and_bump_quota(db, cfg)

    from ..integrations.claude import (
        build_strength_review_payload, strength_review,
    )
    payload = await build_strength_review_payload(db, workout_id)
    payload_hash = hash_payload(payload)
    range_kind = f"strength_review:{workout_id}"
    cached = (await db.execute(
        select(models.AiSummary)
        .where(models.AiSummary.range_kind == range_kind)
        .where(models.AiSummary.payload_hash == payload_hash)
        .order_by(models.AiSummary.generated_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if cached is not None:
        import json as _json
        try: review = _json.loads(cached.content)
        except Exception: review = {}  # noqa: BLE001
        return {
            "review": review, "generated_at": cached.generated_at,
            "model": cached.model, "cached": True,
            "input_tokens": cached.input_tokens, "output_tokens": cached.output_tokens,
        }

    result = await strength_review(db, workout_id, cfg)
    cfg.calls_today += 1
    summary = models.AiSummary(
        generated_at=datetime.now(timezone.utc),
        range_kind=range_kind, payload_hash=payload_hash,
        model=result.model,
        input_tokens=result.input_tokens, output_tokens=result.output_tokens,
        content=result.content,
    )
    db.add(summary)
    await db.commit()
    import json as _json
    try: review = _json.loads(result.content)
    except Exception: review = {}  # noqa: BLE001
    return {
        "review": review, "generated_at": summary.generated_at,
        "model": result.model, "cached": False,
        "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
    }


# ─────────────── Strength variety nudge ───────────────

@router.post("/strength/nudge/{workout_id}")
async def strength_nudge_endpoint(
    workout_id: int, db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Up to 2 swap suggestions for today's planned workout, based on
    recent exercise history. Cached in ai_summaries by payload hash:
    same plan + same trailing-4-week history = free re-fetch."""
    workout = await db.get(models.StrengthWorkout, workout_id)
    if workout is None:
        raise HTTPException(status_code=404, detail="workout not found")

    cfg = await _get_config(db)
    await _check_and_bump_quota(db, cfg)

    from ..analytics import strength as strength_algo
    from ..integrations.claude import (
        build_strength_nudge_payload, strength_nudge,
    )
    catalog_by_id = strength_algo.CATALOG_BY_ID

    payload = await build_strength_nudge_payload(db, workout_id, catalog_by_id)
    payload_hash = hash_payload(payload)
    range_kind = f"strength_nudge:{workout_id}"
    cached = (await db.execute(
        select(models.AiSummary)
        .where(models.AiSummary.range_kind == range_kind)
        .where(models.AiSummary.payload_hash == payload_hash)
        .order_by(models.AiSummary.generated_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if cached is not None:
        import json as _json
        try: nudge = _json.loads(cached.content)
        except Exception: nudge = {"swaps": []}  # noqa: BLE001
        return {
            "nudge": nudge, "generated_at": cached.generated_at,
            "model": cached.model, "cached": True,
            "input_tokens": cached.input_tokens, "output_tokens": cached.output_tokens,
        }

    result = await strength_nudge(db, workout_id, cfg, catalog_by_id)
    cfg.calls_today += 1
    summary = models.AiSummary(
        generated_at=datetime.now(timezone.utc),
        range_kind=range_kind, payload_hash=payload_hash,
        model=result.model,
        input_tokens=result.input_tokens, output_tokens=result.output_tokens,
        content=result.content,
    )
    db.add(summary)
    await db.commit()
    import json as _json
    try: nudge = _json.loads(result.content)
    except Exception: nudge = {"swaps": []}  # noqa: BLE001
    return {
        "nudge": nudge, "generated_at": summary.generated_at,
        "model": result.model, "cached": False,
        "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
    }


# ─────────────── Pre-workout focus cue ───────────────

@router.post("/strength/focus-cue/{workout_id}")
async def strength_focus_cue_endpoint(
    workout_id: int, db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Short pre-workout coaching cue tied to today's specific plan
    + 6-week per-exercise history. Cached by payload hash like the
    other strength AI endpoints."""
    workout = await db.get(models.StrengthWorkout, workout_id)
    if workout is None:
        raise HTTPException(status_code=404, detail="workout not found")

    cfg = await _get_config(db)
    await _check_and_bump_quota(db, cfg)

    from ..analytics import strength as strength_algo
    from ..integrations.claude import (
        build_focus_cue_payload, strength_focus_cue,
    )
    catalog_by_id = strength_algo.CATALOG_BY_ID

    payload = await build_focus_cue_payload(db, workout_id, catalog_by_id)
    payload_hash = hash_payload(payload)
    range_kind = f"strength_focus_cue:{workout_id}"
    cached = (await db.execute(
        select(models.AiSummary)
        .where(models.AiSummary.range_kind == range_kind)
        .where(models.AiSummary.payload_hash == payload_hash)
        .order_by(models.AiSummary.generated_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if cached is not None:
        import json as _json
        try: cue = _json.loads(cached.content)
        except Exception: cue = {}  # noqa: BLE001
        return {
            "cue": cue, "generated_at": cached.generated_at,
            "model": cached.model, "cached": True,
            "input_tokens": cached.input_tokens, "output_tokens": cached.output_tokens,
        }

    result = await strength_focus_cue(db, workout_id, cfg, catalog_by_id)
    cfg.calls_today += 1
    summary = models.AiSummary(
        generated_at=datetime.now(timezone.utc),
        range_kind=range_kind, payload_hash=payload_hash,
        model=result.model,
        input_tokens=result.input_tokens, output_tokens=result.output_tokens,
        content=result.content,
    )
    db.add(summary)
    await db.commit()
    import json as _json
    try: cue = _json.loads(result.content)
    except Exception: cue = {}  # noqa: BLE001
    return {
        "cue": cue, "generated_at": summary.generated_at,
        "model": result.model, "cached": False,
        "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
    }


# ─────────────── Deload trigger (multi-signal AI judgment) ───────────────

@router.post("/strength/deload-check")
async def strength_deload_check_endpoint(
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Multi-signal AI deload trigger. Reads 28d of vitals + 14d of
    strength performance, returns a structured judgment with severity.

    Cached by signals-payload hash in ai_summaries — repeated calls on
    the same day with unchanged data are free."""
    cfg = await _get_config(db)
    await _check_and_bump_quota(db, cfg)

    from ..integrations.claude import build_deload_payload, deload_check

    payload = await build_deload_payload(db)
    payload_hash = hash_payload(payload)
    range_kind = "strength_deload"
    cached = (await db.execute(
        select(models.AiSummary)
        .where(models.AiSummary.range_kind == range_kind)
        .where(models.AiSummary.payload_hash == payload_hash)
        .order_by(models.AiSummary.generated_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if cached is not None:
        import json as _json
        try: judgment = _json.loads(cached.content)
        except Exception: judgment = {}  # noqa: BLE001
        return {
            "judgment": judgment, "generated_at": cached.generated_at,
            "model": cached.model, "cached": True,
            "input_tokens": cached.input_tokens, "output_tokens": cached.output_tokens,
        }

    result = await deload_check(db, cfg)
    cfg.calls_today += 1
    summary = models.AiSummary(
        generated_at=datetime.now(timezone.utc),
        range_kind=range_kind, payload_hash=payload_hash,
        model=result.model,
        input_tokens=result.input_tokens, output_tokens=result.output_tokens,
        content=result.content,
    )
    db.add(summary)
    await db.commit()
    import json as _json
    try: judgment = _json.loads(result.content)
    except Exception: judgment = {}  # noqa: BLE001
    return {
        "judgment": judgment, "generated_at": summary.generated_at,
        "model": result.model, "cached": False,
        "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
    }


@router.get("/strength/deload-check/latest")
async def strength_deload_latest(
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any] | None:
    """Read the most recent cached deload judgment without billing.
    Phone + web banners poll this so they can render without forcing a
    Claude call on every screen open."""
    row = (await db.execute(
        select(models.AiSummary)
        .where(models.AiSummary.range_kind == "strength_deload")
        .order_by(models.AiSummary.generated_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if row is None:
        return None
    import json as _json
    try: judgment = _json.loads(row.content)
    except Exception: judgment = {}  # noqa: BLE001
    return {
        "judgment": judgment, "generated_at": row.generated_at,
        "model": row.model,
    }


# ─────────────── Batch mode ───────────────

@router.post("/explain-all")
async def explain_all_endpoint(db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    cfg = await _get_config(db)
    await _check_and_bump_quota(db, cfg)
    from ..integrations.claude import explain_all
    result = await explain_all(db, cfg)
    cfg.calls_today += 1
    await db.commit()
    import json as _json
    try:
        topics = _json.loads(result.content)
    except Exception:  # noqa: BLE001
        topics = {"raw": result.content}
    return {
        "topics": topics,
        "generated_at": datetime.now(timezone.utc),
        "model": result.model,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }


# ─────────────── Coach endpoints ───────────────


async def _coach_cached(
    db: AsyncSession, range_kind: str, payload_hash: str,
) -> dict[str, Any] | None:
    row = (await db.execute(
        select(models.AiSummary)
        .where(models.AiSummary.range_kind == range_kind)
        .where(models.AiSummary.payload_hash == payload_hash)
        .order_by(models.AiSummary.generated_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if row is None:
        return None
    import json as _json
    try:
        analysis = _json.loads(row.content)
    except Exception:  # noqa: BLE001
        analysis = {"raw": row.content}
    return {
        "analysis": analysis,
        "generated_at": row.generated_at,
        "model": row.model,
        "cached": True,
    }


async def _coach_persist(
    db: AsyncSession, range_kind: str, payload_hash: str, result: Any,
) -> dict[str, Any]:
    import json as _json
    summary = models.AiSummary(
        generated_at=datetime.now(timezone.utc),
        range_kind=range_kind,
        payload_hash=payload_hash,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        content=result.content,
    )
    db.add(summary)
    await db.commit()
    try:
        analysis = _json.loads(result.content)
    except Exception:  # noqa: BLE001
        analysis = {"raw": result.content}
    return {
        "analysis": analysis,
        "generated_at": summary.generated_at,
        "model": result.model,
        "cached": False,
    }


@router.post("/coach/cardio")
async def coach_cardio_endpoint(
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """AI cardio coach card. Caches by payload-hash so re-asking the
    same data doesn't re-bill — invalidates the moment a new cardio
    session lands."""
    cfg = await _get_config(db)
    await _check_and_bump_quota(db, cfg)
    payload = await build_cardio_coach_payload(db)
    payload_hash = hash_payload({"kind": "coach_cardio", "tone": cfg.tone, "p": payload})
    cached = await _coach_cached(db, "coach_cardio", payload_hash)
    if cached is not None:
        return cached
    result = await cardio_coach(db, cfg)
    cfg.calls_today += 1
    return await _coach_persist(db, "coach_cardio", payload_hash, result)


@router.get("/coach/cardio/latest")
async def coach_cardio_latest(
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any] | None:
    """Return the most recent cardio-coach card without billing."""
    row = (await db.execute(
        select(models.AiSummary)
        .where(models.AiSummary.range_kind == "coach_cardio")
        .order_by(models.AiSummary.generated_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if row is None:
        return None
    import json as _json
    try:
        analysis = _json.loads(row.content)
    except Exception:  # noqa: BLE001
        analysis = {"raw": row.content}
    return {
        "analysis": analysis,
        "generated_at": row.generated_at,
        "model": row.model,
        "cached": True,
    }


@router.post("/coach/workout")
async def coach_workout_endpoint(
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Multi-signal AI workout coach — synthesizes strength, cardio,
    sleep, HRV, and training load into a single weekly card."""
    cfg = await _get_config(db)
    await _check_and_bump_quota(db, cfg)
    payload = await build_workout_coach_payload(db)
    payload_hash = hash_payload({"kind": "coach_workout", "tone": cfg.tone, "p": payload})
    cached = await _coach_cached(db, "coach_workout", payload_hash)
    if cached is not None:
        return cached
    result = await workout_coach(db, cfg)
    cfg.calls_today += 1
    return await _coach_persist(db, "coach_workout", payload_hash, result)


@router.get("/coach/workout/latest")
async def coach_workout_latest(
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any] | None:
    row = (await db.execute(
        select(models.AiSummary)
        .where(models.AiSummary.range_kind == "coach_workout")
        .order_by(models.AiSummary.generated_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if row is None:
        return None
    import json as _json
    try:
        analysis = _json.loads(row.content)
    except Exception:  # noqa: BLE001
        analysis = {"raw": row.content}
    return {
        "analysis": analysis,
        "generated_at": row.generated_at,
        "model": row.model,
        "cached": True,
    }


@router.post("/coach/sleep")
async def coach_sleep_endpoint(
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """AI sleep coach card. Verdict on whether sleep is supporting
    recovery — synthesises duration, consistency, stage breakdown,
    sleep_debt_h, and HRV/RHR drift."""
    cfg = await _get_config(db)
    await _check_and_bump_quota(db, cfg)
    payload = await build_sleep_coach_payload(db)
    payload_hash = hash_payload({"kind": "coach_sleep", "tone": cfg.tone, "p": payload})
    cached = await _coach_cached(db, "coach_sleep", payload_hash)
    if cached is not None:
        return cached
    result = await sleep_coach(db, cfg)
    cfg.calls_today += 1
    return await _coach_persist(db, "coach_sleep", payload_hash, result)


@router.get("/coach/sleep/latest")
async def coach_sleep_latest(
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any] | None:
    """Return the most recent sleep-coach card without billing."""
    row = (await db.execute(
        select(models.AiSummary)
        .where(models.AiSummary.range_kind == "coach_sleep")
        .order_by(models.AiSummary.generated_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if row is None:
        return None
    import json as _json
    try:
        analysis = _json.loads(row.content)
    except Exception:  # noqa: BLE001
        analysis = {"raw": row.content}
    return {
        "analysis": analysis,
        "generated_at": row.generated_at,
        "model": row.model,
        "cached": True,
    }


@router.post("/coach/recovery")
async def coach_recovery_endpoint(
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """AI recovery coach card — multi-week HRV/RHR/skin-temp/readiness
    trend verdict. Broader than the per-workout deload check."""
    cfg = await _get_config(db)
    await _check_and_bump_quota(db, cfg)
    payload = await build_recovery_coach_payload(db)
    payload_hash = hash_payload({"kind": "coach_recovery", "tone": cfg.tone, "p": payload})
    cached = await _coach_cached(db, "coach_recovery", payload_hash)
    if cached is not None:
        return cached
    result = await recovery_coach(db, cfg)
    cfg.calls_today += 1
    return await _coach_persist(db, "coach_recovery", payload_hash, result)


@router.get("/coach/recovery/latest")
async def coach_recovery_latest(
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any] | None:
    """Return the most recent recovery-coach card without billing."""
    row = (await db.execute(
        select(models.AiSummary)
        .where(models.AiSummary.range_kind == "coach_recovery")
        .order_by(models.AiSummary.generated_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if row is None:
        return None
    import json as _json
    try:
        analysis = _json.loads(row.content)
    except Exception:  # noqa: BLE001
        analysis = {"raw": row.content}
    return {
        "analysis": analysis,
        "generated_at": row.generated_at,
        "model": row.model,
        "cached": True,
    }

