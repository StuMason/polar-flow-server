"""Security headers + hardening batch tests (issues #54, #57)."""

import re

from litestar.testing import AsyncTestClient

from polar_flow_server.core.config import settings

EXPECTED_HEADERS = {
    "content-security-policy",
    "x-frame-options",
    "x-content-type-options",
    "referrer-policy",
    "permissions-policy",
}


class TestSecurityHeaders:
    async def test_headers_on_api_response(self, app_client):
        response = await app_client.get("/health")
        for header in EXPECTED_HEADERS:
            assert header in response.headers, f"missing {header}"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]

    async def test_headers_on_admin_response(self, app_client):
        response = await app_client.get("/admin", follow_redirects=False)
        for header in EXPECTED_HEADERS:
            assert header in response.headers, f"missing {header}"

    async def test_csp_allows_the_cdns_the_ui_uses(self, app_client):
        response = await app_client.get("/health")
        csp = response.headers["content-security-policy"]
        for host in ("unpkg.com", "cdn.tailwindcss.com", "cdn.jsdelivr.net"):
            assert host in csp

    async def test_hsts_absent_on_plain_http(self, app_client):
        response = await app_client.get("/health")
        assert "strict-transport-security" not in response.headers

    async def test_hsts_present_when_edge_is_https(self, app_client):
        response = await app_client.get(
            "/health", headers={"X-Forwarded-Proto": "https"}
        )
        assert "strict-transport-security" in response.headers


class TestSecureCookiesFlag:
    async def test_cookies_marked_secure_when_enabled(self, monkeypatch):
        monkeypatch.setattr(settings, "secure_cookies", True)
        from polar_flow_server.app import create_app

        async with AsyncTestClient(app=create_app()) as client:
            response = await client.get("/admin", follow_redirects=False)
            set_cookies = response.headers.get_list("set-cookie")
            csrf = [c for c in set_cookies if c.startswith("csrf_token=")]
            assert csrf and "Secure" in csrf[0]

    async def test_cookies_not_secure_by_default(self, app_client):
        response = await app_client.get("/admin", follow_redirects=False)
        set_cookies = response.headers.get_list("set-cookie")
        csrf = [c for c in set_cookies if c.startswith("csrf_token=")]
        assert csrf and "Secure" not in csrf[0]


class TestSessionCookieName:
    async def test_session_cookie_is_named_session_not_the_secret(
        self, app_client, admin_account
    ):
        """Issue #97: the session secret must never appear as the cookie NAME."""
        response = await app_client.post(
            "/admin/login",
            data={"email": admin_account["email"], "password": admin_account["password"]},
            follow_redirects=False,
        )
        assert response.status_code == 303
        cookie_names = [
            c.split("=", 1)[0] for c in response.headers.get_list("set-cookie")
        ]
        assert "session" in cookie_names
        secret = settings.get_session_secret()
        assert secret not in cookie_names
        assert all(secret not in name for name in cookie_names)


class TestSessionRotation:
    async def test_session_id_rotates_on_login(self, app_client, admin_account):
        """Session fixation: a pre-login session ID must die at login."""
        planted = "a" * 64  # attacker-fixed session ID
        app_client.cookies.set("session", planted)

        response = await app_client.post(
            "/admin/login",
            data={"email": admin_account["email"], "password": admin_account["password"]},
            follow_redirects=False,
        )
        assert response.status_code == 303

        set_cookies = response.headers.get_list("set-cookie")
        session_cookies = [c for c in set_cookies if c.startswith("session=")]
        assert session_cookies, "login response must set a session cookie"
        new_session = session_cookies[0].split(";", 1)[0].split("=", 1)[1]
        assert new_session and new_session != planted
        # avoid a stale duplicate in the client jar for the follow-up requests
        app_client.cookies.delete("session")
        app_client.cookies.set("session", new_session)

        # New ID is a real authenticated session (no OAuth configured yet, so
        # /admin renders the setup page rather than bouncing to /admin/login)
        dashboard = await app_client.get("/admin", follow_redirects=False)
        assert dashboard.status_code == 200

        # …and the planted ID is not authenticated
        app_client.cookies.delete("session")
        app_client.cookies.set("session", planted)
        anon = await app_client.get("/admin", follow_redirects=False)
        assert anon.status_code == 303
        assert anon.headers["location"] == "/admin/login"


class TestScriptBlockEscaping:
    def test_samples_json_cannot_break_out_of_script_block(self):
        """dashboard.html JSON islands escape '</', so '</script>' in any
        string field can't terminate the block (issue #57)."""
        import json
        from pathlib import Path

        from jinja2 import Environment

        template_source = (
            Path("src/polar_flow_server/templates/admin/dashboard.html").read_text()
        )
        expressions = re.findall(r"\{\{ [a-z_.]+samples_json[^}]*\}\}", template_source)
        assert len(expressions) == 2, "expected the two JSON island expressions"

        env = Environment()
        malicious = json.dumps({"v": "</script><script>alert(1)</script>"})
        for expression in expressions:
            normalized = re.sub(r"[a-z_.]+samples_json", "x", expression)
            rendered = env.from_string(normalized).render(x=malicious)
            assert "</script" not in rendered
            # Still exactly the same data once parsed
            assert json.loads(rendered) == json.loads(malicious)
