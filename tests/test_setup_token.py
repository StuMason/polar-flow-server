"""First-run setup token tests (issue #52).

Proves the instance can no longer be claimed by whoever visits first: admin
creation requires the token from the server log, and concurrent submits
cannot create two admins.
"""

import asyncio
import logging

import pytest
from sqlalchemy import func, select

from polar_flow_server.core import setup_token as setup_token_module
from polar_flow_server.core.setup_token import (
    announce_setup_token,
    get_setup_token,
    reset_setup_token_for_tests,
    verify_setup_token,
)

VALID_FORM = {
    "email": "owner@example.com",
    "password": "a-strong-password",
    "password_confirm": "a-strong-password",
    "name": "Owner",
}


@pytest.fixture(autouse=True)
def fresh_token():
    reset_setup_token_for_tests()
    yield
    reset_setup_token_for_tests()


async def _admin_count() -> int:
    from polar_flow_server.core.database import async_session_maker
    from polar_flow_server.models.admin_user import AdminUser

    async with async_session_maker() as session:
        result = await session.execute(select(func.count(AdminUser.id)))
        return result.scalar() or 0


class TestTokenPrimitive:
    def test_token_is_stable_within_run(self):
        assert get_setup_token() == get_setup_token()

    def test_verify(self):
        assert verify_setup_token(get_setup_token())
        assert verify_setup_token("  " + get_setup_token() + " ")  # forgiving paste
        assert not verify_setup_token("nope")
        assert not verify_setup_token("")

    def test_announce_logs_the_token(self, caplog):
        with caplog.at_level(logging.WARNING, logger="polar_flow_server.core.setup_token"):
            announce_setup_token()
        assert get_setup_token() in caplog.text
        assert "FIRST-RUN SETUP" in caplog.text


class TestSetupFlow:
    async def test_setup_page_loads_and_announces_token(self, app_client, caplog):
        with caplog.at_level(logging.WARNING, logger="polar_flow_server.core.setup_token"):
            response = await app_client.get("/admin/setup/account")
        assert response.status_code == 200
        assert get_setup_token() in caplog.text
        # The token must never be IN the page itself
        assert get_setup_token() not in response.text

    async def test_submit_without_token_is_rejected(self, app_client):
        response = await app_client.post(
            "/admin/setup/account", data=VALID_FORM, follow_redirects=False
        )
        assert response.status_code == 200
        assert "Invalid setup token" in response.text
        assert await _admin_count() == 0

    async def test_submit_with_wrong_token_is_rejected(self, app_client):
        response = await app_client.post(
            "/admin/setup/account",
            data={**VALID_FORM, "setup_token": "guessed-wrong"},
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert "Invalid setup token" in response.text
        assert await _admin_count() == 0

    async def test_submit_with_token_creates_admin_and_logs_in(self, app_client):
        response = await app_client.post(
            "/admin/setup/account",
            data={**VALID_FORM, "setup_token": get_setup_token()},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/admin"
        assert await _admin_count() == 1

        # Setup is now closed: the form redirects away...
        page = await app_client.get("/admin/setup/account", follow_redirects=False)
        assert page.status_code == 303
        # ...and replaying the token creates nothing
        replay = await app_client.post(
            "/admin/setup/account",
            data={**VALID_FORM, "email": "second@example.com", "setup_token": get_setup_token()},
            follow_redirects=False,
        )
        assert replay.status_code == 303
        assert await _admin_count() == 1

    async def test_concurrent_submits_create_exactly_one_admin(self, app_client):
        """Two racing submits with distinct emails must not both create."""
        token = get_setup_token()

        async def submit(email: str):
            return await app_client.post(
                "/admin/setup/account",
                data={**VALID_FORM, "email": email, "setup_token": token},
                follow_redirects=False,
            )

        results = await asyncio.gather(submit("first@example.com"), submit("second@example.com"))
        assert {r.status_code for r in results} == {303}
        assert await _admin_count() == 1

    async def test_login_and_dashboard_still_work_after_token_setup(self, app_client):
        """Full first-run journey: setup -> logout -> login."""
        await app_client.post(
            "/admin/setup/account",
            data={**VALID_FORM, "setup_token": get_setup_token()},
            follow_redirects=False,
        )
        # Fresh session
        app_client.cookies.clear()
        response = await app_client.post(
            "/admin/login",
            data={"email": VALID_FORM["email"], "password": VALID_FORM["password"]},
            follow_redirects=False,
        )
        assert response.status_code == 303


class TestModuleState:
    def test_reset_generates_new_token(self):
        first = get_setup_token()
        reset_setup_token_for_tests()
        assert get_setup_token() != first
        assert setup_token_module._token is not None
