# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[1.0.0]: https://github.com/StuMason/polar-flow-server/compare/v0.2.0...v1.0.0
[0.2.0]: https://github.com/StuMason/polar-flow-server/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/StuMason/polar-flow-server/releases/tag/v0.1.0
