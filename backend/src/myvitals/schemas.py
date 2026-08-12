from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class TimePoint(BaseModel):
    time: datetime
    value: float


class HeartRateSeries(BaseModel):
    points: list[TimePoint]
    avg: float | None = None
    min_bpm: float | None = None
    max_bpm: float | None = None


class HrvSeries(BaseModel):
    points: list[TimePoint]
    avg: float | None = None


class StepsSeries(BaseModel):
    points: list[TimePoint]
    total: int


class SleepStageBucket(BaseModel):
    stage: str
    duration_s: int


class SleepNight(BaseModel):
    date: date
    start: datetime
    end: datetime
    total_s: int
    stages: list[SleepStageBucket]
    # "sleep" or "nap", from analytics.events.classify_session — the same rule
    # the narrative cards use. Without it clients counted every session as a
    # night, so an afternoon nap made "STAGE BREAKDOWN - 13 NIGHTS" out of
    # twelve nights and a doze on the sofa, and dragged the nightly average
    # down with a 40-minute "night".
    kind: str = "sleep"


class TodaySummary(BaseModel):
    date: date
    resting_hr: float | None = None
    hrv_avg: float | None = None
    recovery_score: float | None = None
    sleep_duration_s: int | None = None
    sleep_score: float | None = None
    steps_total: int | None = None
    weight_kg: float | None = None
    body_fat_pct: float | None = None
    bp_systolic_avg: float | None = None
    bp_diastolic_avg: float | None = None
    skin_temp_delta_avg: float | None = None
    readiness_score: float | None = None
    training_stress_score: float | None = None
    ctl: float | None = None
    atl: float | None = None
    tsb: float | None = None
    sleep_consistency_score: float | None = None
    sleep_debt_h: float | None = None
    fasting_hours: float | None = None
    last_sync: datetime | None = None
    # Fields whose value did NOT come from today's row but was carried
    # forward from an earlier day, mapped to the date it came from.
    # Overnight metrics go missing whenever the watch hasn't synced last
    # night yet; without this the clients render a day-old HRV, sleep and
    # readiness under a "today" heading with nothing to say otherwise.
    # Additive and optional — existing consumers are unaffected.
    carried_from: dict[str, str] = {}


class AnnotationOut(BaseModel):
    id: int
    ts: datetime
    type: str
    payload: dict[str, Any]
    note: str | None = None


class AnnotationCreate(BaseModel):
    """Manual log entry. ts defaults to server-now if omitted."""
    ts: datetime | None = None
    type: str = Field(..., description="caffeine | alcohol | food | mood | meds | note")
    payload: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None


class AnnotationUpdate(BaseModel):
    """Partial update — only fields explicitly provided are touched."""
    ts: datetime | None = None
    payload: dict[str, Any] | None = None
    note: str | None = None
