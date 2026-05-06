"""AI summary endpoints — config + explain + weekly digest."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_query
from ..db import models
from ..db.session import get_session
from ..integrations.claude import build_summary_payload, explain, hash_payload

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
        cfg = models.AiConfig(id=1, enabled=False, model="claude-sonnet-4-6")
        db.add(cfg)
        await db.commit()
        await db.refresh(cfg)
    return cfg


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
    }


class ConfigUpdate(BaseModel):
    enabled: bool | None = None
    anthropic_api_key: str | None = None  # null = leave unchanged; "" = clear
    clear_key: bool = False
    model: str | None = None
    daily_call_limit: int | None = None
    weekly_digest_enabled: bool | None = None


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
    cfg.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return await get_config(db)


@router.get("/preview-payload")
async def preview_payload(
    range: str = "week", db: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Return the exact aggregate JSON we'd send to Claude — for the user to
    audit before flipping the feature on. No external calls are made."""
    if range not in ("week", "month"):
        raise HTTPException(status_code=400, detail="range must be week or month")
    return await build_summary_payload(db, range)


@router.post("/explain")
async def explain_endpoint(
    range: str = "week", db: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    if range not in ("week", "month"):
        raise HTTPException(status_code=400, detail="range must be week or month")
    cfg = await _get_config(db)
    if not cfg.enabled:
        raise HTTPException(status_code=400, detail="AI summaries disabled in Settings")
    if not cfg.anthropic_api_key:
        raise HTTPException(status_code=400, detail="Anthropic API key not configured")

    # Reset daily counter at UTC midnight rollover
    today = date.today()
    if cfg.calls_today_date != today:
        cfg.calls_today = 0
        cfg.calls_today_date = today
    if cfg.calls_today >= cfg.daily_call_limit:
        raise HTTPException(
            status_code=429,
            detail=f"Daily call limit ({cfg.daily_call_limit}) reached",
        )

    payload = await build_summary_payload(db, range)
    payload_hash = hash_payload(payload)

    # Cache hit: return existing summary for the same payload-hash + range.
    cached = (await db.execute(
        select(models.AiSummary)
        .where(models.AiSummary.range_kind == range)
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
            "input_tokens": cached.input_tokens,
            "output_tokens": cached.output_tokens,
        }

    result = await explain(db, range, cfg)

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
        "content": result.content,
        "generated_at": summary.generated_at,
        "model": result.model,
        "cached": False,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }


@router.get("/latest")
async def latest_summary(
    range: str = "week", db: AsyncSession = Depends(get_session)
) -> dict[str, Any] | None:
    """Return the most recent AI summary for the given range, if any.
    Used by Today.vue to show last week's digest without re-billing."""
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
    return {
        "content": row.content,
        "generated_at": row.generated_at,
        "model": row.model,
    }
