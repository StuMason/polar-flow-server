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
        "get_activity",
        "get_exercises",
        "get_biosensing",
        "get_baselines",
        "get_patterns",
        "trigger_sync",
        "get_sync_status",
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


# =============================================================================
# MCP Apps: the "Today at a glance" card on get_health_insights
# =============================================================================


async def test_insights_tool_carries_apps_card(app_client) -> None:
    """get_health_insights is bound to a ui:// resource that Apps-capable
    hosts render; the card must be fully self-contained (sandbox CSP allows
    inline only) and the tool must stay a normal tool everywhere else."""
    user_id = await _seed_user()
    raw_key = await _user_key(user_id)

    async with _mcp_client(app_client.app, raw_key) as client:
        tools = await client.list_tools()
        insights = next(t for t in tools.tools if t.name == "get_health_insights")
        assert insights.meta == {"ui": {"resourceUri": "ui://polar-flow/insights-card.html"}}

        content = await client.read_resource("ui://polar-flow/insights-card.html")
        card = content.contents[0]

    assert card.mime_type == "text/html;profile=mcp-app"
    html_text = card.text
    assert "Today at a glance" in html_text
    assert "<script>" in html_text and "<style>" in html_text
    # Self-contained: no external fetches - the Apps sandbox would block them
    assert 'src="http' not in html_text
    assert "<link" not in html_text
    # Theme via host variables so light/dark follows the client
    assert "--color-text-primary" in html_text


def test_claude_ui_domain_derivation(monkeypatch) -> None:
    import hashlib

    from polar_flow_server.core.config import settings
    from polar_flow_server.mcp_server.apps_ui import claude_ui_domain

    monkeypatch.setattr(settings, "base_url", None)
    assert claude_ui_domain() is None

    monkeypatch.setattr(settings, "base_url", "https://polar.example.com")
    expected = (
        hashlib.sha256(b"https://polar.example.com/mcp").hexdigest()[:32] + ".claudemcpcontent.com"
    )
    assert claude_ui_domain() == expected


# =============================================================================
# Slice 2 tools: activity, exercises, biosensing, baselines, patterns
# =============================================================================


async def test_get_activity(app_client) -> None:
    from polar_flow_server.models.activity import Activity

    user_id = await _seed_user()
    async with async_session_maker() as session:
        session.add(
            Activity(
                user_id=user_id,
                date=date.today() - timedelta(days=1),
                steps=12000,
                calories_active=450,
                calories_total=2400,
                distance_meters=8500.0,
                active_time_seconds=5400,
                activity_score=95,
            )
        )
        await session.commit()
    raw_key = await _user_key(user_id)

    async with _mcp_client(app_client.app, raw_key) as client:
        result = await client.call_tool("get_activity", {"days": 7})

    assert not result.is_error
    record = result.structured_content["records"][0]
    assert record["steps"] == 12000
    assert record["distance_km"] == 8.5
    assert record["active_minutes"] == 90.0


async def test_get_exercises_list_and_uuid_detail(app_client) -> None:
    """Exercise ids are UUID strings - the detail path must round-trip them
    (the REST route once declared them int and was unreachable, #66)."""
    from datetime import UTC, datetime

    from polar_flow_server.models.exercise import Exercise

    user_id = await _seed_user()
    async with async_session_maker() as session:
        session.add(
            Exercise(
                user_id=user_id,
                polar_exercise_id="polar-ex-1",
                start_time=datetime.now(UTC) - timedelta(days=2),
                sport="RUNNING",
                duration_seconds=1800,
                distance_meters=5000.0,
                calories=350,
                average_heart_rate=150,
                max_heart_rate=175,
                average_power=210,
            )
        )
        await session.commit()
    raw_key = await _user_key(user_id)

    async with _mcp_client(app_client.app, raw_key) as client:
        listing = await client.call_tool("get_exercises", {"days": 7})
        assert not listing.is_error
        records = listing.structured_content["records"]
        assert len(records) == 1
        assert records[0]["sport"] == "RUNNING"
        assert records[0]["duration_minutes"] == 30.0

        detail = await client.call_tool("get_exercises", {"exercise_id": records[0]["id"]})
        assert not detail.is_error
        assert detail.structured_content["polar_exercise_id"] == "polar-ex-1"
        assert detail.structured_content["average_power_watts"] == 210

        missing = await client.call_tool("get_exercises", {"exercise_id": "no-such-id"})
        assert missing.is_error
        assert "not found" in missing.content[0].text


async def test_get_biosensing_spo2(app_client) -> None:
    from datetime import UTC, datetime

    from polar_flow_server.models.spo2 import SpO2

    user_id = await _seed_user()
    async with async_session_maker() as session:
        session.add(
            SpO2(
                user_id=user_id,
                device_id="dev-1",
                test_time=datetime.now(UTC) - timedelta(days=1),
                blood_oxygen_percent=97,
                spo2_class="NORMAL",
            )
        )
        await session.commit()
    raw_key = await _user_key(user_id)

    async with _mcp_client(app_client.app, raw_key) as client:
        result = await client.call_tool("get_biosensing", {"metric": "spo2", "days": 7})

    assert not result.is_error
    payload = result.structured_content
    assert payload["metric"] == "spo2"
    assert payload["records"][0]["blood_oxygen_percent"] == 97
    assert payload["records"][0]["spo2_class"] == "NORMAL"


async def test_get_biosensing_rejects_unknown_metric(app_client) -> None:
    user_id = await _seed_user()
    raw_key = await _user_key(user_id)

    async with _mcp_client(app_client.app, raw_key) as client:
        result = await client.call_tool("get_biosensing", {"metric": "blood_pressure"})

    assert result.is_error


async def test_get_baselines_and_patterns_after_analysis(app_client) -> None:
    from tests.fixtures.analytics_seed import seed_analytics_data

    user_id = await _seed_user()
    async with async_session_maker() as session:
        await seed_analytics_data(session=session, user_id=user_id, days=35)
    async with async_session_maker() as session:
        from polar_flow_server.services.baseline import BaselineService
        from polar_flow_server.services.pattern import PatternService

        await BaselineService(session).calculate_all_baselines(user_id)
        await PatternService(session).detect_all_patterns(user_id)
    raw_key = await _user_key(user_id)

    async with _mcp_client(app_client.app, raw_key) as client:
        baselines = await client.call_tool("get_baselines", {})
        patterns = await client.call_tool("get_patterns", {})

    assert not baselines.is_error
    metric_names = {b["metric_name"] for b in baselines.structured_content["baselines"]}
    assert "hrv_rmssd" in metric_names
    first = baselines.structured_content["baselines"][0]
    assert first["lower_bound"] is not None
    assert first["sample_count"] > 0

    assert not patterns.is_error
    payload = patterns.structured_content
    pattern_names = {p["pattern_name"] for p in payload["patterns"]}
    assert "hrv_trend" in pattern_names
    assert "anomaly_count" in payload


# =============================================================================
# Sync tools: trigger (background) + status (poll)
# =============================================================================


async def _seed_syncable_user(polar_user_id: str = "mcp-user") -> str:
    """User whose stored token actually decrypts (trigger_sync needs it)."""
    from polar_flow_server.core.security import token_encryption
    from polar_flow_server.models.user import User

    async with async_session_maker() as session:
        session.add(
            User(
                polar_user_id=polar_user_id,
                access_token_encrypted=token_encryption.encrypt("fake-polar-token"),
                is_active=True,
            )
        )
        await session.commit()
    return polar_user_id


async def test_trigger_sync_starts_and_status_shows_result(app_client, monkeypatch) -> None:
    import asyncio

    from polar_flow_server.models.sync_log import SyncLog, SyncTrigger
    from polar_flow_server.services.sync_orchestrator import SyncOrchestrator

    async def fake_sync_user(self, user_id, polar_token, trigger=SyncTrigger.MANUAL, **kwargs):
        from datetime import UTC, datetime

        assert polar_token == "fake-polar-token"  # decrypted from the stored token
        async with async_session_maker() as session:
            # started_at is a server default - set it explicitly so
            # complete_success can compute duration before the flush
            log = SyncLog(
                user_id=user_id,
                job_id="test-job",
                trigger=trigger.value,
                started_at=datetime.now(UTC),
            )
            log.complete_success(records={"sleep": 3}, api_calls=13)
            session.add(log)
            await session.commit()
        return log

    monkeypatch.setattr(SyncOrchestrator, "sync_user", fake_sync_user)

    user_id = await _seed_syncable_user()
    raw_key = await _user_key(user_id)

    async with _mcp_client(app_client.app, raw_key) as client:
        started = await client.call_tool("trigger_sync", {})
        assert not started.is_error
        assert started.structured_content["status"] == "started"

        # Poll get_sync_status until the background sync lands (fake = fast)
        last_sync = None
        for _ in range(50):
            status = await client.call_tool("get_sync_status", {})
            assert not status.is_error
            last_sync = status.structured_content["last_sync"]
            if last_sync is not None:
                break
            await asyncio.sleep(0.1)

    assert last_sync is not None, "background sync never recorded a SyncLog"
    assert last_sync["status"] == "success"
    assert last_sync["trigger"] == "manual"
    assert last_sync["records_synced"] == {"sleep": 3}


async def test_trigger_sync_reports_already_running(app_client) -> None:
    from polar_flow_server.services.sync_guard import sync_slot

    user_id = await _seed_syncable_user()
    raw_key = await _user_key(user_id)

    async with _mcp_client(app_client.app, raw_key) as client:
        with sync_slot(user_id):
            result = await client.call_tool("trigger_sync", {})

    assert not result.is_error
    assert result.structured_content["status"] == "already_running"


async def test_trigger_sync_honours_rate_limit_cooldown(app_client) -> None:
    from polar_flow_server.services.sync_orchestrator import shared_rate_limit_tracker

    user_id = await _seed_syncable_user()
    raw_key = await _user_key(user_id)

    shared_rate_limit_tracker.note_rate_limited(retry_after_seconds=600)
    try:
        async with _mcp_client(app_client.app, raw_key) as client:
            result = await client.call_tool("trigger_sync", {})
            status = await client.call_tool("get_sync_status", {})
    finally:
        shared_rate_limit_tracker.rate_limited_until = None  # module singleton

    assert not result.is_error
    assert result.structured_content["status"] == "rate_limited"
    assert result.structured_content["retry_after_seconds"] > 0
    assert status.structured_content["polar_rate_limit"]["rate_limited_until"] is not None


async def test_get_sync_status_before_any_sync(app_client) -> None:
    user_id = await _seed_user()
    raw_key = await _user_key(user_id)

    async with _mcp_client(app_client.app, raw_key) as client:
        result = await client.call_tool("get_sync_status", {})

    assert not result.is_error
    payload = result.structured_content
    assert payload["currently_syncing"] is False
    assert payload["last_sync"] is None


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
