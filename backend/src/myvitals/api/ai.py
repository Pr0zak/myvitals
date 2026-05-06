"""AI summary endpoints — config + targeted explain + weekly digest."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..analytics.trends import compute_badges
from ..auth import require_query
from ..db import models
from ..db.session import get_session
from ..integrations.claude import (
    ask,
    build_summary_payload,
    build_topic_payload,
    explain_discovery,
    explain_legacy,
    explain_topic,
    hash_payload,
    pre_workout,
    verdict,
)

router = APIRouter(prefix="/ai", dependencies=[Depends(require_query)])


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
         "metric": r.metric, "z_score": r.z_score, "acked_at": r.acked_at}
        for r in rows
    ]


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


@router.get("/goals")
async def list_goals(
    active_only: bool = True, db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    stmt = select(models.AiGoal).order_by(models.AiGoal.started_at.desc())
    if active_only:
        stmt = stmt.where(models.AiGoal.ended_at.is_(None))
    return [_goal_to_dict(g) for g in (await db.execute(stmt)).scalars().all()]


@router.post("/goals")
async def create_goal(
    body: GoalCreate, db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    g = models.AiGoal(
        kind=body.kind, title=body.title,
        target_value=body.target_value, target_unit=body.target_unit,
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
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(g, k, v)
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
