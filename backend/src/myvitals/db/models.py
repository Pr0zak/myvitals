from datetime import date, datetime

from sqlalchemy import JSON, BigInteger, Boolean, Date, DateTime, Float, Integer, String, Text
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


class Steps(Base):
    __tablename__ = "vitals_steps"
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(Integer)


class SleepStage(Base):
    __tablename__ = "sleep_stages"
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    stage: Mapped[str] = mapped_column(String(16), primary_key=True)
    duration_s: Mapped[int] = mapped_column(Integer)


class Workout(Base):
    __tablename__ = "workouts"
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    type: Mapped[str] = mapped_column(String(32))
    duration_s: Mapped[int] = mapped_column(Integer)
    kcal: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_hr: Mapped[float | None] = mapped_column(Float, nullable=True)


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
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Alert(Base):
    """Surface-worthy events (RHR drift, missed sync, low HRV streak, ...)."""
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
