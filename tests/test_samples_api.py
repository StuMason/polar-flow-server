"""Tests for minute-level sample endpoints (issue #67).

Stored `samples_json` was synced but unreachable: clients only ever saw
`has_samples` flags and daily aggregates. These endpoints serve the
actual intraday data.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

USER_ID = "polar-1"
TARGET_DATE = dt.date(2026, 6, 1)


async def _seed_user_with_key() -> str:
    from polar_flow_server.core.api_keys import create_api_key_for_user
    from polar_flow_server.core.database import async_session_maker
    from polar_flow_server.models.user import User

    async with async_session_maker() as session:
        session.add(
            User(
                id="user-1",
                polar_user_id=USER_ID,
                access_token_encrypted="not-a-real-token",
                is_active=True,
            )
        )
        await session.flush()
        _, raw_key = await create_api_key_for_user(
            user_id=USER_ID, name="test key", session=session
        )
        await session.commit()
    return raw_key


async def _seed_sample_data(*, with_samples: bool = True) -> int:
    """Seed one day of activity samples + continuous HR + one ECG; return ECG id."""
    from polar_flow_server.core.database import async_session_maker
    from polar_flow_server.models.activity_samples import ActivitySamples
    from polar_flow_server.models.continuous_hr import ContinuousHeartRate
    from polar_flow_server.models.ecg import ECG

    async with async_session_maker() as session:
        session.add(
            ActivitySamples(
                user_id=USER_ID,
                date=TARGET_DATE,
                total_steps=8000,
                interval_ms=60000,
                sample_count=3,
                samples_json=(
                    json.dumps(
                        [
                            {"time": "08:00:00", "steps": 12},
                            {"time": "08:01:00", "steps": 40},
                            {"time": "08:02:00", "steps": 0},
                        ]
                    )
                    if with_samples
                    else None
                ),
            )
        )
        session.add(
            ContinuousHeartRate(
                user_id=USER_ID,
                date=TARGET_DATE,
                sample_count=2,
                hr_min=52,
                hr_avg=64,
                hr_max=110,
                samples_json=(
                    json.dumps(
                        [
                            {"time": "08:00:00", "heart_rate": 62},
                            {"time": "08:05:00", "heart_rate": 66},
                        ]
                    )
                    if with_samples
                    else None
                ),
            )
        )
        ecg = ECG(
            user_id=USER_ID,
            device_id="ABC123",
            test_time=dt.datetime(2026, 6, 1, 8, 30, tzinfo=dt.UTC),
            avg_heart_rate=61,
            hrv_ms=42.0,
            hrv_level="NORMAL",
            rri_ms=980.0,
            sample_count=3,
            duration_seconds=30.0,
            samples_json=json.dumps([0.12, 0.14, 0.11]) if with_samples else None,
            quality_json=json.dumps([{"segment": 1, "quality": "GOOD"}]) if with_samples else None,
        )
        session.add(ecg)
        await session.commit()
        return ecg.id


class TestActivitySamplesByDate:
    @pytest.mark.asyncio
    async def test_returns_parsed_samples(self, app_client) -> None:
        key = await _seed_user_with_key()
        await _seed_sample_data()

        response = await app_client.get(
            f"/api/v1/users/{USER_ID}/activity-samples/{TARGET_DATE}", headers={"X-API-Key": key}
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["total_steps"] == 8000
        assert payload["interval_ms"] == 60000
        assert payload["samples"][1] == {"time": "08:01:00", "steps": 40}

    @pytest.mark.asyncio
    async def test_missing_date_404(self, app_client) -> None:
        key = await _seed_user_with_key()

        response = await app_client.get(
            f"/api/v1/users/{USER_ID}/activity-samples/2020-01-01", headers={"X-API-Key": key}
        )

        assert response.status_code == 404
        assert "No activity samples" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_record_without_samples_404(self, app_client) -> None:
        key = await _seed_user_with_key()
        await _seed_sample_data(with_samples=False)

        response = await app_client.get(
            f"/api/v1/users/{USER_ID}/activity-samples/{TARGET_DATE}", headers={"X-API-Key": key}
        )

        assert response.status_code == 404
        assert "has no samples" in response.json()["detail"]


class TestHeartRateSamples:
    @pytest.mark.asyncio
    async def test_returns_parsed_samples(self, app_client) -> None:
        key = await _seed_user_with_key()
        await _seed_sample_data()

        response = await app_client.get(
            f"/api/v1/users/{USER_ID}/heart-rate/{TARGET_DATE}/samples",
            headers={"X-API-Key": key},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["hr_min"] == 52
        assert payload["samples"][0]["heart_rate"] == 62

    @pytest.mark.asyncio
    async def test_missing_date_404(self, app_client) -> None:
        key = await _seed_user_with_key()

        response = await app_client.get(
            f"/api/v1/users/{USER_ID}/heart-rate/2020-01-01/samples", headers={"X-API-Key": key}
        )

        assert response.status_code == 404


class TestECGDetail:
    @pytest.mark.asyncio
    async def test_returns_waveform(self, app_client) -> None:
        key = await _seed_user_with_key()
        ecg_id = await _seed_sample_data()

        response = await app_client.get(
            f"/api/v1/users/{USER_ID}/ecg/{ecg_id}", headers={"X-API-Key": key}
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["samples"] == [0.12, 0.14, 0.11]
        assert payload["quality"][0]["quality"] == "GOOD"
        assert payload["hrv_ms"] == 42.0

    @pytest.mark.asyncio
    async def test_list_carries_id_and_flag(self, app_client) -> None:
        key = await _seed_user_with_key()
        ecg_id = await _seed_sample_data()

        response = await app_client.get(
            f"/api/v1/users/{USER_ID}/ecg?days=365", headers={"X-API-Key": key}
        )

        assert response.status_code == 200
        record = response.json()[0]
        assert record["id"] == ecg_id
        assert record["has_samples"] is True

    @pytest.mark.asyncio
    async def test_missing_ecg_404(self, app_client) -> None:
        key = await _seed_user_with_key()

        response = await app_client.get(
            f"/api/v1/users/{USER_ID}/ecg/999999", headers={"X-API-Key": key}
        )

        assert response.status_code == 404
