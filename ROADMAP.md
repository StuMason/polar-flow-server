# ROADMAP: Analytics Engine for Health Coaching

## Status
Active Development

## Vision

Transform polar-flow-server from a data sync/storage layer into a comprehensive health analytics engine that provides actionable insights for AI coaching applications.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         TARGET ARCHITECTURE                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────────┐    ┌──────────────────────────────────────────────────┐  │
│   │ Polar API   │───▶│           polar-flow-server                      │  │
│   │ (Raw Data)  │    │  ┌────────────────────────────────────────────┐  │  │
│   └─────────────┘    │  │            ANALYTICS ENGINE                 │  │  │
│                      │  │                                            │  │  │
│                      │  │  ┌──────────┐  ┌──────────┐  ┌──────────┐ │  │  │
│                      │  │  │ Derived  │  │ Pattern  │  │    ML    │ │  │  │
│                      │  │  │ Metrics  │  │ Detection│  │  Models  │ │  │  │
│                      │  │  └────┬─────┘  └────┬─────┘  └────┬─────┘ │  │  │
│                      │  │       │             │             │       │  │  │
│                      │  │       └─────────────┴─────────────┘       │  │  │
│                      │  │                     │                     │  │  │
│                      │  │              ┌──────▼──────┐              │  │  │
│                      │  │              │  INSIGHTS   │              │  │  │
│                      │  │              │    API      │              │  │  │
│                      │  │              └─────────────┘              │  │  │
│                      │  └────────────────────────────────────────────┘  │  │
│                      └───────────────────────────────────────────────────┘  │
│                                           │                                 │
│                                           ▼                                 │
│   ┌─────────────────────────────────────────────────────────────────────┐  │
│   │                      Laravel SaaS (Coach)                            │  │
│   │                                                                      │  │
│   │   polar-flow-server provides: "Your HRV is 15% below your baseline,  │  │
│   │   training load has been high for 3 days, sleep quality declining"   │  │
│   │                                                                      │  │
│   │   Laravel + LLM transforms into: "Hey! I noticed you've been         │  │
│   │   pushing hard lately. Your body's asking for a rest day - maybe     │  │
│   │   swap that HIIT session for some yoga? Your recovery will thank     │  │
│   │   you!"                                                              │  │
│   │                                                                      │  │
│   └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**The Server Provides Facts. The Coach Provides Personality.**

---

## Current State (v0.2.0)

### What's Working

| Component | Status | Notes |
|-----------|--------|-------|
| Data Sync | Complete | 9 Polar endpoints synced hourly |
| Storage | Complete | PostgreSQL with 18 models |
| OAuth Flow | Complete | Full SaaS multi-user support |
| Per-User API Keys | Complete | Rate limiting (1000 req/hr) |
| Admin Dashboard | Complete | HTMX-powered, shows all metrics |
| REST API | Complete | All data endpoints with filtering |

### Data Currently Stored

| Data Type | Model | Key Fields |
|-----------|-------|------------|
| Sleep | `Sleep` | score, stages, duration, HR, HRV, breathing |
| Nightly Recharge | `NightlyRecharge` | ANS charge, recovery status, HRV |
| Daily Activity | `Activity` | steps, distance, calories, active time |
| Exercises | `Exercise` | sport, duration, HR zones, training load |
| Cardio Load | `CardioLoad` | strain, tolerance, load ratio, status |
| Continuous HR | `ContinuousHR` | daily min/avg/max heart rate |
| Activity Samples | `ActivitySamples` | minute-by-minute step data |
| SleepWise Alertness | `SleepWiseAlertness` | hourly alertness predictions |
| SleepWise Bedtime | `SleepWiseBedtime` | optimal sleep timing |
| SpO2 | `SpO2` | blood oxygen measurements |
| ECG | `ECG` | heart recordings with waveforms |
| Body Temperature | `BodyTemperature` | continuous body temp |
| Skin Temperature | `SkinTemperature` | nightly skin temp readings |

---

## Phase 1: Derived Metrics Engine

**Goal:** Calculate rolling averages, baselines, and trends that Polar doesn't provide natively.

### 1.1 User Baselines Table

New model to store computed personal baselines:

```python
class UserBaseline(Base):
    """Computed personal baselines for each metric."""

    __tablename__ = "user_baselines"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(50), index=True)

    # Metric identification
    metric_name: Mapped[str] = mapped_column(String(50))  # "hrv_rmssd", "sleep_score", etc.

    # Baseline values (calculated from historical data)
    baseline_value: Mapped[float] = mapped_column(Float)
    baseline_7d: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_30d: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_90d: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Statistics
    std_dev: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_count: Mapped[int] = mapped_column(default=0)

    # Timestamps
    calculated_at: Mapped[datetime] = mapped_column(server_default=func.now())
    data_start_date: Mapped[date | None] = mapped_column(nullable=True)
    data_end_date: Mapped[date | None] = mapped_column(nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "metric_name", name="uq_user_baseline"),
    )
```

### 1.2 Metrics to Calculate

| Metric | Source | Calculation | Use Case |
|--------|--------|-------------|----------|
| HRV Baseline | `NightlyRecharge.hrv` | 30-day rolling avg | Recovery assessment |
| HRV 7-Day Trend | `NightlyRecharge.hrv` | Linear regression slope | Trend direction |
| Sleep Score Baseline | `Sleep.sleep_score` | 30-day avg | Sleep quality norm |
| Resting HR Baseline | `ContinuousHR.hr_avg` | 14-day avg | Fitness indicator |
| Training Load Weekly | `CardioLoad.strain` | Sum last 7 days | Load management |
| Training Load Ratio | `CardioLoad` | Acute:Chronic (7d:28d) | Injury risk |
| Active Calories Baseline | `Activity.calories` | 30-day avg | Energy expenditure |
| Sleep Consistency Score | `Sleep.sleep_start` | Std dev of bedtimes | Circadian health |

### 1.3 Baseline Calculation Service

```python
class BaselineService:
    """Calculate and update user baselines."""

    async def calculate_hrv_baseline(self, user_id: str, session: AsyncSession) -> dict:
        """Calculate HRV baselines from nightly recharge data."""

        # Fetch last 90 days of HRV data
        stmt = select(NightlyRecharge.hrv, NightlyRecharge.date).where(
            NightlyRecharge.user_id == user_id,
            NightlyRecharge.hrv.isnot(None),
            NightlyRecharge.date >= date.today() - timedelta(days=90)
        ).order_by(NightlyRecharge.date)

        result = await session.execute(stmt)
        data = result.all()

        if len(data) < 7:
            return {"status": "insufficient_data", "sample_count": len(data)}

        # Calculate baselines
        values = [row.hrv for row in data]
        recent_7d = values[-7:] if len(values) >= 7 else values
        recent_30d = values[-30:] if len(values) >= 30 else values

        return {
            "baseline_value": statistics.mean(values),
            "baseline_7d": statistics.mean(recent_7d),
            "baseline_30d": statistics.mean(recent_30d) if len(recent_30d) >= 14 else None,
            "baseline_90d": statistics.mean(values) if len(values) >= 60 else None,
            "std_dev": statistics.stdev(values) if len(values) >= 2 else None,
            "min_value": min(values),
            "max_value": max(values),
            "sample_count": len(values),
        }

    async def calculate_all_baselines(self, user_id: str, session: AsyncSession) -> None:
        """Calculate all baselines for a user."""

        calculations = [
            ("hrv_rmssd", self.calculate_hrv_baseline),
            ("sleep_score", self.calculate_sleep_baseline),
            ("resting_hr", self.calculate_hr_baseline),
            ("training_load", self.calculate_training_baseline),
            # ... more metrics
        ]

        for metric_name, calc_func in calculations:
            result = await calc_func(user_id, session)
            await self.upsert_baseline(user_id, metric_name, result, session)
```

### 1.4 API Endpoints

```
GET /users/{user_id}/baselines
  Returns all calculated baselines for user

GET /users/{user_id}/baselines/{metric}
  Returns specific baseline with trend data

GET /users/{user_id}/metrics/current
  Returns current values vs baselines
  {
    "hrv": {
      "current": 45,
      "baseline": 52,
      "percent_of_baseline": 86.5,
      "trend": "declining",
      "status": "below_normal"  // normal, above_normal, below_normal, critical
    }
  }
```

### 1.5 Files to Create

| File | Purpose |
|------|---------|
| `src/polar_flow_server/models/baseline.py` | UserBaseline model |
| `src/polar_flow_server/services/baseline.py` | Baseline calculation service |
| `src/polar_flow_server/api/baselines.py` | Baseline API endpoints |
| `alembic/versions/xxx_add_baselines.py` | Migration for baselines table |

---

## Phase 2: Pattern Detection

**Goal:** Identify correlations, consistency patterns, and anomalies in user data.

### 2.1 Pattern Types

| Pattern | Detection Method | Output |
|---------|-----------------|--------|
| Sleep-HRV Correlation | Pearson correlation | r-value, significance |
| Training-Recovery Lag | Cross-correlation | Optimal recovery days |
| Circadian Consistency | Variance in sleep/wake times | Consistency score |
| Overtraining Risk | Multi-metric decline | Risk score 0-100 |
| Performance Readiness | Composite score | Readiness percentage |

### 2.2 Pattern Analysis Model

```python
class PatternAnalysis(Base):
    """Detected patterns and correlations for a user."""

    __tablename__ = "pattern_analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(50), index=True)

    pattern_type: Mapped[str] = mapped_column(String(50))  # "correlation", "anomaly", etc.
    pattern_name: Mapped[str] = mapped_column(String(100))  # "sleep_hrv_correlation"

    # Pattern details (JSON)
    metrics_involved: Mapped[dict] = mapped_column(JSON)  # ["sleep_score", "hrv"]
    analysis_window_days: Mapped[int] = mapped_column(default=30)

    # Results
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    significance: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "high", "medium", "low"
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Timestamps
    analyzed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    valid_until: Mapped[datetime | None] = mapped_column(nullable=True)
```

### 2.3 Pattern Detection Service

```python
class PatternService:
    """Detect patterns and correlations in user data."""

    async def detect_sleep_hrv_correlation(
        self, user_id: str, session: AsyncSession
    ) -> PatternResult:
        """Analyze correlation between sleep quality and HRV."""

        # Fetch aligned sleep and HRV data
        sleep_data = await self.get_sleep_scores(user_id, days=30, session=session)
        hrv_data = await self.get_hrv_values(user_id, days=30, session=session)

        # Align by date
        aligned = self.align_time_series(sleep_data, hrv_data)

        if len(aligned) < 14:
            return PatternResult(status="insufficient_data")

        # Calculate correlation
        r, p_value = scipy.stats.pearsonr(aligned.sleep, aligned.hrv)

        return PatternResult(
            pattern_type="correlation",
            pattern_name="sleep_hrv_correlation",
            score=r,
            confidence=1 - p_value,
            significance="high" if p_value < 0.05 else "low",
            details={
                "correlation_coefficient": r,
                "p_value": p_value,
                "sample_size": len(aligned),
                "interpretation": self.interpret_correlation(r, p_value)
            }
        )

    async def detect_overtraining_risk(
        self, user_id: str, session: AsyncSession
    ) -> PatternResult:
        """Multi-metric analysis for overtraining detection."""

        # Gather multiple signals
        hrv_trend = await self.get_hrv_trend(user_id, days=7, session=session)
        sleep_trend = await self.get_sleep_trend(user_id, days=7, session=session)
        rhr_trend = await self.get_rhr_trend(user_id, days=7, session=session)
        training_load = await self.get_recent_load(user_id, days=7, session=session)

        # Score each factor (0-25 points each)
        risk_score = 0
        factors = []

        if hrv_trend < -10:  # HRV declining >10%
            risk_score += 25
            factors.append("HRV declining significantly")
        elif hrv_trend < -5:
            risk_score += 15
            factors.append("HRV declining moderately")

        if sleep_trend < -10:  # Sleep score declining
            risk_score += 25
            factors.append("Sleep quality declining")

        if rhr_trend > 5:  # Resting HR increasing
            risk_score += 25
            factors.append("Resting heart rate elevated")

        if training_load > 1.5:  # Acute:Chronic ratio high
            risk_score += 25
            factors.append("Training load ratio elevated")

        return PatternResult(
            pattern_type="composite",
            pattern_name="overtraining_risk",
            score=risk_score,
            significance="high" if risk_score >= 50 else "medium" if risk_score >= 25 else "low",
            details={
                "risk_factors": factors,
                "recommendations": self.get_recovery_recommendations(risk_score)
            }
        )
```

### 2.4 Anomaly Detection

```python
async def detect_anomalies(self, user_id: str, session: AsyncSession) -> list[Anomaly]:
    """Identify unusual values based on personal baselines."""

    anomalies = []

    # Get baselines
    baselines = await self.baseline_service.get_all_baselines(user_id, session)

    # Get latest values
    latest = await self.get_latest_metrics(user_id, session)

    for metric_name, baseline in baselines.items():
        current = latest.get(metric_name)
        if current is None or baseline.std_dev is None:
            continue

        # Z-score calculation
        z_score = (current - baseline.baseline_value) / baseline.std_dev

        if abs(z_score) > 2:  # More than 2 std devs from mean
            anomalies.append(Anomaly(
                metric=metric_name,
                current_value=current,
                baseline_value=baseline.baseline_value,
                z_score=z_score,
                direction="above" if z_score > 0 else "below",
                severity="critical" if abs(z_score) > 3 else "warning"
            ))

    return anomalies
```

### 2.5 Files to Create

| File | Purpose |
|------|---------|
| `src/polar_flow_server/models/pattern.py` | PatternAnalysis model |
| `src/polar_flow_server/services/pattern.py` | Pattern detection service |
| `src/polar_flow_server/services/anomaly.py` | Anomaly detection |
| `src/polar_flow_server/api/patterns.py` | Pattern API endpoints |

---

## Phase 3: ML Models (Optional Enhancement)

**Goal:** Add predictive capabilities using scikit-learn and Prophet.

### 3.1 Prediction Types

| Prediction | Model | Features | Output |
|------------|-------|----------|--------|
| Tomorrow's Readiness | Gradient Boosting | HRV, sleep, training load | Readiness % |
| HRV Forecast (7 days) | Prophet | Historical HRV series | Predicted values |
| Optimal Training Day | Classification | Recovery metrics | Yes/No + confidence |
| Sleep Score Prediction | Random Forest | Activity, bedtime, stress | Expected score |

### 3.2 Model Service

```python
from sklearn.ensemble import GradientBoostingRegressor
from prophet import Prophet

class MLService:
    """Machine learning predictions for health metrics."""

    async def train_readiness_model(
        self, user_id: str, session: AsyncSession
    ) -> ModelTrainingResult:
        """Train personalized readiness prediction model."""

        # Gather training data (historical features + outcomes)
        features, targets = await self.prepare_readiness_dataset(user_id, session)

        if len(features) < 30:  # Need minimum data
            return ModelTrainingResult(status="insufficient_data")

        # Train model
        model = GradientBoostingRegressor(
            n_estimators=100,
            max_depth=3,
            random_state=42
        )

        # Cross-validation
        scores = cross_val_score(model, features, targets, cv=5)

        # Final training
        model.fit(features, targets)

        # Save model (using joblib for safe serialization)
        await self.save_model(user_id, "readiness", model, session)

        return ModelTrainingResult(
            status="trained",
            model_type="gradient_boosting",
            cv_score_mean=scores.mean(),
            cv_score_std=scores.std(),
            feature_importance=dict(zip(
                self.readiness_features,
                model.feature_importances_
            ))
        )

    async def predict_readiness(
        self, user_id: str, session: AsyncSession
    ) -> ReadinessPrediction:
        """Predict readiness for tomorrow."""

        model = await self.load_model(user_id, "readiness", session)
        if model is None:
            # Fall back to rule-based
            return await self.rule_based_readiness(user_id, session)

        # Get current feature values
        features = await self.get_current_features(user_id, session)

        # Predict
        readiness = model.predict([features])[0]

        return ReadinessPrediction(
            score=readiness,
            confidence=self.calculate_confidence(model, features),
            factors=self.explain_prediction(model, features)
        )

    async def forecast_hrv(
        self, user_id: str, days: int, session: AsyncSession
    ) -> HRVForecast:
        """7-day HRV forecast using Prophet."""

        # Get historical HRV
        hrv_history = await self.get_hrv_history(user_id, days=90, session=session)

        if len(hrv_history) < 30:
            return HRVForecast(status="insufficient_data")

        # Prepare for Prophet
        df = pd.DataFrame({
            "ds": [h.date for h in hrv_history],
            "y": [h.hrv for h in hrv_history]
        })

        # Train Prophet model
        model = Prophet(
            yearly_seasonality=False,
            weekly_seasonality=True,
            daily_seasonality=False
        )
        model.fit(df)

        # Forecast
        future = model.make_future_dataframe(periods=days)
        forecast = model.predict(future)

        return HRVForecast(
            predictions=[
                HRVPrediction(
                    date=row.ds,
                    predicted=row.yhat,
                    lower=row.yhat_lower,
                    upper=row.yhat_upper
                )
                for _, row in forecast.tail(days).iterrows()
            ],
            trend=self.calculate_trend(forecast)
        )
```

### 3.3 Model Storage

```python
class UserModel(Base):
    """Stored ML models for users."""

    __tablename__ = "user_models"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(50), index=True)
    model_type: Mapped[str] = mapped_column(String(50))  # "readiness", "hrv_forecast"

    # Model data (serialized with joblib - safe for sklearn models)
    model_data: Mapped[bytes] = mapped_column(LargeBinary)

    # Metadata
    trained_at: Mapped[datetime] = mapped_column(server_default=func.now())
    training_samples: Mapped[int] = mapped_column(default=0)
    cv_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    feature_importance: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "model_type", name="uq_user_model"),
    )
```

**Note:** Model serialization uses `joblib` (scikit-learn's recommended serializer) which is safe for sklearn models. Models are only loaded from the database for the same user who created them.

### 3.4 Dependencies to Add

```toml
# pyproject.toml additions
[project.optional-dependencies]
ml = [
    "scikit-learn>=1.4.0",
    "prophet>=1.1.5",
    "pandas>=2.0.0",
    "joblib>=1.3.0",  # Safe model serialization
]
```

### 3.5 Files to Create

| File | Purpose |
|------|---------|
| `src/polar_flow_server/models/user_model.py` | UserModel for stored ML models |
| `src/polar_flow_server/services/ml.py` | ML training and prediction |
| `src/polar_flow_server/api/predictions.py` | Prediction API endpoints |

---

## Phase 4: Insights API

**Goal:** Package all analytics into a single, coach-friendly API response.

### 4.1 Unified Insights Response

```python
@dataclass
class UserInsights:
    """Complete insights package for coaching layer."""

    # Current state
    current_metrics: CurrentMetrics

    # Baselines comparison
    baselines: dict[str, BaselineComparison]

    # Detected patterns
    patterns: list[Pattern]

    # Anomalies (if any)
    anomalies: list[Anomaly]

    # Predictions (if ML enabled)
    predictions: Predictions | None

    # Pre-built observations (natural language)
    observations: list[Observation]

    # Suggested actions
    suggestions: list[Suggestion]
```

### 4.2 Observations Generator

The key innovation: convert data into natural language observations that the LLM can use.

```python
class ObservationGenerator:
    """Generate natural language observations from analytics."""

    def generate_observations(self, insights: dict) -> list[Observation]:
        """Convert metrics, patterns, anomalies into observations."""

        observations = []

        # HRV observations
        hrv = insights["baselines"]["hrv_rmssd"]
        if hrv["percent_of_baseline"] < 85:
            observations.append(Observation(
                category="recovery",
                priority="high",
                fact=f"HRV is {100 - hrv['percent_of_baseline']:.0f}% below personal baseline",
                context=f"Current: {hrv['current']:.0f}ms, Baseline: {hrv['baseline']:.0f}ms",
                trend=hrv["trend"]
            ))

        # Sleep observations
        sleep = insights["baselines"]["sleep_score"]
        if sleep["trend"] == "declining" and sleep["trend_days"] >= 3:
            observations.append(Observation(
                category="sleep",
                priority="medium",
                fact=f"Sleep quality has been declining for {sleep['trend_days']} consecutive days",
                context=f"Average score this week: {sleep['weekly_avg']:.0f}",
                trend="declining"
            ))

        # Training load observations
        load = insights["patterns"].get("training_load_ratio")
        if load and load["score"] > 1.3:
            observations.append(Observation(
                category="training",
                priority="high",
                fact=f"Training load ratio is {load['score']:.2f} (above recommended 1.3)",
                context="Acute training load significantly exceeds chronic fitness",
                trend="increasing"
            ))

        # Anomaly observations
        for anomaly in insights["anomalies"]:
            observations.append(Observation(
                category="anomaly",
                priority="critical" if anomaly["severity"] == "critical" else "high",
                fact=f"{anomaly['metric']} is {abs(anomaly['z_score']):.1f} standard deviations {anomaly['direction']} normal",
                context=f"Current: {anomaly['current']}, Normal range: {anomaly['baseline']} +/- {anomaly['std_dev']}",
                trend="anomalous"
            ))

        # Positive observations too
        if hrv["percent_of_baseline"] > 105:
            observations.append(Observation(
                category="recovery",
                priority="positive",
                fact=f"HRV is {hrv['percent_of_baseline'] - 100:.0f}% above baseline - excellent recovery",
                context="Body is well-recovered and ready for training",
                trend="positive"
            ))

        return sorted(observations, key=lambda x: self.priority_order(x.priority))
```

### 4.3 Insights API Endpoint

```
GET /users/{user_id}/insights
  Query params:
    - include_predictions: bool (requires ML models)
    - include_raw_data: bool (for debugging)
    - observation_limit: int (default 10)

  Response:
  {
    "generated_at": "2024-01-15T10:30:00Z",
    "data_freshness": "2024-01-15T06:00:00Z",

    "current_metrics": {
      "hrv": 45,
      "sleep_score": 78,
      "resting_hr": 52,
      "training_readiness": 72
    },

    "baselines": {
      "hrv_rmssd": {
        "current": 45,
        "baseline": 52,
        "percent_of_baseline": 86.5,
        "trend": "declining",
        "trend_days": 3,
        "status": "below_normal"
      }
    },

    "patterns": [
      {
        "name": "overtraining_risk",
        "score": 45,
        "significance": "medium",
        "factors": ["HRV declining", "High training load"]
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
        "category": "training",
        "priority": "medium",
        "fact": "Training load has been high for 3 consecutive days",
        "context": "Consider a recovery day",
        "trend": "stable"
      }
    ],

    "suggestions": [
      {
        "action": "rest_day",
        "confidence": 0.85,
        "reason": "HRV below baseline + high training load"
      }
    ]
  }
```

### 4.4 Files to Create

| File | Purpose |
|------|---------|
| `src/polar_flow_server/services/insights.py` | Insights aggregation |
| `src/polar_flow_server/services/observations.py` | Observation generator |
| `src/polar_flow_server/api/insights.py` | Insights API endpoint |
| `src/polar_flow_server/schemas/insights.py` | Pydantic response schemas |

---

## Implementation Priority

### Immediate (Phase 1) - Foundation
1. UserBaseline model and migration
2. Baseline calculation service (HRV, sleep, HR)
3. Baselines API endpoints
4. Background task to recalculate daily

### Short-term (Phase 2) - Value Add
1. Pattern detection service
2. Anomaly detection
3. Overtraining risk score
4. Patterns API

### Medium-term (Phase 4) - Integration Ready
1. Insights aggregation service
2. Observations generator
3. Unified insights API
4. Laravel integration docs

### Long-term (Phase 3) - Advanced
1. ML model infrastructure (optional)
2. Readiness predictions
3. HRV forecasting
4. Model retraining scheduler

---

## Success Criteria

| Metric | Target |
|--------|--------|
| Baseline calculation latency | < 500ms |
| Insights API response time | < 200ms |
| Pattern detection accuracy | > 80% correlation significance |
| Anomaly false positive rate | < 10% |
| API uptime | 99.9% |

## Tech Stack Additions

| Component | Choice | Reason |
|-----------|--------|--------|
| Statistics | Python `statistics` | No deps, simple |
| Correlations | `scipy.stats` | Industry standard |
| Data manipulation | `polars` (existing) | Fast, memory-efficient |
| ML (optional) | `scikit-learn` | Proven, well-documented |
| Time series (optional) | `prophet` | Facebook's proven forecasting |
| Model serialization | `joblib` | Safe, sklearn-native |

---

## Migration Path

```
v0.2.0 (current)
    |
    v
v0.3.0 - Phase 1: Baselines
    - UserBaseline model
    - Baseline service
    - /baselines API
    |
    v
v0.4.0 - Phase 2: Patterns
    - PatternAnalysis model
    - Pattern detection
    - Anomaly detection
    - /patterns API
    |
    v
v0.5.0 - Phase 4: Insights API
    - Observations generator
    - /insights unified API
    - Laravel integration docs
    |
    v
v1.0.0 - Production Ready
    - Full test coverage
    - Performance optimized
    - Documentation complete
    |
    v
v1.x.x - Phase 3: ML (optional)
    - UserModel storage
    - Prediction service
    - /predictions API
```

---

## Questions to Resolve

1. **Baseline recalculation frequency**: Daily? On each sync? Background task?
2. **ML model storage**: PostgreSQL binary? Separate model store? S3?
3. **Observation language**: English only? Localization needed?
4. **Historical data requirements**: Minimum days before analytics available?
5. **Laravel caching strategy**: Cache insights responses? TTL?

---

## References

- [ADR-001: Per-User API Keys](docs/adr/001-per-user-api-keys.md)
- [Architecture Overview](docs/architecture.md)
- [polar-flow SDK](https://github.com/StuMason/polar-flow)
- [Polar AccessLink API Docs](https://www.polar.com/accesslink-api/)
