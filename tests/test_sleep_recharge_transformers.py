"""Tests for the rich sleep/recharge capture (issue #77).

Verifies the transformers keep every field the API returns, apply Polar's
in-band no-data sentinels (continuity 0, sleep_charge -1, zero heart rates)
as NULL, and derive in-sleep HR aggregates from the sample series.
"""

from __future__ import annotations

import json

from polar_flow.models.recharge import NightlyRecharge
from polar_flow.models.sleep import SleepData

from polar_flow_server.transformers.recharge import RechargeTransformer
from polar_flow_server.transformers.sleep import SleepTransformer

USER_ID = "12345"


def _sleep(**overrides: object) -> SleepData:
    base: dict[str, object] = {
        "polar_user": "https://www.polaraccesslink.com/v3/users/1",
        "date": "2026-06-01",
        "sleep_start_time": "2026-05-31T23:10:00+01:00",
        "sleep_end_time": "2026-06-01T07:05:00+01:00",
        "device_id": "ABC123",
        "continuity": 3.4,
        "continuity_class": 3,
        "light_sleep": 14000,
        "deep_sleep": 6000,
        "rem_sleep": 5000,
        "unrecognized_sleep_stage": 300,
        "sleep_score": 82,
        "total_interruption_duration": 1200,
        "sleep_charge": 78,
        "sleep_goal": 28800,
        "sleep_rating": 4,
        "short_interruption_duration": 900,
        "long_interruption_duration": 300,
        "sleep_cycles": 5,
        "group_duration_score": 88.0,
        "group_solidity_score": 74.5,
        "group_regeneration_score": 81.0,
        "hypnogram": {"00:39": 1, "01:19": 3, "02:05": 4, "03:10": 0},
        "heart_rate_samples": {"23:15": 62, "00:15": 58, "01:15": 0, "02:15": 54},
    }
    base.update(overrides)
    return SleepData.model_validate(base)


def _recharge(**overrides: object) -> NightlyRecharge:
    base: dict[str, object] = {
        "polar-user": "https://www.polaraccesslink.com/v3/users/1",
        "date": "2026-06-01",
        "heart-rate-avg": 55,
        "beat-to-beat-avg": 1090,
        "heart-rate-variability-avg": 45,
        "breathing-rate-avg": 13.2,
        "nightly-recharge-status": 4,
        "ans-charge": 2.5,
        "ans-charge-status": 4,
        "hrv-samples": {"23:20": 44, "23:25": 47},
        "breathing-samples": {"23:20": 12.8, "23:25": 13.1},
    }
    base.update(overrides)
    return NightlyRecharge.model_validate(base)


class TestSleepTransformer:
    def test_captures_structure_fields(self) -> None:
        result = SleepTransformer.transform(_sleep(), USER_ID)

        assert result["device_id"] == "ABC123"
        assert result["continuity"] == 3.4
        assert result["continuity_class"] == 3
        assert result["sleep_cycles"] == 5
        assert result["unrecognized_sleep_seconds"] == 300
        assert result["short_interruption_seconds"] == 900
        assert result["long_interruption_seconds"] == 300
        assert result["sleep_charge"] == 78
        assert result["sleep_goal_seconds"] == 28800
        assert result["group_duration_score"] == 88.0
        assert result["group_solidity_score"] == 74.5
        assert result["group_regeneration_score"] == 81.0

    def test_series_stored_as_json(self) -> None:
        result = SleepTransformer.transform(_sleep(), USER_ID)

        hypnogram = json.loads(result["hypnogram_json"])
        assert hypnogram["01:19"] == 3
        hr = json.loads(result["heart_rate_samples_json"])
        assert hr["23:15"] == 62

    def test_hr_aggregates_derived_excluding_zero_signal(self) -> None:
        result = SleepTransformer.transform(_sleep(), USER_ID)

        # 62, 58, 54 count; the 0 sample is no-signal, not a heart rate
        assert result["heart_rate_min"] == 54
        assert result["heart_rate_max"] == 62
        assert result["heart_rate_avg"] == 58.0

    def test_no_samples_leaves_aggregates_null(self) -> None:
        result = SleepTransformer.transform(
            _sleep(hypnogram=None, heart_rate_samples=None), USER_ID
        )

        assert result["hypnogram_json"] is None
        assert result["heart_rate_samples_json"] is None
        assert result["heart_rate_avg"] is None
        assert result["heart_rate_min"] is None
        assert result["heart_rate_max"] is None

    def test_no_data_sentinels_become_null(self) -> None:
        result = SleepTransformer.transform(
            _sleep(continuity=0.0, continuity_class=0, sleep_charge=-1), USER_ID
        )

        assert result["continuity"] is None
        assert result["continuity_class"] is None
        assert result["sleep_charge"] is None

    def test_existing_fields_unchanged(self) -> None:
        result = SleepTransformer.transform(_sleep(), USER_ID)

        assert str(result["date"]) == "2026-06-01"
        assert result["total_sleep_seconds"] == 25000
        assert result["sleep_score"] == 82
        assert result["interruptions_seconds"] == 1200


class TestRechargeTransformer:
    def test_captures_new_fields(self) -> None:
        result = RechargeTransformer.transform(_recharge(), USER_ID)

        assert result["nightly_recharge_status"] == 4
        assert result["beat_to_beat_avg"] == 1090
        assert json.loads(result["hrv_samples_json"])["23:25"] == 47
        assert json.loads(result["breathing_samples_json"])["23:20"] == 12.8

    def test_zero_beat_to_beat_is_no_signal(self) -> None:
        result = RechargeTransformer.transform(_recharge(**{"beat-to-beat-avg": 0}), USER_ID)

        assert result["beat_to_beat_avg"] is None

    def test_missing_series_stay_null(self) -> None:
        result = RechargeTransformer.transform(
            _recharge(**{"hrv-samples": None, "breathing-samples": None}), USER_ID
        )

        assert result["hrv_samples_json"] is None
        assert result["breathing_samples_json"] is None

    def test_existing_fields_unchanged(self) -> None:
        result = RechargeTransformer.transform(_recharge(), USER_ID)

        assert str(result["date"]) == "2026-06-01"
        assert result["hrv_avg"] == 45
        assert result["ans_charge"] == 2.5
        assert result["heart_rate_avg"] == 55
