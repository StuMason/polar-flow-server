"""Stale-data handling on the dashboard (issues #70 and #68's client side).

#70: stat tiles show `latest_*` records — after a sync gap they presented
4-day-old numbers as if they were today's, and "Today's Readiness" blended
whatever was latest per metric regardless of freshness. Tiles now carry an
"Nd ago" badge and the readiness calculation excludes metrics older than 48h.

#68 (client side): formatDateLabel parsed date-only strings as UTC midnight,
shifting every chart label a day west of UTC. Regression-guarded here; the
behavioural fix lives in the template JS.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from polar_flow_server.app import days_old


class TestDaysOldFilter:
    def test_today_is_zero(self):
        assert days_old(date.today()) == 0

    def test_dates_and_datetimes(self):
        assert days_old(date.today() - timedelta(days=3)) == 3
        assert days_old(datetime.now(UTC) - timedelta(days=2)) == 2


class TestReadinessFreshnessGate:
    def _sleep(self, days_ago: int, score: int = 30):
        from polar_flow_server.models.sleep import Sleep

        return Sleep(
            id=f"s-{days_ago}",
            user_id="u",
            date=date.today() - timedelta(days=days_ago),
            sleep_score=score,
        )

    def test_fresh_sleep_counts(self):
        from polar_flow_server.admin.routes import _calculate_recovery_status

        status = _calculate_recovery_status(
            sleep=self._sleep(0, score=30), recharge=None, cardio=None
        )
        assert any("Poor sleep" in r for r in status["recommendations"])

    def test_stale_sleep_is_excluded(self):
        """Four-day-old poor sleep must not drive today's advice."""
        from polar_flow_server.admin.routes import _calculate_recovery_status

        status = _calculate_recovery_status(
            sleep=self._sleep(4, score=30), recharge=None, cardio=None
        )
        assert not any("Poor sleep" in r for r in status["recommendations"])

    def test_two_day_old_sleep_still_counts(self):
        """48h is the cutoff — within it, data participates."""
        from polar_flow_server.admin.routes import _calculate_recovery_status

        status = _calculate_recovery_status(
            sleep=self._sleep(1, score=30), recharge=None, cardio=None
        )
        assert any("Poor sleep" in r for r in status["recommendations"])


async def _login(app_client, admin_account) -> None:
    response = await app_client.post(
        "/admin/login",
        data={"email": admin_account["email"], "password": admin_account["password"]},
        follow_redirects=False,
    )
    assert response.status_code == 303


class TestTileAgeBadges:
    @pytest.mark.asyncio
    async def test_stale_tile_shows_age_badge(self, app_client, admin_account):
        from polar_flow_server.core.database import async_session_maker
        from polar_flow_server.models.activity import Activity

        async with async_session_maker() as session:
            session.add(
                Activity(
                    id="a-old",
                    user_id="u",
                    date=date.today() - timedelta(days=4),
                    steps=9999,
                )
            )
            await session.commit()

        await _login(app_client, admin_account)
        response = await app_client.get("/admin/dashboard")
        assert response.status_code == 200
        assert "9,999" in response.text
        assert "4d ago" in response.text

    @pytest.mark.asyncio
    async def test_todays_data_has_no_badge(self, app_client, admin_account):
        from polar_flow_server.core.database import async_session_maker
        from polar_flow_server.models.activity import Activity

        async with async_session_maker() as session:
            session.add(Activity(id="a-now", user_id="u", date=date.today(), steps=1234))
            await session.commit()

        await _login(app_client, admin_account)
        response = await app_client.get("/admin/dashboard")
        assert response.status_code == 200
        assert "1,234" in response.text
        assert "d ago" not in response.text


class TestChartLabelParsing:
    def test_no_utc_midnight_date_parsing_in_template(self):
        """new Date('YYYY-MM-DD') parses as UTC midnight — the day-shift bug.
        The label formatter must build the date from parts instead."""
        from pathlib import Path

        import polar_flow_server

        template = (
            Path(polar_flow_server.__file__).parent / "templates" / "admin" / "dashboard.html"
        ).read_text()
        assert "new Date(dateStr)" not in template
        assert "toLocaleDateString('en-US'" not in template
