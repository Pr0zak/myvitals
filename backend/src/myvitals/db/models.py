from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# --- time-series (TimescaleDB hypertables; created via migration) ---
# All time columns are TIMESTAMPTZ — Health Connect emits UTC instants.

class HeartRate(Base):
    __tablename__ = "vitals_heartrate"
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    bpm: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(64), default="watch")


class Hrv(Base):
    __tablename__ = "vitals_hrv"
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    rmssd_ms: Mapped[float] = mapped_column(Float)


class Spo2(Base):
    __tablename__ = "vitals_spo2"
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    percent: Mapped[float] = mapped_column(Float)


class SkinTemp(Base):
    __tablename__ = "vitals_skin_temp"
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    celsius_delta: Mapped[float] = mapped_column(Float)


class BloodPressure(Base):
    """BP cuff readings (OMRON Connect → Health Connect → here, or manual)."""
    __tablename__ = "blood_pressure"
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    systolic: Mapped[int] = mapped_column(Integer)
    diastolic: Mapped[int] = mapped_column(Integer)
    pulse_bpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="manual")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class BodyMetric(Base):
    """Weight, body fat, BMI snapshots (manual log, scale, watch, import)."""
    __tablename__ = "body_metrics"
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    body_fat_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    bmi: Mapped[float | None] = mapped_column(Float, nullable=True)
    lean_mass_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="manual")


class Steps(Base):
    __tablename__ = "vitals_steps"
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(Integer)


class SleepStage(Base):
    __tablename__ = "sleep_stages"
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    stage: Mapped[str] = mapped_column(String(16), primary_key=True)
    duration_s: Mapped[int] = mapped_column(Integer)


class SleepSession(Base):
    """Canonical session boundaries from HC (or import). Authoritative
    'when did I actually fall asleep / wake up'. Stages are children
    of these sessions but exist independently to allow back-fill from
    sources that only ship per-stage data."""
    __tablename__ = "sleep_sessions"
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(32), default="watch")
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Workout(Base):
    __tablename__ = "workouts"
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    type: Mapped[str] = mapped_column(String(32))
    duration_s: Mapped[int] = mapped_column(Integer)
    kcal: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)


class EnvReading(Base):
    """External sensor data (HA bedroom temp, weather, etc.)."""
    __tablename__ = "env_readings"
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    metric: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[float] = mapped_column(Float)


# --- relational ---

class Annotation(Base):
    """Manual logs: caffeine, alcohol, food, mood, meds, notes."""
    __tablename__ = "annotations"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class DailySummary(Base):
    """One row per local day, written by the nightly analytics job."""
    __tablename__ = "daily_summary"
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    resting_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    hrv_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    recovery_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    sleep_duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sleep_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    steps_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    body_fat_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    bp_systolic_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    bp_diastolic_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    skin_temp_delta_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    readiness_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    training_stress_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ctl: Mapped[float | None] = mapped_column(Float, nullable=True)
    atl: Mapped[float | None] = mapped_column(Float, nullable=True)
    tsb: Mapped[float | None] = mapped_column(Float, nullable=True)
    sleep_consistency_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    sleep_debt_h: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Alert(Base):
    """Surface-worthy events (RHR drift, missed sync, low HRV streak, ...)."""
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)


class AppLog(Base):
    """Log entries shipped from the phone (and from the backend itself)."""
    __tablename__ = "app_logs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)  # "phone" | "server"
    level: Mapped[str] = mapped_column(String(8), index=True)
    tag: Mapped[str | None] = mapped_column(String(128), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    stack: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ImportJob(Base):
    """Tracks long-running historical imports so the UI can show progress."""
    __tablename__ = "import_jobs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # "fitbit" | "garmin" | "garmin_fit_tracks" | ...
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(16), index=True)  # "running" | "done" | "failed"
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    counts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class UserProfile(Base):
    """Single-row user profile for percentile analytics + zones.

    Single-user app, so id is always 1. Stores enough to compute age-adjusted
    max HR (Tanaka), HR zones, BMI, and to look up cohort percentiles for
    RHR / HRV / VO2 max.
    """
    __tablename__ = "user_profile"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sex: Mapped[str | None] = mapped_column(String(8), nullable=True)  # "male" | "female" | "other"
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_goal_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    resting_hr_baseline: Mapped[float | None] = mapped_column(Float, nullable=True)
    activity_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sleep_target_h: Mapped[float | None] = mapped_column(Float, nullable=True, default=8)
    # Free-form JSON for conditions / medications / notes
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StravaCredentials(Base):
    """Single-row table (id=1) holding the user's Strava OAuth tokens."""
    __tablename__ = "strava_credentials"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    athlete_id: Mapped[int] = mapped_column(BigInteger)
    athlete_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    scope: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StravaAppConfig(Base):
    """Dashboard-editable Strava OAuth credentials. Single row (id=1) wins
    over the STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET env vars."""
    __tablename__ = "strava_app_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    client_id: Mapped[str] = mapped_column(String(64))
    client_secret: Mapped[str] = mapped_column(String(255))
    callback_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Activity(Base):
    """Workouts pulled from Strava (and later Garmin, etc.)."""
    __tablename__ = "activities"
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_s: Mapped[int] = mapped_column(Integer)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_power_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_power_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    kcal: Mapped[float | None] = mapped_column(Float, nullable=True)
    suffer_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    polyline: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String(64)), nullable=True)
    hr_recovery_60s: Mapped[float | None] = mapped_column(Float, nullable=True)
    hr_recovery_120s: Mapped[float | None] = mapped_column(Float, nullable=True)


class AiConfig(Base):
    """Single-row table (id=1) holding the user's Claude API settings.
    Lives in DB rather than .env so the user can manage it from the
    dashboard without touching the host."""
    __tablename__ = "ai_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    anthropic_api_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    model: Mapped[str] = mapped_column(String(64), default="claude-haiku-4-5-20251001")
    daily_call_limit: Mapped[int] = mapped_column(Integer, default=10)
    calls_today: Mapped[int] = mapped_column(Integer, default=0)
    calls_today_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    weekly_digest_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AiSummary(Base):
    """Cached AI-generated summary. Hashing the payload means rerunning the
    same window without new data is free; once a fresh sync arrives, the
    hash differs and a new summary is generated."""
    __tablename__ = "ai_summaries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    range_kind: Mapped[str] = mapped_column(String(16))   # 'week' | 'month'
    payload_hash: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text)


class SoberStreak(Base):
    """One row per sobriety streak — past streaks are closed (end_at set),
    the current streak has end_at = NULL (enforced by partial unique index)."""
    __tablename__ = "sober_streaks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    addiction: Mapped[str] = mapped_column(String(64), default="alcohol")
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class SyncHeartbeat(Base):
    """Companion-app sync diagnostics — one row per doWork() invocation."""
    __tablename__ = "sync_heartbeat"
    attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    success: Mapped[bool] = mapped_column(Boolean)
    permissions_lost: Mapped[bool] = mapped_column(Boolean, default=False)
    perms_granted: Mapped[int | None] = mapped_column(Integer, nullable=True)
    perms_required: Mapped[int | None] = mapped_column(Integer, nullable=True)
    perms_missing: Mapped[list | None] = mapped_column(JSON, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    records_pulled: Mapped[int | None] = mapped_column(Integer, nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
