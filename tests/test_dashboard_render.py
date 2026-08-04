"""Dashboard template render smoke tests (issues #58 and #65).

#58: the SpO2 tiles referenced model fields that don't exist (spo2_avg /
spo2_min), so Jinja's default Undefined silently rendered "--" forever.
These tests render the real dashboard through the real app with a real
SpO2 row and assert the value actually appears — a wrong field name fails.

#65: the post-sync partials emitted hx-swap-oob swaps for elements removed
in the dashboard redesign; the swaps (and the count queries feeding them)
are gone.
"""

from datetime import UTC, datetime

import pytest


async def _login(app_client, admin_account) -> None:
    response = await app_client.post(
        "/admin/login",
        data={"email": admin_account["email"], "password": admin_account["password"]},
        follow_redirects=False,
    )
    assert response.status_code == 303


async def _seed_spo2(blood_oxygen_percent: int = 97, spo2_class: str = "NORMAL") -> None:
    from polar_flow_server.core.database import async_session_maker
    from polar_flow_server.models.spo2 import SpO2

    async with async_session_maker() as session:
        session.add(
            SpO2(
                user_id="test-user",
                device_id="polar-loop-test",
                test_time=datetime(2026, 8, 1, 7, 30, tzinfo=UTC),
                blood_oxygen_percent=blood_oxygen_percent,
                spo2_class=spo2_class,
            )
        )
        await session.commit()


class TestSpO2Tiles:
    async def test_spo2_value_renders_on_dashboard(self, app_client, admin_account):
        """The stat card shows the stored blood oxygen value, not '--'."""
        await _login(app_client, admin_account)
        await _seed_spo2(blood_oxygen_percent=97)

        response = await app_client.get("/admin/dashboard")
        assert response.status_code == 200
        assert "97" in response.text
        # The SpO2 stat card guard is just the row's presence now — with a
        # row seeded there must be no '--' fallback inside the SpO2 card.
        spo2_card = response.text.split('text-fuchsia-700 text-xs font-medium uppercase">SpO2')[1]
        spo2_card = spo2_card.split("</div>")[1]
        assert "--" not in spo2_card
        assert "97" in spo2_card

    async def test_spo2_classification_renders(self, app_client, admin_account):
        """The biosensing panel shows the real spo2_class field."""
        await _login(app_client, admin_account)
        await _seed_spo2(blood_oxygen_percent=91, spo2_class="LOW")

        response = await app_client.get("/admin/dashboard")
        assert response.status_code == 200
        assert "Low" in response.text  # spo2_class | title

    async def test_dashboard_never_references_removed_fields(self):
        """Regression guard: the dead field names must not creep back in."""
        from pathlib import Path

        import polar_flow_server

        template = (
            Path(polar_flow_server.__file__).parent / "templates" / "admin" / "dashboard.html"
        ).read_text()
        assert "spo2_avg" not in template
        assert "spo2_min" not in template


class TestDeadOobSwapsRemoved:
    @pytest.mark.parametrize("partial", ["sync_success.html", "sync_partial.html"])
    def test_partials_have_no_oob_swaps(self, partial):
        """The swap targets were removed in the #44 redesign; the swaps too."""
        from pathlib import Path

        import polar_flow_server

        text = (
            Path(polar_flow_server.__file__).parent / "templates" / "admin" / "partials" / partial
        ).read_text()
        assert "hx-swap-oob" not in text
        assert "sleep_count" not in text

    def test_oob_targets_do_not_exist_anywhere(self):
        """If someone reintroduces the IDs AND the swaps, this documents the pair."""
        from pathlib import Path

        import polar_flow_server

        templates = Path(polar_flow_server.__file__).parent / "templates"
        for page in templates.rglob("*.html"):
            assert 'id="sleep-count"' not in page.read_text()
