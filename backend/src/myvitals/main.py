import asyncio
import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from . import version as version_mod
from .analytics.jobs import compute_daily_summary
from .api import annotations, debug, ingest, query, summary
from .config import settings
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


app = FastAPI(title="myvitals", version=version_mod.__version__, lifespan=lifespan)

app.include_router(ingest.router, prefix="/ingest", tags=["ingest"])
app.include_router(query.router, prefix="/query", tags=["query"])
app.include_router(summary.router, prefix="/summary", tags=["summary"])
app.include_router(annotations.router, tags=["log"])
app.include_router(debug.router, tags=["debug"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/version")
async def get_version() -> dict[str, str]:
    return version_mod.info()
