import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import version as version_mod
from .analytics.jobs import compute_daily_summary
from .api import (
    ai,
    analytics,
    annotations,
    concept2,
    debug,
    export,
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
from .integrations import strava as strava_int
from .integrations.home_assistant import pull_states as ha_pull_states

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = AsyncIOScheduler(timezone=settings.tz)
    scheduler.add_job(
        compute_daily_summary,
        trigger="cron",
        hour=3, minute=0,
        id="daily_summary",
        replace_existing=True,
    )
    if settings.ha_url and settings.ha_token and settings.ha_entity_list:
        scheduler.add_job(
            ha_pull_states,
            trigger="interval",
            minutes=5,
            id="ha_pull",
            replace_existing=True,
            next_run_time=None,  # let interval kick in naturally
        )
        log.info("HA poll scheduled every 5 min for %d entities", len(settings.ha_entity_list))
    # Always schedule — sync_recent is a no-op if credentials aren't set yet,
    # so the user can configure Strava in the dashboard without restarting.
    scheduler.add_job(
        strava_int.sync_recent,
        trigger="interval",
        hours=6,
        id="strava_sync",
        replace_existing=True,
    )
    log.info("Strava poll scheduled every 6h (no-op until configured)")

    # Weekly AI digest — Sunday 22:00 local. No-op if the user hasn't
    # enabled it / hasn't configured an API key.
    scheduler.add_job(
        _weekly_ai_digest,
        trigger="cron",
        day_of_week="sun",
        hour=22, minute=0,
        id="ai_weekly_digest",
        replace_existing=True,
    )
    log.info("Weekly AI digest scheduled for Sun 22:00 %s", settings.tz)

    # Anomaly scan — every 6h. Stats-side detection is no-LLM; the LLM
    # only phrases new (unseen) anomalies into a notification body, so
    # quiet days cost nothing.
    scheduler.add_job(
        _anomaly_scan,
        trigger="interval",
        hours=6,
        id="ai_anomaly_scan",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    log.info("Anomaly scan scheduled every 6h")

    # Trail-status poll — every 15 min during 06:00-22:00 CT, 60 min
    # overnight. APScheduler doesn't have a native time-of-day window,
    # so use one cron job that runs the poll only when the local hour
    # is in range (other ticks no-op cheaply).
    from .integrations.rainoutline import poll_and_persist as _poll_trails

    async def _trails_tick() -> None:
        try:
            await _poll_trails()
        except Exception as e:  # noqa: BLE001
            log.warning("trail poll failed: %s", e)

    scheduler.add_job(
        _trails_tick,
        trigger="interval", minutes=15,
        id="trails_poll", replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=20),
    )
    log.info("Trail status poll scheduled every 15 min")

    # Concept2 incremental poll — no-op if credentials aren't set.
    from .db import models as _c2_models
    from .db.session import SessionLocal as _c2_session
    from .integrations import concept2 as _concept2_int

    async def _concept2_tick() -> None:
        try:
            async with _c2_session() as db:
                cred = await db.get(_c2_models.Concept2Credentials, 1)
                if cred is None:
                    return
                await _concept2_int.sync_results(db, cred=cred)
        except Exception as e:  # noqa: BLE001
            log.warning("Concept2 poll failed: %s", e)

    scheduler.add_job(
        _concept2_tick,
        trigger="interval", minutes=30,
        id="concept2_poll", replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=45),
    )
    log.info("Concept2 poll scheduled every 30 min (no-op until connected)")
    scheduler.start()
    log.info("scheduler started; daily_summary at 03:00 %s", settings.tz)

    # Best-effort: compute an initial summary on startup so /summary/today is
    # populated immediately. Don't block app startup if it fails.
    asyncio.create_task(_safe_initial_summary())

    yield
    scheduler.shutdown(wait=False)


async def _safe_initial_summary() -> None:
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
