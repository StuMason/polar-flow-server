"""Regression tests for ANS scale alignment and related HR handling."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import polar_flow_server.admin.routes as admin_routes
from polar_flow_server.models.recharge import NightlyRecharge
from polar_flow_server.transformers.continuous_hr import ContinuousHRTransformer


@dataclass
class _FakeHrSample:
    heart_rate: int | None
    sample_time: str


@dataclass
class _FakeContinuousHr:
    date: str
    heart_rate_samples: list[_FakeHrSample]


@pytest.mark.parametrize(
    ("ans_charge", "expected_score"),
    [
        (-10.0, 0),
        (0.0, 50),
        (10.0, 100),
        (-20.0, 0),  # clamped
        (20.0, 100),  # clamped
    ],
)
def test_recovery_status_normalizes_and_clamps_ans(ans_charge: float, expected_score: int) -> None:
    """ANS charge should be normalized from -10..10 to 0..100 and clamped."""
    recharge = NightlyRecharge(user_id="user-1", date=date.today(), ans_charge=ans_charge)

    status = admin_routes._calculate_recovery_status(sleep=None, recharge=recharge, cardio=None)

    assert status["readiness_score"] == expected_score


@pytest.mark.asyncio
async def test_chart_hrv_data_preserves_missing_ans_as_null(
    async_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing ANS charge should remain null in chart payload, not coerced to 0."""
    monkeypatch.setattr(admin_routes, "is_authenticated", lambda _request: True)

    today = date.today()
    async_session.add_all(
        [
            NightlyRecharge(user_id="user-1", date=today - timedelta(days=1), hrv_avg=42.0),
            NightlyRecharge(user_id="user-1", date=today, hrv_avg=45.0, ans_charge=2.0),
        ]
    )
    await async_session.commit()

    result = await admin_routes.chart_hrv_data(  # type: ignore[arg-type]
        request=None,
        session=async_session,
        days=30,
    )

    assert result["datasets"]["ans_charge"] == [None, 2.0]


def test_continuous_hr_transformer_filters_invalid_values_for_aggregates_only() -> None:
    """Zero/None placeholders should not affect min/avg/max but raw samples are kept."""
    sdk_hr = _FakeContinuousHr(
        date=date.today().isoformat(),
        heart_rate_samples=[
            _FakeHrSample(heart_rate=None, sample_time="00:00"),
            _FakeHrSample(heart_rate=0, sample_time="00:05"),
            _FakeHrSample(heart_rate=55, sample_time="00:10"),
            _FakeHrSample(heart_rate=65, sample_time="00:15"),
        ],
    )

    result = ContinuousHRTransformer.transform(sdk_hr, "user-1")  # type: ignore[arg-type]

    assert result["sample_count"] == 4
    assert result["hr_min"] == 55
    assert result["hr_avg"] == 60
    assert result["hr_max"] == 65

    raw_samples = json.loads(result["samples_json"])
    assert len(raw_samples) == 4
    assert raw_samples[0]["heart_rate"] is None
    assert raw_samples[1]["heart_rate"] == 0
