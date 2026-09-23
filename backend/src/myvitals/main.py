import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from . import version as version_mod
from .db.session import get_session
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
    mcp,
    meals,
    ingest,
    profile,
    query,
    sober,
    google_health,
    strava,
    summary,
    trails,
    update as update_api,
)
from .api import errors as api_errors
from .api.workout import strength as workout_strength
from .config import settings
from .logging_config import configure_logging

# Before anything else: without this every log.info in the app is discarded,
# because `fastapi run` configures only the uvicorn loggers and leaves root
# at WARNING.
configure_logging(settings.log_level)

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

    # Load the bundled USDA food catalog (MEAL-1). Idempotent and a no-op
    # once seeded, so the steady-state cost is a single COUNT. Backgrounded
    # because the first run writes ~7,000 rows and nothing else at startup
    # needs to wait for it.
    asyncio.create_task(_safe_seed_foods())

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


async def _safe_seed_foods() -> None:
    """Seed the food catalog, never blocking startup on it.

    A failure here costs an empty food picker, not a broken app, so it is
    logged and swallowed. Notably it also fails harmlessly on a backend
    that starts before migration 0056 has run.
    """
    from .db import session as _session
    from .db.seed_foods import seed_foods
    try:
        async with _session.SessionLocal() as db:
            await seed_foods(db)
    except Exception as e:  # noqa: BLE001
        log.warning("food catalog seed failed: %s", e)


async def _anomaly_scan() -> None:
    """Every 6h: detect statistical anomalies in the last day's vitals.
    For each new anomaly (not already in ai_alerts), call Claude for a
    one-sentence notification body and persist. Phone polls /ai/alerts
    and posts system notifications for any unnotified rows."""
    from sqlalchemy import select
    from .db import models, session as _session
    from .integrations.claude import _credentials_missing, detect_anomalies, phrase_anomaly

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
                if not _credentials_missing(cfg):
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
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import delete, select
    from .db import models, session as _session
    from .integrations.claude import (
        _credentials_missing, build_summary_payload, explain_legacy, hash_payload,
    )

    async with _session.SessionLocal() as db:
        # Retention: ai_summaries is append-only on every AI call and never
        # pruned otherwise. Keep ~120 days; cache hits past that are vanishingly
        # rare (the underlying payload has long since changed) and the content
        # blobs accumulate forever. Runs weekly regardless of AI being enabled.
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=120)
            res = await db.execute(
                delete(models.AiSummary).where(models.AiSummary.generated_at < cutoff)
            )
            await db.commit()
            if res.rowcount:
                log.info("ai_summaries retention: pruned %d rows older than 120d", res.rowcount)
        except Exception as e:  # noqa: BLE001
            log.warning("ai_summaries retention prune failed: %s", e)

        cfg = await db.get(models.AiConfig, 1)
        # OG3-L2. This read `not cfg.anthropic_api_key` — one of the guards
        # `_credentials_missing` was written to replace when the CLI provider
        # shipped. That test is correct for Anthropic and wrong for every
        # other provider: `claude_cli` authenticates through the machine's
        # subscription OAuth and deliberately has no API key, so the Sunday
        # digest has been silently returning at this line ever since, logging
        # only at debug level.
        if (
            not cfg
            or not cfg.enabled
            or not cfg.weekly_digest_enabled
            or _credentials_missing(cfg)
        ):
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
            result = await explain_legacy(db, "week", cfg)
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
api_errors.install(app)

app.include_router(ingest.router, prefix="/ingest", tags=["ingest"])
app.include_router(query.router, prefix="/query", tags=["query"])
app.include_router(summary.router, prefix="/summary", tags=["summary"])
app.include_router(annotations.router, tags=["log"])
app.include_router(debug.router, tags=["debug"])
app.include_router(strava.router, tags=["strava"])
app.include_router(google_health.router, tags=["google-health"])
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
app.include_router(update_api.router, tags=["update"])
app.include_router(meals.router, tags=["meals"])
# MCP-1: read-only MCP endpoint. Publishes the same aggregates the AI
# surfaces use, so the user's own Claude subscription can read their
# health data without billing this app's key.
app.include_router(mcp.router, tags=["mcp"])
app.include_router(concept2.router)
app.include_router(concept2._webhook_router)

# Bundled exercise images (yuhonas/free-exercise-db, public domain).
# Mounted off the package's data dir so the wheel ships them.
_IMG_DIR = Path(__file__).resolve().parent / "data" / "img"
if _IMG_DIR.is_dir():
    app.mount(
        "/exercises/img", StaticFiles(directory=_IMG_DIR), name="exercise-images"
    )


# SA-O4: `/health` used to be a literal `{"status": "ok"}` — no DB round
# trip, so it could not tell "serving" from "every request 500s". It is
# the sole gate on deploy/auto-update.sh's 60s rollback probe (30 retries,
# 2s apart) and the intended target of an external uptime check (see
# docs/operations.md), so both directions matter: too weak and a dead DB
# ships as "healthy" forever; too strict and a one-off blip becomes an
# automatic rollback, which is worse than the always-OK it replaces. The
# 2s per-attempt budget below is well inside the auto-update retry
# cadence, so a transient hiccup gets several free retries before the
# script's own 60s window is spent — it takes a DB that is down for the
# whole minute to actually flip this red.
#
# `SELECT 1` touches no table (this app also has a 24.5M-row hypertable a
# health probe must never go near) and measured ~0.1-2ms against the live
# DB from inside the CT, against ~1.6ms for the old no-op response — the
# added cost is noise next to the "every few seconds" polling budget.
_HEALTH_DB_TIMEOUT_S = 2.0


@app.get("/health")
async def health(db: AsyncSession = Depends(get_session)) -> JSONResponse:
    info = version_mod.info()
    try:
        await asyncio.wait_for(db.execute(text("SELECT 1")), timeout=_HEALTH_DB_TIMEOUT_S)
    except Exception:  # noqa: BLE001 — DB down/slow/unreachable, all read the same to a probe
        return JSONResponse(status_code=503, content={"status": "error", **info})
    return JSONResponse(status_code=200, content={"status": "ok", **info})


@app.get("/version")
async def get_version() -> dict[str, str]:
    return version_mod.info()
