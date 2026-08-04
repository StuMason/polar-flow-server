"""Concurrent-sync guard tests (issue #63).

Double-clicking "Sync Now" (or a manual sync overlapping a scheduled run)
used to run two full sync cycles concurrently — doubled Polar API usage
and interleaved SyncLogs. APScheduler's max_instances=1 only ever guarded
the scheduled job against itself.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from polar_flow_server.models.sync_log import SyncLog, SyncTrigger
from polar_flow_server.services.sync_guard import (
    SyncInProgressError,
    is_syncing,
    reset_for_tests,
    sync_slot,
)
from polar_flow_server.services.sync_orchestrator import SyncOrchestrator


@pytest.fixture(autouse=True)
def _clean_guard():
    reset_for_tests()
    yield
    reset_for_tests()


class TestSyncSlot:
    def test_second_acquire_raises(self):
        with sync_slot("user-a"):
            assert is_syncing("user-a")
            with pytest.raises(SyncInProgressError):
                with sync_slot("user-a"):
                    pass

    def test_different_users_do_not_collide(self):
        with sync_slot("user-a"), sync_slot("user-b"):
            assert is_syncing("user-a")
            assert is_syncing("user-b")

    def test_slot_released_on_exit(self):
        with sync_slot("user-a"):
            pass
        assert not is_syncing("user-a")
        with sync_slot("user-a"):
            pass

    def test_slot_released_on_exception(self):
        with pytest.raises(RuntimeError), sync_slot("user-a"):
            raise RuntimeError("sync blew up")
        assert not is_syncing("user-a")


class TestOrchestratorGuard:
    @pytest.mark.asyncio
    async def test_refuses_while_slot_held_and_creates_no_synclog(self, async_session):
        """The refusal happens before any SyncLog row exists."""
        from sqlalchemy import func, select

        orchestrator = SyncOrchestrator(async_session)
        with sync_slot("user-a"):
            with pytest.raises(SyncInProgressError):
                await orchestrator.sync_user(
                    user_id="user-a",
                    polar_token="fake",
                    trigger=SyncTrigger.MANUAL,
                )

        count = (await async_session.execute(select(func.count(SyncLog.id)))).scalar()
        assert count == 0

    @pytest.mark.asyncio
    async def test_concurrent_manual_syncs_one_wins(self, async_session):
        """The double-click shape: two syncs at once, exactly one runs."""
        orchestrator = SyncOrchestrator(async_session)
        ran = []

        async def slow_sync(**kwargs):
            await asyncio.sleep(0.05)
            ran.append(kwargs["user_id"])
            return SyncLog(user_id=kwargs["user_id"], job_id="job", trigger="manual")

        with patch.object(orchestrator, "_sync_user_locked", AsyncMock(side_effect=slow_sync)):
            results = await asyncio.gather(
                orchestrator.sync_user(user_id="user-a", polar_token="fake"),
                orchestrator.sync_user(user_id="user-a", polar_token="fake"),
                return_exceptions=True,
            )

        refused = [r for r in results if isinstance(r, SyncInProgressError)]
        completed = [r for r in results if isinstance(r, SyncLog)]
        assert len(refused) == 1
        assert len(completed) == 1
        assert ran == ["user-a"]
        assert not is_syncing("user-a")

    @pytest.mark.asyncio
    async def test_slot_released_after_sync_failure(self, async_session):
        """A failing sync must not wedge the user's slot forever."""
        orchestrator = SyncOrchestrator(async_session)

        with patch.object(
            orchestrator,
            "_sync_user_locked",
            AsyncMock(side_effect=RuntimeError("network down")),
        ):
            with pytest.raises(RuntimeError):
                await orchestrator.sync_user(user_id="user-a", polar_token="fake")

        assert not is_syncing("user-a")


class TestAdminSyncRoute:
    async def _login_with_csrf(self, app_client, admin_account) -> str:
        response = await app_client.get("/admin", follow_redirects=False)
        assert response.status_code in (200, 303)
        token = app_client.cookies.get("csrf_token")
        assert token
        response = await app_client.post(
            "/admin/login",
            data={"email": admin_account["email"], "password": admin_account["password"]},
            follow_redirects=False,
        )
        assert response.status_code == 303
        return token

    @pytest.mark.asyncio
    async def test_sync_now_refused_while_in_flight(self, app_client, admin_account):
        """With the connected user's slot held, Sync Now says so instead of
        starting a second cycle."""
        from polar_flow_server.core.database import async_session_maker
        from polar_flow_server.core.security import token_encryption
        from polar_flow_server.models.user import User

        async with async_session_maker() as session:
            session.add(
                User(
                    id="user-connected",
                    polar_user_id="connected",
                    access_token_encrypted=token_encryption.encrypt("fake-token"),
                    is_active=True,
                )
            )
            await session.commit()

        csrf = await self._login_with_csrf(app_client, admin_account)

        with sync_slot("connected"):
            response = await app_client.post("/admin/sync", headers={"X-CSRF-Token": csrf})

        assert response.status_code == 200
        assert "already running" in response.text
