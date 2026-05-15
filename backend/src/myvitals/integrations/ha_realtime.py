"""Home Assistant realtime consumer — Pixel Watch (and future devices) liveness.

Subscribes to HA's WebSocket `state_changed` events for a fixed allowlist
of device_status-class entities (battery / charger / activity / on-body)
and writes one dense row to `device_status` per event. Heart-rate / steps
were originally in scope but dropped — the Wear OS Companion App emits
them as sparse polls (~hourly), strictly worse than the existing Health
Connect ingest path. See docs/HA_REALTIME_PLAN.md → "Scope trim".

Lifecycle: started from `main.py`'s lifespan when both
`settings.ha_url` and `settings.ha_token` are set AND
`settings.ha_realtime_enabled` is True. Cancellable via the parent
asyncio task — SIGTERM propagation handled by FastAPI.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
from datetime import datetime, timezone
from typing import Any

import httpx
import websockets
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ..config import settings
from ..db import models
from ..db.session import SessionLocal

log = logging.getLogger(__name__)


# Dispatch — HA entity suffix → device_status field setter.
#
# The device-id prefix (e.g. "pixel_watch_3") is substituted at subscribe
# time from `settings.ha_realtime_device_id`, so swapping devices is a
# config change, not a code change.
_FIELD_MAP: dict[str, str] = {
    "battery_level": "battery_pct",
    "battery_state": "battery_state",
    "charger_type": "is_charging",
    "activity_state": "activity_state",
    "on_body_sensor": "is_worn",
}


_DEAD = ("unknown", "unavailable", "")


def _coerce(field: str, state: str) -> Any:
    """Map HA state string → DB column value."""
    if state in _DEAD:
        return None
    if field == "battery_pct":
        try:
            return int(float(state))
        except ValueError:
            return None
    if field == "is_charging":
        # charger_type is a string enum: 'none' / 'ac' / 'usb' / 'wireless'
        return state != "none"
    if field == "is_worn":
        # binary_sensor → 'on' / 'off'
        return state == "on"
    # battery_state / activity_state: pass through
    return state[:48]


async def _latest_row(device_id: str) -> dict[str, Any] | None:
    """Most recent device_status row for `device_id`, as a dict, or None."""
    async with SessionLocal() as db:
        row = (await db.execute(
            select(models.DeviceStatus)
            .where(models.DeviceStatus.device_id == device_id)
            .order_by(models.DeviceStatus.time.desc())
            .limit(1)
        )).scalar_one_or_none()
    if row is None:
        return None
    return {
        "battery_pct": row.battery_pct,
        "battery_state": row.battery_state,
        "is_charging": row.is_charging,
        "activity_state": row.activity_state,
        "is_worn": row.is_worn,
        "online": row.online,
    }


async def _write_row(
    device_id: str, ts: datetime, mutations: dict[str, Any],
) -> None:
    """Copy-forward the latest row, apply mutations, insert at `ts`.

    Concurrent inserts at the same timestamp deduplicate via the
    composite PK — `on_conflict_do_nothing` keeps the consumer idempotent.
    """
    prev = await _latest_row(device_id) or {}
    merged = {**prev, **mutations}
    async with SessionLocal() as db:
        stmt = insert(models.DeviceStatus).values(
            time=ts, device_id=device_id, **merged,
        ).on_conflict_do_nothing(index_elements=["time", "device_id"])
        await db.execute(stmt)
        await db.commit()


def _build_entity_map(device_id: str) -> dict[str, str]:
    """{full HA entity_id → device_status field} for the configured device."""
    out: dict[str, str] = {}
    for suffix, field in _FIELD_MAP.items():
        # binary_sensor.* for on_body_sensor, sensor.* for the rest
        domain = "binary_sensor" if suffix == "on_body_sensor" else "sensor"
        out[f"{domain}.{device_id}_{suffix}"] = field
    return out


async def _seed_offline(device_id: str) -> None:
    """Write online=false at consumer-stop / disconnect. Caller decides ts."""
    await _write_row(
        device_id, datetime.now(timezone.utc), {"online": False},
    )


async def _load_config() -> tuple[str | None, str | None, str, bool]:
    """Read (url, token, device_id, enabled) from ha_config singleton.
    Falls back to settings env-vars only if the DB row is empty — keeps
    early-adopter setups working without forcing a Settings round-trip."""
    async with SessionLocal() as db:
        row = await db.get(models.HaConfig, 1)
    url = (row.url if row else None) or settings.ha_url
    token = (row.token if row else None) or settings.ha_token
    device_id = (row.device_id if row else None) or settings.ha_realtime_device_id
    enabled = (row.realtime_enabled if row else False) or settings.ha_realtime_enabled
    return url, token, device_id, enabled


async def _consume_once(device_id: str, entity_map: dict[str, str]) -> None:
    """One connect-subscribe-process cycle. Raises on disconnect."""
    url, token, _did, _en = await _load_config()
    if not (url and token):
        raise RuntimeError("HA url/token missing (cleared from Settings?)")
    ws_url = url.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
    if not ws_url.endswith("/api/websocket"):
        ws_url = ws_url.rstrip("/") + "/api/websocket"

    async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
        # 1. auth handshake
        auth_req = json.loads(await ws.recv())
        if auth_req.get("type") != "auth_required":
            raise RuntimeError(f"unexpected HA greeting: {auth_req}")
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        auth_resp = json.loads(await ws.recv())
        if auth_resp.get("type") != "auth_ok":
            raise RuntimeError(f"HA auth rejected: {auth_resp}")

        # 2. subscribe to state_changed
        msg_id = 1
        await ws.send(json.dumps({
            "id": msg_id, "type": "subscribe_events", "event_type": "state_changed",
        }))
        sub_ack = json.loads(await ws.recv())
        if not sub_ack.get("success"):
            raise RuntimeError(f"HA subscribe rejected: {sub_ack}")

        log.info(
            "HA WebSocket connected, subscribed (%d entities)",
            len(entity_map),
        )

        # 3. mark online=true now that the channel is up
        await _write_row(
            device_id, datetime.now(timezone.utc), {"online": True},
        )

        # 4. event loop
        async for raw in ws:
            try:
                msg = json.loads(raw)
                if msg.get("type") != "event":
                    continue
                data = msg.get("event", {}).get("data", {})
                entity_id = data.get("entity_id")
                if entity_id not in entity_map:
                    continue
                new_state = (data.get("new_state") or {}).get("state")
                if new_state is None:
                    continue
                field = entity_map[entity_id]
                value = _coerce(field, new_state)
                # An 'unavailable' transition for any subscribed entity →
                # the watch dropped off HA; mark online=false too.
                mutations: dict[str, Any] = {field: value}
                if new_state in _DEAD:
                    mutations["online"] = False
                else:
                    mutations["online"] = True
                ts_iso = (data.get("new_state") or {}).get("last_updated")
                ts = (
                    datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
                    if ts_iso else datetime.now(timezone.utc)
                )
                await _write_row(device_id, ts, mutations)
            except Exception as e:  # noqa: BLE001 — per-message isolation
                log.warning("HA event handling failed: %s", e, exc_info=True)


# HA-9: live re-arm. PUT /ha-config sets this event so the consumer
# loop drops its current connection (or its "not configured" sleep)
# and re-reads url/token/device_id/enabled. Constructed lazily inside
# the asyncio loop because asyncio.Event needs a running loop on
# Python < 3.10 — at module import time, FastAPI hasn't started yet.
_restart_event: asyncio.Event | None = None


def request_restart() -> None:
    """Signal the running consumer to re-read ha_config and rebind.
    Safe to call from any coroutine (event.set is non-blocking) and
    a no-op if the consumer hasn't been started yet."""
    if _restart_event is not None and not _restart_event.is_set():
        _restart_event.set()


async def _consume_with_restart(
    device_id: str, entity_map: dict[str, str],
) -> str:
    """Run one consume cycle, racing it against the restart event.

    Returns "restart" if the event fired (caller should rebind config),
    or raises whatever the consume coroutine raised on disconnect."""
    assert _restart_event is not None
    consume = asyncio.create_task(_consume_once(device_id, entity_map))
    waiter = asyncio.create_task(_restart_event.wait())
    try:
        done, _pending = await asyncio.wait(
            {consume, waiter}, return_when=asyncio.FIRST_COMPLETED,
        )
        if waiter in done:
            _restart_event.clear()
            consume.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await consume
            return "restart"
        # consume completed (likely raised) — surface its exception.
        waiter.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await waiter
        consume.result()      # re-raises any error from _consume_once
        return "ok"
    except asyncio.CancelledError:
        consume.cancel(); waiter.cancel()
        raise


async def run() -> None:
    """Top-level consumer loop with exponential backoff reconnect.

    Cancellation propagates out cleanly — finally writes online=false
    so /device-status/latest reflects the gap.

    Live re-arm: PUT /ha-config calls request_restart(); the consumer
    drops the current WebSocket / sleep and re-reads config without
    needing a backend restart.
    """
    global _restart_event
    _restart_event = asyncio.Event()
    current_device_id: str | None = None

    try:
        while True:
            url, token, device_id, enabled = await _load_config()
            if not (url and token):
                log.warning(
                    "HA realtime: url/token not configured, idling "
                    "(will rebind on PUT /ha-config)"
                )
                await _restart_event.wait()
                _restart_event.clear()
                continue
            if not enabled:
                log.info(
                    "HA realtime: configured but realtime_enabled=false, idling"
                )
                # Seed offline so UI shows the channel is down by choice.
                if current_device_id:
                    with contextlib.suppress(Exception):
                        await _seed_offline(current_device_id)
                await _restart_event.wait()
                _restart_event.clear()
                continue

            entity_map = _build_entity_map(device_id)
            current_device_id = device_id
            backoff_s = 1.0
            should_rebind = False
            while not should_rebind:
                try:
                    outcome = await _consume_with_restart(device_id, entity_map)
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    log.warning(
                        "HA WebSocket dropped (%s); retrying in %.1fs",
                        e, backoff_s, exc_info=True,
                    )
                    try:
                        await _seed_offline(device_id)
                    except Exception:  # noqa: BLE001
                        log.warning("offline marker write failed", exc_info=True)
                    # Sleep with restart-aware wait so a re-arm during
                    # backoff doesn't get stuck behind a 60 s nap.
                    jitter = random.uniform(0, backoff_s * 0.25)
                    try:
                        await asyncio.wait_for(
                            _restart_event.wait(), timeout=backoff_s + jitter,
                        )
                        _restart_event.clear()
                        should_rebind = True
                    except asyncio.TimeoutError:
                        pass
                    backoff_s = min(backoff_s * 2.0, 60.0)
                else:
                    if outcome == "restart":
                        log.info("HA realtime: re-arm requested, reloading config")
                        should_rebind = True
                    else:
                        backoff_s = 1.0
    finally:
        # Final offline marker on shutdown — best effort.
        if current_device_id:
            with contextlib.suppress(Exception):
                await _seed_offline(current_device_id)
