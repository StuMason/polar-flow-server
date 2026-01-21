# API Reference

REST API for accessing synced Polar health data.

## Base URL

```
{base_url}/api/v1
```

Replace `{base_url}` with your server address:
- **Local development**: `http://localhost:8000`
- **Docker**: `http://localhost:8000` or your configured port
- **Production**: Your deployed server URL (e.g., `https://polar.example.com`)

## OpenAPI Specification

The full OpenAPI 3.1 specification is available at:

- **JSON**: `GET /schema/openapi.json`
- **Interactive Docs**: `GET /schema/swagger` (Swagger UI)
- **ReDoc**: `GET /schema/redoc`

```bash
# Download OpenAPI spec
curl {base_url}/schema/openapi.json > openapi.json
```

## Authentication

### API Key Authentication

If an API key is configured (recommended for production), include it in the `X-API-Key` header:

```bash
curl -H "X-API-Key: your_api_key_here" {base_url}/api/v1/users/12345/sleep
```

API keys can be created and managed from the **Admin Dashboard → API Keys** section.

### User ID

All data endpoints require a `user_id` in the URL path. For self-hosted deployments, this is your Polar user ID (visible in the admin dashboard). For SaaS integrations, this is your application's user identifier.

### Sync Endpoints

Sync endpoints additionally require a Polar API access token via the `X-Polar-Token` header.

## Endpoints

### Sleep

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/users/{user_id}/sleep` | List sleep data |
| GET | `/users/{user_id}/sleep/{date}` | Get sleep by date |

**Query Parameters:**
- `days` (int, default: 7) - Number of days to fetch (1-365)

**Example:**
```bash
curl {base_url}/api/v1/users/12345/sleep?days=30
```

**Response:**
```json
[
  {
    "date": "2026-01-11",
    "sleep_score": 85,
    "total_sleep_hours": 7.5,
    "deep_sleep_hours": 1.8,
    "rem_sleep_hours": 1.9,
    "light_sleep_hours": 3.8,
    "hrv_avg": 45.2,
    "heart_rate_avg": 52
  }
]
```

---

### Activity

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/users/{user_id}/activity` | List daily activity |
| GET | `/users/{user_id}/activity/{date}` | Get activity by date |

**Query Parameters:**
- `days` (int, default: 30) - Number of days to fetch (1-365)

**Example:**
```bash
curl {base_url}/api/v1/users/12345/activity?days=7
```

**Response:**
```json
[
  {
    "date": "2026-01-11",
    "steps": 8542,
    "calories_active": 450,
    "calories_total": 2150,
    "distance_km": 6.2,
    "active_minutes": 45.5,
    "activity_score": 78
  }
]
```

---

### Nightly Recharge (HRV)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/users/{user_id}/recharge` | List nightly recharge data |

**Query Parameters:**
- `days` (int, default: 30) - Number of days to fetch (1-365)

**Example:**
```bash
curl {base_url}/api/v1/users/12345/recharge?days=14
```

**Response:**
```json
[
  {
    "date": "2026-01-11",
    "hrv_avg": 48.5,
    "ans_charge": 4.2,
    "ans_charge_status": "WELL_RECOVERED",
    "breathing_rate_avg": 14.2,
    "heart_rate_avg": 51
  }
]
```

---

### Exercises

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/users/{user_id}/exercises` | List exercises |
| GET | `/users/{user_id}/exercises/{id}` | Get exercise detail |

**Query Parameters:**
- `days` (int, default: 30) - Number of days to fetch (1-365)

**Example:**
```bash
curl {base_url}/api/v1/users/12345/exercises?days=30
```

**Response:**
```json
[
  {
    "id": 1,
    "polar_exercise_id": "abc123",
    "start_time": "2026-01-11 07:30:00",
    "sport": "RUNNING",
    "duration_minutes": 45.5,
    "distance_km": 8.2,
    "calories": 520,
    "average_heart_rate": 145,
    "max_heart_rate": 172,
    "training_load": 85
  }
]
```

---

### Cardio Load

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/users/{user_id}/cardio-load` | List cardio load data |

**Query Parameters:**
- `days` (int, default: 30) - Number of days to fetch (1-365)

**Response:**
```json
[
  {
    "date": "2026-01-11",
    "strain": 125.5,
    "tolerance": 180.2,
    "cardio_load": 85.3,
    "cardio_load_ratio": 0.70,
    "cardio_load_status": "PRODUCTIVE"
  }
]
```

---

### Heart Rate

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/users/{user_id}/heart-rate` | List daily HR summaries |

**Query Parameters:**
- `days` (int, default: 30) - Number of days to fetch (1-365)

**Response:**
```json
[
  {
    "date": "2026-01-11",
    "hr_min": 48,
    "hr_avg": 62,
    "hr_max": 165,
    "sample_count": 1440
  }
]
```

---

### SleepWise

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/users/{user_id}/sleepwise/alertness` | Hourly alertness predictions |
| GET | `/users/{user_id}/sleepwise/bedtime` | Optimal bedtime recommendations |

**Query Parameters:**
- `days` (int, default: 7) - Number of days to fetch (1-30)

**Alertness Response:**
```json
[
  {
    "period_start_time": "2026-01-11 08:00:00",
    "period_end_time": "2026-01-11 09:00:00",
    "grade": 4.2,
    "grade_classification": "GOOD"
  }
]
```

**Bedtime Response:**
```json
[
  {
    "period_start_time": "2026-01-11 00:00:00",
    "period_end_time": "2026-01-12 00:00:00",
    "preferred_sleep_start": "22:30:00",
    "preferred_sleep_end": "06:30:00",
    "sleep_gate_start": "22:00:00",
    "sleep_gate_end": "23:00:00",
    "quality": "GOOD"
  }
]
```

---

### Biosensing (Vantage V3)

Requires compatible device with Elixir sensor platform.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/users/{user_id}/spo2` | Blood oxygen measurements |
| GET | `/users/{user_id}/ecg` | ECG recordings |
| GET | `/users/{user_id}/temperature/body` | Body temperature |
| GET | `/users/{user_id}/temperature/skin` | Skin temperature |

**Query Parameters:**
- `days` (int, default: 30) - Number of days to fetch (1-365)

**SpO2 Response:**
```json
[
  {
    "test_time": "2026-01-11 22:30:00",
    "blood_oxygen_percent": 98,
    "spo2_class": "NORMAL",
    "avg_heart_rate": 62,
    "hrv_ms": 45.2,
    "altitude_meters": 150
  }
]
```

---

### Sync

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/users/{user_id}/sync/trigger` | Trigger data sync |

**Headers:**
- `X-Polar-Token` (required) - Polar API access token

**Query Parameters:**
- `days` (int, optional) - Days to sync (default from config)

**Example:**
```bash
curl -X POST \
  -H "X-Polar-Token: your_polar_token" \
  {base_url}/api/v1/users/12345/sync/trigger?days=30
```

**Response:**
```json
{
  "status": "success",
  "user_id": "12345",
  "results": {
    "sleep": 28,
    "recharge": 28,
    "activity": 28,
    "exercises": 15,
    "cardio_load": 28,
    "sleepwise_alertness": 168,
    "sleepwise_bedtime": 7,
    "spo2": 5,
    "ecg": 3,
    "body_temperature": 7,
    "skin_temperature": 7
  }
}
```

---

### Export

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/users/{user_id}/export/summary` | Export summary manifest |

**Query Parameters:**
- `days` (int, default: 30) - Number of days to include (1-365)

**Response:**
```json
{
  "user_id": "12345",
  "days": 30,
  "from_date": "2025-12-12",
  "to_date": "2026-01-11",
  "record_counts": {
    "sleep": 30,
    "activity": 30,
    "recharge": 30,
    "cardio_load": 28,
    "heart_rate": 30,
    "exercises": 12
  },
  "total_records": 160
}
```

---

### Baselines & Analytics

Personal baselines computed from historical data. Use these for anomaly detection and personalized insights.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/users/{user_id}/baselines` | Get all computed baselines |
| GET | `/users/{user_id}/baselines/{metric_name}` | Get specific baseline |
| POST | `/users/{user_id}/baselines/calculate` | Trigger baseline calculation |
| GET | `/users/{user_id}/baselines/check/{metric_name}/{value}` | Check if value is anomalous |
| GET | `/users/{user_id}/analytics/status` | Get analytics readiness status |

**Valid Metric Names:**
- `hrv_rmssd` - Heart Rate Variability (RMSSD)
- `sleep_score` - Overall sleep quality score
- `resting_hr` - Resting heart rate
- `training_load` - Training load (cardio load)
- `training_load_ratio` - Acute:chronic load ratio

#### Get All Baselines

```bash
curl {base_url}/api/v1/users/12345/baselines
```

**Response:**
```json
[
  {
    "metric_name": "hrv_rmssd",
    "baseline_value": 42.5,
    "baseline_7d": 44.2,
    "baseline_30d": 41.8,
    "baseline_90d": 40.5,
    "median": 42.0,
    "q1": 38.5,
    "q3": 48.2,
    "iqr": 9.7,
    "std_dev": 8.3,
    "min": 28.0,
    "max": 65.0,
    "lower_bound": 24.0,
    "upper_bound": 62.8,
    "sample_count": 45,
    "status": "ready",
    "data_start_date": "2025-11-01",
    "data_end_date": "2026-01-11",
    "calculated_at": "2026-01-11T08:00:00Z"
  }
]
```

**Baseline Status:**
- `ready` - Full baseline (21+ days of data)
- `partial` - Limited baseline (7-20 days)
- `insufficient` - Not enough data (<7 days)

#### Check for Anomaly

Uses IQR-based anomaly detection:
- **Warning**: value outside Q1 - 1.5×IQR to Q3 + 1.5×IQR
- **Critical**: value outside Q1 - 3×IQR to Q3 + 3×IQR

```bash
curl {base_url}/api/v1/users/12345/baselines/check/hrv_rmssd/25.5
```

**Response:**
```json
{
  "value": 25.5,
  "metric_name": "hrv_rmssd",
  "is_anomaly": true,
  "severity": "warning",
  "baseline": 42.5,
  "baseline_7d": 44.2,
  "lower_bound": 24.0,
  "upper_bound": 62.8,
  "status": "ready"
}
```

#### Calculate Baselines

Trigger baseline recalculation from historical data:

```bash
curl -X POST {base_url}/api/v1/users/12345/baselines/calculate
```

**Response:**
```json
{
  "user_id": "12345",
  "baselines_calculated": {
    "hrv_rmssd": "ready",
    "sleep_score": "ready",
    "resting_hr": "ready",
    "training_load": "partial",
    "training_load_ratio": "partial"
  }
}
```

#### Analytics Status

Check feature availability based on data history:

```bash
curl {base_url}/api/v1/users/12345/analytics/status
```

**Response:**
```json
{
  "user_id": "12345",
  "data_days": {
    "sleep": 45,
    "recharge": 45,
    "activity": 45,
    "cardio_load": 30
  },
  "min_data_days": 30,
  "features_available": {
    "basic_stats": true,
    "trend_analysis": true,
    "personalized_baselines": true,
    "predictive_models": true,
    "advanced_ml": false,
    "long_term_patterns": false
  },
  "unlock_progress": {
    "advanced_ml": {
      "unlocked": false,
      "days_required": 60,
      "days_remaining": 30,
      "progress_percent": 50.0
    }
  },
  "recommendations": [
    "Great progress! Advanced ML features unlock after 60 days of data."
  ]
}
```

**Feature Unlock Timeline:**
| Days | Features Unlocked |
|------|-------------------|
| 7 | Basic statistics, daily tracking |
| 14 | Trend analysis, basic anomaly alerts |
| 21 | Reliable correlations, personalized baselines |
| 30 | Predictive models, outcome forecasting |
| 60 | Advanced ML models, behavior patterns |
| 90 | Long-term pattern recognition |

---

### Patterns & Anomalies

Advanced pattern detection for correlations, trends, and risk assessment.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/users/{user_id}/patterns` | Get all detected patterns |
| GET | `/users/{user_id}/patterns/{pattern_name}` | Get specific pattern |
| POST | `/users/{user_id}/patterns/detect` | Trigger pattern detection |
| GET | `/users/{user_id}/anomalies` | Scan all metrics for anomalies |

**Pattern Types:**
- `correlation` - Statistical relationships between metrics
- `trend` - Directional changes over time
- `composite` - Multi-metric risk scores

**Available Patterns:**
- `sleep_hrv_correlation` - Correlation between sleep quality and HRV
- `overtraining_risk` - Multi-metric overtraining risk score (0-100)
- `hrv_trend` - 7-day HRV trend vs 30-day baseline
- `sleep_trend` - 7-day sleep score trend vs 30-day baseline

#### Get All Patterns

```bash
curl {base_url}/api/v1/users/12345/patterns
```

**Response:**
```json
[
  {
    "pattern_type": "correlation",
    "pattern_name": "sleep_hrv_correlation",
    "score": 0.72,
    "confidence": 0.95,
    "significance": "high",
    "metrics_involved": ["sleep_score", "hrv_rmssd"],
    "sample_count": 28,
    "details": {
      "correlation_coefficient": 0.72,
      "p_value": 0.001,
      "interpretation": "Strong positive correlation between sleep quality and HRV"
    },
    "analyzed_at": "2026-01-13T08:00:00Z"
  },
  {
    "pattern_type": "composite",
    "pattern_name": "overtraining_risk",
    "score": 35,
    "confidence": 0.88,
    "significance": "medium",
    "metrics_involved": ["hrv_rmssd", "sleep_score", "resting_hr", "training_load_ratio"],
    "sample_count": 7,
    "details": {
      "risk_factors": ["HRV trending 8% below baseline"],
      "recommendations": [
        "Monitor your body's response to training",
        "Consider adding an extra recovery day this week"
      ]
    },
    "analyzed_at": "2026-01-13T08:00:00Z"
  }
]
```

**Significance Levels:**
- `high` - Statistically significant pattern (p < 0.01)
- `medium` - Moderate significance (p < 0.05)
- `low` - Weak pattern (p < 0.1)
- `insufficient` - Not enough data for reliable analysis

#### Get Specific Pattern

```bash
curl {base_url}/api/v1/users/12345/patterns/overtraining_risk
```

#### Trigger Pattern Detection

Analyzes historical data and stores pattern results:

```bash
curl -X POST {base_url}/api/v1/users/12345/patterns/detect
```

**Response:**
```json
{
  "user_id": "12345",
  "patterns_detected": {
    "sleep_hrv_correlation": "high",
    "overtraining_risk": "medium",
    "hrv_trend": "low",
    "sleep_trend": "insufficient"
  }
}
```

#### Bulk Anomaly Scan

Scans all metrics against stored baselines and returns any values outside normal bounds:

```bash
curl {base_url}/api/v1/users/12345/anomalies
```

**Response:**
```json
{
  "user_id": "12345",
  "anomaly_count": 2,
  "anomalies": [
    {
      "metric_name": "hrv_rmssd",
      "current_value": 22.5,
      "baseline_value": 42.5,
      "lower_bound": 24.0,
      "upper_bound": 62.8,
      "severity": "critical",
      "direction": "below",
      "deviation_percent": -47.1
    },
    {
      "metric_name": "resting_hr",
      "current_value": 68,
      "baseline_value": 55,
      "lower_bound": 48,
      "upper_bound": 65,
      "severity": "warning",
      "direction": "above",
      "deviation_percent": 23.6
    }
  ]
}
```

**Anomaly Severity:**
- `warning` - Value outside Q1 - 1.5×IQR to Q3 + 1.5×IQR
- `critical` - Value outside Q1 - 3×IQR to Q3 + 3×IQR

---

### Unified Insights

The unified insights endpoint aggregates all analytics into a single response optimized for downstream consumers (dashboards, coaching apps, etc.).

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/users/{user_id}/insights` | Get complete insights package |

**Response includes:**
- Current metric values
- Personal baseline comparisons
- Detected patterns (correlations, trends, risk scores)
- Anomalies (values outside normal bounds)
- Natural language observations
- Actionable suggestions
- Feature availability based on data history

#### Feature Unlock Timeline

Features unlock progressively as more data becomes available:

| Days of Data | Features Available |
|--------------|-------------------|
| 0-6 | Raw data only, no analytics |
| 7+ | 7-day baselines |
| 21+ | Pattern detection, anomaly detection |
| 30+ | Full 30-day baselines |
| 60+ | ML predictions (future) |

#### Example Request

```bash
curl {base_url}/api/v1/users/12345/insights
```

#### Example Response (30+ days of data)

```json
{
  "user_id": "12345",
  "generated_at": "2026-01-13T10:30:00Z",
  "data_freshness": "2026-01-13T06:00:00Z",
  "data_age_days": 45,
  "status": "ready",

  "feature_availability": {
    "baselines_7d": {"available": true, "message": null},
    "baselines_30d": {"available": true, "message": null},
    "patterns": {"available": true, "message": null},
    "anomaly_detection": {"available": true, "message": null},
    "ml_predictions": {"available": false, "message": "Unlocks in 15 days", "unlock_at_days": 60}
  },

  "unlock_progress": {
    "next_unlock": "ml_predictions",
    "days_until_next": 15,
    "percent_to_next": 75.0
  },

  "current_metrics": {
    "hrv": 45.2,
    "sleep_score": 78,
    "resting_hr": 52,
    "training_load_ratio": 1.1
  },

  "baselines": {
    "hrv_rmssd": {
      "current": 45.2,
      "baseline": 52.0,
      "baseline_7d": 48.5,
      "baseline_30d": 52.0,
      "percent_of_baseline": 86.9,
      "trend": "declining",
      "status": "ready"
    },
    "sleep_score": {
      "current": 78,
      "baseline": 82.0,
      "percent_of_baseline": 95.1,
      "trend": "stable",
      "status": "ready"
    }
  },

  "patterns": [
    {
      "name": "sleep_hrv_correlation",
      "pattern_type": "correlation",
      "score": 0.72,
      "significance": "high",
      "factors": [],
      "interpretation": "Strong positive correlation between sleep quality and HRV"
    },
    {
      "name": "overtraining_risk",
      "pattern_type": "composite",
      "score": 35,
      "significance": "medium",
      "factors": ["HRV trending below baseline"],
      "interpretation": null
    }
  ],

  "anomalies": [],

  "observations": [
    {
      "category": "recovery",
      "priority": "high",
      "fact": "HRV is 13% below personal baseline",
      "context": "Current: 45ms, Baseline: 52ms",
      "trend": "declining"
    },
    {
      "category": "recovery",
      "priority": "info",
      "fact": "Strong connection between your sleep quality and HRV detected",
      "context": "Better sleep directly improves your recovery metrics",
      "trend": null
    }
  ],

  "suggestions": [
    {
      "action": "prioritize_recovery",
      "description": "Prioritize sleep and recovery today",
      "confidence": 0.85,
      "reason": "HRV is 13% below baseline"
    }
  ]
}
```

#### Example Response (New User - 5 days)

```json
{
  "user_id": "12345",
  "generated_at": "2026-01-13T10:30:00Z",
  "data_age_days": 5,
  "status": "unavailable",

  "feature_availability": {
    "baselines_7d": {"available": false, "message": "Unlocks in 2 days", "unlock_at_days": 7},
    "baselines_30d": {"available": false, "message": "Unlocks in 25 days", "unlock_at_days": 30},
    "patterns": {"available": false, "message": "Unlocks in 16 days", "unlock_at_days": 21},
    "anomaly_detection": {"available": false, "message": "Unlocks in 16 days", "unlock_at_days": 21},
    "ml_predictions": {"available": false, "message": "Unlocks in 55 days", "unlock_at_days": 60}
  },

  "unlock_progress": {
    "next_unlock": "baselines_7d",
    "days_until_next": 2,
    "percent_to_next": 71.4
  },

  "current_metrics": {
    "hrv": 48.0,
    "sleep_score": 75,
    "resting_hr": 55,
    "training_load_ratio": null
  },

  "baselines": {},
  "patterns": [],
  "anomalies": [],

  "observations": [
    {
      "category": "onboarding",
      "priority": "info",
      "fact": "Building your personal baselines (5/7 days)",
      "context": "Keep wearing your device. Basic insights unlock in 2 days.",
      "trend": null
    }
  ],

  "suggestions": []
}
```

#### Response Fields

| Field | Description |
|-------|-------------|
| `status` | Overall status: `ready`, `partial`, or `unavailable` |
| `data_age_days` | Number of days of data available |
| `feature_availability` | Which analytics features are unlocked |
| `unlock_progress` | Progress toward unlocking the next feature |
| `current_metrics` | Most recent values of key health metrics |
| `baselines` | Personal baseline comparisons by metric |
| `patterns` | Detected patterns (correlations, trends, risk scores) |
| `anomalies` | Values outside normal IQR bounds |
| `observations` | Natural language observations for coaching |
| `suggestions` | Actionable suggestions based on current state |

#### Observation Categories

| Category | Description |
|----------|-------------|
| `recovery` | Recovery and HRV-related observations |
| `sleep` | Sleep quality observations |
| `training` | Training load and overtraining observations |
| `anomaly` | Detected anomalies in metrics |
| `onboarding` | New user guidance |
| `trend` | Trend-related observations |

#### Observation Priorities

| Priority | Description |
|----------|-------------|
| `critical` | Requires immediate attention |
| `high` | Important observation |
| `medium` | Moderate importance |
| `low` | Minor observation |
| `info` | Informational |
| `positive` | Good news |

---

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Server health check |

**Response:**
```json
{
  "status": "healthy",
  "database": "connected"
}
```
