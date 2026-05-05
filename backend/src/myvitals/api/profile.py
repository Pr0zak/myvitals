"""User profile + derived metrics (age-adjusted max HR, HR zones, BMI)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_query
from ..db import models
from ..db.session import get_session

router = APIRouter(prefix="/profile", dependencies=[Depends(require_query)])


class ProfileIn(BaseModel):
    birth_date: date | None = None
    sex: str | None = None  # "male" | "female" | "other"
    height_cm: float | None = None
    weight_goal_kg: float | None = None
    resting_hr_baseline: float | None = None
    activity_level: str | None = None  # "sedentary"|"light"|"moderate"|"active"|"athlete"
    extra: dict[str, Any] | None = None


def _age_years(birth: date | None) -> int | None:
    if not birth:
        return None
    today = date.today()
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def _hr_zones(max_hr: float) -> list[dict[str, Any]]:
    """Karvonen-ish 5-zone split as a fraction of max HR."""
    return [
        {"zone": 1, "label": "Recovery",   "low": round(max_hr * 0.50), "high": round(max_hr * 0.60)},
        {"zone": 2, "label": "Endurance",  "low": round(max_hr * 0.60), "high": round(max_hr * 0.70)},
        {"zone": 3, "label": "Tempo",      "low": round(max_hr * 0.70), "high": round(max_hr * 0.80)},
        {"zone": 4, "label": "Threshold",  "low": round(max_hr * 0.80), "high": round(max_hr * 0.90)},
        {"zone": 5, "label": "VO2 Max",    "low": round(max_hr * 0.90), "high": round(max_hr * 1.00)},
    ]


async def _auto_rhr_baseline(db: AsyncSession) -> float | None:
    """Recent rolling average of daily_summary.resting_hr — best objective
    estimate of the user's current resting HR baseline. Used when the
    profile doesn't override with a manual value.

    Walks back from the most recent day with RHR data (instead of always
    today minus 30) so a brief gap in syncing doesn't drop the count to 0
    or pull in stale readings from years ago when historical imports
    happened to land in the window."""
    latest = (await db.execute(
        select(func.max(models.DailySummary.date))
        .where(models.DailySummary.resting_hr.is_not(None))
    )).scalar()
    if latest is None:
        return None
    cutoff = latest - timedelta(days=14)
    val = (await db.execute(
        select(func.avg(models.DailySummary.resting_hr))
        .where(models.DailySummary.date >= cutoff)
        .where(models.DailySummary.date <= latest)
        .where(models.DailySummary.resting_hr.is_not(None))
    )).scalar()
    return float(val) if val is not None else None


async def _profile_dict(
    db: AsyncSession, p: models.UserProfile | None,
) -> dict[str, Any]:
    auto_rhr = await _auto_rhr_baseline(db)
    if p is None:
        return {
            "id": 1, "birth_date": None, "sex": None, "height_cm": None,
            "weight_goal_kg": None, "resting_hr_baseline": None,
            "activity_level": None, "extra": None, "updated_at": None,
            "derived": {"resting_hr_baseline_auto": auto_rhr},
        }
    age = _age_years(p.birth_date)
    derived: dict[str, Any] = {"age": age, "resting_hr_baseline_auto": auto_rhr}
    if age is not None:
        # Tanaka 2001: max HR ≈ 208 - 0.7 × age (more accurate than 220-age).
        max_hr = 208 - 0.7 * age
        derived["max_hr_estimated"] = round(max_hr)
        derived["hr_zones"] = _hr_zones(max_hr)
    if p.height_cm and p.weight_goal_kg:
        h_m = p.height_cm / 100
        derived["bmi_at_goal"] = round(p.weight_goal_kg / (h_m * h_m), 1)
    return {
        "id": p.id,
        "birth_date": p.birth_date.isoformat() if p.birth_date else None,
        "sex": p.sex,
        "height_cm": p.height_cm,
        "weight_goal_kg": p.weight_goal_kg,
        "resting_hr_baseline": p.resting_hr_baseline,
        "activity_level": p.activity_level,
        "extra": p.extra,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        "derived": derived,
    }


@router.get("")
async def get_profile(db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    p = await db.get(models.UserProfile, 1)
    return await _profile_dict(db, p)


@router.put("")
async def put_profile(
    body: ProfileIn,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if body.sex is not None and body.sex not in {"male", "female", "other"}:
        raise HTTPException(status_code=400, detail="sex must be male|female|other")
    p = await db.get(models.UserProfile, 1)
    now = datetime.now(timezone.utc)
    if p is None:
        p = models.UserProfile(id=1, updated_at=now)
        db.add(p)
    p.birth_date = body.birth_date
    p.sex = body.sex
    p.height_cm = body.height_cm
    p.weight_goal_kg = body.weight_goal_kg
    p.resting_hr_baseline = body.resting_hr_baseline
    p.activity_level = body.activity_level
    p.extra = body.extra
    p.updated_at = now
    await db.commit()
    await db.refresh(p)
    return await _profile_dict(db, p)
