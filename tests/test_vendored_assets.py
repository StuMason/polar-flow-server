"""Vendored frontend assets (issue #71).

The admin UI depended on the Tailwind Play CDN (explicitly not-for-production,
un-SRI-pinnable, recompiles CSS in-browser per load) plus CDN htmx/Chart.js.
A LAN/offline install rendered unstyled with no charts, and a CDN compromise
would have executed arbitrary JS in the admin panel. Everything is served
from /static now.
"""

from pathlib import Path

import pytest

import polar_flow_server

TEMPLATES = Path(polar_flow_server.__file__).parent / "templates"
VENDOR = Path(polar_flow_server.__file__).parent / "static" / "vendor"


class TestStaticServing:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("path", "content_type", "sentinel"),
        [
            ("/static/vendor/htmx.min.js", "javascript", "htmx"),
            ("/static/vendor/chart.umd.js", "javascript", "Chart"),
            ("/static/vendor/tailwind.css", "css", "tailwind"),
        ],
    )
    async def test_asset_is_served(self, app_client, path, content_type, sentinel):
        response = await app_client.get(path)
        assert response.status_code == 200
        assert content_type in response.headers["content-type"]
        assert sentinel in response.text[:2000]


class TestNoCdnReferences:
    def test_templates_reference_no_app_asset_cdns(self):
        """App assets must come from /static. (The /schema doc UIs still load
        from CDNs — that's Litestar's own rendering, covered by the CSP.)"""
        for page in TEMPLATES.rglob("*.html"):
            text = page.read_text()
            assert "cdn.tailwindcss.com" not in text, page.name
            assert "unpkg.com/htmx" not in text, page.name
            assert "jsdelivr.net/npm/chart.js" not in text, page.name
            assert "chartjs-adapter-date-fns" not in text, page.name

    def test_csp_no_longer_allows_tailwind_cdn(self):
        from polar_flow_server.middleware.security_headers import _CSP

        assert "cdn.tailwindcss.com" not in _CSP


class TestBuiltCss:
    def test_sentinel_classes_are_present(self):
        """The build must actually cover the templates' classes; a stale or
        empty build would ship an unstyled dashboard."""
        css = (VENDOR / "tailwind.css").read_text()
        # (htmx-indicator styles are injected by htmx itself, not Tailwind)
        for cls in (".max-w-7xl", ".bg-gray-50", ".animate-spin", ".grid-cols-2"):
            assert cls in css, f"{cls} missing - rebuild per docs/frontend-assets.md"

    def test_css_is_not_trivially_small(self):
        assert (VENDOR / "tailwind.css").stat().st_size > 10_000
