"""Settings-page display fixes (issues #69, #73, and #68's server side).

#69: the Sync Configuration card hardcoded "1 hour" / "30 days" whatever
SYNC_INTERVAL_MINUTES / SYNC_DAYS_LOOKBACK actually were.
#73: the revoke-key modal claimed restoring access needs OAuth (it needs a
new API key), and scheduler timestamps rendered raw isoformat.
#68 (server side): stored-UTC timestamps rendered with no timezone label.
All timestamp rendering now goes through one `utc_dt` Jinja filter.
"""

from datetime import UTC, datetime

import pytest

from polar_flow_server.app import format_utc


class TestUtcDtFilter:
    def test_datetime_is_labelled_utc(self):
        value = datetime(2026, 8, 4, 12, 30, tzinfo=UTC)
        assert format_utc(value) == "2026-08-04 12:30 UTC"

    def test_custom_format(self):
        value = datetime(2026, 8, 4, 12, 30, tzinfo=UTC)
        assert format_utc(value, "%m/%d %H:%M") == "08/04 12:30 UTC"

    def test_isoformat_string_is_parsed(self):
        assert format_utc("2026-08-04T12:30:45.123456+00:00") == "2026-08-04 12:30 UTC"

    def test_none_is_dashes(self):
        assert format_utc(None) == "--"

    def test_unparseable_string_passes_through(self):
        assert format_utc("soon") == "soon"


async def _login(app_client, admin_account) -> None:
    response = await app_client.post(
        "/admin/login",
        data={"email": admin_account["email"], "password": admin_account["password"]},
        follow_redirects=False,
    )
    assert response.status_code == 303


class TestSettingsPage:
    @pytest.mark.asyncio
    async def test_sync_configuration_reflects_settings(
        self, app_client, admin_account, monkeypatch
    ):
        """Tuned env values must show up, not the old hardcoded copy."""
        from polar_flow_server.core.config import settings

        monkeypatch.setattr(settings, "sync_interval_minutes", 90)
        monkeypatch.setattr(settings, "sync_days_lookback", 14)

        await _login(app_client, admin_account)
        response = await app_client.get("/admin/settings")
        assert response.status_code == 200
        assert "90 minutes" in response.text
        assert "14 days" in response.text

    @pytest.mark.asyncio
    async def test_default_interval_renders_as_hours(self, app_client, admin_account):
        """60-minute default still reads '1 hour', but derived, not hardcoded."""
        await _login(app_client, admin_account)
        response = await app_client.get("/admin/settings")
        assert response.status_code == 200
        assert "1 hour" in response.text
        assert "30 days" in response.text

    @pytest.mark.asyncio
    async def test_revoke_copy_no_longer_mentions_oauth(self, app_client, admin_account):
        await _login(app_client, admin_account)
        response = await app_client.get("/admin/settings")
        assert response.status_code == 200
        assert "reconnect via OAuth" not in response.text
        assert "create a new API key" in response.text

    @pytest.mark.asyncio
    async def test_sync_log_timestamps_are_utc_labelled(self, app_client, admin_account):
        """A seeded sync log's started_at renders through the utc_dt filter."""
        from polar_flow_server.core.database import async_session_maker
        from polar_flow_server.models.sync_log import SyncLog

        async with async_session_maker() as session:
            session.add(
                SyncLog(
                    user_id="u1",
                    job_id="job-1",
                    trigger="manual",
                    started_at=datetime(2026, 8, 4, 9, 15, tzinfo=UTC),
                )
            )
            await session.commit()

        await _login(app_client, admin_account)
        response = await app_client.get("/admin/settings")
        assert response.status_code == 200
        assert "08/04 09:15 UTC" in response.text
