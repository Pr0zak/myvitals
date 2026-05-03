"""Home Assistant REST client + periodic pull job.

Reads a configured list of entities every N minutes and writes the parsed
state into env_readings(time, source=entity_id, metric, value).
"""
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.dialects.postgresql import insert

from ..config import settings
from ..db import models
from ..db.session import SessionLocal

log = logging.getLogger(__name__)

# Map common non-numeric HA states to 0/1 so they're plottable.
_STATE_MAP: dict[str, float] = {
    "on": 1.0, "off": 0.0,
    "true": 1.0, "false": 0.0,
    "home": 1.0, "not_home": 0.0, "away": 0.0,
    "open": 1.0, "closed": 0.0,
    "unlocked": 1.0, "locked": 0.0,
    "detected": 1.0, "clear": 0.0,
}


def _parse_state(state: Any) -> float | None:
    if state is None:
        return None
    if isinstance(state, (int, float)):
        return float(state)
    s = str(state).strip().lower()
    if s in _STATE_MAP:
        return _STATE_MAP[s]
    try:
        return float(s)
    except ValueError:
        return None


async def _fetch_state(client: httpx.AsyncClient, entity_id: str) -> dict[str, Any] | None:
    try:
        r = await client.get(f"/api/states/{entity_id}", timeout=10.0)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        log.warning("HA fetch failed for %s: %s", entity_id, e)
        return None


async def pull_states() -> int:
    """Pull all configured entities, write env_readings rows. Returns count written."""
    if not settings.ha_url or not settings.ha_token:
        return 0
    entities = settings.ha_entity_list
    if not entities:
        return 0

    written = 0
    headers = {"Authorization": f"Bearer {settings.ha_token}"}
    async with httpx.AsyncClient(base_url=settings.ha_url.rstrip("/"), headers=headers) as client:
        async with SessionLocal() as db:
            now = datetime.now(timezone.utc)
            for eid in entities:
                payload = await _fetch_state(client, eid)
                if payload is None:
                    continue

                value = _parse_state(payload.get("state"))
                if value is None:
                    log.debug("HA: skipping non-numeric state for %s: %r", eid, payload.get("state"))
                    continue

                stmt = insert(models.EnvReading).values(
                    time=now, source=eid, metric="state", value=value,
                ).on_conflict_do_nothing(index_elements=["time", "source", "metric"])
                await db.execute(stmt)
                written += 1

                # Climate / weather entities expose extra numeric attributes worth capturing.
                attrs = payload.get("attributes") or {}
                for attr_key in ("current_temperature", "temperature", "humidity"):
                    if attr_key in attrs:
                        v = _parse_state(attrs[attr_key])
                        if v is not None:
                            stmt = insert(models.EnvReading).values(
                                time=now, source=eid, metric=attr_key, value=v,
                            ).on_conflict_do_nothing(index_elements=["time", "source", "metric"])
                            await db.execute(stmt)
                            written += 1

            await db.commit()

    if written:
        log.info("HA pull: wrote %d env_readings rows", written)
    return written
