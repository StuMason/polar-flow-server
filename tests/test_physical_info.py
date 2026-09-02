"""Tests for physical info capture (issue #75).

The transformer is exercised with a duck-typed stand-in for the SDK's
UserPhysicalInfo model (added in polar-flow-api 1.5.0) so this suite
passes regardless of which SDK version is installed — the sync step is
hasattr-gated the same way.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from polar_flow_server.transformers.physical_info import PhysicalInfoTransformer, _duration_seconds

USER_ID = "polar-1"


def _sdk_info(**overrides: object) -> SimpleNamespace:
    base = {
        "weight": 70.5,
        "height": 175.0,
        "created": dt.datetime(2026, 6, 1, 12, 0, tzinfo=dt.UTC),
        "modified": dt.datetime(2026, 6, 10, 12, 0, tzinfo=dt.UTC),
        "birthday": dt.date(1990, 1, 1),
        "gender": "MALE",
        "maximum_heart_rate": 190,
        "resting_heart_rate": 60,
        "aerobic_threshold": 140,
        "anaerobic_threshold": 170,
        "vo2_max": 50,
        "weight_source": "SOURCE_USER",
        "training_background": "REGULAR",
        "typical_day": "MOSTLY_MOVING",
        "sleep_goal": "PT8H",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestPhysicalInfoTransformer:
    def test_transforms_all_fields(self) -> None:
        result = PhysicalInfoTransformer.transform(_sdk_info(), USER_ID)

        assert result["recorded_at"] == dt.datetime(2026, 6, 10, 12, 0, tzinfo=dt.UTC)
        assert result["weight_kg"] == 70.5
        assert result["height_cm"] == 175.0
        assert result["birthday"] == dt.date(1990, 1, 1)
        assert result["gender"] == "MALE"
        assert result["maximum_heart_rate"] == 190
        assert result["resting_heart_rate"] == 60
        assert result["aerobic_threshold"] == 140
        assert result["anaerobic_threshold"] == 170
        assert result["vo2_max"] == 50
        assert result["training_background"] == "REGULAR"
        assert result["sleep_goal_seconds"] == 28800

    def test_recorded_at_falls_back_to_created(self) -> None:
        result = PhysicalInfoTransformer.transform(_sdk_info(modified=None), USER_ID)

        assert result["recorded_at"] == dt.datetime(2026, 6, 1, 12, 0, tzinfo=dt.UTC)

    def test_sleep_goal_parsing(self) -> None:
        assert _duration_seconds("PT8H") == 28800
        assert _duration_seconds("PT7H30M") == 27000
        assert _duration_seconds("PT45M") == 2700
        assert _duration_seconds(None) is None
        assert _duration_seconds("") is None
        assert _duration_seconds("garbage") is None


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


async def _seed_physical_info(snapshots: int = 1) -> None:
    from polar_flow_server.core.database import async_session_maker
    from polar_flow_server.models.physical_info import PhysicalInfo

    async with async_session_maker() as session:
        for i in range(snapshots):
            session.add(
                PhysicalInfo(
                    user_id=USER_ID,
                    recorded_at=dt.datetime(2026, 6, 1 + i, 12, 0, tzinfo=dt.UTC),
                    weight_kg=70.0 + i,
                    height_cm=175.0,
                    maximum_heart_rate=190,
                    resting_heart_rate=60,
                    aerobic_threshold=140,
                    anaerobic_threshold=170,
                    vo2_max=50 + i,
                    sleep_goal_seconds=28800,
                )
            )
        await session.commit()


class TestPhysicalInfoEndpoint:
    @pytest.mark.asyncio
    async def test_latest_snapshot_with_history(self, app_client) -> None:
        key = await _seed_user_with_key()
        await _seed_physical_info(snapshots=3)

        response = await app_client.get(
            f"/api/v1/users/{USER_ID}/physical-info", headers={"X-API-Key": key}
        )

        assert response.status_code == 200
        payload = response.json()
        # Most recent snapshot first (highest vo2), older ones in history
        assert payload["vo2_max"] == 52
        assert payload["weight_kg"] == 72.0
        assert payload["sleep_goal_hours"] == 8.0
        assert len(payload["history"]) == 2
        assert payload["history"][0]["vo2_max"] == 51

    @pytest.mark.asyncio
    async def test_no_data_returns_null(self, app_client) -> None:
        key = await _seed_user_with_key()

        response = await app_client.get(
            f"/api/v1/users/{USER_ID}/physical-info", headers={"X-API-Key": key}
        )

        assert response.status_code == 200
        assert response.json() is None


class TestMCPBaselinesPhysicalInfo:
    @pytest.mark.asyncio
    async def test_baselines_carries_physical_info(self, app_client) -> None:
        from tests.test_mcp_server import _mcp_client, _seed_user, _user_key

        user_id = await _seed_user(USER_ID)
        await _seed_physical_info()
        raw_key = await _user_key(user_id)

        async with _mcp_client(app_client.app, raw_key) as client:
            result = await client.call_tool("get_baselines", {})

        assert not result.is_error
        info = result.structured_content["physical_info"]
        assert info["vo2_max"] == 50
        assert info["resting_heart_rate_bpm"] == 60
        assert info["anaerobic_threshold_bpm"] == 170
        assert info["sleep_goal_hours"] == 8.0

    @pytest.mark.asyncio
    async def test_baselines_physical_info_null_when_unsynced(self, app_client) -> None:
        from tests.test_mcp_server import _mcp_client, _seed_user, _user_key

        user_id = await _seed_user(USER_ID)
        raw_key = await _user_key(user_id)

        async with _mcp_client(app_client.app, raw_key) as client:
            result = await client.call_tool("get_baselines", {})

        assert not result.is_error
        assert result.structured_content["physical_info"] is None
