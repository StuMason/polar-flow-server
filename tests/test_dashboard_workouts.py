"""Dashboard Recent Workouts card render tests (issue #74).

Exercises were fully synced and API-exposed but the dashboard had no
workout UI at all - "exercise" appeared once, in a tooltip string.
"""

import json
from datetime import UTC, datetime

import pytest


async def _login(app_client, admin_account) -> None:
    response = await app_client.post(
        "/admin/login",
        data={"email": admin_account["email"], "password": admin_account["password"]},
        follow_redirects=False,
    )
    assert response.status_code == 303


async def _seed_exercise(*, with_zones: bool = False) -> None:
    from polar_flow_server.core.database import async_session_maker
    from polar_flow_server.models.exercise import Exercise

    async with async_session_maker() as session:
        session.add(
            Exercise(
                user_id="test-user",
                polar_exercise_id="ex-dash-1",
                start_time=datetime(2026, 8, 1, 18, 30, tzinfo=UTC),
                duration_seconds=3900,
                sport="RUNNING",
                detailed_sport_info="TRAIL_RUNNING",
                distance_meters=8500.0,
                average_heart_rate=148,
                max_heart_rate=176,
                calories=610,
                training_load=95.5,
                running_index=52,
                heart_rate_zones_json=(
                    json.dumps(
                        [
                            {
                                "index": 1,
                                "lower_limit_bpm": 100,
                                "upper_limit_bpm": 120,
                                "in_zone_seconds": 600,
                            },
                            {
                                "index": 2,
                                "lower_limit_bpm": 120,
                                "upper_limit_bpm": 140,
                                "in_zone_seconds": 1800,
                            },
                        ]
                    )
                    if with_zones
                    else None
                ),
                route_json=(
                    json.dumps([{"latitude": 60.0, "longitude": 25.0}]) if with_zones else None
                ),
            )
        )
        await session.commit()


class TestRecentWorkoutsCard:
    @pytest.mark.asyncio
    async def test_workout_renders(self, app_client, admin_account):
        await _login(app_client, admin_account)
        await _seed_exercise()

        response = await app_client.get("/admin/dashboard")

        assert response.status_code == 200
        html = response.text
        assert "Recent Workouts" in html
        assert "Trail Running" in html
        assert "1h 05m" in html
        assert "8.5 km" in html
        assert "148" in html  # avg HR
        assert "95.5" in html  # training load

    @pytest.mark.asyncio
    async def test_zone_bar_renders_when_detail_exists(self, app_client, admin_account):
        await _login(app_client, admin_account)
        await _seed_exercise(with_zones=True)

        response = await app_client.get("/admin/dashboard")

        html = response.text
        # Zone 2 is 1800 of 2400 seconds = 75%
        assert "width: 75.0%" in html
        assert "Zone 2 (120-140 bpm): 30 min" in html
        assert "GPS route recorded" in html

    @pytest.mark.asyncio
    async def test_empty_state(self, app_client, admin_account):
        await _login(app_client, admin_account)

        response = await app_client.get("/admin/dashboard")

        assert "No workouts synced yet" in response.text
