"""Accessibility markup tests (issue #72).

Tabs lacked aria-controls/tabpanel wiring and keyboard nav, the export
dropdown had no aria-expanded/haspopup and couldn't be dismissed from the
keyboard, the API-key modals had no dialog semantics or focus handling, and
charts had no text alternative. The JS behaviours (arrow keys, focus trap)
live in the templates; these tests pin the semantics the markup must carry.
"""

import re

import pytest


async def _login(app_client, admin_account) -> None:
    response = await app_client.post(
        "/admin/login",
        data={"email": admin_account["email"], "password": admin_account["password"]},
        follow_redirects=False,
    )
    assert response.status_code == 303


async def _dashboard(app_client, admin_account) -> str:
    await _login(app_client, admin_account)
    response = await app_client.get("/admin/dashboard")
    assert response.status_code == 200
    return response.text


async def _settings(app_client, admin_account) -> str:
    await _login(app_client, admin_account)
    response = await app_client.get("/admin/settings")
    assert response.status_code == 200
    return response.text


class TestTabs:
    @pytest.mark.asyncio
    async def test_tablists_are_labelled(self, app_client, admin_account):
        html = await _dashboard(app_client, admin_account)
        assert html.count('role="tablist"') >= 2  # top bar + mobile bottom bar
        assert 'aria-label="Dashboard sections"' in html

    @pytest.mark.asyncio
    async def test_tabs_have_selected_state(self, app_client, admin_account):
        html = await _dashboard(app_client, admin_account)
        assert 'aria-selected="true"' in html
        assert 'aria-selected="false"' in html

    @pytest.mark.asyncio
    async def test_aria_wiring_script_is_present(self, app_client, admin_account):
        """Panel ids/aria-controls are derived in JS (panels are shared
        between tabs) — the wiring function must ship with the page."""
        html = await _dashboard(app_client, admin_account)
        assert "initTabAccessibility" in html
        assert "role', 'tabpanel'" in html.replace('"', "'")
        assert "ArrowRight" in html
        assert "ArrowLeft" in html


class TestExportDropdown:
    @pytest.mark.asyncio
    async def test_button_declares_popup_state(self, app_client, admin_account):
        html = await _dashboard(app_client, admin_account)
        button = re.search(r'<button id="export-btn"[^>]*>', html)
        assert button
        assert 'aria-haspopup="true"' in button.group(0)
        assert 'aria-expanded="false"' in button.group(0)
        assert 'aria-controls="export-menu"' in button.group(0)

    @pytest.mark.asyncio
    async def test_menu_semantics(self, app_client, admin_account):
        html = await _dashboard(app_client, admin_account)
        menu = re.search(r'<div id="export-menu"[^>]*>', html)
        assert menu
        assert 'role="menu"' in menu.group(0)
        assert html.count('role="menuitem"') == 4


class TestCharts:
    @pytest.mark.asyncio
    async def test_every_canvas_has_a_text_alternative(self, app_client, admin_account):
        html = await _dashboard(app_client, admin_account)
        canvases = re.findall(r"<canvas[^>]*>", html)
        assert len(canvases) >= 5  # some are conditional on data being present
        for tag in canvases:
            assert 'role="img"' in tag, tag
            assert "aria-label=" in tag, tag

    def test_every_canvas_in_the_template_has_a_text_alternative(self):
        """Source-level check covering the conditionally rendered ones too."""
        from pathlib import Path

        import polar_flow_server

        template = (
            Path(polar_flow_server.__file__).parent / "templates" / "admin" / "dashboard.html"
        ).read_text()
        for tag in re.findall(r"<canvas[^>]*>", template):
            assert 'role="img"' in tag, tag
            assert "aria-label=" in tag, tag


class TestModals:
    @pytest.mark.asyncio
    async def test_modals_have_dialog_semantics(self, app_client, admin_account):
        html = await _settings(app_client, admin_account)
        for modal_id in ("regenerate-modal", "revoke-modal", "create-key-modal"):
            tag = re.search(rf'<div id="{modal_id}"[^>]*>', html)
            assert tag, modal_id
            assert 'role="dialog"' in tag.group(0), modal_id
            assert 'aria-modal="true"' in tag.group(0), modal_id
            labelled_by = re.search(r'aria-labelledby="([^"]+)"', tag.group(0))
            assert labelled_by, modal_id
            assert f'id="{labelled_by.group(1)}"' in html, modal_id

    @pytest.mark.asyncio
    async def test_focus_management_ships_with_the_page(self, app_client, admin_account):
        html = await _settings(app_client, admin_account)
        assert "modalReturnFocus" in html
        assert "Escape" in html
        assert "shiftKey" in html  # the Tab focus trap
