from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
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


class BodyCircumference(Base):
    """BODY-1: tape-measure circumference sites (cm), manual entry only (no
    Health Connect source). One row per measurement session, keyed on time;
    any subset of sites may be filled. Plain table (low cardinality)."""
    __tablename__ = "body_circumference"
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    waist_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    chest_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    arms_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    hips_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    thighs_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    neck_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    calves_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="manual")


class Steps(Base):
    __tablename__ = "vitals_steps"
    # Source is part of the PK so multiple HC writers (watch + phone
    # pedometer + Google Fit aggregator) can co-exist for the same
    # minute without overwriting each other; the summary picks one.
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    source: Mapped[str] = mapped_column(String(96), primary_key=True, default="unknown")
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
    fasting_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
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
    # Measured maximum heart rate, when the user has one. Null means "derive
    # it from birth_date with Tanaka" -- which is the default and is fine, but
    # every zone boundary in the app hangs off this number, so the difference
    # between a measured value and an age estimate is worth being explicit
    # about rather than hiding behind a single figure.
    max_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    activity_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sleep_target_h: Mapped[float | None] = mapped_column(Float, nullable=True, default=8)
    # FAST-17: weekly fasting-hours target — auto-syncs with the
    # fast_streak AiGoal kind. Null when fasting isn't goal-tracked.
    fasting_target_hours_per_week: Mapped[float | None] = mapped_column(Float, nullable=True)
    # When true, the strength workout generator reads recovery_score / sleep /
    # readiness from daily_summary and adjusts intensity accordingly.
    strength_recovery_aware: Mapped[bool] = mapped_column(Boolean, default=True)
    # Free-form JSON for conditions / medications / notes
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Map default-center coordinates (set in Settings → Profile). Used by
    # the Activities Map / Trails Map to anchor the view instead of
    # fit-bounds-to-all.
    home_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    home_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GoogleHealthDaily(Base):
    """Daily aggregates the Google Health API only serves at day granularity.

    Deliberately NOT daily_summary: compute_daily_summary derives resting_hr
    and hrv_avg from raw samples and rewrites that row on every lazy
    recompute, so anything stored there would be clobbered. And deliberately
    not vitals_hrv: that table is per-sample RMSSD, and one daily value
    dropped into it would coexist by timestamp while skewing every average
    taken across it.

    The analytics read this only as a fallback, when the sample-derived
    figure is None because the phone was not syncing.
    """
    __tablename__ = "google_health_daily"
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    resting_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    hrv_avg_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    deep_sleep_rmssd_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    respiratory_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    vo2_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GoogleHealthConfig(Base):
    """The OAuth app the user registers in their own Google Cloud project.

    Bring-your-own-app, exactly as the Strava integration works: there is no
    shared client to leak, the quota is the user's own, and nothing here
    depends on this project maintaining a registration.
    """
    __tablename__ = "google_health_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    callback_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GoogleHealthCredentials(Base):
    """Tokens from authorising the app above. Single row, id=1."""
    __tablename__ = "google_health_credentials"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Persisted, not just logged. The Strava cookie failed silently for six
    # weeks before anyone noticed; every integration added since carries a
    # user-visible failure state for that reason.
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    poll_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
    )
    # Minutes between polls. The scheduler ticks on a fixed short cadence and
    # each tick skips unless this much time has passed since last_sync_at —
    # simpler and more responsive than rescheduling an APScheduler job every
    # time the setting changes, and the setting takes effect immediately.
    poll_interval_min: Mapped[int] = mapped_column(
        Integer, default=60, server_default="60", nullable=False,
    )


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


class StravaCookieCreds(Base):
    """Single-row table (id=1) for cookie-session Strava ingestion.

    Strava's June 2026 policy puts the OAuth API behind a paid Strava
    subscription. As a free-tier hedge we let the user paste their
    `strava_remember_token` cookie (and optionally `_strava4_session`)
    and pull activities via the same authenticated session their
    browser uses. Each ride's original FIT file carries the
    chest-strap HR stream that the OAuth API would otherwise gate.

    No automatic background poll — sync is user-triggered (button on
    Activities / Today / Settings). Cookie staleness manifests as a
    401 on the next sync; user re-pastes from chrome devtools.
    """
    __tablename__ = "strava_cookie_creds"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    remember_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    sid_cookie: Mapped[str | None] = mapped_column(Text, nullable=True)
    athlete_id_cached: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    athlete_name_cached: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Scheduled poll (migration 0055). Default OFF: this reaches a third
    # party on a timer, and unlike Google Health the credential cannot
    # self-heal — with no stored auto-login, only a human can restore an
    # expired cookie. `poll_consecutive_failures` drives both the backoff
    # and the hard stop, so a dead cookie is not retried forever.
    poll_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
    )
    poll_interval_min: Mapped[int] = mapped_column(
        Integer, default=360, server_default="360", nullable=False,
    )
    poll_consecutive_failures: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False,
    )
    # SCS-6 auto-login. Email is plain; password is Fernet-encrypted
    # with settings.strava_creds_key. Both nullable so the row can
    # still hold paste-only cookies when auto-login is off.
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_login_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_auto_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # SCS-7: Fernet key for encrypting password_encrypted, auto-generated
    # on first save. DB-resident so setup is fully Settings-UI-driven,
    # no .env shell session required.
    creds_key_b64: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Concept2Credentials(Base):
    """Single-row table (id=1) for the Concept2 Logbook API. Long-lived
    personal tokens (issued from the Concept2 dev console) cover the
    single-user case; OAuth refresh fields are present for future use."""
    __tablename__ = "concept2_credentials"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scope: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Random per-user secret embedded in the webhook URL path so random
    # POST traffic can't be processed. Concept2 doesn't publicly document
    # its signature scheme, so a path-secret is the simplest viable gate.
    webhook_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)


class TrailStatusConfig(Base):
    """Dashboard-editable RainoutLine DNIS. Single row (id=1)."""
    __tablename__ = "trail_status_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    dnis: Mapped[str | None] = mapped_column(String(16), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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
    # RDP-simplified copy of `polyline`, for the all-activities map (0046).
    # Derived + lazily backfilled — null means "not computed yet", never
    # "no GPS". `polyline` stays the source of truth.
    polyline_simple: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String(64)), nullable=True)
    hr_recovery_60s: Mapped[float | None] = mapped_column(Float, nullable=True)
    hr_recovery_120s: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Linked trail (RainoutLine catalog) when the activity's start GPS
    # falls within ~2km of a trail's pinned coords. Auto-detected on
    # ingest + via /trails/link-activities; manually settable.
    trail_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)


class AiConfig(Base):
    """Single-row table (id=1) holding the user's Claude API settings.
    Lives in DB rather than .env so the user can manage it from the
    dashboard without touching the host."""
    __tablename__ = "ai_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    anthropic_api_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    model: Mapped[str] = mapped_column(String(64), default="claude-haiku-4-5-20251001")
    # TD-8 — which backend answers. Null means Anthropic, which is every
    # existing row: the columns are additive and nothing is migrated, so an
    # instance that never opens the setting behaves exactly as before.
    # "openai_compatible" / "ollama" route through integrations/llm and need
    # base_url; the API key field is reused as the bearer token (Ollama
    # ignores it entirely).
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    #: Subscription OAuth token for the `claude_cli` provider, from
    #: `claude setup-token`. Kept SEPARATE from `anthropic_api_key`: an
    #: API key in the CLI's environment makes it bill per token, which
    #: defeats the point, so the provider strips that variable and passes
    #: this one instead.
    cli_oauth_token: Mapped[str | None] = mapped_column(String(500), nullable=True)
    daily_call_limit: Mapped[int] = mapped_column(Integer, default=30)
    calls_today: Mapped[int] = mapped_column(Integer, default=0)
    calls_today_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    weekly_digest_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    tone: Mapped[str] = mapped_column(String(16), default="supportive")
    # Standing instructions appended verbatim to every system prompt under a
    # fixed heading. The tone enum was the entire user model the AI had; this
    # is where "rehabbing a left shoulder, never suggest overhead pressing"
    # or "my fasts are religious, don't read a low HRV as overtraining"
    # lives. Length-capped in the API layer -- it is a prompt-injection
    # surface aimed at the model's own guardrails.
    custom_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AiAlert(Base):
    """Anomaly / coaching alert generated by the analytics + Claude pipeline.
    Phone polls /ai/alerts on each SyncWorker tick and surfaces new ones
    as system notifications."""
    __tablename__ = "ai_alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(64))               # "anomaly" | "goal" | "streak" | "illness_risk"
    severity: Mapped[str] = mapped_column(String(16), default="warn")  # info | warn | bad | good
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    metric: Mapped[str | None] = mapped_column(String(64), nullable=True)
    z_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    dedup_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    phone_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AiGoal(Base):
    """User-defined goal for AI coaching ("lose 5 kg by Sept 1", "30 sober days")."""
    __tablename__ = "ai_goals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32))  # weight | sober | sleep | steps | custom
    title: Mapped[str] = mapped_column(String(255))
    target_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class AiSummary(Base):
    """Cached AI-generated summary. Hashing the payload means rerunning the
    same window without new data is free; once a fresh sync arrives, the
    hash differs and a new summary is generated."""
    __tablename__ = "ai_summaries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    range_kind: Mapped[str] = mapped_column(String(64))   # 'week' | 'month' | 'strength_review:<id>'
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


class UserEquipment(Base):
    """Single-row table (id=1) holding the user's available gear.

    Payload is free-form JSON so adding new equipment categories
    (kettlebells, bands, barbell + plates, ...) doesn't need a
    migration. Pydantic in api/workout/strength.py is the source of truth
    for the shape — see EquipmentPayload."""
    __tablename__ = "user_equipment"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    payload: Mapped[dict] = mapped_column(JSON)
    unit: Mapped[str] = mapped_column(String(4), default="lb")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StrengthWorkout(Base):
    """One row per scheduled / in-progress / completed strength session.

    `seed` is the deterministic-generation seed (date string by default,
    bumped by the regenerate button). `recovery_score_used` etc. capture
    the daily_summary inputs at generation time so we can audit *why*
    the algorithm picked a given plan."""
    __tablename__ = "strength_workouts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    split_focus: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="planned")
    seed: Mapped[str] = mapped_column(String(64))
    recovery_score_used: Mapped[float | None] = mapped_column(Float, nullable=True)
    readiness_score_used: Mapped[float | None] = mapped_column(Float, nullable=True)
    sleep_h_used: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Automatic recovery/readiness deload multiplier applied to target weights
    # (1.0 = none). Surfaced on WorkoutOut for the "load eased — use full
    # weight" banner. Null on legacy rows (treated as 1.0). v0.7.307.
    deload_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_by_activity_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completed_by_activity_source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # WP-14 pause/resume. `paused_at` is set when status flips to
    # "paused" and cleared on resume; `total_paused_s` accumulates the
    # paused intervals so net training duration excludes time away.
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_paused_s: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class StrengthWorkoutExercise(Base):
    """An exercise slot within a strength workout. exercise_id is the
    slug from the bundled catalog (data/exercises.json) — not a foreign
    key, since the catalog is a static asset, not a DB table.

    `superset_id` groups two or more exercises performed back-to-back
    in the isolation block (e.g. biceps curl + triceps extension)."""
    __tablename__ = "strength_workout_exercises"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workout_id: Mapped[int] = mapped_column(BigInteger, index=True)
    exercise_id: Mapped[str] = mapped_column(String(128))
    order_index: Mapped[int] = mapped_column(Integer)
    superset_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    target_sets: Mapped[int] = mapped_column(Integer)
    target_reps_low: Mapped[int] = mapped_column(Integer)
    target_reps_high: Mapped[int] = mapped_column(Integer)
    target_weight_lb: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_rest_s: Mapped[int] = mapped_column(Integer, default=90)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The user declined this slot. Distinct from "has no logged sets yet":
    # this records an explicit decision, so the AI reviewer can tell a
    # deliberate skip from a forgotten exercise. Deliberately NOT expressed
    # as placeholder skipped StrengthSet rows — those poison the mobility
    # hold-time tuner (which counts a skipped set as a failed one) and the
    # deload signal. Set by PATCH /workout-exercises/{id} and by the
    # close-remaining sweep on workout completion.
    skipped: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
    )
    # The user appended this slot mid-session rather than the generator
    # prescribing it. Mirrors the SKIP-1 distinction between a declined
    # exercise and a forgotten one: explain_workout must not claim to have
    # reasoned its way to a lift the user chose, and the AI reviewer reads a
    # self-added accessory differently from a planned one.
    added_ad_hoc: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
    )


class StrengthSet(Base):
    """One logged set. `target_*` is what the generator prescribed,
    `actual_*` is what the user did, `rating` is 1=Failed .. 5=Easy
    and drives the next-session weight selection."""
    __tablename__ = "strength_sets"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workout_exercise_id: Mapped[int] = mapped_column(BigInteger, index=True)
    set_number: Mapped[int] = mapped_column(Integer)
    target_weight_lb: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_reps: Mapped[int] = mapped_column(Integer)
    actual_weight_lb: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_reps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rest_seconds_taken: Mapped[int | None] = mapped_column(Integer, nullable=True)
    logged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    skipped: Mapped[bool] = mapped_column(Boolean, default=False)
    # Set classification (SETTYPE-1): 'working' (default) counts toward
    # volume/PRs; 'warmup' is logged but excluded from working-set counts
    # and PR detection; 'drop'/'failure' are working intensity techniques
    # that still count. v0.7.328.
    set_type: Mapped[str] = mapped_column(
        String(16), default="working", server_default="working")


class Trail(Base):
    """Single trail (one RainoutLine 'extension' under a DNIS).

    Status history is in trail_status_snapshots; the user opts into
    push notifications via trail_subscriptions. Lat/lon point at the
    primary trailhead (parking lot) for one-tap maps navigation."""
    __tablename__ = "trails"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dnis: Mapped[str] = mapped_column(String(16))
    extension: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(64))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    city: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # GeoJSON FeatureCollection of OSM-tagged paths within a small radius
    # of the trail pin. Populated by POST /trails/{id}/fetch-osm-paths
    # via integrations/osm.py. Cached because Overpass is rate-limited.
    osm_paths_geojson: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    osm_paths_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )


class TrailStatusSnapshot(Base):
    """Append-only history of every trail status reading. Hypertable
    on fetched_at; one row per (trail_id, fetched_at)."""
    __tablename__ = "trail_status_snapshots"
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    trail_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    status: Mapped[str] = mapped_column(String(16))     # open|closed|pending|unknown
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TrailSubscription(Base):
    """One row per trail the user wants alerts for."""
    __tablename__ = "trail_subscriptions"
    trail_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    subscribed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notify_on: Mapped[str] = mapped_column(String(16), default="any")
    # any | open_only | close_only


class TrailAlert(Base):
    """Status-flip alert for a subscribed trail. Mirrors ai_alerts so
    the existing ack/notify plumbing carries over."""
    __tablename__ = "trail_alerts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trail_id: Mapped[int] = mapped_column(BigInteger, index=True)
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str] = mapped_column(String(16))
    source_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    phone_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FastingSession(Base):
    """One row per intermittent-fasting session. A row with ended_at IS
    NULL is the (single) active fast; the partial unique index in the
    schema enforces only one ongoing row at a time."""
    __tablename__ = "fasting_sessions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    protocol: Mapped[str] = mapped_column(String(32))
    mode: Mapped[str] = mapped_column(String(16), default="active")
    target_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_eating_window_h: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class FastingLog(Base):
    """Freeform in-fast log entries — hunger / mood / hydration / notes.
    Joined to fasting_sessions on session_id."""
    __tablename__ = "fasting_logs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(BigInteger, index=True)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    hunger: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mood: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hydration_ml: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class HaConfig(Base):
    """Singleton (id=1) config row for the HA WebSocket consumer.
    Replaces the env-only HA_URL / HA_TOKEN / HA_REALTIME_ENABLED so
    the user can manage them from Settings instead of editing .env."""
    __tablename__ = "ha_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    token: Mapped[str | None] = mapped_column(Text, nullable=True)
    realtime_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    device_id: Mapped[str] = mapped_column(String(96), default="pixel_watch_3")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DeviceStatus(Base):
    """Pixel Watch (and future devices) liveness snapshot from the HA
    WebSocket consumer. Each HA event mutates one field; the consumer
    copies forward unchanged fields from the most recent row and
    inserts a new dense row at the event timestamp. HC has no
    equivalent signal — HA is the only source."""
    __tablename__ = "device_status"
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    battery_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    battery_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_charging: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    activity_state: Mapped[str | None] = mapped_column(String(48), nullable=True)
    is_worn: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    online: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


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


# ===== Meals: foods, recipes, pantry (MEAL-1) ========================
#
# See docs/MEALS_PLAN.md. Two shape decisions worth knowing before
# editing:
#
# 1. Nutrition is stored PER 100 G, which is how USDA publishes it and
#    how every conversion in the app is then a single multiply. Storing
#    per-serving would mean re-deriving whenever a recipe scales.
# 2. There is no household or portion model. Confirmed 2026-08-22:
#    cooking for one. A recipe has `servings` and meal prep multiplies
#    it; nothing else is needed.

class Food(Base):
    """A canonical ingredient with its nutrition per 100 g.

    Seeded from USDA FoodData Central (public domain) and extendable by
    the user — `source` distinguishes the two, so a re-seed can replace
    the bundled rows without touching anything hand-entered.
    """

    __tablename__ = "foods"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #: Stable slug. For USDA rows this embeds the FDC id, so a re-seed
    #: updates a row rather than inserting a duplicate.
    slug: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    #: "usda" | "user". Only "usda" rows are touched by a re-seed.
    source: Mapped[str] = mapped_column(String(16), default="usda")
    category: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)

    # Per 100 g. Nullable throughout: USDA does not carry every nutrient
    # for every food, and a null must stay distinguishable from a zero —
    # "we do not know the sodium" is not "this food has no sodium".
    kcal: Mapped[float | None] = mapped_column(Float, nullable=True)
    protein_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    carbs_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: The nutrient that matters most here — see MEALS_PLAN hard part 5.
    fat_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    saturated_fat_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    fiber_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    sugar_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    sodium_mg: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Fat-soluble vitamins (migration 0057). Carried because absorbing
    # them depends on absorbing fat, which is the one thing this user's
    # cholecystectomy changes — so they are the nutrients a macro-only
    # tracker would miss. Units are in the names deliberately: USDA
    # publishes vitamin A in both RAE micrograms and IU.
    vitamin_a_ug: Mapped[float | None] = mapped_column(Float, nullable=True)
    vitamin_d_ug: Mapped[float | None] = mapped_column(Float, nullable=True)
    vitamin_e_mg: Mapped[float | None] = mapped_column(Float, nullable=True)
    vitamin_k_ug: Mapped[float | None] = mapped_column(Float, nullable=True)

    #: The packaging's ingredient declaration, transcribed verbatim from
    #: a photo (migration 0062). Null on every USDA row — this is only
    #: ever user-supplied, for a packaged product. Kept as text in its
    #: original ORDER, which is meaningful: items are declared by
    #: descending weight.
    ingredients: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Canonical pantry concept (migration 0060). USDA rows are nutrition
    #: rows: raw and grilled chicken breast are separate ids with genuinely
    #: different nutrition, but they are ONE thing to buy and to have in
    #: the house. Matching a pantry item to a recipe ingredient happens on
    #: this, never on `id`. NULL means "not a pantry ingredient" — a
    #: prepared dish — so `concept IS NOT NULL` is the stockable test.
    concept: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)

    #: Grams per common household unit, e.g. {"cup": 240, "tbsp": 15}.
    #: Without this a recipe written in cups cannot be costed in grams,
    #: which is how recipes are actually written.
    unit_grams: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # No Python-side default: migration 0056 sets server_default now(),
    # which is how every other model in this file does it. A
    # `default=lambda: datetime.now(timezone.utc)` here raised NameError
    # on every INSERT, because this module imports `date` and `datetime`
    # but not `timezone`.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Recipe(Base):
    """A recipe the USER owns.

    The app never ships or scrapes third-party recipes — see MEALS_PLAN
    hard part 1. Everything here is entered or imported by the user into
    their own private install, and none of it belongs in the repo.
    """

    __tablename__ = "recipes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    #: How many portions the ingredient quantities below produce.
    servings: Mapped[int] = mapped_column(Integer, default=1)
    prep_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cook_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    method: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    #: Where an imported recipe came from, so its provenance is visible.
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    archived: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
    )
    # No Python-side default: migration 0056 sets server_default now(),
    # which is how every other model in this file does it. A
    # `default=lambda: datetime.now(timezone.utc)` here raised NameError
    # on every INSERT, because this module imports `date` and `datetime`
    # but not `timezone`.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )


class RecipeIngredient(Base):
    """One line of a recipe.

    `food_id` is nullable on purpose. An imported or hand-typed line may
    not resolve to a known food ("splash of sesame oil"), and dropping it
    would silently shorten the recipe. An unresolved line keeps its raw
    text, is shown as-is, and is EXCLUDED from nutrition totals — which
    the API reports, so a total is never quietly incomplete.
    """

    __tablename__ = "recipe_ingredients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipe_id: Mapped[int] = mapped_column(
        ForeignKey("recipes.id", ondelete="CASCADE"), index=True,
    )
    food_id: Mapped[int | None] = mapped_column(
        ForeignKey("foods.id", ondelete="SET NULL"), nullable=True,
    )
    #: What the user actually wrote, kept verbatim even when resolved.
    raw_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: "g" | "ml" | "cup" | "tbsp" | "tsp" | "item" ...
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)


class PantryItem(Base):
    """Something currently in the house.

    Quantities are optional: "we have olive oil" is a useful fact even
    without knowing how much, and demanding a number is the kind of
    friction that stops a pantry being kept up to date at all.
    """

    __tablename__ = "pantry_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    food_id: Mapped[int | None] = mapped_column(
        ForeignKey("foods.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    #: For things with no food row yet.
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MealPlanEntry(Base):
    """One planned meal on one day (MEAL-3).

    A plan entry is deliberately thin: a date, a slot, and either a
    recipe or a free-text note. There is no household or portion model —
    confirmed single-person — so `servings` is a plain multiplier on a
    recipe already sized for one or two, which is what meal prep needs
    ("make four containers of this").

    `recipe_id` is nullable with ON DELETE SET NULL rather than CASCADE.
    Deleting a recipe must not silently empty days out of the plan; the
    entry keeps its note and is shown as needing attention.
    """

    __tablename__ = "meal_plan_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #: The LOCAL calendar day, resolved server-side in settings.tz. Never
    #: derived from a UTC timestamp — see the day-boundary rule.
    day: Mapped[date] = mapped_column(Date, index=True)
    #: "breakfast" | "lunch" | "dinner" | "snack" | "prep"
    slot: Mapped[str] = mapped_column(String(16))
    recipe_id: Mapped[int | None] = mapped_column(
        ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    #: For a planned meal with no recipe behind it — eating out, or
    #: leftovers. Carries no nutrition, and the shopping list ignores it.
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    #: How many portions of the recipe to make. The meal-prep multiplier.
    servings: Mapped[int] = mapped_column(Integer, default=1)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ShoppingList(Base):
    """A generated shopping list and its state (MEAL-3).

    Persisted rather than recomputed on every view because the user ticks
    items off as they shop, and that state has to survive a page reload
    and follow them to the other client. Regenerating would silently undo
    their ticks.
    """

    __tablename__ = "shopping_lists"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: The local-day window the list was generated from, kept so the list
    #: can say what it covers rather than being an undated snapshot.
    start_day: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_day: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: "open" | "done"
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ShoppingListItem(Base):
    """One line on a shopping list.

    Quantities are stored as computed — the aggregation across planned
    meals and the pantry subtraction both happen server-side, so the two
    clients cannot disagree about what to buy.
    """

    __tablename__ = "shopping_list_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    list_id: Mapped[int] = mapped_column(
        ForeignKey("shopping_lists.id", ondelete="CASCADE"), index=True,
    )
    food_id: Mapped[int | None] = mapped_column(
        ForeignKey("foods.id", ondelete="SET NULL"), nullable=True,
    )
    #: Display name, snapshotted at generation time so a renamed or
    #: deleted food does not leave a blank line on a list mid-shop.
    label: Mapped[str] = mapped_column(String(255))
    #: Total needed, in grams, when every contributing line converted.
    grams: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: A human-readable amount ("2 cup, 1 clove"). Populated when the
    #: lines could NOT all be reduced to grams, which is common and not
    #: an error — there is no general weight for one clove.
    amount_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: True when the pantry already holds some of this but in an unknown
    #: quantity. The item stays ON the list, flagged — silently dropping
    #: it would send the user home without something they needed.
    pantry_uncertain: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
    )
    #: How much the pantry covered, in grams, when it could be subtracted.
    pantry_covered_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    checked: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0)


class FoodLogEntry(Base):
    """One thing eaten, at one meal, on one day (MEAL-5).

    An entry points at a food, a recipe, or neither. "Neither" is a
    first-class case: someone logging a meal out has a name and maybe a
    fat figure off a menu, and refusing that would make the log unusable
    exactly when it matters most.
    """

    __tablename__ = "food_log_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #: The user's LOCAL calendar day, resolved in settings.tz. Deriving
    #: it from a UTC timestamp would file an evening meal under tomorrow.
    day: Mapped[date] = mapped_column(Date, index=True)
    #: "breakfast" | "lunch" | "dinner" | "snack". The unit of interest
    #: for fat, which is why it is required rather than optional.
    slot: Mapped[str] = mapped_column(String(16), default="dinner")
    food_id: Mapped[int | None] = mapped_column(
        ForeignKey("foods.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    recipe_id: Mapped[int | None] = mapped_column(
        ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    #: Free text for anything that resolves to neither.
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: Servings, when the entry is a recipe.
    servings: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Nutrition typed in by hand, for a meal out where the only source
    #: is a menu. Kept separate from the computed figures so the API can
    #: say which is which rather than presenting a guess as a lookup.
    manual_kcal: Mapped[float | None] = mapped_column(Float, nullable=True)
    manual_fat_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FoodLogDay(Base):
    """Whether a day's log is COMPLETE, as declared by the user.

    This exists because logging here is expected to be intermittent, and
    a half-logged day is worse than an unlogged one: it reads as "you
    barely ate" rather than "you barely logged", and any average built
    from it is wrong in a direction that looks like progress.

    So completeness is never inferred — the app cannot know. The user
    marks a day complete, the default is partial, and everything derived
    counts ONLY complete days and says how many it used.
    """

    __tablename__ = "food_log_days"
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    complete: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
