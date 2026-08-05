"""Tests for exercise detail capture: HR zones, samples, route (issue #76)."""

from __future__ import annotations

import datetime as dt
import json

import pytest
from polar_flow.models.exercise import Exercise as SDKExercise

from polar_flow_server.transformers.exercise import ExerciseTransformer

USER_ID = "polar-1"


def _sdk_exercise(**overrides: object) -> SDKExercise:
    base: dict[str, object] = {
        "id": "2AC312F",
        "upload-time": "2026-06-01T10:40:02.000Z",
        "polar-user": "https://www.polaraccesslink.com/v3/users/1",
        "device": "Polar Vantage V2",
        "start-time": "2026-06-01T08:00:00Z",
        "start-time-utc-offset": 60,
        "duration": "PT1H",
        "calories": 500,
        "distance": 10000.0,
        "heart-rate": {"average": 140, "maximum": 175},
        "training-load": 80.0,
        "sport": "RUNNING",
        "has-route": True,
        "running-index": 51,
        "training-load-pro": {"cardio-load": 1.0, "muscle-load": "NOT_AVAILABLE"},
        "heart_rate_zones": [
            {"index": 1, "lower-limit": 100, "upper-limit": 120, "in-zone": "PT5M"},
            {"index": 2, "lower-limit": 120, "upper-limit": 140, "in-zone": "PT30M"},
        ],
        "samples": [
            {"sample-type": "0", "recording-rate": 5, "data": "120,125,130"},
        ],
        "route": [
            {"latitude": 60.2198, "longitude": 25.1392, "time": "PT0S", "satellites": 4, "fix": 1},
            {"latitude": 60.2199, "longitude": 25.1394, "time": "PT5S", "satellites": 5, "fix": 1},
        ],
    }
    base.update(overrides)
    return SDKExercise.model_validate(base)


class TestExerciseTransformerDetail:
    def test_captures_zones_samples_route(self) -> None:
        result = ExerciseTransformer.transform(_sdk_exercise(), USER_ID)

        zones = json.loads(result["heart_rate_zones_json"])
        assert zones[0] == {
            "index": 1,
            "lower_limit_bpm": 100,
            "upper_limit_bpm": 120,
            "in_zone_seconds": 300,
        }
        assert zones[1]["in_zone_seconds"] == 1800

        samples = json.loads(result["samples_json"])
        assert samples[0]["sample_type"] == "0"
        assert samples[0]["recording_rate"] == 5
        assert samples[0]["values"] == [120.0, 125.0, 130.0]

        route = json.loads(result["route_json"])
        assert len(route) == 2
        assert route[0]["latitude"] == 60.2198
        assert route[1]["satellites"] == 5

    def test_captures_running_index_and_tlp(self) -> None:
        result = ExerciseTransformer.transform(_sdk_exercise(), USER_ID)

        assert result["running_index"] == 51
        tlp = json.loads(result["training_load_pro_json"])
        assert tlp["cardio-load"] == 1.0

    def test_without_detail_stays_null(self) -> None:
        result = ExerciseTransformer.transform(
            _sdk_exercise(
                heart_rate_zones=None,
                samples=None,
                route=None,
                **{"running-index": None, "training-load-pro": None},
            ),
            USER_ID,
        )

        assert result["heart_rate_zones_json"] is None
        assert result["samples_json"] is None
        assert result["route_json"] is None
        assert result["running_index"] is None
        assert result["training_load_pro_json"] is None

    def test_existing_fields_unchanged(self) -> None:
        result = ExerciseTransformer.transform(_sdk_exercise(), USER_ID)

        assert result["polar_exercise_id"] == "2AC312F"
        assert result["sport"] == "RUNNING"
        assert result["calories"] == 500
        assert result["average_heart_rate"] == 140
        assert result["has_route"] is True


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


async def _seed_exercise(*, with_detail: bool) -> None:
    from polar_flow_server.core.database import async_session_maker
    from polar_flow_server.models.exercise import Exercise

    async with async_session_maker() as session:
        session.add(
            Exercise(
                id="exercise-1",
                user_id=USER_ID,
                polar_exercise_id="2AC312F",
                start_time=dt.datetime(2026, 6, 1, 8, 0, tzinfo=dt.UTC),
                sport="RUNNING",
                duration_seconds=3600,
                running_index=51 if with_detail else None,
                heart_rate_zones_json=(
                    json.dumps(
                        [
                            {
                                "index": 1,
                                "lower_limit_bpm": 100,
                                "upper_limit_bpm": 120,
                                "in_zone_seconds": 300,
                            }
                        ]
                    )
                    if with_detail
                    else None
                ),
                samples_json=(
                    json.dumps(
                        [{"sample_type": "0", "recording_rate": 5, "values": [120, 125, 130]}]
                    )
                    if with_detail
                    else None
                ),
                route_json=(
                    json.dumps([{"latitude": 60.2198, "longitude": 25.1392, "time": "PT0S"}])
                    if with_detail
                    else None
                ),
            )
        )
        await session.commit()


class TestExerciseDetailEndpoints:
    @pytest.mark.asyncio
    async def test_detail_carries_zones_and_flags(self, app_client) -> None:
        key = await _seed_user_with_key()
        await _seed_exercise(with_detail=True)

        response = await app_client.get(
            f"/api/v1/users/{USER_ID}/exercises/exercise-1", headers={"X-API-Key": key}
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["running_index"] == 51
        assert payload["heart_rate_zones"][0]["in_zone_seconds"] == 300
        assert payload["has_samples"] is True
        assert payload["has_route_data"] is True

    @pytest.mark.asyncio
    async def test_samples_endpoint(self, app_client) -> None:
        key = await _seed_user_with_key()
        await _seed_exercise(with_detail=True)

        response = await app_client.get(
            f"/api/v1/users/{USER_ID}/exercises/exercise-1/samples", headers={"X-API-Key": key}
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["samples"][0]["values"] == [120, 125, 130]

    @pytest.mark.asyncio
    async def test_route_endpoint(self, app_client) -> None:
        key = await _seed_user_with_key()
        await _seed_exercise(with_detail=True)

        response = await app_client.get(
            f"/api/v1/users/{USER_ID}/exercises/exercise-1/route", headers={"X-API-Key": key}
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["point_count"] == 1
        assert payload["route"][0]["latitude"] == 60.2198

    @pytest.mark.asyncio
    async def test_missing_detail_is_404(self, app_client) -> None:
        key = await _seed_user_with_key()
        await _seed_exercise(with_detail=False)

        for sub in ("samples", "route"):
            response = await app_client.get(
                f"/api/v1/users/{USER_ID}/exercises/exercise-1/{sub}",
                headers={"X-API-Key": key},
            )
            assert response.status_code == 404
            assert "has no" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_mcp_detail_carries_zones(self, app_client) -> None:
        from tests.test_mcp_server import _mcp_client, _seed_user, _user_key

        user_id = await _seed_user(USER_ID)
        await _seed_exercise(with_detail=True)
        raw_key = await _user_key(user_id)

        async with _mcp_client(app_client.app, raw_key) as client:
            result = await client.call_tool("get_exercises", {"exercise_id": "exercise-1"})

        assert not result.is_error
        payload = result.structured_content
        assert payload["running_index"] == 51
        assert payload["heart_rate_zones"][0]["index"] == 1
        assert payload["has_samples"] is True
        assert payload["route_point_count"] == 1
