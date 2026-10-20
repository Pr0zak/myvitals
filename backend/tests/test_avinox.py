from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from myvitals.db import models
from myvitals.integrations import activity_sink, avinox


@pytest.fixture
def sample_avinox_payload() -> dict:
    return {
        "id": 101,
        "serial": "AVX-BIKE-789",
        "ride_id": 42,
        "start": "2026-10-15T14:00:00Z",
        "end": "2026-10-15T15:15:00Z",
        "duration_s": 4500,
        "moving_time_s": 4200,
        "distance_km": 25.5,
        "ascent_m": 180.5,
        "descent_m": 175.2,
        "battery_start": 98,
        "battery_end": 55,
        "battery_used_pct": 43,
        "odometer_end_km": 1540.2,
        "max_speed_kmh": 41.5,
        "avg_speed_kmh": 21.8,
        "avg_cadence": 78.4,
        "avg_rider_power_w": 150.0,
        "max_rider_power_w": 420.0,
        "avg_motor_power_w": 220.0,
        "max_motor_power_w": 650.0,
        "avg_heart_rate": 135.0,
        "max_heart_rate": 168,
        "rider_energy_kj": 630.0,
        "assist_seconds": {"0": 60, "1": 300, "2": 2400, "3": 1400, "4": 40},
        "sample_count": 4200,
        "track": [
            [39.001, -94.501],
            [39.005, -94.505],
            [39.010, -94.510],
        ],
        "hr_samples": [
            ["2026-10-15T14:00:01Z", 125],
            ["2026-10-15T14:00:02Z", 126],
            ["2026-10-15T14:00:03Z", 128],
        ],
        "series": {
            "t": [1792072801, 1792072802, 1792072803],
            "distance_km": [0.01, 0.02, 0.03],
            "speed_kmh": [20.1, 21.4, 22.0],
            "assist": [2, 2, 3],
            "gear": [5, 5, 6],
            "cadence": [75.0, 78.0, 80.0],
            "rider_power_w": [140.0, 150.0, 160.0],
            "motor_power_w": [200.0, 210.0, 230.0],
            "rider_torque_nm": [20.0, 22.0, 24.0],
            "motor_torque_nm": [35.0, 38.0, 40.0],
            "total_power_w": [340.0, 360.0, 390.0],
            "total_torque_nm": [55.0, 60.0, 64.0],
            "altitude_m": [250.0, 251.0, 252.0],
            "gradient_pct": [1.5, 2.0, 1.8],
            "heart_rate": [125, 126, 128],
            "battery_pct": [98, 98, 97],
            "temperature_c": [22.5, 22.5, 22.6],
            "lat": [39.001, 39.005, 39.010],
            "lon": [-94.501, -94.505, -94.510],
        },
    }


def test_map_avinox_payload(sample_avinox_payload):
    values = avinox.map_avinox_payload(sample_avinox_payload)

    assert values["source"] == "avinox"
    assert values["source_id"] == "42"
    assert values["type"] == "ebikeride"
    assert values["duration_s"] == 4500
    assert values["moving_time_s"] == 4200
    assert values["distance_m"] == 25500.0
    assert values["elevation_gain_m"] == 180.5
    assert values["elevation_loss_m"] == 175.2
    assert values["avg_cadence"] == 78.4
    assert values["avg_power_w"] == 150.0
    assert values["max_power_w"] == 420.0
    assert values["avg_motor_power_w"] == 220.0
    assert values["max_motor_power_w"] == 650.0
    assert values["battery_start"] == 98
    assert values["battery_end"] == 55
    assert values["odometer_end_km"] == 1540.2
    assert values["assist_seconds"] == {"0": 60, "1": 300, "2": 2400, "3": 1400, "4": 40}
    assert values["kcal"] == round(630.0 * 0.239006, 1)
    assert values["polyline"] is not None
    assert values["raw"] == sample_avinox_payload


@pytest.mark.asyncio
async def test_ingest_ride_payload_creates_activity(sample_avinox_payload):
    mock_db = AsyncMock()

    # Mock no existing Strava activity
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_exec_result

    # Mock get_or_create_config
    mock_cfg = models.AvinoxConfig(id=1, server_url="http://avinox.lan:8000")
    mock_db.get.return_value = mock_cfg

    with patch.object(activity_sink, "upsert_activity", new_callable=AsyncMock) as mock_upsert:
        mock_upsert.return_value = models.Activity(
            source="avinox", source_id="42", type="ebikeride", name="Avinox Ride #42",
            start_at=datetime(2026, 10, 15, 14, 0, tzinfo=timezone.utc), duration_s=4500
        )
        res = await avinox.ingest_ride_payload(mock_db, sample_avinox_payload)

        assert res["status"] == "ok"
        assert res["source"] == "avinox"
        assert res["source_id"] == "42"
        mock_upsert.assert_called_once()
        args, kwargs = mock_upsert.call_args
        values = args[1]
        assert values["source"] == "avinox"
        assert values["source_id"] == "42"
        assert values["avg_motor_power_w"] == 220.0
        assert values["battery_start"] == 98
        assert values["battery_end"] == 55
        assert values["odometer_end_km"] == 1540.2


@pytest.mark.asyncio
async def test_ingest_ride_payload_supersedes_strava_activity(sample_avinox_payload):
    mock_db = AsyncMock()

    # Simulate an existing Strava activity for the same ride with user notes and tags
    existing_strava = models.Activity(
        source="strava",
        source_id="strava_999",
        type="ebikeride",
        start_at=datetime(2026, 10, 15, 14, 0, 10, tzinfo=timezone.utc),
        duration_s=4490,
        notes="Sunny afternoon ride along the creek",
        tags=["creek", "sunny"],
        trail_id=15,
        recorded_type="ebikeride",
    )

    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = existing_strava
    mock_db.execute.return_value = mock_exec_result

    mock_cfg = models.AvinoxConfig(id=1, server_url="http://avinox.lan:8000")
    mock_db.get.return_value = mock_cfg

    with patch.object(activity_sink, "upsert_activity", new_callable=AsyncMock) as mock_upsert:
        mock_upsert.return_value = models.Activity(
            source="avinox", source_id="42", type="ebikeride", name="Avinox Ride #42",
            start_at=datetime(2026, 10, 15, 14, 0, tzinfo=timezone.utc), duration_s=4500
        )
        res = await avinox.ingest_ride_payload(mock_db, sample_avinox_payload)

        # Strava activity was deleted
        mock_db.delete.assert_called_once_with(existing_strava)

        # User-owned columns migrated to Avinox values
        args, kwargs = mock_upsert.call_args
        values = args[1]
        assert values["notes"] == "Sunny afternoon ride along the creek"
        assert values["tags"] == ["creek", "sunny"]
        assert values["trail_id"] == 15
        assert values["recorded_type"] == "ebikeride"


@pytest.mark.asyncio
async def test_avinox_push_route_handler(sample_avinox_payload):
    from myvitals.api import avinox as avinox_api

    mock_db = AsyncMock()
    mock_cfg = models.AvinoxConfig(id=1, server_url="http://avinox.lan:8000", webhook_secret="secret123")
    mock_db.get.return_value = mock_cfg

    with patch.object(avinox, "ingest_ride_payload", new_callable=AsyncMock) as mock_ingest:
        mock_ingest.return_value = {"status": "ok", "source": "avinox", "source_id": "42"}

        # Authorized via Bearer webhook_secret
        resp = await avinox_api.avinox_push(
            payload=sample_avinox_payload,
            authorization="Bearer secret123",
            x_avinox_secret=None,
            x_ingest_token=None,
            db=mock_db,
        )
        assert resp["ok"] is True
        assert resp["result"]["source_id"] == "42"

        # Authorized via X-Avinox-Secret
        resp2 = await avinox_api.avinox_push(
            payload=sample_avinox_payload,
            authorization=None,
            x_avinox_secret="secret123",
            x_ingest_token=None,
            db=mock_db,
        )
        assert resp2["ok"] is True


@pytest.mark.asyncio
async def test_avinox_push_route_unauthorized(sample_avinox_payload):
    from fastapi import HTTPException
    from myvitals.api import avinox as avinox_api

    mock_db = AsyncMock()
    mock_cfg = models.AvinoxConfig(id=1, server_url="http://avinox.lan:8000", webhook_secret="secret123")
    mock_db.get.return_value = mock_cfg

    with pytest.raises(HTTPException) as exc_info:
        await avinox_api.avinox_push(
            payload=sample_avinox_payload,
            authorization="Bearer wrong_token",
            x_avinox_secret=None,
            x_ingest_token=None,
            db=mock_db,
        )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_avinox_status_and_config():
    from myvitals.api import avinox as avinox_api

    mock_db = AsyncMock()
    mock_cfg = models.AvinoxConfig(
        id=1,
        server_url="http://avinox.lan:8000",
        webhook_secret="sec789",
        last_sync_at=datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc),
        last_push_at=datetime(2026, 10, 15, 15, 30, tzinfo=timezone.utc),
        auto_sync_enabled=True,
    )
    mock_db.get.return_value = mock_cfg
    mock_db.scalar.return_value = 5  # total rides

    mock_exec = MagicMock()
    mock_exec.scalars.return_value.first.return_value = models.Activity(
        source="avinox", source_id="42", type="ebikeride",
        start_at=datetime(2026, 10, 15, 14, 0, tzinfo=timezone.utc), duration_s=3600
    )
    mock_db.execute.return_value = mock_exec

    status_resp = await avinox_api.get_status(mock_db)
    assert status_resp["connected"] is True
    assert status_resp["server_url"] == "http://avinox.lan:8000"
    assert status_resp["total_rides"] == 5
    assert "/integrations/avinox/webhook/sec789" in status_resp["webhook_path"]

    # Test config update
    cfg_in = avinox_api.AvinoxConfigIn(server_url="http://10.0.0.104:8000", query_token="mytoken")
    updated = await avinox_api.update_config(cfg_in, mock_db)
    assert mock_cfg.server_url == "http://10.0.0.104:8000"
    assert mock_cfg.query_token == "mytoken"

