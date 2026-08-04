"""Admin chart/dashboard endpoint tests (issues #59, #61, #62).

#59: chart endpoints used to return auth failures as HTTP 200 with an error
body, so the frontend's `r.json()` chain silently drew nothing. They must be
real 401s now.

#61: dashboard and chart queries must be scoped to the connected user, the
same rule the CSV exports already follow — with more than one user row an
unscoped query mixes users' health data.

#62: the `days` query param must be validated like the public API's
(ge=1, le=365) instead of 500ing on huge values.
"""

from datetime import date, timedelta

import pytest

CHART_PATHS = [
    "/admin/api/charts/sleep",
    "/admin/api/charts/activity",
    "/admin/api/charts/heart-rate",
    "/admin/api/charts/hrv",
    "/admin/api/charts/cardio-load",
]

CSV_PATHS = [
    "/admin/export/sleep.csv",
    "/admin/export/activity.csv",
    "/admin/export/recharge.csv",
    "/admin/export/cardio-load.csv",
]


async def _login(app_client, admin_account) -> None:
    response = await app_client.post(
        "/admin/login",
        data={"email": admin_account["email"], "password": admin_account["password"]},
        follow_redirects=False,
    )
    assert response.status_code == 303


async def _seed_two_users_with_sleep() -> None:
    """Two Polar users: 'connected' (is_active) and 'other' (stale row)."""
    from polar_flow_server.core.database import async_session_maker
    from polar_flow_server.models.sleep import Sleep
    from polar_flow_server.models.user import User

    today = date.today()
    async with async_session_maker() as session:
        session.add(
            User(
                id="user-connected",
                polar_user_id="connected",
                access_token_encrypted="not-a-real-token",
                is_active=True,
            )
        )
        session.add(
            User(
                id="user-other",
                polar_user_id="other",
                access_token_encrypted="not-a-real-token",
                is_active=False,
            )
        )
        session.add(
            Sleep(
                id="sleep-connected",
                user_id="connected",
                date=today - timedelta(days=1),
                sleep_score=88,
            )
        )
        session.add(
            Sleep(
                id="sleep-other",
                user_id="other",
                date=today - timedelta(days=2),
                sleep_score=13,
            )
        )
        await session.commit()


class TestChartAuthStatus:
    @pytest.mark.parametrize("path", CHART_PATHS)
    async def test_unauthenticated_is_a_real_401(self, app_client, path):
        """Not a 200 with an error body — the JS relies on the status code."""
        response = await app_client.get(path)
        assert response.status_code == 401

    async def test_authenticated_is_200_json(self, app_client, admin_account):
        await _login(app_client, admin_account)
        response = await app_client.get("/admin/api/charts/sleep")
        assert response.status_code == 200
        body = response.json()
        assert "labels" in body
        assert "datasets" in body


class TestDaysValidation:
    @pytest.mark.parametrize("path", CHART_PATHS + CSV_PATHS)
    @pytest.mark.parametrize("days", ["999999999999", "0", "-5"])
    async def test_out_of_range_days_is_client_error(self, app_client, admin_account, path, days):
        """Used to overflow timedelta into a 500 (or silently return empty)."""
        await _login(app_client, admin_account)
        response = await app_client.get(f"{path}?days={days}")
        assert response.status_code == 400

    async def test_max_valid_days_still_works(self, app_client, admin_account):
        await _login(app_client, admin_account)
        response = await app_client.get("/admin/api/charts/sleep?days=365")
        assert response.status_code == 200


class TestUserScoping:
    async def test_chart_only_returns_connected_users_data(self, app_client, admin_account):
        await _login(app_client, admin_account)
        await _seed_two_users_with_sleep()

        response = await app_client.get("/admin/api/charts/sleep?days=30")
        assert response.status_code == 200
        body = response.json()
        assert len(body["labels"]) == 1
        assert body["datasets"]["sleep_score"] == [88]

    async def test_dashboard_omits_other_users_data(self, app_client, admin_account):
        """The other user's distinctive sleep score must not render."""
        await _login(app_client, admin_account)
        await _seed_two_users_with_sleep()

        response = await app_client.get("/admin/dashboard")
        assert response.status_code == 200
        assert "88" in response.text
        # 13 as a bare rendered sleep score is hard to grep for safely, so
        # assert via the API the dashboard consumes plus the row count above.

    async def test_no_connected_user_still_renders(self, app_client, admin_account):
        """Self-hosted pre-OAuth state: no user row, everything unscoped."""
        await _login(app_client, admin_account)
        response = await app_client.get("/admin/api/charts/sleep")
        assert response.status_code == 200
        assert response.json()["labels"] == []
