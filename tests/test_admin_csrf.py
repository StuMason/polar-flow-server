"""CSRF enforcement tests for destructive admin POSTs (issue #53).

These run the real app (middleware included) via the app_client fixture, so
they prove both directions: forged requests are rejected AND the legitimate
frontend flows (HTMX header, hidden form field) still work.
"""

import pytest
from litestar.status_codes import HTTP_200_OK, HTTP_403_FORBIDDEN

DESTRUCTIVE_POSTS = [
    "/admin/sync",
    "/admin/settings/reset-oauth",
    "/admin/api-keys/create",
]


async def _get_csrf_token(app_client) -> str:
    """Fetch /admin so the CSRF middleware sets the cookie.

    Note: paths in the CSRF exclude list (like /admin/login) are skipped by
    the middleware entirely, so they never SET the cookie either. Browsers
    always arrive via /admin (redirect to login/setup), which does set it.
    """
    response = await app_client.get("/admin", follow_redirects=False)
    assert response.status_code in (200, 303)
    token = app_client.cookies.get("csrf_token")
    assert token, "CSRF middleware should set csrf_token cookie on GET /admin"
    return token


async def _login(app_client, admin_account) -> None:
    response = await app_client.post(
        "/admin/login",
        data={"email": admin_account["email"], "password": admin_account["password"]},
        follow_redirects=False,
    )
    assert response.status_code == 303, "login should succeed and redirect"


class TestCsrfRejectsForgedRequests:
    @pytest.mark.parametrize("path", DESTRUCTIVE_POSTS)
    async def test_post_without_token_is_forbidden(self, app_client, path):
        response = await app_client.post(path)
        assert response.status_code == HTTP_403_FORBIDDEN

    @pytest.mark.parametrize("path", DESTRUCTIVE_POSTS)
    async def test_post_with_wrong_token_is_forbidden(self, app_client, path):
        await _get_csrf_token(app_client)
        response = await app_client.post(path, headers={"X-CSRF-Token": "forged-token"})
        assert response.status_code == HTTP_403_FORBIDDEN

    async def test_logged_in_session_alone_is_not_enough(self, app_client, admin_account):
        """The actual CSRF attack shape: valid session, no token."""
        await _get_csrf_token(app_client)
        await _login(app_client, admin_account)
        # Simulate a cross-site request: cookies ride along, header does not
        response = await app_client.post("/admin/sync")
        assert response.status_code == HTTP_403_FORBIDDEN


class TestCsrfAllowsLegitimateRequests:
    async def test_header_token_reaches_handler(self, app_client):
        """X-CSRF-Token header (what base.html's HTMX hook + settings.html send)."""
        token = await _get_csrf_token(app_client)
        response = await app_client.post("/admin/sync", headers={"X-CSRF-Token": token})
        # Handler ran (returns the auth-required partial, not a 403)
        assert response.status_code == HTTP_200_OK
        assert "Authentication required" in response.text

    async def test_form_field_token_reaches_handler(self, app_client):
        """_csrf_token hidden input (what dashboard.html forms send)."""
        token = await _get_csrf_token(app_client)
        response = await app_client.post("/admin/sync", data={"_csrf_token": token})
        assert response.status_code == HTTP_200_OK
        assert "Authentication required" in response.text

    async def test_full_flow_login_then_sync(self, app_client, admin_account):
        """End to end: login, then trigger sync with the token like the UI does."""
        token = await _get_csrf_token(app_client)
        await _login(app_client, admin_account)
        response = await app_client.post("/admin/sync", headers={"X-CSRF-Token": token})
        assert response.status_code == HTTP_200_OK
        # Authenticated: past the auth check, into the no-Polar-user-yet branch
        assert "Authentication required" not in response.text
        assert "No user configured" in response.text

    async def test_api_key_create_with_token(self, app_client, admin_account):
        token = await _get_csrf_token(app_client)
        await _login(app_client, admin_account)
        response = await app_client.post("/admin/api-keys/create", headers={"X-CSRF-Token": token})
        assert response.status_code == HTTP_200_OK
        assert "Authentication required" not in response.text

    async def test_login_stays_excluded(self, app_client):
        """Login must work with no prior CSRF cookie (entry point)."""
        response = await app_client.post(
            "/admin/login",
            data={"email": "nobody@example.com", "password": "wrong"},
            follow_redirects=False,
        )
        assert response.status_code != HTTP_403_FORBIDDEN
