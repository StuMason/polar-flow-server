# API Reference

REST API for accessing synced Polar health data.

Base URL: `http://localhost:8000/api/v1`

## Authentication

All data endpoints require a `user_id` in the URL path. For self-hosted deployments, this is your Polar user ID. For SaaS integrations, this is your application's user identifier.

Sync endpoints require a Polar API access token via the `X-Polar-Token` header.

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
curl http://localhost:8000/api/v1/users/12345/sleep?days=30
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
curl http://localhost:8000/api/v1/users/12345/activity?days=7
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
curl http://localhost:8000/api/v1/users/12345/recharge?days=14
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
curl http://localhost:8000/api/v1/users/12345/exercises?days=30
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
  http://localhost:8000/api/v1/users/12345/sync/trigger?days=30
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
