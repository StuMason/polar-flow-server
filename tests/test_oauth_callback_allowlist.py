"""SaaS OAuth callback allowlist + error hygiene tests (issue #56)."""

import pytest

from polar_flow_server.api.keys import _validate_callback_url
from polar_flow_server.core.config import settings


@pytest.fixture
def allow(monkeypatch):
    def set_value(value: str | None) -> None:
        monkeypatch.setattr(settings, "oauth_allowed_callback_origins", value)

    return set_value


class TestCallbackAllowlist:
    def test_rejected_when_no_origins_registered(self, allow):
        allow(None)
        ok, message = _validate_callback_url("https://app.example.com/callback")
        assert not ok
        assert "OAUTH_ALLOWED_CALLBACK_ORIGINS" in message

    def test_registered_origin_passes_any_path(self, allow):
        allow("https://app.example.com")
        for path in ("/callback", "/oauth/done", "/x?y=z"):
            ok, message = _validate_callback_url(f"https://app.example.com{path}")
            assert ok, message

    def test_unregistered_origin_rejected(self, allow):
        allow("https://app.example.com")
        ok, message = _validate_callback_url("https://evil.example.com/callback")
        assert not ok
        assert "not registered" in message

    def test_subdomain_is_a_different_origin(self, allow):
        allow("https://app.example.com")
        ok, _ = _validate_callback_url("https://app.example.com.evil.net/cb")
        assert not ok
        ok, _ = _validate_callback_url("https://sub.app.example.com/cb")
        assert not ok

    def test_port_must_match(self, allow):
        allow("https://app.example.com:8443")
        assert _validate_callback_url("https://app.example.com:8443/cb")[0]
        assert not _validate_callback_url("https://app.example.com/cb")[0]

    def test_host_case_insensitive_and_trailing_slash_forgiven(self, allow):
        allow("https://App.Example.com/, https://other.example.com")
        assert _validate_callback_url("https://app.example.com/cb")[0]
        assert _validate_callback_url("https://other.example.com/cb")[0]

    def test_scheme_is_part_of_the_origin(self, allow, monkeypatch):
        # http://localhost is dev-permitted at the scheme layer, but the
        # https origin registration must not cover it
        monkeypatch.setattr(settings, "base_url", None)
        allow("https://localhost:8080")
        assert not _validate_callback_url("http://localhost:8080/cb")[0]
        allow("http://localhost:8080")
        assert _validate_callback_url("http://localhost:8080/cb")[0]

    def test_preexisting_shape_checks_still_apply(self, allow):
        allow("https://app.example.com")
        assert not _validate_callback_url("x" * 3000)[0]
        assert not _validate_callback_url("ftp://app.example.com/cb")[0]
        assert not _validate_callback_url("not a url")[0]


class TestOAuthStartEndpoint:
    async def test_start_rejects_unregistered_callback(self, app_client, allow):
        allow("https://app.example.com")
        response = await app_client.get(
            "/oauth/start",
            params={"callback_url": "https://evil.example.com/cb"},
            follow_redirects=False,
        )
        assert response.status_code == 401

    async def test_start_with_registered_callback_reaches_config_check(self, app_client, allow):
        """Past validation, the next failure is unconfigured OAuth creds (404)
        — proving the allowlist let the registered origin through."""
        allow("https://app.example.com")
        response = await app_client.get(
            "/oauth/start",
            params={"callback_url": "https://app.example.com/cb"},
            follow_redirects=False,
        )
        assert response.status_code == 404


class TestCallbackErrorHygiene:
    async def test_exception_text_never_reaches_the_callback(self, app_client, allow, monkeypatch):
        """Force the token exchange to blow up with a sensitive message and
        assert only the generic 'server_error' token is redirected."""
        import httpx as httpx_module

        from polar_flow_server.api.keys import _saas_oauth_states
        from polar_flow_server.core.database import async_session_maker
        from polar_flow_server.core.security import token_encryption
        from polar_flow_server.models.settings import AppSettings

        async with async_session_maker() as db:
            db.add(
                AppSettings(
                    id=1,
                    polar_client_id="client-id",
                    polar_client_secret_encrypted=token_encryption.encrypt("shh"),
                )
            )
            await db.commit()

        secret_detail = "password authentication failed for host db-internal-9000"

        class ExplodingClient:
            async def __aenter__(self):
                raise RuntimeError(secret_detail)

            async def __aexit__(self, *args):
                return False

        monkeypatch.setattr(httpx_module, "AsyncClient", ExplodingClient)

        await _saas_oauth_states.set("test-state", "https://app.example.com/cb", None)
        response = await app_client.get(
            "/oauth/callback",
            params={"code": "fake-code", "state": "test-state"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        location = response.headers["location"]
        assert location.startswith("https://app.example.com/cb?")
        assert "error=server_error" in location
        assert "password" not in location
        assert "db-internal" not in location
