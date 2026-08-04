"""MCP endpoint tests (issue #80).

Full-stack: the official MCP SDK client speaks streamable HTTP (protocol
revision 2026-07-28) through the real Litestar app via an in-process ASGI
transport, hitting the real /mcp mount, API-key auth, and Postgres. HTTP-level
auth failures are asserted with plain POSTs since the SDK client can't speak
"no credentials".
"""

from datetime import date, timedelta

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from polar_flow_server.core.database import async_session_maker

MCP_URL = "http://testserver.local/mcp"


async def _seed_user(polar_user_id: str = "mcp-user") -> str:
    """Create an active connected user; returns its polar_user_id."""
    from polar_flow_server.models.user import User

    async with async_session_maker() as session:
        session.add(
            User(
                polar_user_id=polar_user_id,
                access_token_encrypted="encrypted-test-token",
                is_active=True,
            )
        )
        await session.commit()
    return polar_user_id


async def _user_key(polar_user_id: str) -> str:
    """Create a user-scoped API key; returns the raw key."""
    from polar_flow_server.core.api_keys import create_api_key_for_user

    async with async_session_maker() as session:
        _, raw_key = await create_api_key_for_user(
            user_id=polar_user_id, name="MCP test key", session=session
        )
        await session.commit()
    return raw_key


async def _service_key() -> str:
    """Create a service-level API key; returns the raw key."""
    from polar_flow_server.core.api_keys import create_service_key

    async with async_session_maker() as session:
        _, raw_key = await create_service_key(name="MCP service key", session=session)
        await session.commit()
    return raw_key


async def _seed_sleep(user_id: str, nights: int) -> None:
    """Seed simple sleep rows, one per night ending yesterday."""
    from polar_flow_server.models.sleep import Sleep

    async with async_session_maker() as session:
        for i in range(nights):
            session.add(
                Sleep(
                    user_id=user_id,
                    date=date.today() - timedelta(days=i + 1),
                    sleep_score=80,
                    total_sleep_seconds=7 * 3600,
                    deep_sleep_seconds=90 * 60,
                    hrv_avg=42.5,
                )
            )
        await session.commit()


def _mcp_client(app, api_key: str | None) -> Client:
    """SDK client wired through the app's ASGI stack (no network)."""
    headers = {"X-API-Key": api_key} if api_key else {}
    http_client = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="http://testserver.local",
        headers=headers,
    )
    return Client(
        streamable_http_client(MCP_URL, http_client=http_client),
        raise_exceptions=True,
    )


# =============================================================================
# HTTP-level auth (plain POSTs - below the MCP protocol layer)
# =============================================================================


async def test_mcp_requires_api_key(app_client) -> None:
    response = await app_client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "x"})
    assert response.status_code == 401
    assert "Missing API key" in response.json()["error"]


async def test_mcp_rejects_invalid_api_key(app_client) -> None:
    response = await app_client.post("/mcp", headers={"X-API-Key": "not-a-key"}, json={})
    assert response.status_code == 401
    assert response.json()["error"] == "Invalid API key"


async def test_mcp_rate_limited_key_gets_429(app_client) -> None:
    from sqlalchemy import update

    from polar_flow_server.models.api_key import APIKey

    user_id = await _seed_user()
    raw_key = await _user_key(user_id)
    async with async_session_maker() as session:
        await session.execute(update(APIKey).values(rate_limit_requests=0))
        await session.commit()

    response = await app_client.post("/mcp", headers={"X-API-Key": raw_key}, json={})
    assert response.status_code == 429
    assert "retry-after" in response.headers


# =============================================================================
# MCP protocol round-trips through the SDK client
# =============================================================================


async def test_tools_list_names_and_order(app_client) -> None:
    user_id = await _seed_user()
    raw_key = await _user_key(user_id)

    async with _mcp_client(app_client.app, raw_key) as client:
        tools = await client.list_tools()

    # Registration order is the wire order; keep stable for client caches.
    assert [t.name for t in tools.tools] == [
        "get_health_insights",
        "get_sleep",
        "get_recovery",
    ]
    sleep_tool = tools.tools[1]
    assert "sleep" in (sleep_tool.description or "").lower()
    assert "days" in sleep_tool.input_schema["properties"]


async def test_get_sleep_scoped_to_key_user(app_client) -> None:
    user_a = await _seed_user("mcp-user-a")
    user_b = await _seed_user("mcp-user-b")
    await _seed_sleep(user_a, nights=3)
    await _seed_sleep(user_b, nights=5)
    raw_key = await _user_key(user_a)

    async with _mcp_client(app_client.app, raw_key) as client:
        result = await client.call_tool("get_sleep", {"days": 30})

    assert not result.is_error
    payload = result.structured_content
    assert payload["count"] == 3  # user A's nights only, never user B's
    record = payload["records"][0]
    assert record["sleep_score"] == 80
    assert record["total_sleep_hours"] == 7.0
    assert record["deep_sleep_hours"] == 1.5
    assert record["hrv_avg_ms"] == 42.5


async def test_user_scoped_key_cannot_read_other_user(app_client) -> None:
    user_a = await _seed_user("mcp-user-a")
    await _seed_user("mcp-user-b")
    raw_key = await _user_key(user_a)

    async with _mcp_client(app_client.app, raw_key) as client:
        result = await client.call_tool("get_sleep", {"user_id": "mcp-user-b"})

    assert result.is_error
    assert "not authorized" in result.content[0].text


async def test_service_key_defaults_to_connected_user(app_client) -> None:
    user_id = await _seed_user()
    await _seed_sleep(user_id, nights=2)
    raw_key = await _service_key()

    async with _mcp_client(app_client.app, raw_key) as client:
        result = await client.call_tool("get_recovery", {"days": 7})

    assert not result.is_error
    payload = result.structured_content
    assert payload["nightly_recharge"] == []
    assert payload["cardio_load"] == []


async def test_no_connected_user_is_a_clean_tool_error(app_client) -> None:
    raw_key = await _service_key()

    async with _mcp_client(app_client.app, raw_key) as client:
        result = await client.call_tool("get_sleep", {})

    assert result.is_error
    assert "No connected Polar user" in result.content[0].text


async def test_get_health_insights_full_payload(app_client) -> None:
    from tests.fixtures.analytics_seed import seed_analytics_data

    user_id = await _seed_user()
    async with async_session_maker() as session:
        await seed_analytics_data(session=session, user_id=user_id, days=35)
    raw_key = await _user_key(user_id)

    async with _mcp_client(app_client.app, raw_key) as client:
        result = await client.call_tool("get_health_insights", {})

    assert not result.is_error
    payload = result.structured_content
    assert payload["user_id"] == user_id
    assert payload["status"] in {"ready", "partial"}
    assert payload["data_age_days"] >= 30
    assert "current_metrics" in payload
    assert "baselines" in payload
    assert isinstance(payload["observations"], list)
    assert isinstance(payload["suggestions"], list)


async def test_get_health_insights_empty_history(app_client) -> None:
    """A brand-new user gets an unavailable-status payload, not an error."""
    user_id = await _seed_user()
    raw_key = await _user_key(user_id)

    async with _mcp_client(app_client.app, raw_key) as client:
        result = await client.call_tool("get_health_insights", {})

    assert not result.is_error
    assert result.structured_content["status"] == "unavailable"


async def test_days_out_of_range_rejected_by_schema(app_client) -> None:
    user_id = await _seed_user()
    raw_key = await _user_key(user_id)

    async with _mcp_client(app_client.app, raw_key) as client:
        result = await client.call_tool("get_sleep", {"days": 4000})

    assert result.is_error


async def test_rest_api_still_works_after_refactor(app_client) -> None:
    """The guard refactor (resolve_key_scope extraction) must not change REST."""
    user_id = await _seed_user()
    await _seed_sleep(user_id, nights=2)
    raw_key = await _user_key(user_id)

    ok = await app_client.get(f"/api/v1/users/{user_id}/sleep", headers={"X-API-Key": raw_key})
    assert ok.status_code == 200
    assert len(ok.json()) == 2
    assert "x-ratelimit-remaining" in ok.headers

    denied = await app_client.get(
        "/api/v1/users/someone-else/sleep", headers={"X-API-Key": raw_key}
    )
    assert denied.status_code == 401
