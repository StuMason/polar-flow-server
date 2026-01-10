# Architecture & Design Decisions

## Overview

polar-flow-server is a **self-hosted health analytics server** for Polar devices, designed to be both:
1. A simple single-user deployment for self-hosters
2. A data analytics engine for a managed SaaS (with Laravel frontend)

## Core Philosophy

**Focus over breadth**: We do Polar devices extremely well, not all wearables poorly.

**Simplicity over features**: Clean architecture, minimal dependencies, easy to deploy.

**Analytics first**: We're not just storing data - we're generating insights (HRV baselines, recovery scores, ML predictions).

**Multi-user from day 1**: Same codebase serves both self-hosted and SaaS deployments.

## Competitive Analysis: Open Wearables Platform

### What is Open Wearables?

A multi-provider health data aggregation platform (like Plaid for health data). Self-hosted middleware for app developers to unify Garmin, Polar, Suunto, Whoop, Apple Health data.

**Tech Stack:**
- FastAPI + React + TypeScript
- PostgreSQL + Redis + Celery
- Single-tenant (one deployment per organization)
- Developer portal, not user dashboard

### What They Do Well

1. **Provider abstraction** - Clean strategy pattern for adding wearables
2. **Unified data model** - Normalizes workouts/sleep across providers
3. **Cursor pagination** - Scalable for large datasets
4. **Developer portal** - API key management, stats
5. **Background sync** - Celery workers for scheduled tasks
6. **Documentation** - Mintlify site with guides and examples
7. **Test factories** - factory-boy for test data generation

### What They Do Wrong

1. **Incomplete implementation** - Many endpoints return 501 Not Implemented
2. **Single-tenant only** - One deployment per organization, not true multi-user SaaS
3. **Over-engineered** - Celery + Redis + Flower for simple scheduled tasks
4. **No analytics** - Just data storage, no insights or ML
5. **No rate limiting** - Open to abuse
6. **Poor time-series design** - Single table will scale poorly
7. **No user authentication** - Users managed by API consumers only

### Why We're Different (and Better)

| Aspect | Open Wearables | polar-flow-server |
|--------|----------------|-------------------|
| **Scope** | Multi-provider middleware | Polar analytics server |
| **Use Case** | Infrastructure for developers | Analytics for end users |
| **Multi-user** | Single-org per deployment | True multi-user SaaS ready |
| **Analytics** | None (just storage) | HRV baselines, recovery, ML |
| **Complexity** | High (Celery/Redis/Docker) | Low (PostgreSQL only) |
| **Deployment** | Self-hosted platform | Self-hosted OR managed SaaS |
| **Type Safety** | Experimental `ty` checker | mypy strict mode |
| **Test Coverage** | Unknown | 90%+ enforced |
| **API Coverage** | Partial (501s everywhere) | Complete Polar V3 API |

**Bottom Line**: They're solving a different problem (infrastructure for devs). We're solving analytics for users.

## Architecture Decisions

### 1. PostgreSQL Only (No DuckDB/SQLite)

**Decision**: Use PostgreSQL for both self-hosted and SaaS deployments.

**Rationale**:
- Self-hosted gets docker-compose with Postgres (no hassle)
- SaaS shares same Postgres with Laravel
- Same database = zero conditional logic in code
- Better timeseries support than SQLite
- Proper async support (no thread executor wrapping)
- Can add indexes on (user_id, date) for fast queries
- Multi-user ready out of the box

**Trade-off**: Requires docker-compose for self-hosted (vs embedded DB).

**Validation**: Open Wearables uses PostgreSQL successfully for similar workload.

### 2. Multi-User from Day 1

**Decision**: Every table includes `user_id` column, all endpoints scoped by `user_id`.

**Rationale**:
- Self-hosted: one user in database
- SaaS: many users in database
- Same codebase, no retrofitting later
- No multi-tenancy complexity (shared schema, filtered by user_id)
- Enables future growth without architectural changes

**Trade-off**: Slightly more complex than assuming single user.

**Validation**: Open Wearables is single-org only - limits their SaaS potential.

### 3. Python Analytics Engine + Laravel Frontend (for SaaS)

**Decision**: Python handles data sync and analytics, Laravel handles UI/auth/billing.

**Rationale**:
- Python excels at data processing and ML (Polars, scikit-learn, PyTorch)
- PHP/Laravel can't do ML/analytics well
- Laravel excels at auth, billing, UI (what you're confident in)
- Clean separation of concerns
- Laravel calls Python API for data retrieval

**Implementation**:
```php
// Laravel example
$response = Http::get("http://python-service:8000/api/v1/users/{$user->id}/sleep");
$sleepData = $response->json();
```

**Trade-off**: Two services instead of one monolith.

**Validation**: Common microservices pattern (auth service + data service).

### 4. Litestar over FastAPI

**Decision**: Use Litestar async web framework.

**Rationale**:
- Modern async framework (like FastAPI but newer)
- Built-in dependency injection
- Better SQLAlchemy integration
- Faster than FastAPI in benchmarks
- Active development, good docs

**Trade-off**: Smaller community than FastAPI.

**Validation**: Open Wearables uses FastAPI successfully (similar approach works).

### 5. No Celery (APScheduler Instead)

**Decision**: Use APScheduler for background sync tasks, not Celery.

**Rationale**:
- Celery requires Redis + workers + monitoring
- APScheduler runs in-process (simpler deployment)
- Good enough for scheduled sync every hour
- No distributed task queue needed (not that many users)
- Can upgrade to Celery later if needed

**Trade-off**: Can't scale workers horizontally.

**Validation**: Open Wearables uses Celery but has operational complexity we don't need yet.

### 6. HTMX Admin Panel (Not React)

**Decision**: Build self-hosted admin panel with HTMX, not React.

**Rationale**:
- Self-hosters need simple setup wizard and status dashboard
- HTMX = server-side rendering, no JavaScript build step
- No XSS via JSON parsing
- Simpler security model
- Plain and functional (not a flashy UI)
- Single-user setup on first login (like most open source tools)

**Trade-off**: Less interactive than React SPA.

**Validation**: Many successful self-hosted tools use server-side rendering (Plausible, Umami).

### 7. Strict Type Safety (mypy strict mode)

**Decision**: Enforce mypy strict mode in CI.

**Rationale**:
- Catches bugs at development time
- Self-documenting code
- Better IDE support
- Industry standard for Python type checking

**Trade-off**: More verbose code (explicit types everywhere).

**Validation**: Open Wearables uses experimental `ty` - mypy is more mature.

## What We're Building

### Phase 1: Core Infrastructure ✅ (COMPLETE)

- [x] Database models with user_id on all tables
- [x] PostgreSQL database with async SQLAlchemy
- [x] REST API endpoints scoped by user_id
- [x] Polar sync service (sleep, recharge, activity, exercises)
- [x] Docker and docker-compose setup
- [x] Full CI/CD (tests, lint, security, docs)
- [x] MkDocs documentation

### Phase 2: Admin Panel 🔄 (IN PROGRESS)

**Why this is next:**
- Validates entire stack works end-to-end
- Visual way to test API endpoints
- Useful for self-hosters
- Forces us to test sync functionality
- Simple first-time setup wizard

**Features:**
- [ ] First-time setup wizard (create user, connect Polar)
- [ ] Sync status dashboard (last sync, record counts)
- [ ] Manual sync trigger button
- [ ] Basic data visualization (sleep/HRV last 7 days)
- [ ] Settings page (sync interval, etc.)

**Tech:**
- HTMX for interactivity
- Server-side Jinja2 templates
- TailwindCSS for styling (keep it plain)
- Litestar template rendering

### Phase 3: Analytics Engine

**Why this comes after admin:**
- Needs working data pipeline first
- Admin panel helps validate data quality
- Can test analytics in UI

**Features:**
- [ ] HRV baseline calculation (7/30/60-day rolling medians)
- [ ] Recovery score algorithm (HRV + sleep + ANS charge)
- [ ] Sleep debt tracking
- [ ] Training load analysis
- [ ] Polars for fast data processing
- [ ] SQL views for pre-computed metrics

### Phase 4: MCP Server (Claude Desktop Integration)

**Why this is later:**
- Requires working analytics first
- Nice-to-have, not core functionality
- Can query data via natural language

**Features:**
- [ ] MCP server implementation
- [ ] Tools for querying user data
- [ ] Natural language health insights
- [ ] Claude Desktop config example

### Phase 5: Advanced Features (Future)

- [ ] Background scheduler (APScheduler or Celery)
- [ ] Webhook support from Polar
- [ ] Data export (CSV, JSON)
- [ ] ML predictions (injury risk, recovery time)
- [ ] API rate limiting
- [ ] Observability (metrics, tracing)

## What We're NOT Building

**Multi-provider support** - We're Polar-focused. If we expand later, we'll adopt Open Wearables' provider strategy pattern.

**Mobile app** - SaaS customers get Laravel frontend. Self-hosters use admin panel or API.

**Social features** - No following, sharing, leaderboards. This is personal analytics.

**Complex auth** - Self-hosted is simple. SaaS uses Laravel auth.

**Distributed workers** - APScheduler is enough. Celery if we really need it.

## Lessons from Open Wearables

### Steal These Ideas

1. **OAuth state management** - Store state in Redis with TTL for better security
2. **Cursor pagination** - For large datasets (when we need it)
3. **Provider strategy pattern** - If we ever add Garmin/Whoop
4. **Test factories** - factory-boy for cleaner test data
5. **Mintlify docs** - Upgrade from MkDocs Material (later)
6. **Unified data schemas** - If we add multi-provider support

### Avoid These Mistakes

1. **Incomplete endpoints** - Ship working features, not 501s
2. **Single-tenant design** - We're multi-user from day 1
3. **Over-abstraction** - Generic repository pattern is overkill
4. **Missing rate limiting** - Add protection from day 1
5. **No analytics** - Our differentiator, not just storage
6. **Poor time-series design** - Consider TimescaleDB extension if needed

## Success Metrics

**Self-hosted deployment:**
- Time to first data: < 5 minutes (docker-compose up + OAuth)
- Disk space: < 100MB for first month of data
- Memory: < 512MB RAM
- CPU: Negligible (sync runs hourly)

**SaaS deployment:**
- Support 1000+ users on single instance
- Sync latency: < 30 seconds per user
- API response time: < 100ms p95
- Database size: ~10MB per user per year

**Code quality:**
- Test coverage: >90%
- Type coverage: 100% (mypy strict)
- CI green: Always
- Docs: Complete and accurate

## Tech Stack Summary

**Core:**
- Python 3.12+
- PostgreSQL 17
- Litestar 2.14+
- SQLAlchemy 2.0 (async)
- polar-flow-api 1.1.0

**Data Processing:**
- Polars (DataFrames)
- NumPy/SciPy (analytics)

**Background Tasks:**
- APScheduler (start)
- Celery (if needed later)

**Admin UI:**
- HTMX
- Jinja2 templates
- TailwindCSS

**Development:**
- uv (package manager)
- Ruff (linting/formatting)
- mypy (type checking)
- pytest (testing)

**Deployment:**
- Docker + docker-compose
- GitHub Actions (CI/CD)
- MkDocs Material (docs)

## Conclusion

We're building a **focused, well-architected health analytics server** for Polar devices. We've learned from Open Wearables (multi-provider platform) but chosen a simpler, more focused approach.

**Next step**: Build HTMX admin panel to validate the entire stack works.
