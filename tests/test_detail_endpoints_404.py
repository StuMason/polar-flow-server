"""Detail endpoints must 404 on missing data, not return `200 null` (#66).

`GET /users/{id}/activity/{date}` and `GET /users/{id}/exercises/{id}`
returned `None` — HTTP 200 with body `null` — when nothing matched, so
clients couldn't distinguish "no data" from success and the OpenAPI schema
(which advertises an object) lied.
"""

from datetime import UTC, date, datetime, timedelta

import pytest


async def _seed_user_with_key() -> str:
    """Connected user + a real API key; returns the raw key for headers."""
    from polar_flow_server.core.api_keys import create_api_key_for_user
    from polar_flow_server.core.database import async_session_maker
    from polar_flow_server.models.user import User

    async with async_session_maker() as session:
        session.add(
            User(
                id="user-1",
                polar_user_id="polar-1",
                access_token_encrypted="not-a-real-token",
                is_active=True,
            )
        )
        await session.flush()
        _, raw_key = await create_api_key_for_user(
            user_id="polar-1", name="test key", session=session
        )
        await session.commit()
    return raw_key


async def _seed_activity_and_exercise() -> int:
    """One activity for yesterday and one exercise; returns the exercise id."""
    from polar_flow_server.core.database import async_session_maker
    from polar_flow_server.models.activity import Activity
    from polar_flow_server.models.exercise import Exercise

    async with async_session_maker() as session:
        session.add(
            Activity(
                id="activity-1",
                user_id="polar-1",
                date=date.today() - timedelta(days=1),
                steps=12345,
            )
        )
        session.add(
            Exercise(
                id="exercise-1",
                user_id="polar-1",
                polar_exercise_id="polar-ex-1",
                start_time=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
                sport="RUNNING",
            )
        )
        await session.commit()
    return 0


class TestActivityByDate:
    @pytest.mark.asyncio
    async def test_missing_date_is_404(self, app_client):
        key = await _seed_user_with_key()
        response = await app_client.get(
            "/api/v1/users/polar-1/activity/2020-01-01", headers={"X-API-Key": key}
        )
        assert response.status_code == 404
        # Our handler's message, not the router's generic "Not Found"
        assert "No activity data" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_existing_date_is_200_object(self, app_client):
        key = await _seed_user_with_key()
        await _seed_activity_and_exercise()
        target = (date.today() - timedelta(days=1)).isoformat()

        response = await app_client.get(
            f"/api/v1/users/polar-1/activity/{target}", headers={"X-API-Key": key}
        )
        assert response.status_code == 200
        assert response.json()["steps"] == 12345


class TestExerciseDetail:
    @pytest.mark.asyncio
    async def test_missing_exercise_is_404(self, app_client):
        key = await _seed_user_with_key()
        response = await app_client.get(
            "/api/v1/users/polar-1/exercises/no-such-exercise", headers={"X-API-Key": key}
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
        assert "no-such-exercise" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_existing_exercise_is_200_object(self, app_client):
        """Exercise ids are UUID strings; the old {exercise_id:int} route
        could never match a real id from the list endpoint."""
        key = await _seed_user_with_key()
        await _seed_activity_and_exercise()

        response = await app_client.get(
            "/api/v1/users/polar-1/exercises/exercise-1", headers={"X-API-Key": key}
        )
        assert response.status_code == 200
        assert response.json()["sport"] == "RUNNING"
