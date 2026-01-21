# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

---

## [1.3.3] - 2026-01-21

### Fixed

**Partial Sync Failure Handling (Issue #19)**
- Sync now continues when individual Polar API endpoints fail (e.g., 403 on sleep)
- Previously, a single endpoint failure would stop the entire sync with no data saved
- Now syncs each endpoint independently - failures are captured but don't block other data

**Manual Sync Audit Logging**
- Admin "Sync Now" button now creates `SyncLog` entries for proper audit trail
- Previously, manual syncs bypassed `SyncOrchestrator` and weren't logged

### Added

- `SyncResult` dataclass to track both successful records and per-endpoint errors
- Actionable error messages for common HTTP errors:
  - 403: Guidance about Polar data sharing consent settings
  - 401: Token expiration/re-authentication needed
  - 429: Rate limit information
- Partial success UI template showing both synced data and errors
- Dynamic endpoint display in templates (all 13 data types now shown)
- API sync endpoint now returns `status: "partial"` with error details when some endpoints fail
- Expandable sync log rows in admin dashboard showing full details (records, errors, analytics, metadata)

### Changed

- `SyncService.sync_user()` now returns `SyncResult` instead of `dict[str, int]`
- `SyncOrchestrator` properly tracks partial success status in `SyncLog`
- Admin sync templates dynamically iterate over all endpoints instead of hardcoding

---

## [1.3.2] - 2026-01-20

### Fixed

- CSRF cookie configuration for proxy deployments
- Admin route CSRF exclusions

---

## [1.3.1] - 2026-01-20

### Fixed

- Version mismatch between pyproject.toml and __init__.py

---

## [1.3.0] - 2026-01-20

### Added

- MCP server integration for Claude Desktop
- Additional Polar SDK endpoints (cardio load, sleepwise, biosensing)

---

## [1.2.0] - 2026-01-13

### Added

**Admin Dashboard Analytics**
- Personal Baselines section displaying:
  - All calculated baselines (HRV, sleep score, resting HR, training load, etc.)
  - Rolling averages (7-day, 30-day) with percentage change from baseline
  - Min/max range and sample counts
  - Status indicators (ready, partial, insufficient)
- Detected Patterns section displaying:
  - Correlations (sleep-HRV, training-recovery, activity-sleep)
  - Composite scores (overtraining risk, recovery readiness)
  - Trends (HRV, sleep, fitness)
  - Statistical significance levels (high/medium/low)
  - Pattern interpretations and contributing factors
- Empty state guidance explaining analytics requirements (7+ days of data)

### Documentation
- This release makes analytics features visible in the admin dashboard
- Analytics power the `/users/{user_id}/insights` API endpoint for downstream consumers

---

## [1.1.0] - 2026-01-13

### Added

**Automatic Background Sync**
- Smart sync scheduler with APScheduler for automatic background syncing
- Rate-limit-aware orchestration respecting Polar API limits (15-min and 24-hour windows)
- Priority queue system for efficient multi-user sync:
  - CRITICAL: Users who haven't synced in 48h+ or have expiring tokens
  - HIGH: Active users, hasn't synced in 12h+
  - NORMAL: Regular users, hasn't synced in 24h+
  - LOW: Dormant users, hasn't synced in 7d+
- Comprehensive `SyncLog` model for complete audit trail of every sync operation
- Consistent error classification with `SyncErrorType` enum covering:
  - Authentication errors (TOKEN_EXPIRED, TOKEN_INVALID, TOKEN_REVOKED)
  - Rate limiting (RATE_LIMITED_15M, RATE_LIMITED_24H)
  - API errors (API_UNAVAILABLE, API_TIMEOUT, API_ERROR)
  - Data errors (INVALID_RESPONSE, TRANSFORM_ERROR)
  - Internal errors (DATABASE_ERROR, INTERNAL_ERROR)
- Post-sync analytics: Automatic baseline recalculation and pattern detection

**Admin Dashboard**
- Sync scheduler status section (running state, next run, 24h stats)
- Recent sync history table with status, duration, records synced
- Biosensing data counts (SpO2, ECG, Temperature)
- Analytics counts (Baselines, Patterns)

**Configuration**
- `SYNC_ENABLED`: Enable/disable automatic syncing (default: true)
- `SYNC_INTERVAL_MINUTES`: Sync cycle interval (default: 60)
- `SYNC_ON_STARTUP`: Run sync immediately on startup (default: false)
- `SYNC_MAX_USERS_PER_RUN`: Maximum users per sync cycle (default: 10)
- `SYNC_STAGGER_SECONDS`: Delay between user syncs (default: 5)

**Database**
- New `sync_logs` table with comprehensive fields for audit and debugging
- Composite indexes for efficient querying by user, status, and error type

### Fixed
- Alertness scale display corrected from /5 to /10 (Polar API uses 0-10 scale)

---

## [1.0.0] - 2025-01-13

First stable release of polar-flow-server - a self-hosted health analytics server for Polar devices.

### Added

**Core Infrastructure**
- REST API with user-scoped endpoints (`/api/v1/users/{user_id}/...`)
- Per-user API key authentication with Argon2 hashing
- Database models with multi-user support from day one
- Polar Flow SDK integration for automated data sync
- DuckDB support for self-hosted deployments
- PostgreSQL support for SaaS/multi-user deployments
- Alembic database migrations
- Litestar async web framework with OpenAPI documentation
- Structured logging with structlog

**Data Endpoints**
- Sleep data with sleep stages and HRV metrics
- Nightly Recharge (ANS charge, recovery metrics)
- Daily activity (steps, calories, activity zones)
- Exercises/workouts with detailed metrics
- Cardio Load tracking with acute/chronic load ratios
- Continuous heart rate data
- Activity samples (time series)

**Analytics Engine**
- Personal baselines with IQR-based anomaly detection
- Rolling averages (7-day, 30-day, 90-day windows)
- Sleep-HRV correlation analysis (Spearman)
- Overtraining risk scoring (multi-metric composite)
- Trend detection (7-day vs 30-day baseline comparison)
- Training load ratio monitoring
- Automatic anomaly alerts (warning/critical severity)

**Unified Insights API**
- Single `/users/{id}/insights` endpoint aggregating all analytics
- Feature unlock timeline based on data availability:
  - 7 days: Basic baselines
  - 21 days: Patterns and anomaly detection
  - 30 days: Extended baselines
  - 60 days: ML predictions (planned)
- Natural language observation generation for coaching layers
- Actionable suggestions based on current metrics
- Data readiness tracking with progress indicators

**Developer Experience**
- Comprehensive test suite (74+ tests)
- Type safety with mypy strict mode
- Ruff for linting and formatting
- OpenAPI schema at `/schema/openapi.json`
- Swagger UI at `/schema/swagger`
- ReDoc at `/schema/redoc`
- MkDocs Material documentation

**Deployment**
- Docker support with health checks
- CI/CD workflows (tests, lint, security, publish, docs)
- Dependabot with auto-merge for minor/patch updates

### Documentation

- Quick Start guide
- Architecture overview
- Complete API reference with examples
- ADR for per-user API key design

---

## [0.2.0] - 2025-01-10

### Added
- Pattern detection service (correlations, trends, risk scores)
- Anomaly scanning across all tracked metrics
- Cardio Load endpoints with training load ratios
- Per-user API key authentication

### Changed
- Migrated from simple token auth to per-user API keys

## [0.1.0] - 2025-01-05

### Added
- Initial project structure
- Basic REST API endpoints
- Database models for Polar data types
- Sync service foundation

[1.2.0]: https://github.com/StuMason/polar-flow-server/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/StuMason/polar-flow-server/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/StuMason/polar-flow-server/compare/v0.2.0...v1.0.0
[0.2.0]: https://github.com/StuMason/polar-flow-server/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/StuMason/polar-flow-server/releases/tag/v0.1.0
