"""APScheduler job registration. Each scheduled job has a small
wrapper here; main.py just calls register_jobs(scheduler).

Earlier this lived inline in main.py's lifespan and grew to ~80 lines.
Pulling it out keeps main.py focused on app lifecycle and makes the
"what runs on a schedule" surface easier to audit at a glance.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ..config import settings
from ..integrations.home_assistant import pull_states as ha_pull_states
from ..integrations import strava as strava_int

log = logging.getLogger(__name__)


# ── Job wrappers ─────────────────────────────────────────────────

async def _trails_tick() -> None:
    """Poll RainoutLine. No-op if DNIS isn't configured."""
    try:
        from ..integrations.rainoutline import poll_and_persist
        await poll_and_persist()
    except Exception as e:  # noqa: BLE001
        log.warning("trail poll failed: %s", e)


async def _concept2_tick() -> None:
    """Pull recent Concept2 logbook results. No-op if credentials aren't set."""
    try:
        from ..db import models, session
        from ..integrations import concept2
        async with session.SessionLocal() as db:
            cred = await db.get(models.Concept2Credentials, 1)
            if cred is None:
                return
            await concept2.sync_results(db, cred=cred)
    except Exception as e:  # noqa: BLE001
        log.warning("Concept2 poll failed: %s", e)


# ── Registration ─────────────────────────────────────────────────

def register_jobs(scheduler: AsyncIOScheduler) -> None:
    """Register every scheduled job.

    Note: daily_summary and ai_anomaly_scan have BEEN RETIRED — both
    are now triggered on-demand from the API endpoints that surface
    their output. Don't re-add them here.
    """
    # Home Assistant entity-state pull (only when configured).
    if settings.ha_url and settings.ha_token and settings.ha_entity_list:
        scheduler.add_job(
            ha_pull_states,
            trigger="interval", minutes=5,
            id="ha_pull", replace_existing=True,
            next_run_time=None,
        )
        log.info("HA poll scheduled every 5 min for %d entities",
                 len(settings.ha_entity_list))

    # Strava sync — always schedule; sync_recent is a no-op if creds
    # aren't configured, so the user can connect Strava without restart.
    scheduler.add_job(
        strava_int.sync_recent,
        trigger="interval", hours=6,
        id="strava_sync", replace_existing=True,
    )
    log.info("Strava poll scheduled every 6h (no-op until configured)")

    # Weekly AI digest — Sun 22:00 local. No-op if user hasn't opted in.
    from ..main import _weekly_ai_digest
    scheduler.add_job(
        _weekly_ai_digest,
        trigger="cron", day_of_week="sun", hour=22, minute=0,
        id="ai_weekly_digest", replace_existing=True,
    )
    log.info("Weekly AI digest scheduled for Sun 22:00 %s", settings.tz)

    # RainoutLine trail poll — real periodic ingestion (no push). 15 min.
    scheduler.add_job(
        _trails_tick,
        trigger="interval", minutes=15,
        id="trails_poll", replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=20),
    )
    log.info("Trail status poll scheduled every 15 min")

    # Concept2 incremental poll — every 30 min, no-op until connected.
    scheduler.add_job(
        _concept2_tick,
        trigger="interval", minutes=30,
        id="concept2_poll", replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=45),
    )
    log.info("Concept2 poll scheduled every 30 min (no-op until connected)")
