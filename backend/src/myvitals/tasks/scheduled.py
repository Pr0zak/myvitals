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


async def _fasting_scheduled_tick() -> None:
    """Scheduled-mode fasting auto-start/end.

    Reads `profile.extra.fasting_prefs` and, when scheduled_mode_enabled
    is true, transitions between active fast / fed window based on the
    user's eating_window_start_h / eating_window_end_h. Manual
    start/end always wins — this only acts when there's nothing to
    contradict.

    Eating window is a daily span in local-clock hours
    (e.g. 12.0 → 20.0 = noon-to-8pm window, fast from 20:00 → 12:00).

    Runs every 5 min. Idempotent: re-checks if it should start or end,
    no-ops when state already matches.
    """
    try:
        from datetime import time as _time
        from sqlalchemy import select as _select
        from zoneinfo import ZoneInfo
        from ..db import models, session as _session
        async with _session.SessionLocal() as db:
            prof = await db.get(models.UserProfile, 1)
            if prof is None or not prof.extra:
                return
            prefs = (prof.extra.get("fasting_prefs") or {}) if isinstance(prof.extra, dict) else {}
            if not prefs.get("scheduled_mode_enabled"):
                return
            try:
                eat_start = float(prefs.get("eating_window_start_h", 12.0))
                eat_end = float(prefs.get("eating_window_end_h", 20.0))
            except (TypeError, ValueError):
                return
            if eat_start >= eat_end or not (0 <= eat_start < 24) or not (0 < eat_end <= 24):
                return

            # Resolve local clock-hour for the user's TZ.
            try:
                local_tz = ZoneInfo(settings.tz) if settings.tz != "UTC" else timezone.utc
            except Exception:
                local_tz = timezone.utc
            now_local = datetime.now(local_tz)
            now_h = now_local.hour + now_local.minute / 60.0

            in_eating_window = eat_start <= now_h < eat_end
            active = (await db.execute(
                _select(models.FastingSession)
                .where(models.FastingSession.ended_at.is_(None))
                .limit(1)
            )).scalar_one_or_none()

            if not in_eating_window and active is None:
                # We should be fasting and aren't → start.
                target_h = (24.0 - (eat_end - eat_start))
                protocol = prefs.get("default_protocol") or "16:8"
                # started_at = eat_end today (or yesterday) so elapsed is real.
                today = now_local.date()
                start_local = datetime.combine(today, _time(int(eat_end), 0), tzinfo=local_tz)
                # If we're past midnight in the fasting window, the window
                # started yesterday at eat_end.
                if now_h < eat_start:
                    start_local = start_local - timedelta(days=1)
                start_utc = start_local.astimezone(timezone.utc)
                db.add(models.FastingSession(
                    started_at=start_utc,
                    protocol=protocol,
                    mode="scheduled",
                    target_hours=target_h,
                    target_eating_window_h=eat_end - eat_start,
                ))
                await db.commit()
                log.info("Scheduled fasting auto-start: protocol=%s, started_at=%s",
                         protocol, start_utc.isoformat())
            elif in_eating_window and active is not None and active.mode == "scheduled":
                # Eating-window has opened on a scheduled fast → end.
                active.ended_at = datetime.now(timezone.utc)
                await db.commit()
                log.info("Scheduled fasting auto-end: id=%s", active.id)
            # In any other combination (active=manual; or fasting window
            # with active=scheduled; or eating window with no active) →
            # no-op.
    except Exception as e:  # noqa: BLE001
        log.warning("scheduled fasting tick failed: %s", e)


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

    # Scheduled-mode fasting auto-start/end — every 5 min. No-op
    # unless profile.extra.fasting_prefs.scheduled_mode_enabled is true.
    scheduler.add_job(
        _fasting_scheduled_tick,
        trigger="interval", minutes=5,
        id="fasting_scheduled", replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=30),
    )
    log.info("Scheduled fasting tick every 5 min (no-op until profile prefs enabled)")

    # Concept2 incremental poll — every 30 min, no-op until connected.
    scheduler.add_job(
        _concept2_tick,
        trigger="interval", minutes=30,
        id="concept2_poll", replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=45),
    )
    log.info("Concept2 poll scheduled every 30 min (no-op until connected)")
