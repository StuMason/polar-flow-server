"""Data-quality fixes from the MCP field test (2026-10-02).

Polar's -1 sentinels become NULL, exercises fall back to Training Load Pro
cardio load, sleep rows pick up HRV/breathing from the night's recharge, and
resting HR is the lowest in-sleep heart rate rather than the overnight average.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import AsyncMock

from polar_flow.models.cardio_load import CardioLoad as SDKCardioLoad
from polar_flow.models.recharge import NightlyRecharge as SDKNightlyRecharge
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.models.baseline import MetricName
from polar_flow_server.models.recharge import NightlyRecharge
from polar_flow_server.models.sleep import Sleep
from polar_flow_server.services.baseline import BaselineService
from polar_flow_server.services.sync import SyncService
from polar_flow_server.transformers.cardio_load import CardioLoadTransformer
from polar_flow_server.transformers.exercise import ExerciseTransformer
from tests.test_exercise_detail import _sdk_exercise

USER_ID = "polar-1"


class TestCardioLoadSentinels:
    def test_negative_one_is_null(self) -> None:
        sdk = SDKCardioLoad.model_validate(
            {
                "date": "2026-09-28",
                "cardio_load_status": "LOAD_STATUS_NOT_AVAILABLE",
                "cardio_load_ratio": -1.0,
                "cardio_load": -1.0,
                "strain": 84.6,
                "tolerance": -1.0,
                "cardio_load_level": {},
            }
        )

        result = CardioLoadTransformer.transform(sdk, USER_ID)

        assert result["cardio_load"] is None
        assert result["cardio_load_ratio"] is None
        assert result["tolerance"] is None
        assert result["strain"] == 84.6

    def test_real_values_kept(self) -> None:
        sdk = SDKCardioLoad.model_validate(
            {
                "date": "2026-10-01",
                "cardio_load_status": "OVERREACHING",
                "cardio_load_ratio": 1.9,
                "cardio_load": 0.0,
                "strain": 54.9,
                "tolerance": 28.8,
                "cardio_load_level": {},
            }
        )

        result = CardioLoadTransformer.transform(sdk, USER_ID)

        assert result["cardio_load"] == 0.0
        assert result["cardio_load_ratio"] == 1.9
        assert result["tolerance"] == 28.8


class TestExerciseTrainingLoad:
    def test_falls_back_to_training_load_pro_cardio_load(self) -> None:
        sdk = _sdk_exercise(
            **{
                "training-load": None,
                "training-load-pro": {
                    "cardio-load": 140.665,
                    "cardio-load-interpretation": "VERY_HIGH",
                    "muscle-load": -1,
                    "muscle-load-interpretation": "NOT_AVAILABLE",
                },
            }
        )

        result = ExerciseTransformer.transform(sdk, USER_ID)

        assert result["training_load"] == 140.665
        tlp = json.loads(result["training_load_pro_json"])
        assert tlp["muscle-load"] is None
        assert tlp["cardio-load-interpretation"] == "VERY_HIGH"

    def test_prefers_polar_training_load(self) -> None:
        result = ExerciseTransformer.transform(_sdk_exercise(), USER_ID)

        assert result["training_load"] == 80.0

    def test_no_load_anywhere_stays_null(self) -> None:
        sdk = _sdk_exercise(**{"training-load": None, "training-load-pro": None})

        result = ExerciseTransformer.transform(sdk, USER_ID)

        assert result["training_load"] is None
        assert result["training_load_pro_json"] is None


async def test_recharge_sync_copies_hrv_onto_sleep(async_session: AsyncSession, test_user) -> None:
    night = date.today() - timedelta(days=1)
    async_session.add(Sleep(user_id=test_user.polar_user_id, date=night, sleep_score=70))
    await async_session.commit()

    sdk = SDKNightlyRecharge.model_validate(
        {
            "polar-user": "https://www.polaraccesslink.com/v3/users/1",
            "date": str(night),
            "heart-rate-avg": 86,
            "beat-to-beat-avg": 696,
            "heart-rate-variability-avg": 21,
            "breathing-rate-avg": 14.4,
            "nightly-recharge-status": 1,
            "ans-charge": -9.0,
            "ans-charge-status": 1,
        }
    )
    client = AsyncMock()
    client.recharge.list = AsyncMock(return_value=[sdk])

    await SyncService(async_session)._sync_recharge(client, test_user.polar_user_id)
    await async_session.commit()

    sleep = (
        await async_session.execute(select(Sleep).where(Sleep.user_id == test_user.polar_user_id))
    ).scalar_one()
    await async_session.refresh(sleep)
    assert sleep.hrv_avg == 21
    assert sleep.breathing_rate_avg == 14.4


async def test_resting_hr_baseline_uses_lowest_sleep_hr(
    async_session: AsyncSession, test_user
) -> None:
    today = date.today()
    for i in range(10):
        night = today - timedelta(days=i)
        async_session.add(
            Sleep(user_id=test_user.polar_user_id, date=night, heart_rate_min=60, heart_rate_avg=75)
        )
        async_session.add(
            NightlyRecharge(user_id=test_user.polar_user_id, date=night, heart_rate_avg=85)
        )
    await async_session.commit()

    service = BaselineService(async_session)
    await service.calculate_resting_hr_baseline(test_user.polar_user_id)
    await async_session.commit()

    baseline = await service.get_baseline(test_user.polar_user_id, MetricName.RESTING_HR)
    assert baseline is not None
    assert baseline.baseline_value == 60
