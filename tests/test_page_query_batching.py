"""Page-load query batching (issue #87).

admin_settings issued ~22 sequential queries per view (15 of them bare
COUNTs) and admin_dashboard ~18 — on a remote Postgres that's ~20x RTT per
page. Settings now folds all counts into one SELECT of scalar subqueries;
the dashboard builds its independent lookups up front and executes them
concurrently on short-lived sessions.

These tests count real statements hitting the engine during a page view so
a regression back to per-metric queries (or a new N+1) fails loudly.
"""

import pytest
from sqlalchemy import event


async def _login(app_client, admin_account) -> None:
    response = await app_client.post(
        "/admin/login",
        data={"email": admin_account["email"], "password": admin_account["password"]},
        follow_redirects=False,
    )
    assert response.status_code == 303


class _QueryCounter:
    def __init__(self):
        self.statements: list[str] = []

    def __call__(self, conn, cursor, statement, parameters, context, executemany):
        if statement.strip().upper().startswith("SELECT"):
            self.statements.append(statement)


async def _count_selects_during(app_client, path: str) -> int:
    from polar_flow_server.core.database import engine

    counter = _QueryCounter()
    event.listen(engine.sync_engine, "before_cursor_execute", counter)
    try:
        response = await app_client.get(path)
        assert response.status_code == 200
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", counter)
    return len(counter.statements)


class TestSettingsPageQueries:
    @pytest.mark.asyncio
    async def test_counts_are_one_round_trip(self, app_client, admin_account):
        """Was ~22 SELECTs (15 of them individual COUNTs); the counts are a
        single statement now. Budget: app_settings + user + api_keys +
        combined counts + sync logs + sync stats = 6, plus slack."""
        await _login(app_client, admin_account)
        n = await _count_selects_during(app_client, "/admin/settings")
        assert n <= 8, f"settings page ran {n} SELECTs - counts have unbatched"


class TestDashboardPageQueries:
    @pytest.mark.asyncio
    async def test_no_query_explosion(self, app_client, admin_account):
        """The dashboard's lookups run concurrently, so RTT stacking is gone;
        this guards the query COUNT against a regression/N+1 creep.
        Was 20 sequential; still concurrent - the budget covers the fixed
        per-section lookups (workouts #74 + ECG/body-temp/bedtime #78), not
        per-row queries."""
        await _login(app_client, admin_account)
        n = await _count_selects_during(app_client, "/admin/dashboard")
        assert n <= 22, f"dashboard ran {n} SELECTs - something added per-row queries"

    @pytest.mark.asyncio
    async def test_dashboard_still_renders_all_sections(self, app_client, admin_account):
        """Belt and braces on the restructure: seeded data still shows up."""
        from datetime import date, timedelta

        from polar_flow_server.core.database import async_session_maker
        from polar_flow_server.models.activity import Activity
        from polar_flow_server.models.sleep import Sleep

        async with async_session_maker() as session:
            session.add(
                Sleep(
                    id="s1",
                    user_id="u",
                    date=date.today() - timedelta(days=1),
                    sleep_score=88,
                )
            )
            session.add(Activity(id="a1", user_id="u", date=date.today(), steps=4321))
            await session.commit()

        await _login(app_client, admin_account)
        response = await app_client.get("/admin/dashboard")
        assert response.status_code == 200
        assert "88" in response.text
        assert "4,321" in response.text
