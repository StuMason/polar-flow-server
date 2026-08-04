"""OAuth 2.1 flow tests for the MCP connector sign-in (BASE_URL configured).

Drives the complete dance a real MCP client performs: discovery via
WWW-Authenticate and the .well-known documents, Dynamic Client Registration,
/authorize with PKCE, admin login + consent, code exchange, authenticated
MCP calls with the issued bearer, refresh rotation, and revocation.
"""

import base64
import hashlib
import re
import secrets
from urllib.parse import parse_qs, urlparse

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from polar_flow_server.core.database import async_session_maker

BASE = "https://testserver.local"
REDIRECT_URI = "https://client.example/callback"


@pytest.fixture
async def oauth_app_client(monkeypatch):
    """Full-stack client with OAuth mode on (base_url set before create_app)."""
    from litestar.testing import AsyncTestClient
    from sqlalchemy.exc import OperationalError

    import polar_flow_server.models  # noqa: F401 - register all models on Base
    from polar_flow_server.core.config import settings
    from polar_flow_server.core.database import engine
    from polar_flow_server.models.base import Base

    monkeypatch.setattr(settings, "base_url", BASE)

    from polar_flow_server.app import create_app

    await engine.dispose()
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    except (OperationalError, OSError) as exc:  # pragma: no cover
        pytest.skip(f"Postgres test database unavailable: {exc}")

    try:
        async with AsyncTestClient(app=create_app(), base_url=BASE) as client:
            yield client
    finally:
        await engine.dispose()


async def _seed_admin_and_user(client) -> str:
    """Admin account + connected user; logs the client's session in."""
    from polar_flow_server.core.password import hash_password
    from polar_flow_server.models.admin_user import AdminUser
    from polar_flow_server.models.user import User

    async with async_session_maker() as session:
        session.add(
            AdminUser(
                email="admin@example.com",
                password_hash=hash_password("correct-horse-battery"),
                is_active=True,
            )
        )
        session.add(
            User(
                polar_user_id="oauth-user",
                access_token_encrypted="encrypted-test-token",
                is_active=True,
            )
        )
        await session.commit()

    response = await client.post(
        "/admin/login",
        data={"email": "admin@example.com", "password": "correct-horse-battery"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return "oauth-user"


async def _register_client(client) -> str:
    response = await client.post(
        "/register",
        json={
            "client_name": "Test MCP Client",
            "redirect_uris": [REDIRECT_URI],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["client_id"]


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    return verifier, challenge


async def _authorize_and_consent(client, client_id: str, challenge: str) -> str:
    """Run /authorize -> consent screen -> approve; returns the auth code."""
    response = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "state-123",
            "scope": "health",
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 307), response.text
    consent_url = response.headers["location"]
    assert "/admin/oauth/consent" in consent_url

    page = await client.get(consent_url)
    assert page.status_code == 200
    assert "Test MCP Client" in page.text
    match = re.search(r'name="_csrf_token" value="([^"]+)"', page.text)
    req = re.search(r'name="req" value="([^"]+)"', page.text)
    assert req is not None

    form = {"req": req.group(1), "action": "approve"}
    if match:
        form["_csrf_token"] = match.group(1)
    # Approval renders a self-navigating page, NOT a redirect: a 303 to the
    # client's origin would be blocked by the form-action 'self' CSP.
    approved = await client.post("/admin/oauth/consent", data=form, follow_redirects=False)
    assert approved.status_code == 200, approved.text
    location = _interstitial_target(approved.text)
    assert location.startswith(REDIRECT_URI)
    query = parse_qs(urlparse(location).query)
    assert query["state"] == ["state-123"]
    return query["code"][0]


def _interstitial_target(html_text: str) -> str:
    """Pull the client redirect target out of the consent interstitial."""
    import html as html_mod

    match = re.search(r'<a href="([^"]+)"', html_text)
    assert match, "interstitial has no continue link"
    return html_mod.unescape(match.group(1))


async def _exchange_code(client, client_id: str, code: str, verifier: str) -> dict:
    response = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _bearer_mcp_client(app, token: str) -> Client:
    http_client = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url=BASE,
        headers={"Authorization": f"Bearer {token}"},
    )
    return Client(streamable_http_client(f"{BASE}/mcp", http_client=http_client))


# =============================================================================
# Discovery
# =============================================================================


async def test_protected_resource_metadata(oauth_app_client) -> None:
    response = await oauth_app_client.get("/.well-known/oauth-protected-resource/mcp")
    assert response.status_code == 200
    body = response.json()
    assert body["resource"] == f"{BASE}/mcp"
    assert f"{BASE}/" in body["authorization_servers"] or BASE in body["authorization_servers"]


async def test_authorization_server_metadata(oauth_app_client) -> None:
    response = await oauth_app_client.get("/.well-known/oauth-authorization-server")
    assert response.status_code == 200
    body = response.json()
    assert body["authorization_endpoint"].endswith("/authorize")
    assert body["token_endpoint"].endswith("/token")
    assert body["registration_endpoint"].endswith("/register")
    assert "S256" in body["code_challenge_methods_supported"]


async def test_unauthenticated_mcp_advertises_discovery(oauth_app_client) -> None:
    """No credentials -> 401 with WWW-Authenticate pointing at the resource
    metadata. This header is what makes clients' Connect buttons work."""
    response = await oauth_app_client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "x"})
    assert response.status_code == 401
    www = response.headers.get("www-authenticate", "")
    assert "resource_metadata" in www
    assert "/.well-known/oauth-protected-resource/mcp" in www


# =============================================================================
# The full dance
# =============================================================================


async def test_full_oauth_flow(oauth_app_client) -> None:
    from datetime import date, timedelta

    from polar_flow_server.models.sleep import Sleep

    user_id = await _seed_admin_and_user(oauth_app_client)
    async with async_session_maker() as session:
        session.add(
            Sleep(
                user_id=user_id,
                date=date.today() - timedelta(days=1),
                sleep_score=88,
                total_sleep_seconds=8 * 3600,
            )
        )
        await session.commit()

    client_id = await _register_client(oauth_app_client)
    verifier, challenge = _pkce()
    code = await _authorize_and_consent(oauth_app_client, client_id, challenge)
    tokens = await _exchange_code(oauth_app_client, client_id, code, verifier)
    assert tokens["token_type"].lower() == "bearer"

    # The issued token works for real MCP calls, scoped to the user
    async with _bearer_mcp_client(oauth_app_client.app, tokens["access_token"]) as mcp:
        result = await mcp.call_tool("get_sleep", {"days": 7})
    assert not result.is_error
    assert result.structured_content["records"][0]["sleep_score"] == 88

    # Refresh rotates the pair: new tokens work, old access token is dead
    refreshed = (
        await oauth_app_client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": client_id,
            },
        )
    ).json()
    assert refreshed["access_token"] != tokens["access_token"]

    old = await oauth_app_client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "x"},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert old.status_code == 401

    async with _bearer_mcp_client(oauth_app_client.app, refreshed["access_token"]) as mcp:
        result = await mcp.call_tool("get_sleep", {"days": 7})
    assert not result.is_error

    # Revocation kills the new pair too
    # client_secret must be PRESENT even for public clients: the SDK's
    # RevocationRequest declares it `str | None` with no default
    revoke = await oauth_app_client.post(
        "/revoke",
        data={"token": refreshed["access_token"], "client_id": client_id, "client_secret": ""},
    )
    assert revoke.status_code == 200
    dead = await oauth_app_client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "x"},
        headers={"Authorization": f"Bearer {refreshed['access_token']}"},
    )
    assert dead.status_code == 401


async def test_authorization_code_is_single_use(oauth_app_client) -> None:
    await _seed_admin_and_user(oauth_app_client)
    client_id = await _register_client(oauth_app_client)
    verifier, challenge = _pkce()
    code = await _authorize_and_consent(oauth_app_client, client_id, challenge)
    await _exchange_code(oauth_app_client, client_id, code, verifier)

    replay = await oauth_app_client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert replay.status_code == 400


async def test_consent_deny_bounces_with_error(oauth_app_client) -> None:
    await _seed_admin_and_user(oauth_app_client)
    client_id = await _register_client(oauth_app_client)
    _, challenge = _pkce()

    response = await oauth_app_client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "state-deny",
        },
        follow_redirects=False,
    )
    consent_url = response.headers["location"]
    page = await oauth_app_client.get(consent_url)
    match = re.search(r'name="_csrf_token" value="([^"]+)"', page.text)
    req = re.search(r'name="req" value="([^"]+)"', page.text)
    form = {"req": req.group(1), "action": "deny"}
    if match:
        form["_csrf_token"] = match.group(1)

    denied = await oauth_app_client.post("/admin/oauth/consent", data=form, follow_redirects=False)
    assert denied.status_code == 200
    location = _interstitial_target(denied.text)
    assert location.startswith(REDIRECT_URI)
    assert "error=access_denied" in location
    assert "state=state-deny" in location


async def test_consent_requires_admin_login(oauth_app_client) -> None:
    """Unauthenticated consent hits the login wall with a next redirect."""
    response = await oauth_app_client.get(
        "/admin/oauth/consent", params={"req": "whatever"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert "/admin/login?next=" in response.headers["location"]


async def test_settings_lists_and_revokes_connected_app(oauth_app_client) -> None:
    """Settings shows connector apps and the revoke button kills their tokens."""
    await _seed_admin_and_user(oauth_app_client)
    client_id = await _register_client(oauth_app_client)
    verifier, challenge = _pkce()
    code = await _authorize_and_consent(oauth_app_client, client_id, challenge)
    tokens = await _exchange_code(oauth_app_client, client_id, code, verifier)

    page = await oauth_app_client.get("/admin/settings")
    assert page.status_code == 200
    assert "Test MCP Client" in page.text

    match = re.search(r'name="_csrf_token" value="([^"]+)"', page.text)
    form = {"client_id": client_id}
    if match:
        form["_csrf_token"] = match.group(1)
    revoked = await oauth_app_client.post(
        "/admin/oauth-apps/revoke", data=form, follow_redirects=False
    )
    assert revoked.status_code == 303

    dead = await oauth_app_client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "x"},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert dead.status_code == 401


# =============================================================================
# API keys still work in OAuth mode
# =============================================================================


async def test_api_key_header_still_works(oauth_app_client) -> None:
    from tests.test_mcp_server import _mcp_client, _seed_user, _user_key

    user_id = await _seed_user()
    raw_key = await _user_key(user_id)

    async with _mcp_client(oauth_app_client.app, raw_key) as mcp:
        tools = await mcp.list_tools()
    assert len(tools.tools) == 10


async def test_api_key_as_bearer_still_works(oauth_app_client) -> None:
    from tests.test_mcp_server import _seed_user, _user_key

    user_id = await _seed_user()
    raw_key = await _user_key(user_id)

    async with _bearer_mcp_client(oauth_app_client.app, raw_key) as mcp:
        result = await mcp.call_tool("get_sync_status", {})
    assert not result.is_error
    assert result.structured_content["user_id"] == user_id
