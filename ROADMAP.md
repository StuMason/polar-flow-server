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

### 1.3 Performance Considerations

**Database indices required** (add in migration):
```sql
CREATE INDEX idx_nightly_recharge_user_date ON nightly_recharge(user_id, date);
CREATE INDEX idx_sleep_user_date ON sleep(user_id, date);
CREATE INDEX idx_activity_user_date ON activity(user_id, date);
CREATE INDEX idx_cardio_load_user_date ON cardio_load(user_id, date);
```

**Incremental calculation strategy:**
- Don't recalculate from scratch each time
- Store last calculation date, only process new data
- Use materialized views for complex aggregations if needed

### 1.4 Baseline Calculation Service

```python
from datetime import datetime, timezone

class BaselineService:
    """Calculate and update user baselines."""

    async def calculate_hrv_baseline(self, user_id: str, session: AsyncSession) -> dict:
        """Calculate HRV baselines from nightly recharge data."""

        # Use UTC for consistent timezone handling
        today_utc = datetime.now(timezone.utc).date()

        # Fetch last 90 days of HRV data
        stmt = select(NightlyRecharge.hrv, NightlyRecharge.date).where(
            NightlyRecharge.user_id == user_id,
            NightlyRecharge.hrv.isnot(None),
            NightlyRecharge.date >= today_utc - timedelta(days=90)
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

### 1.5 API Endpoints

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

### 1.6 Files to Create

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

        # Require minimum 21 samples for statistical significance
        # (14 was too small - need n >= 20 for reliable correlation)
        if len(aligned) < 21:
            return PatternResult(status="insufficient_data")

        # Use Spearman correlation - more robust for non-normal distributions
        # (HRV and sleep scores often have non-linear relationships)
        r, p_value = scipy.stats.spearmanr(aligned.sleep, aligned.hrv)

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

**Important:** Health metrics like HRV are often right-skewed (not normally distributed).
Z-score based detection produces too many false positives. Use IQR (Interquartile Range)
which is robust to non-normal distributions.

```python
async def detect_anomalies(self, user_id: str, session: AsyncSession) -> list[Anomaly]:
    """Identify unusual values using IQR method (robust to non-normal distributions)."""

    anomalies = []

    # Get historical data for IQR calculation
    history = await self.get_metric_history(user_id, days=90, session=session)

    # Get latest values
    latest = await self.get_latest_metrics(user_id, session)

    for metric_name, values in history.items():
        current = latest.get(metric_name)
        if current is None or len(values) < 14:
            continue

        # Calculate IQR (robust to outliers and non-normal distributions)
        q1 = statistics.quantiles(values, n=4)[0]  # 25th percentile
        q3 = statistics.quantiles(values, n=4)[2]  # 75th percentile
        iqr = q3 - q1
        median = statistics.median(values)

        # IQR bounds (1.5 * IQR is standard, 3 * IQR for extreme)
        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr
        extreme_lower = q1 - 3 * iqr
        extreme_upper = q3 + 3 * iqr

        if current < extreme_lower or current > extreme_upper:
            severity = "critical"
        elif current < lower_bound or current > upper_bound:
            severity = "warning"
        else:
            continue  # Not an anomaly

        anomalies.append(Anomaly(
            metric=metric_name,
            current_value=current,
            median_value=median,
            iqr_bounds=(lower_bound, upper_bound),
            direction="above" if current > median else "below",
            severity=severity
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

> **Security Note:** This phase requires careful implementation. See section 3.3 for
> secure model storage approach that avoids pickle/joblib deserialization risks.

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

        if len(features) < 60:  # Need minimum 60 days to avoid overfitting
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

        if len(hrv_history) < 60:  # Need 60+ days for reliable forecasting
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

### 3.3 Model Storage (Security-First Approach)

> **Why not pickle/joblib?** Pickle-based serialization (including joblib) can execute
> arbitrary code during deserialization. If an attacker gains database write access,
> they could inject malicious serialized objects. Loading with `joblib.load()` would
> execute the attack.

**Secure approach: Store model parameters as JSON, reconstruct on load.**

```python
class UserModel(Base):
    """Stored ML models for users - parameters only, no serialized objects."""

    __tablename__ = "user_models"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(50), index=True)
    model_type: Mapped[str] = mapped_column(String(50))  # "readiness", "hrv_forecast"

    # Model architecture and hyperparameters (safe JSON, no code execution)
    model_class: Mapped[str] = mapped_column(String(100))  # "GradientBoostingRegressor"
    hyperparameters: Mapped[dict] = mapped_column(JSON)  # {"n_estimators": 100, ...}

    # For tree-based models: store the learned structure
    # sklearn trees can export/import via get_params() and set_params()
    learned_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Metadata
    trained_at: Mapped[datetime] = mapped_column(server_default=func.now())
    training_samples: Mapped[int] = mapped_column(default=0)
    cv_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    feature_importance: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    feature_names: Mapped[list | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "model_type", name="uq_user_model"),
    )


# Whitelist of allowed model classes (prevents arbitrary class instantiation)
ALLOWED_MODELS = {
    "GradientBoostingRegressor": GradientBoostingRegressor,
    "RandomForestRegressor": RandomForestRegressor,
    "RandomForestClassifier": RandomForestClassifier,
}


async def load_model(user_id: str, model_type: str, session: AsyncSession):
    """Reconstruct model from stored parameters (no deserialization)."""
    record = await get_model_record(user_id, model_type, session)
    if not record:
        return None

    # Only allow whitelisted model classes
    if record.model_class not in ALLOWED_MODELS:
        raise ValueError(f"Unknown model class: {record.model_class}")

    # Reconstruct model from parameters (safe - no code execution)
    model_cls = ALLOWED_MODELS[record.model_class]
    model = model_cls(**record.hyperparameters)

    # For production: consider ONNX export for truly portable, safe models
    return model
```

**Alternative: ONNX format** for maximum safety and portability:
```python
# Export trained model to ONNX (framework-agnostic, no code execution)
import skl2onnx
onnx_model = skl2onnx.convert_sklearn(model, initial_types=input_types)

# Store as bytes (safe binary format, not executable)
model_onnx_bytes: Mapped[bytes] = mapped_column(LargeBinary)

# Load with ONNX Runtime (sandboxed execution)
import onnxruntime as ort
session = ort.InferenceSession(onnx_bytes)
```

### 3.4 Minimum Data Requirements

| Model | Minimum Days | Recommended | Notes |
|-------|--------------|-------------|-------|
| Readiness prediction | 60 | 90+ | 30 days causes overfitting |
| HRV forecast | 60 | 90+ | Prophet needs seasonal patterns |
| Sleep prediction | 45 | 60+ | Weekly patterns important |

### 3.5 Dependencies to Add

```toml
# pyproject.toml additions
[project.optional-dependencies]
ml = [
    "scikit-learn>=1.4.0",
    "pandas>=2.0.0",
]

# Optional: ONNX for secure model serialization
ml-onnx = [
    "skl2onnx>=1.16.0",
    "onnxruntime>=1.17.0",
]

# Optional: Prophet for time series (heavyweight - 10GB+ RAM for training)
ml-prophet = [
    "prophet>=1.1.5",
]
```

> **Note on Prophet:** Requires Stan/PyTorch backend and 10GB+ RAM during training.
> Consider lighter alternatives like `statsmodels` or `pmdarima` for resource-constrained
> deployments.

### 3.6 Files to Create

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

## Data Readiness Convention

**Problem:** Users won't have 60-90 days of data on day one. The API must gracefully
communicate what's available and what's coming.

### Feature Unlock Timeline

| Days of Data | Features Available |
|--------------|-------------------|
| 0-6 | Raw data only, no analytics |
| 7-13 | 7-day baselines (partial) |
| 14-20 | 7-day baselines, basic trends |
| 21-29 | Patterns unlock (correlations), anomaly detection |
| 30-59 | Full baselines (30-day), all patterns |
| 60+ | ML predictions unlock |
| 90+ | Full ML with seasonal patterns |

### API Response Convention

Every analytics endpoint returns a consistent structure:

```json
{
  "status": "partial",  // "ready", "partial", "unavailable"
  "data_age_days": 12,
  "user_id": "12345678",
  "generated_at": "2024-01-15T10:30:00Z",

  "feature_availability": {
    "baselines_7d": {"available": true, "message": null},
    "baselines_30d": {"available": false, "message": "Unlocks in 18 days", "unlock_at_days": 30},
    "patterns": {"available": false, "message": "Unlocks in 9 days", "unlock_at_days": 21},
    "anomaly_detection": {"available": false, "message": "Unlocks in 9 days", "unlock_at_days": 21},
    "ml_predictions": {"available": false, "message": "Unlocks in 48 days", "unlock_at_days": 60}
  },

  "unlock_progress": {
    "next_unlock": "patterns",
    "days_until_next": 9,
    "percent_to_next": 57
  },

  "baselines": {
    "hrv_rmssd": {
      "current": 45,
      "baseline_7d": 48.5,
      "baseline_30d": null,
      "status": "partial",
      "message": "30-day baseline available in 18 days"
    }
  },

  "patterns": null,

  "observations": [
    {
      "category": "onboarding",
      "priority": "info",
      "fact": "Building your personal baselines",
      "context": "Pattern detection unlocks in 9 days. Keep wearing your device!",
      "trend": null
    },
    {
      "category": "recovery",
      "priority": "medium",
      "fact": "HRV is 7% below your 7-day average",
      "context": "Based on limited data - accuracy improves over time",
      "trend": "declining"
    }
  ]
}
```

### Coach Integration Notes

The coaching layer should:

1. **Check `status` first** - if `"unavailable"`, show onboarding message
2. **Use `feature_availability`** to know what data to request
3. **Show `unlock_progress`** to encourage continued use ("2 more days until we can detect patterns!")
4. **Adjust confidence language** based on data age:
   - < 14 days: "Based on early data..."
   - 14-30 days: "Based on your recent patterns..."
   - 30+ days: "Based on your established baseline..."

### Status Endpoint

```
GET /users/{user_id}/status

{
  "user_id": "12345678",
  "data_age_days": 12,
  "first_sync": "2024-01-03T08:00:00Z",
  "last_sync": "2024-01-15T06:00:00Z",
  "sync_status": "healthy",

  "data_counts": {
    "sleep_records": 12,
    "recharge_records": 12,
    "activity_records": 12,
    "exercise_records": 8
  },

  "feature_availability": { ... },
  "unlock_progress": { ... }
}
```

---

## Implementation Plan

### Sprint 1: Foundation (Phase 1)

**Goal:** Baselines API working end-to-end

| Step | Task | Depends On |
|------|------|------------|
| 1.1 | Create `UserBaseline` model | - |
| 1.2 | Add Alembic migration with indices | 1.1 |
| 1.3 | Implement `BaselineService.calculate_hrv_baseline()` | 1.1 |
| 1.4 | Implement remaining baseline calculations | 1.3 |
| 1.5 | Create `/users/{id}/baselines` endpoint | 1.4 |
| 1.6 | Create `/users/{id}/status` endpoint | 1.1 |
| 1.7 | Add background task for daily recalculation | 1.4 |
| 1.8 | **Seed test data fixtures** (90 days) | 1.1 |
| 1.9 | Write tests against seeded data | 1.8 |

### Sprint 2: Patterns (Phase 2)

**Goal:** Pattern detection and anomalies working

| Step | Task | Depends On |
|------|------|------------|
| 2.1 | Create `PatternAnalysis` model | 1.2 |
| 2.2 | Implement Spearman correlation detection | 2.1 |
| 2.3 | Implement IQR anomaly detection | 1.4 |
| 2.4 | Implement overtraining risk score | 1.4, 2.2 |
| 2.5 | Create `/users/{id}/patterns` endpoint | 2.4 |
| 2.6 | Create `/users/{id}/anomalies` endpoint | 2.3 |
| 2.7 | Write tests with seeded edge cases | 2.5, 2.6 |

### Sprint 3: Insights API (Phase 4)

**Goal:** Unified insights endpoint for coach consumption

| Step | Task | Depends On |
|------|------|------------|
| 3.1 | Create Pydantic response schemas | - |
| 3.2 | Implement `InsightsService` aggregation | 1.4, 2.4 |
| 3.3 | Implement `ObservationGenerator` | 3.2 |
| 3.4 | Implement data readiness checks | 3.2 |
| 3.5 | Create `/users/{id}/insights` endpoint | 3.4 |
| 3.6 | Test with various data ages (7, 14, 30, 60 days) | 3.5 |
| 3.7 | Document for Laravel integration | 3.5 |

### Sprint 4: ML (Phase 3) - Optional

**Goal:** Predictive capabilities

| Step | Task | Depends On |
|------|------|------------|
| 4.1 | Create `UserModel` with JSON params storage | - |
| 4.2 | Implement model training service | 4.1 |
| 4.3 | Implement model loading with whitelist | 4.2 |
| 4.4 | Create `/users/{id}/predictions` endpoint | 4.3 |
| 4.5 | Add ONNX export option | 4.2 |
| 4.6 | Test with 90-day seeded data | 4.4 |

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
| Correlations | `scipy.stats` | Industry standard, Spearman for non-normal |
| Data manipulation | `polars` (existing) | Fast, memory-efficient |
| ML (optional) | `scikit-learn` | Proven, well-documented |
| Time series (optional) | `prophet` or `statsmodels` | Prophet powerful but heavy |
| Model serialization | JSON params or ONNX | Secure - no pickle/joblib |

---

## Testing Strategy

### Test Data Seeding

**Critical:** Tests MUST use realistic seeded data to prove endpoints work.

#### Seed Data Generator

```python
# tests/fixtures/seed_data.py
from datetime import date, timedelta
import random

def generate_realistic_hrv_data(days: int = 90, base_hrv: float = 50) -> list[dict]:
    """Generate realistic HRV data with weekly patterns and natural variation."""
    data = []
    current_date = date.today() - timedelta(days=days)

    for day in range(days):
        # Weekly pattern: lower HRV on Monday (after weekend activities)
        day_of_week = (current_date + timedelta(days=day)).weekday()
        weekly_factor = 0.95 if day_of_week == 0 else 1.0

        # Natural daily variation (±10%)
        daily_variation = random.gauss(1.0, 0.05)

        # Gradual trend (slight improvement over time)
        trend = 1 + (day / days) * 0.05

        hrv = base_hrv * weekly_factor * daily_variation * trend

        data.append({
            "date": current_date + timedelta(days=day),
            "hrv": round(hrv, 1),
            "ans_charge": random.randint(3, 5),
            "recovery_status": "ok" if hrv > 45 else "compromised"
        })

    return data


def generate_sleep_data(days: int = 90) -> list[dict]:
    """Generate realistic sleep data with consistency patterns."""
    data = []
    current_date = date.today() - timedelta(days=days)
    base_bedtime_hour = 23  # 11 PM

    for day in range(days):
        # Weekend: later bedtime
        day_of_week = (current_date + timedelta(days=day)).weekday()
        is_weekend = day_of_week >= 5

        bedtime_variation = random.gauss(0, 0.5)  # ±30 min typical
        if is_weekend:
            bedtime_variation += 1.0  # Later on weekends

        sleep_score = random.gauss(78, 8)  # Mean 78, std 8
        if is_weekend:
            sleep_score -= 5  # Worse sleep on weekends (staying up late)

        data.append({
            "date": current_date + timedelta(days=day),
            "sleep_score": max(40, min(100, round(sleep_score))),
            "total_sleep_seconds": random.randint(6*3600, 9*3600),
            "light_sleep_seconds": random.randint(2*3600, 4*3600),
            "deep_sleep_seconds": random.randint(1*3600, 2*3600),
            "rem_sleep_seconds": random.randint(1*3600, 2*3600),
        })

    return data


def generate_overtraining_scenario(days: int = 30) -> dict:
    """Generate data showing classic overtraining pattern."""
    # First 20 days: normal
    # Last 10 days: declining HRV, rising RHR, declining sleep
    return {
        "hrv": [50]*20 + [48, 46, 44, 42, 40, 38, 36, 35, 34, 33],
        "rhr": [55]*20 + [56, 57, 58, 59, 60, 61, 62, 63, 64, 65],
        "sleep_score": [80]*20 + [78, 76, 74, 72, 70, 68, 66, 65, 64, 62],
        "expected_risk_score": 75  # High risk
    }


def generate_anomaly_scenario() -> dict:
    """Generate data with known anomalies for testing IQR detection."""
    # 30 days of normal data, then an anomaly
    normal_hrv = [50 + random.gauss(0, 3) for _ in range(30)]
    return {
        "hrv": normal_hrv,
        "anomaly_value": 25,  # Way below normal - should trigger critical
        "expected_severity": "critical"
    }
```

#### Seeding Fixtures for Pytest

```python
# tests/conftest.py
import pytest
from tests.fixtures.seed_data import (
    generate_realistic_hrv_data,
    generate_sleep_data,
    generate_overtraining_scenario
)

@pytest.fixture
async def seeded_user_90_days(session):
    """Create a test user with 90 days of realistic data."""
    user_id = "test_user_90d"

    # Seed all data types
    hrv_data = generate_realistic_hrv_data(days=90)
    sleep_data = generate_sleep_data(days=90)

    for record in hrv_data:
        await session.execute(
            insert(NightlyRecharge).values(user_id=user_id, **record)
        )
    for record in sleep_data:
        await session.execute(
            insert(Sleep).values(user_id=user_id, **record)
        )

    await session.commit()
    return user_id


@pytest.fixture
async def seeded_user_14_days(session):
    """Create a test user with only 14 days - partial features."""
    user_id = "test_user_14d"
    # ... seed 14 days
    return user_id


@pytest.fixture
async def overtraining_user(session):
    """Create user showing overtraining pattern."""
    user_id = "test_overtrained"
    scenario = generate_overtraining_scenario()
    # ... seed the scenario data
    return user_id, scenario["expected_risk_score"]
```

### Unit Tests

| Component | Test Approach |
|-----------|---------------|
| Baseline calculations | Known inputs → expected outputs |
| IQR anomaly detection | Synthetic data with known outliers |
| Correlation detection | Pre-computed datasets with known r-values |
| Observation generation | Mock insights → expected text |

### Integration Tests

```python
# Example: Test baseline calculation end-to-end
async def test_hrv_baseline_calculation(seeded_user_90_days, session):
    # Act: Calculate baselines
    result = await baseline_service.calculate_hrv_baseline(seeded_user_90_days, session)

    # Assert: Should have all baselines with 90 days of data
    assert result["status"] == "ready"
    assert result["baseline_7d"] is not None
    assert result["baseline_30d"] is not None
    assert result["baseline_90d"] is not None
    assert result["sample_count"] == 90


async def test_partial_data_response(seeded_user_14_days, session):
    """Test that 14-day user gets partial response."""
    result = await insights_service.get_insights(seeded_user_14_days, session)

    assert result["status"] == "partial"
    assert result["feature_availability"]["baselines_7d"]["available"] is True
    assert result["feature_availability"]["patterns"]["available"] is False
    assert result["unlock_progress"]["next_unlock"] == "patterns"


async def test_overtraining_detection(overtraining_user, session):
    """Test that overtraining pattern is correctly detected."""
    user_id, expected_score = overtraining_user
    result = await pattern_service.detect_overtraining_risk(user_id, session)

    assert result["score"] >= expected_score - 10  # Allow some tolerance
    assert result["significance"] == "high"
    assert "HRV declining" in result["details"]["risk_factors"]
```

### ML Model Tests

- Use synthetic datasets with known patterns
- Test model reconstruction from JSON params
- Verify ONNX export/import produces same predictions
- Test with edge cases (missing data, outliers)

### Data Age Scenario Tests

| Scenario | Days | Expected Behavior |
|----------|------|-------------------|
| Brand new user | 0 | `status: "unavailable"`, onboarding message |
| Week 1 | 7 | 7-day baselines only, everything else locked |
| Week 2 | 14 | Trends available, patterns locked |
| Week 3 | 21 | Patterns unlock, correlations work |
| Month 1 | 30 | Full baselines, all patterns |
| Month 2 | 60 | ML predictions unlock |
| Month 3+ | 90 | Full functionality |

---

## Data Privacy & Compliance

### GDPR Considerations

| Requirement | Implementation |
|-------------|----------------|
| Right to access | `/users/{id}/export` endpoint exists |
| Right to deletion | Cascade delete baselines, patterns, models when user deleted |
| Data minimization | Only store computed insights, not raw analysis |
| Purpose limitation | Analytics only used for user's own coaching |

### Right to Deletion

When user requests deletion:
```python
async def delete_user_analytics(user_id: str, session: AsyncSession):
    """Delete all analytics data for user (GDPR compliance)."""
    await session.execute(delete(UserBaseline).where(UserBaseline.user_id == user_id))
    await session.execute(delete(PatternAnalysis).where(PatternAnalysis.user_id == user_id))
    await session.execute(delete(UserModel).where(UserModel.user_id == user_id))
    # Note: Raw data (sleep, activity, etc.) handled separately
```

### Data Retention

| Data Type | Retention | Reason |
|-----------|-----------|--------|
| Raw sync data | User-controlled | Their data |
| Baselines | Recalculated daily | Derived, not stored long-term |
| Patterns | 90 days | Historical context |
| ML Models | Until retrained | Requires user data to exist |

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
