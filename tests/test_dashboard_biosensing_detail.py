"""Dashboard biosensing detail render tests (issue #78).

ECG waveforms, body temperature periods, SleepWise alertness curves and
circadian bedtime windows were synced and stored, then died in the DB -
the dashboard showed only counts and single latest grades.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest


async def _login(app_client, admin_account) -> None:
    response = await app_client.post(
        "/admin/login",
        data={"email": admin_account["email"], "password": admin_account["password"]},
        follow_redirects=False,
    )
    assert response.status_code == 303


async def _seed_biosensing_detail() -> None:
    from polar_flow_server.core.database import async_session_maker
    from polar_flow_server.models.ecg import ECG
    from polar_flow_server.models.sleepwise_alertness import SleepWiseAlertness
    from polar_flow_server.models.sleepwise_bedtime import SleepWiseBedtime
    from polar_flow_server.models.temperature import BodyTemperature

    now = datetime.now(UTC)
    async with async_session_maker() as session:
        session.add(
            ECG(
                user_id="test-user",
                device_id="dev-1",
                test_time=now - timedelta(days=1),
                avg_heart_rate=54,
                hrv_ms=46.3,
                hrv_level="NORMAL",
                rri_ms=1080.0,
                ptt_systolic_ms=182.4,
                ptt_diastolic_ms=241.9,
                sample_count=3,
                samples_json=json.dumps(
                    [
                        {"time_ms": 0, "amplitude_mv": 0.02},
                        {"time_ms": 8, "amplitude_mv": 1.1},
                        {"time_ms": 16, "amplitude_mv": -0.04},
                    ]
                ),
                duration_seconds=30.0,
            )
        )
        session.add(
            BodyTemperature(
                user_id="test-user",
                device_id="dev-1",
                start_time=now - timedelta(days=1, hours=8),
                end_time=now - timedelta(days=1, hours=1),
                measurement_type="TM_CORE_TEMPERATURE",
                sensor_location="SL_DISTAL",
                temp_min=36.31,
                temp_max=36.92,
                temp_avg=36.58,
                sample_count=420,
            )
        )
        day = now.replace(hour=7, minute=0, second=0, microsecond=0)
        session.add(
            SleepWiseAlertness(
                user_id="test-user",
                grade=3.6,
                grade_validity_seconds=57600,
                grade_type="GRADE_TYPE_NORMAL",
                grade_classification="ALERTNESS_GRADE_GOOD",
                validity="VALIDITY_VALID",
                sleep_inertia="SLEEP_INERTIA_MILD",
                sleep_type="SLEEP_TYPE_PRIMARY",
                result_type="ALERTNESS_TYPE_HISTORY",
                period_start_time=day,
                period_end_time=day + timedelta(hours=16),
                sleep_period_start_time=day - timedelta(hours=8),
                sleep_period_end_time=day,
                sleep_timezone_offset_minutes=60,
                hourly_data_json=json.dumps(
                    [
                        {
                            "validity": "VALIDITY_VALID",
                            "alertness_level": 3,
                            "start_time": "2026-08-05T09:00:00",
                            "end_time": "2026-08-05T10:00:00",
                        }
                    ]
                ),
            )
        )
        tonight = now.replace(hour=22, minute=45, second=0, microsecond=0)
        session.add(
            SleepWiseBedtime(
                user_id="test-user",
                validity="VALIDITY_VALID",
                quality="CIRCADIAN_BEDTIME_QUALITY_OK",
                result_type="PREDICTION",
                period_start_time=tonight - timedelta(hours=12),
                period_end_time=tonight + timedelta(hours=12),
                preferred_sleep_start=tonight,
                preferred_sleep_end=tonight + timedelta(hours=8, minutes=15),
                sleep_gate_start=tonight + timedelta(minutes=15),
                sleep_gate_end=tonight + timedelta(minutes=45),
                sleep_timezone_offset_minutes=60,
            )
        )
        await session.commit()


class TestBiosensingDetail:
    @pytest.mark.asyncio
    async def test_ecg_card_renders_with_waveform_payload(self, app_client, admin_account):
        await _login(app_client, admin_account)
        await _seed_biosensing_detail()

        response = await app_client.get("/admin/dashboard")

        html = response.text
        assert "Latest ECG" in html
        assert "182.4" in html  # PTT systolic
        assert 'id="ecg-waveform-samples"' in html
        assert '"amplitude_mv": 1.1' in html or '"amplitude_mv":1.1' in html

    @pytest.mark.asyncio
    async def test_body_temperature_trend_renders(self, app_client, admin_account):
        await _login(app_client, admin_account)
        await _seed_biosensing_detail()

        response = await app_client.get("/admin/dashboard")

        html = response.text
        assert "Body Temperature" in html
        assert 'id="body-temp-trend"' in html
        assert "36.58" in html  # avg in the embedded trend JSON

    @pytest.mark.asyncio
    async def test_sleepwise_cards_render(self, app_client, admin_account):
        await _login(app_client, admin_account)
        await _seed_biosensing_detail()

        response = await app_client.get("/admin/dashboard")

        html = response.text
        assert "Alertness Through the Day" in html
        assert 'id="alertness-hourly"' in html
        assert "Circadian Bedtime" in html
        assert "22:45" in html and "07:00" in html  # preferred window
        assert "23:00" in html  # sleep gate start

    @pytest.mark.asyncio
    async def test_absent_data_hides_cards(self, app_client, admin_account):
        await _login(app_client, admin_account)

        response = await app_client.get("/admin/dashboard")

        html = response.text
        assert "Latest ECG" not in html
        assert "Circadian Bedtime" not in html
        assert "Alertness Through the Day" not in html
