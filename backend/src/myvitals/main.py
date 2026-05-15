import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import version as version_mod
from .api import (
    ai,
    analytics,
    annotations,
    concept2,
    debug,
    devices,
    export,
    fasting,
    imports,
    ingest,
    profile,
    query,
    sober,
    strava,
    summary,
    trails,
)
from .api.workout import strength as workout_strength
from .config import settings

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = AsyncIOScheduler(timezone=settings.tz)
    from .tasks.scheduled import register_jobs
    register_jobs(scheduler)
    scheduler.start()
    log.info("scheduler started; daily_summary + anomaly_scan on-demand via API endpoints")

    # Best-effort: compute an initial summary on startup so /summary/today is
    # populated immediately. Don't block app startup if it fails.
    asyncio.create_task(_safe_initial_summary())

    # HA WebSocket realtime consumer — always start the task; the run()
    # function reads ha_config (DB) + env fallbacks and bails out if
    # url / token / realtime_enabled aren't all set. This lets Settings
    # changes pick up after the next backend restart without env-var
    # surgery; in-process re-arm is a future improvement.
    from .integrations.ha_realtime import run as _ha_run
    ha_task: asyncio.Task | None = asyncio.create_task(_ha_run(), name="ha_realtime")

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        if ha_task is not None:
            ha_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(ha_task, timeout=5.0)


async def _safe_initial_summary() -> None:
    from .analytics.jobs import compute_daily_summary
    try:
        await compute_daily_summary()
    except Exception as e:  # noqa: BLE001
        log.warning("initial daily_summary failed (likely no data yet): %s", e)


async def _anomaly_scan() -> None:
    """Every 6h: detect statistical anomalies in the last day's vitals.
    For each new anomaly (not already in ai_alerts), call Claude for a
    one-sentence notification body and persist. Phone polls /ai/alerts
    and posts system notifications for any unnotified rows."""
    from sqlalchemy import select
    from .db import models, session as _session
    from .integrations.claude import detect_anomalies, phrase_anomaly

    async with _session.SessionLocal() as db:
        cfg = await db.get(models.AiConfig, 1)
        if not cfg or not cfg.enabled:
            return
        try:
            anomalies = await detect_anomalies(db)
        except Exception as e:  # noqa: BLE001
            log.warning("anomaly detection failed: %s", e)
            return
        if not anomalies:
            log.debug("anomaly scan: no anomalies")
            return

        for a in anomalies:
            dedup_key = f"{a['date']}:{a['metric']}"
            existing = (await db.execute(
                select(models.AiAlert)
                .where(models.AiAlert.dedup_key == dedup_key)
                .limit(1)
            )).scalar_one_or_none()
            if existing:
                continue
            # Generate the phrasing only if Claude is configured;
            # otherwise drop a structured one-liner.
            try:
                if cfg.anthropic_api_key:
                    body = await phrase_anomaly(cfg, a)
                else:
                    body = (
                        f"{a['metric']} {'spike' if a['z_score'] > 0 else 'dip'}: "
                        f"{a['value']:.1f} (z={a['z_score']:+.1f})."
                    )
            except Exception as e:  # noqa: BLE001
                log.warning("anomaly phrase failed: %s", e)
                continue
            db.add(models.AiAlert(
                created_at=datetime.now(timezone.utc),
                kind="anomaly",
                severity=a["severity"],
                title=f"{a['metric'].upper()} anomaly",
                body=body,
                metric=a["metric"],
                z_score=a["z_score"],
                dedup_key=dedup_key,
            ))
        await db.commit()
        log.info("anomaly scan: persisted %d new alerts", len(anomalies))


async def _weekly_ai_digest() -> None:
    """Generate a weekly AI summary if the user has opted in. Cheap and
    cached — runs once on Sunday night, idempotent if data hasn't moved."""
    from datetime import datetime, timezone
    from sqlalchemy import select
    from .db import models, session as _session
    from .integrations.claude import build_summary_payload, explain, hash_payload

    async with _session.SessionLocal() as db:
        cfg = await db.get(models.AiConfig, 1)
        if not cfg or not cfg.enabled or not cfg.weekly_digest_enabled or not cfg.anthropic_api_key:
            log.debug("weekly AI digest: not configured / disabled, skipping")
            return
        try:
            payload = await build_summary_payload(db, "week")
            payload_hash = hash_payload(payload)
            cached = (await db.execute(
                select(models.AiSummary)
                .where(models.AiSummary.range_kind == "week")
                .where(models.AiSummary.payload_hash == payload_hash)
                .limit(1)
            )).scalar_one_or_none()
            if cached is not None:
                log.info("weekly AI digest: cache hit, no API call needed")
                return
            result = await explain(db, "week", cfg)
            cfg.calls_today = (cfg.calls_today or 0) + 1
            db.add(models.AiSummary(
                generated_at=datetime.now(timezone.utc),
                range_kind="week",
                payload_hash=payload_hash,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                content=result.content,
            ))
            await db.commit()
            log.info("weekly AI digest written (%d in / %d out tokens)",
                     result.input_tokens, result.output_tokens)
        except Exception as e:  # noqa: BLE001
            log.warning("weekly AI digest failed: %s", e)


app = FastAPI(title="myvitals", version=version_mod.__version__, lifespan=lifespan)

app.include_router(ingest.router, prefix="/ingest", tags=["ingest"])
app.include_router(query.router, prefix="/query", tags=["query"])
app.include_router(summary.router, prefix="/summary", tags=["summary"])
app.include_router(annotations.router, tags=["log"])
app.include_router(debug.router, tags=["debug"])
app.include_router(strava.router, tags=["strava"])
app.include_router(analytics.router, tags=["analytics"])
app.include_router(export.router, tags=["export"])
app.include_router(imports.router, tags=["import"])
app.include_router(profile.router, tags=["profile"])
app.include_router(sober.router, tags=["sober"])
app.include_router(ai.router, tags=["ai"])
app.include_router(workout_strength.router, tags=["workout-strength"])
app.include_router(trails.router, tags=["trails"])
app.include_router(devices.router, tags=["devices"])
app.include_router(fasting.router, tags=["fasting"])
app.include_router(concept2.router)
app.include_router(concept2._webhook_router)

# Bundled exercise images (yuhonas/free-exercise-db, public domain).
# Mounted off the package's data dir so the wheel ships them.
_IMG_DIR = Path(__file__).resolve().parent / "data" / "img"
if _IMG_DIR.is_dir():
    app.mount(
        "/exercises/img", StaticFiles(directory=_IMG_DIR), name="exercise-images"
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/version")
async def get_version() -> dict[str, str]:
    return version_mod.info()
