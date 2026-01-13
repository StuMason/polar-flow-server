"""Sync log model for comprehensive audit trail of all sync operations.

This module provides complete visibility into every sync attempt, enabling:
- Debugging sync failures with full context
- Monitoring sync performance and success rates
- Tracking rate limit usage across the Polar API
- Auditing data freshness per user

Every sync operation - whether triggered by scheduler, manual API call,
or webhook - gets logged here with full context.
"""

from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from polar_flow_server.models.base import Base


class SyncStatus(str, Enum):
    """Status of a sync operation.

    Attributes:
        STARTED: Sync has begun but not completed
        SUCCESS: All data types synced successfully
        PARTIAL: Some data types synced, others failed
        FAILED: Sync failed completely
        SKIPPED: Sync was skipped (e.g., rate limited, no token)
    """

    STARTED = "started"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class SyncErrorType(str, Enum):
    """Categorized error types for consistent error handling.

    These categories enable:
    - Appropriate retry strategies per error type
    - Clear dashboards showing error distribution
    - Automated alerting on specific error patterns

    Attributes:
        TOKEN_EXPIRED: OAuth token has expired, user needs to re-authenticate
        TOKEN_INVALID: Token is malformed or unrecognized
        TOKEN_REVOKED: User revoked access in Polar settings
        RATE_LIMITED_15M: Hit 15-minute rate limit, backoff needed
        RATE_LIMITED_24H: Hit 24-hour rate limit, longer backoff needed
        API_UNAVAILABLE: Polar API is down or unreachable
        API_TIMEOUT: Request timed out waiting for response
        API_ERROR: Polar API returned an error response
        INVALID_RESPONSE: Response didn't match expected schema
        TRANSFORM_ERROR: Failed to transform API data to our models
        DATABASE_ERROR: Failed to write to database
        INTERNAL_ERROR: Unexpected internal error
    """

    # Authentication errors
    TOKEN_EXPIRED = "token_expired"
    TOKEN_INVALID = "token_invalid"
    TOKEN_REVOKED = "token_revoked"

    # Rate limiting
    RATE_LIMITED_15M = "rate_limited_15m"
    RATE_LIMITED_24H = "rate_limited_24h"

    # API errors
    API_UNAVAILABLE = "api_unavailable"
    API_TIMEOUT = "api_timeout"
    API_ERROR = "api_error"

    # Data errors
    INVALID_RESPONSE = "invalid_response"
    TRANSFORM_ERROR = "transform_error"

    # Internal errors
    DATABASE_ERROR = "database_error"
    INTERNAL_ERROR = "internal_error"


class SyncTrigger(str, Enum):
    """What initiated the sync operation.

    Attributes:
        SCHEDULER: Automatic sync from background scheduler
        MANUAL: User/admin triggered via API endpoint
        WEBHOOK: Triggered by Polar webhook (future)
        STARTUP: Initial sync on application startup
    """

    SCHEDULER = "scheduler"
    MANUAL = "manual"
    WEBHOOK = "webhook"
    STARTUP = "startup"


class SyncPriority(str, Enum):
    """Priority level for sync queue ordering.

    Higher priority syncs are processed first when queue is backlogged.

    Attributes:
        CRITICAL: Token expiring soon or hasn't synced in 48h+
        HIGH: Active user, hasn't synced in 12h+
        NORMAL: Regular user, hasn't synced in 24h+
        LOW: Dormant user, hasn't synced in 7d+
    """

    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class SyncLog(Base):
    """Complete audit trail of every sync attempt.

    This table is the single source of truth for understanding what happened
    during any sync operation. It captures timing, results, errors, rate limits,
    and follow-up analytics processing.

    Example queries:
        # Find all failed syncs in last 24 hours
        SELECT * FROM sync_logs
        WHERE status = 'failed'
        AND started_at > NOW() - INTERVAL '24 hours'
        ORDER BY started_at DESC;

        # Get sync success rate by user
        SELECT user_id,
               COUNT(*) FILTER (WHERE status = 'success') as successes,
               COUNT(*) as total,
               ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'success') / COUNT(*), 2) as success_rate
        FROM sync_logs
        GROUP BY user_id;

        # Find rate limit issues
        SELECT * FROM sync_logs
        WHERE error_type IN ('rate_limited_15m', 'rate_limited_24h')
        ORDER BY started_at DESC;

    Attributes:
        id: Auto-incrementing primary key
        user_id: User being synced (indexed for user-specific queries)
        job_id: UUID for correlating logs across services
        started_at: When sync began
        completed_at: When sync finished (null if still running)
        duration_ms: Total sync duration in milliseconds
        status: Current status (started/success/partial/failed/skipped)
        error_type: Categorized error type if failed
        error_message: Human-readable error description
        error_details: Full error context as JSON
        records_synced: Count of records synced per data type
        api_calls_made: Total API calls made during sync
        rate_limit_remaining_15m: Remaining 15-min quota after sync
        rate_limit_remaining_24h: Remaining 24-hour quota after sync
        baselines_recalculated: Whether baselines were updated
        patterns_detected: Whether pattern detection ran
        trigger: What initiated this sync
        priority: Queue priority level
    """

    __tablename__ = "sync_logs"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # User identification
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    job_id: Mapped[str] = mapped_column(String(36), index=True)  # UUID for correlation

    # Timing
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(20), default=SyncStatus.STARTED.value, index=True)

    # Error tracking
    error_type: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_details: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)

    # Results
    records_synced: Mapped[dict[str, int] | None] = mapped_column(JSON, nullable=True)
    api_calls_made: Mapped[int] = mapped_column(Integer, default=0)

    # Rate limit tracking (from Polar API response headers)
    rate_limit_remaining_15m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rate_limit_remaining_24h: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rate_limit_limit_15m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rate_limit_limit_24h: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Analytics follow-up
    baselines_recalculated: Mapped[bool] = mapped_column(default=False)
    patterns_detected: Mapped[bool] = mapped_column(default=False)
    insights_generated: Mapped[bool] = mapped_column(default=False)

    # Context
    trigger: Mapped[str] = mapped_column(String(20), default=SyncTrigger.MANUAL.value)
    priority: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Composite indexes for common queries
    __table_args__ = (
        Index("ix_sync_logs_user_started", "user_id", "started_at"),
        Index("ix_sync_logs_status_started", "status", "started_at"),
        Index("ix_sync_logs_error_type_started", "error_type", "started_at"),
    )

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"<SyncLog(id={self.id}, user_id='{self.user_id}', "
            f"status='{self.status}', trigger='{self.trigger}')>"
        )

    @property
    def is_complete(self) -> bool:
        """Return True if sync has finished (success or failure)."""
        return self.status in (
            SyncStatus.SUCCESS.value,
            SyncStatus.PARTIAL.value,
            SyncStatus.FAILED.value,
            SyncStatus.SKIPPED.value,
        )

    @property
    def is_successful(self) -> bool:
        """Return True if sync completed successfully."""
        return self.status == SyncStatus.SUCCESS.value

    @property
    def has_error(self) -> bool:
        """Return True if sync failed with an error."""
        return self.error_type is not None

    def complete_success(self, records: dict[str, int], api_calls: int) -> None:
        """Mark sync as successfully completed.

        Args:
            records: Dict mapping data type to count synced
            api_calls: Total API calls made
        """
        now = datetime.now(UTC)
        self.completed_at = now
        self.duration_ms = int((now - self.started_at).total_seconds() * 1000)
        self.status = SyncStatus.SUCCESS.value
        self.records_synced = records
        self.api_calls_made = api_calls

    def complete_partial(
        self, records: dict[str, int], api_calls: int, error_type: SyncErrorType, message: str
    ) -> None:
        """Mark sync as partially completed (some data synced, some failed).

        Args:
            records: Dict mapping data type to count synced
            api_calls: Total API calls made
            error_type: Type of error that caused partial failure
            message: Human-readable error message
        """
        now = datetime.now(UTC)
        self.completed_at = now
        self.duration_ms = int((now - self.started_at).total_seconds() * 1000)
        self.status = SyncStatus.PARTIAL.value
        self.records_synced = records
        self.api_calls_made = api_calls
        self.error_type = error_type.value
        self.error_message = message

    def complete_failed(
        self,
        error_type: SyncErrorType,
        message: str,
        details: dict[str, object] | None = None,
        api_calls: int = 0,
    ) -> None:
        """Mark sync as failed.

        Args:
            error_type: Categorized error type
            message: Human-readable error message
            details: Additional error context
            api_calls: API calls made before failure
        """
        now = datetime.now(UTC)
        self.completed_at = now
        self.duration_ms = int((now - self.started_at).total_seconds() * 1000)
        self.status = SyncStatus.FAILED.value
        self.error_type = error_type.value
        self.error_message = message
        self.error_details = details
        self.api_calls_made = api_calls

    def complete_skipped(self, reason: str) -> None:
        """Mark sync as skipped (not attempted).

        Args:
            reason: Why sync was skipped
        """
        now = datetime.now(UTC)
        self.completed_at = now
        self.duration_ms = 0
        self.status = SyncStatus.SKIPPED.value
        self.error_message = reason

    def update_rate_limits(
        self,
        remaining_15m: int | None,
        remaining_24h: int | None,
        limit_15m: int | None = None,
        limit_24h: int | None = None,
    ) -> None:
        """Update rate limit tracking from API response headers.

        Args:
            remaining_15m: Remaining requests in 15-min window
            remaining_24h: Remaining requests in 24-hour window
            limit_15m: Max requests in 15-min window
            limit_24h: Max requests in 24-hour window
        """
        self.rate_limit_remaining_15m = remaining_15m
        self.rate_limit_remaining_24h = remaining_24h
        if limit_15m is not None:
            self.rate_limit_limit_15m = limit_15m
        if limit_24h is not None:
            self.rate_limit_limit_24h = limit_24h

    def mark_analytics_complete(
        self, baselines: bool = False, patterns: bool = False, insights: bool = False
    ) -> None:
        """Mark post-sync analytics as completed.

        Args:
            baselines: Whether baselines were recalculated
            patterns: Whether patterns were detected
            insights: Whether insights were regenerated
        """
        self.baselines_recalculated = baselines
        self.patterns_detected = patterns
        self.insights_generated = insights
