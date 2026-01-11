"""Tests for Biosensing transformers.

These tests verify that SDK models are correctly transformed to database dicts.
"""

import json
from datetime import UTC, datetime


class TestSpO2Transformer:
    """Tests for SpO2Transformer."""

    def test_transform_complete_data(self) -> None:
        """Test transforming complete SpO2 data."""
        from polar_flow.models.biosensing import SpO2Result

        from polar_flow_server.transformers.spo2 import SpO2Transformer

        # Create SDK model with all fields
        sdk_data = {
            "source_device_id": "DEVICE123",
            "test_time": 1704844800000,  # 2024-01-10 00:00:00 UTC
            "time_zone_offset": 120,  # +2 hours
            "test_status": "COMPLETED",
            "blood_oxygen_percent": 98,
            "spo2_class": "NORMAL",
            "spo2_value_deviation_from_baseline": "WITHIN_BASELINE",
            "spo2_quality_average_percent": 95.5,
            "average_heart_rate_bpm": 65,
            "heart_rate_variability_ms": 45.2,
            "spo2_hrv_deviation_from_baseline": "WITHIN_BASELINE",
            "altitude_meters": 150.0,
        }
        sdk_model = SpO2Result.model_validate(sdk_data)

        # Transform
        result = SpO2Transformer.transform(sdk_model, "user123")

        # Verify all fields
        assert result["device_id"] == "DEVICE123"
        assert result["blood_oxygen_percent"] == 98
        assert result["spo2_class"] == "NORMAL"
        assert result["quality_percent"] == 95.5
        assert result["avg_heart_rate"] == 65
        assert result["hrv_ms"] == 45.2
        assert result["altitude_meters"] == 150.0
        assert result["timezone_offset_minutes"] == 120
        assert result["test_status"] == "COMPLETED"

        # Verify datetime conversion
        expected_dt = datetime(2024, 1, 10, 0, 0, 0, tzinfo=UTC)
        assert result["test_time"] == expected_dt

    def test_transform_minimal_data(self) -> None:
        """Test transforming with minimal required fields."""
        from polar_flow.models.biosensing import SpO2Result

        from polar_flow_server.transformers.spo2 import SpO2Transformer

        sdk_data = {
            "source_device_id": "DEVICE123",
            "test_time": 1704844800000,
            "time_zone_offset": 0,
            "test_status": "COMPLETED",
            "blood_oxygen_percent": 95,
            "spo2_class": "NORMAL",
            "spo2_value_deviation_from_baseline": "UNKNOWN",
            "spo2_quality_average_percent": 80.0,
            "average_heart_rate_bpm": 70,
            "heart_rate_variability_ms": 40.0,
            "spo2_hrv_deviation_from_baseline": "UNKNOWN",
            "altitude_meters": None,
        }
        sdk_model = SpO2Result.model_validate(sdk_data)

        result = SpO2Transformer.transform(sdk_model, "user123")

        assert result["blood_oxygen_percent"] == 95
        assert result["altitude_meters"] is None


class TestECGTransformer:
    """Tests for ECGTransformer."""

    def test_transform_with_samples(self) -> None:
        """Test transforming ECG with waveform samples."""
        from polar_flow.models.biosensing import ECGResult

        from polar_flow_server.transformers.ecg import ECGTransformer

        sdk_data = {
            "source_device_id": "DEVICE123",
            "test_time": 1704844800000,
            "time_zone_offset": 0,
            "average_heart_rate_bpm": 68,
            "heart_rate_variability_ms": 52.3,
            "heart_rate_variability_level": "NORMAL",
            "rri_ms": 882.4,
            "pulse_transit_time_systolic_ms": 120.5,
            "pulse_transit_time_diastolic_ms": 85.2,
            "pulse_transit_time_quality_index": 0.92,
            "samples": [
                {"recording_time_delta_ms": 0, "amplitude_mv": 0.1},
                {"recording_time_delta_ms": 4, "amplitude_mv": 0.15},
                {"recording_time_delta_ms": 8, "amplitude_mv": 0.8},
            ],
            "quality_measurements": [
                {"recording_time_delta_ms": 0, "quality_level": "GOOD"},
            ],
        }
        sdk_model = ECGResult.model_validate(sdk_data)

        result = ECGTransformer.transform(sdk_model, "user123")

        # Verify core fields
        assert result["device_id"] == "DEVICE123"
        assert result["avg_heart_rate"] == 68
        assert result["hrv_ms"] == 52.3
        assert result["hrv_level"] == "NORMAL"
        assert result["rri_ms"] == 882.4
        assert result["ptt_systolic_ms"] == 120.5
        assert result["ptt_diastolic_ms"] == 85.2
        assert result["ptt_quality_index"] == 0.92
        assert result["sample_count"] == 3

        # Verify JSON serialization
        samples = json.loads(result["samples_json"])
        assert len(samples) == 3
        assert samples[0]["time_ms"] == 0
        assert samples[0]["amplitude_mv"] == 0.1

        quality = json.loads(result["quality_json"])
        assert len(quality) == 1
        assert quality[0]["quality"] == "GOOD"

    def test_transform_without_optional_fields(self) -> None:
        """Test transforming ECG without PTT data."""
        from polar_flow.models.biosensing import ECGResult

        from polar_flow_server.transformers.ecg import ECGTransformer

        sdk_data = {
            "source_device_id": "DEVICE123",
            "test_time": 1704844800000,
            "time_zone_offset": 0,
            "average_heart_rate_bpm": 72,
            "heart_rate_variability_ms": 48.0,
            "heart_rate_variability_level": "NORMAL",
            "rri_ms": 833.3,
            "samples": [],
            "quality_measurements": [],
        }
        sdk_model = ECGResult.model_validate(sdk_data)

        result = ECGTransformer.transform(sdk_model, "user123")

        assert result["ptt_systolic_ms"] is None
        assert result["ptt_diastolic_ms"] is None
        assert result["sample_count"] == 0
        assert result["samples_json"] is None


class TestBodyTemperatureTransformer:
    """Tests for BodyTemperatureTransformer."""

    def test_transform_with_samples(self) -> None:
        """Test transforming body temperature with samples."""
        from polar_flow.models.biosensing import BodyTemperaturePeriod

        from polar_flow_server.transformers.temperature import BodyTemperatureTransformer

        sdk_data = {
            "source_device_id": "DEVICE123",
            "measurement_type": "CONTINUOUS",
            "sensor_location": "WRIST",
            "start_time": "2024-01-10T22:00:00Z",
            "end_time": "2024-01-11T06:00:00Z",
            "modified_time": "2024-01-11T06:05:00Z",
            "samples": [
                {"temperature_celsius": 36.2, "recording_time_delta_milliseconds": 0},
                {"temperature_celsius": 36.4, "recording_time_delta_milliseconds": 3600000},
                {"temperature_celsius": 36.1, "recording_time_delta_milliseconds": 7200000},
            ],
        }
        sdk_model = BodyTemperaturePeriod.model_validate(sdk_data)

        result = BodyTemperatureTransformer.transform(sdk_model, "user123")

        # Verify core fields
        assert result["device_id"] == "DEVICE123"
        assert result["measurement_type"] == "CONTINUOUS"
        assert result["sensor_location"] == "WRIST"
        assert result["sample_count"] == 3

        # Verify datetime parsing
        assert result["start_time"].year == 2024
        assert result["start_time"].month == 1
        assert result["start_time"].day == 10

        # Verify computed aggregates
        assert result["temp_min"] == 36.1
        assert result["temp_max"] == 36.4
        assert 36.2 <= result["temp_avg"] <= 36.3

        # Verify JSON serialization
        samples = json.loads(result["samples_json"])
        assert len(samples) == 3
        assert samples[0]["temp_c"] == 36.2


class TestSkinTemperatureTransformer:
    """Tests for SkinTemperatureTransformer."""

    def test_transform_normal_temperature(self) -> None:
        """Test transforming normal skin temperature."""
        from polar_flow.models.biosensing import SkinTemperature

        from polar_flow_server.transformers.temperature import SkinTemperatureTransformer

        sdk_data = {
            "sleep_time_skin_temperature_celsius": 35.8,
            "deviation_from_baseline_celsius": 0.2,
            "sleep_date": "2024-01-10",
        }
        sdk_model = SkinTemperature.model_validate(sdk_data)

        result = SkinTemperatureTransformer.transform(sdk_model, "user123")

        assert result["temperature_celsius"] == 35.8
        assert result["deviation_from_baseline"] == 0.2
        assert result["is_elevated"] is False
        assert result["sleep_date"].isoformat() == "2024-01-10"

    def test_transform_elevated_temperature(self) -> None:
        """Test transforming elevated skin temperature."""
        from polar_flow.models.biosensing import SkinTemperature

        from polar_flow_server.transformers.temperature import SkinTemperatureTransformer

        sdk_data = {
            "sleep_time_skin_temperature_celsius": 36.8,
            "deviation_from_baseline_celsius": 1.2,
            "sleep_date": "2024-01-10",
        }
        sdk_model = SkinTemperature.model_validate(sdk_data)

        result = SkinTemperatureTransformer.transform(sdk_model, "user123")

        assert result["temperature_celsius"] == 36.8
        assert result["deviation_from_baseline"] == 1.2
        assert result["is_elevated"] is True
