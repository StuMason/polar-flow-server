"""Client IP detection + login rate limiter attribution tests (issue #51).

Unit tests drive _get_client_ip directly with stub requests; the integration
tests prove the two real-world failure modes end to end:
- behind an untrusted peer, X-Forwarded-For spoofing is ignored
- behind a trusted proxy, distinct clients get distinct rate-limit buckets,
  so an attacker's failures no longer lock out the real admin (lockout DoS)
"""

from types import SimpleNamespace

import pytest

from polar_flow_server.admin import routes
from polar_flow_server.admin.routes import LoginRateLimiter, _get_client_ip
from polar_flow_server.core.config import settings


def _request(peer: str, headers: dict[str, str] | None = None):
    return SimpleNamespace(
        client=SimpleNamespace(host=peer),
        headers={k.lower(): v for k, v in (headers or {}).items()},
    )


@pytest.fixture
def trusted(monkeypatch):
    def set_value(value: str) -> None:
        monkeypatch.setattr(settings, "trusted_proxies", value)

    return set_value


class TestGetClientIp:
    def test_untrusted_peer_ignores_spoofed_xff(self, trusted):
        trusted("127.0.0.1,::1")
        request = _request("203.0.113.9", {"X-Forwarded-For": "10.0.0.1"})
        assert _get_client_ip(request) == "203.0.113.9"

    def test_trusted_localhost_uses_xff(self, trusted):
        trusted("127.0.0.1,::1")
        request = _request("127.0.0.1", {"X-Forwarded-For": "203.0.113.9"})
        assert _get_client_ip(request) == "203.0.113.9"

    def test_client_prepended_junk_is_not_believed(self, trusted):
        """Attacker sends their own XFF; the proxy appends the real address.
        The rightmost untrusted hop wins, never the attacker-chosen first."""
        trusted("127.0.0.1,::1")
        request = _request("127.0.0.1", {"X-Forwarded-For": "6.6.6.6, 203.0.113.9"})
        assert _get_client_ip(request) == "203.0.113.9"

    def test_docker_network_cidr(self, trusted):
        """The shipped deployment: reverse proxy is another container."""
        trusted("127.0.0.1,::1,172.16.0.0/12")
        request = _request("172.18.0.5", {"X-Forwarded-For": "203.0.113.9"})
        assert _get_client_ip(request) == "203.0.113.9"

    def test_chained_trusted_proxies_are_skipped(self, trusted):
        trusted("127.0.0.1,172.16.0.0/12")
        request = _request("172.18.0.5", {"X-Forwarded-For": "203.0.113.9, 172.18.0.2"})
        assert _get_client_ip(request) == "203.0.113.9"

    def test_all_hops_trusted_returns_innermost(self, trusted):
        trusted("127.0.0.1,172.16.0.0/12")
        request = _request("172.18.0.5", {"X-Forwarded-For": "172.18.0.7, 172.18.0.2"})
        assert _get_client_ip(request) == "172.18.0.7"

    def test_x_real_ip_fallback_from_trusted_peer(self, trusted):
        trusted("127.0.0.1")
        request = _request("127.0.0.1", {"X-Real-IP": "203.0.113.9"})
        assert _get_client_ip(request) == "203.0.113.9"

    def test_x_real_ip_ignored_from_untrusted_peer(self, trusted):
        trusted("127.0.0.1")
        request = _request("203.0.113.50", {"X-Real-IP": "10.0.0.1"})
        assert _get_client_ip(request) == "203.0.113.50"

    def test_no_headers_returns_peer(self, trusted):
        trusted("127.0.0.1,::1")
        assert _get_client_ip(_request("127.0.0.1")) == "127.0.0.1"

    def test_ipv6_localhost_trusted(self, trusted):
        trusted("127.0.0.1,::1")
        request = _request("::1", {"X-Forwarded-For": "2001:db8::9"})
        assert _get_client_ip(request) == "2001:db8::9"

    def test_invalid_config_entry_is_not_fatal(self, trusted):
        trusted("127.0.0.1,not-a-cidr/99")
        request = _request("127.0.0.1", {"X-Forwarded-For": "203.0.113.9"})
        assert _get_client_ip(request) == "203.0.113.9"

    def test_literal_hostname_entry(self, trusted):
        """Non-IP entries match the peer string literally (e.g. 'localhost')."""
        trusted("localhost")
        request = _request("localhost", {"X-Forwarded-For": "203.0.113.9"})
        assert _get_client_ip(request) == "203.0.113.9"


class TestLockoutAttribution:
    """End to end: the rate limiter keys on the resolved client IP."""

    @pytest.fixture
    def fresh_limiter(self, monkeypatch):
        limiter = LoginRateLimiter(max_attempts=5, lockout_minutes=15)
        monkeypatch.setattr(routes, "_login_rate_limiter", limiter)
        return limiter

    async def _fail_login(self, app_client, xff: str | None = None):
        headers = {"X-Forwarded-For": xff} if xff else {}
        response = await app_client.post(
            "/admin/login",
            data={"email": "admin@example.com", "password": "wrong-password"},
            headers=headers,
            follow_redirects=False,
        )
        assert response.status_code == 200
        return response

    async def test_untrusted_xff_cannot_dodge_lockout(
        self, app_client, admin_account, fresh_limiter, trusted
    ):
        """Attacker rotating XFF values behind NO trusted proxy still shares
        one bucket (the direct peer) and gets locked out."""
        trusted("")  # no trusted proxies at all
        for i in range(5):
            await self._fail_login(app_client, xff=f"203.0.113.{i}")
        response = await app_client.post(
            "/admin/login",
            data={"email": admin_account["email"], "password": admin_account["password"]},
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert "Too many failed attempts" in response.text

    async def test_trusted_proxy_separates_clients(
        self, app_client, admin_account, fresh_limiter, trusted, monkeypatch
    ):
        """The lockout DoS fix: an attacker's 5 failures no longer lock out
        the real admin arriving from a different IP via the same proxy."""
        # The litestar test transport reports a fixed peer ("testclient");
        # trust it so XFF is honoured, exactly like a real reverse proxy peer.
        trusted("127.0.0.1,::1,testclient")

        for _ in range(5):
            await self._fail_login(app_client, xff="6.6.6.6")

        # Attacker's IP is locked out...
        locked = await app_client.post(
            "/admin/login",
            data={"email": admin_account["email"], "password": admin_account["password"]},
            headers={"X-Forwarded-For": "6.6.6.6"},
            follow_redirects=False,
        )
        assert "Too many failed attempts" in locked.text

        # ...but the admin from a different client IP logs in fine
        response = await app_client.post(
            "/admin/login",
            data={"email": admin_account["email"], "password": admin_account["password"]},
            headers={"X-Forwarded-For": "198.51.100.7"},
            follow_redirects=False,
        )
        assert response.status_code == 303
