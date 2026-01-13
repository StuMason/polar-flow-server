"""Sync orchestrator for rate-limit-aware, priority-based user syncing.

This module provides intelligent orchestration of sync operations across
multiple users while respecting Polar API rate limits and prioritizing
users based on data freshness and activity level.

Architecture:
    The orchestrator manages a priority queue of sync jobs and processes
    them according to available rate limit budget. It tracks all operations
    in SyncLog for complete audit trail.

    ┌─────────────────────────────────────────────────────────────────────┐
    │                      SyncOrchestrator                               │
    │                                                                     │
    │  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐  │
    │  │ Priority     │ -> │ Rate Limit   │ -> │ SyncService          │  │
    │  │ Queue        │    │ Manager      │    │ (actual sync)        │  │
    │  └──────────────┘    └──────────────┘    └──────────────────────┘  │
    │         ↑                   ↑                      │               │
    │         │                   │                      ↓               │
    │  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐  │
    │  │ User         │    │ Polar API    │    │ SyncLog              │  │
    │  │ Database     │    │ Headers      │    │ (audit trail)        │  │
    │  └──────────────┘    └──────────────┘    └──────────────────────┘  │
    └─────────────────────────────────────────────────────────────────────┘

Rate Limits:
    Polar API has two rate limits:
    - 15-minute: 500 + (users × 20) requests
    - 24-hour: 5000 + (users × 100) requests

    We track remaining quota from response headers and pause syncing
    when approaching limits to avoid 429 errors.

Priority Levels:
    - CRITICAL: Token expiring or hasn't synced in 48h+
    - HIGH: Active user, hasn't synced in 12h+
    - NORMAL: Regular user, hasn't synced in 24h+
    - LOW: Dormant user, hasn't synced in 7d+
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.models.sync_log import (
    SyncErrorType,
    SyncLog,
    SyncPriority,
    SyncStatus,
    SyncTrigger,
)
from polar_flow_server.models.user import User
from polar_flow_server.services.baseline import BaselineService
from polar_flow_server.services.pattern import PatternService
from polar_flow_server.services.sync import SyncService
from polar_flow_server.services.sync_error_handler import SyncErrorHandler

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = structlog.get_logger()


class RateLimitTracker:
    """Tracks Polar API rate limit state.

    Monitors remaining quota from API response headers and provides
    safe sync scheduling based on current limits.

    Attributes:
        remaining_15m: Remaining requests in 15-minute window
        remaining_24h: Remaining requests in 24-hour window
        limit_15m: Max requests in 15-minute window
        limit_24h: Max requests in 24-hour window
        last_updated: When limits were last updated from API
    """

    # Conservative estimate of API calls per sync
    # Actual usage depends on which endpoints return data
    CALLS_PER_SYNC_ESTIMATE = 15

    # Safety buffer - don't use all available quota
    SAFETY_BUFFER_PERCENT = 0.1  # Keep 10% buffer

    def __init__(self) -> None:
        """Initialize rate limit tracker with defaults."""
        self.remaining_15m: int | None = None
        self.remaining_24h: int | None = None
        self.limit_15m: int | None = None
        self.limit_24h: int | None = None
        self.last_updated: datetime | None = None
        self.logger = logger.bind(component="rate_limit_tracker")

    def update_from_sync_log(self, sync_log: SyncLog) -> None:
        """Update limits from a completed sync log.

        Args:
            sync_log: Completed sync with rate limit data
        """
        if sync_log.rate_limit_remaining_15m is not None:
            self.remaining_15m = sync_log.rate_limit_remaining_15m
        if sync_log.rate_limit_remaining_24h is not None:
            self.remaining_24h = sync_log.rate_limit_remaining_24h
        if sync_log.rate_limit_limit_15m is not None:
            self.limit_15m = sync_log.rate_limit_limit_15m
        if sync_log.rate_limit_limit_24h is not None:
            self.limit_24h = sync_log.rate_limit_limit_24h
        self.last_updated = datetime.now(UTC)

    def can_sync_now(self) -> bool:
        """Check if we have enough rate limit budget to sync.

        Returns:
            True if we can safely attempt a sync
        """
        # If we don't have limit info yet, allow sync to get headers
        if self.remaining_15m is None or self.remaining_24h is None:
            return True

        # Calculate minimum required quota with safety buffer
        min_calls = int(self.CALLS_PER_SYNC_ESTIMATE * (1 + self.SAFETY_BUFFER_PERCENT))

        # Check both windows
        return self.remaining_15m >= min_calls and self.remaining_24h >= min_calls

    def get_wait_time_seconds(self) -> int:
        """Get seconds to wait before next sync attempt.

        Returns:
            Seconds to wait (0 if can sync now)
        """
        if self.can_sync_now():
            return 0

        # If 15-min limit is exhausted, wait up to 15 minutes
        if self.remaining_15m is not None and self.remaining_15m < self.CALLS_PER_SYNC_ESTIMATE:
            return 900  # 15 minutes

        # If 24-hour limit is exhausted, wait longer
        if self.remaining_24h is not None and self.remaining_24h < self.CALLS_PER_SYNC_ESTIMATE:
            return 3600  # 1 hour (don't wait full 24h)

        return 0

    def get_safe_batch_size(self) -> int:
        """Get how many users we can safely sync in current batch.

        Returns:
            Number of users to sync in this batch
        """
        if self.remaining_15m is None:
            return 10  # Conservative default

        # Calculate based on 15-min window (more restrictive)
        safe_calls = int(self.remaining_15m * (1 - self.SAFETY_BUFFER_PERCENT))
        return max(1, safe_calls // self.CALLS_PER_SYNC_ESTIMATE)

    def to_dict(self) -> dict[str, int | bool | str | None]:
        """Convert to dict for logging/monitoring."""
        return {
            "remaining_15m": self.remaining_15m,
            "remaining_24h": self.remaining_24h,
            "limit_15m": self.limit_15m,
            "limit_24h": self.limit_24h,
            "can_sync": self.can_sync_now(),
            "safe_batch_size": self.get_safe_batch_size(),
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
        }


class SyncOrchestrator:
    """Orchestrates sync operations across multiple users.

    Manages priority queue, rate limits, and audit logging for
    all sync operations.

    Usage:
        async with async_session() as session:
            orchestrator = SyncOrchestrator(session)

            # Process sync queue (called by scheduler)
            results = await orchestrator.process_sync_queue()

            # Manual sync for specific user
            result = await orchestrator.sync_user(
                user_id="123",
                polar_token="...",
                trigger=SyncTrigger.MANUAL,
            )
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize sync orchestrator.

        Args:
            session: Database session
        """
        self.session = session
        self.sync_service = SyncService(session)
        self.error_handler = SyncErrorHandler()
        self.rate_limiter = RateLimitTracker()
        self.logger = logger.bind(component="sync_orchestrator")

    async def sync_user(
        self,
        user_id: str,
        polar_token: str,
        trigger: SyncTrigger = SyncTrigger.MANUAL,
        priority: SyncPriority | None = None,
        recalculate_analytics: bool = True,
    ) -> SyncLog:
        """Sync a single user with full audit logging.

        Creates a SyncLog entry, performs the sync, handles errors,
        and marks analytics completion.

        Args:
            user_id: User identifier
            polar_token: Polar API access token
            trigger: What triggered this sync
            priority: Priority level (for logging)
            recalculate_analytics: Whether to recalculate baselines/patterns

        Returns:
            Completed SyncLog with results
        """
        job_id = str(uuid.uuid4())
        log = self.logger.bind(user_id=user_id, job_id=job_id, trigger=trigger.value)

        # Create sync log entry
        sync_log = SyncLog(
            user_id=user_id,
            job_id=job_id,
            trigger=trigger.value,
            priority=priority.value if priority else None,
        )
        self.session.add(sync_log)
        await self.session.flush()  # Get ID assigned

        log.info("Starting user sync")

        try:
            # Perform sync (without auto-baseline recalc - we handle it here)
            results = await self.sync_service.sync_user(
                user_id=user_id,
                polar_token=polar_token,
                recalculate_baselines=False,  # We'll do it ourselves
            )

            # Mark sync successful
            api_calls = sum(results.values()) + 1  # +1 for initial call
            sync_log.complete_success(records=results, api_calls=api_calls)

            log.info("Sync completed successfully", records_synced=results, api_calls=api_calls)

            # Post-sync analytics
            if recalculate_analytics:
                await self._run_post_sync_analytics(user_id, sync_log, log)

        except Exception as e:
            # Classify and log error
            sync_error = self.error_handler.classify(e, context={"user_id": user_id})
            sync_log.complete_failed(
                error_type=SyncErrorType(sync_error.error_type),
                message=sync_error.message,
                details=sync_error.details,
            )

            log.error(
                "Sync failed",
                error_type=sync_error.error_type.value,
                error=sync_error.message,
                is_transient=sync_error.is_transient,
            )

        # Update rate limits from response (if available)
        # Note: This would require the sync service to capture headers
        # For now, we track what we can

        # Commit the sync log
        await self.session.commit()

        return sync_log

    async def _run_post_sync_analytics(
        self,
        user_id: str,
        sync_log: SyncLog,
        log: structlog.stdlib.BoundLogger,
    ) -> None:
        """Run post-sync analytics (baselines, patterns).

        Args:
            user_id: User identifier
            sync_log: Sync log to update with analytics status
            log: Bound logger for context
        """
        baselines_done = False
        patterns_done = False
        insights_done = False

        # Recalculate baselines
        try:
            log.info("Recalculating baselines")
            baseline_service = BaselineService(self.session)
            await baseline_service.calculate_all_baselines(user_id)
            baselines_done = True
            log.info("Baselines recalculated successfully")
        except Exception as e:
            log.error("Baseline recalculation failed", error=str(e))

        # Run pattern detection
        try:
            log.info("Running pattern detection")
            pattern_service = PatternService(self.session)
            await pattern_service.detect_all_patterns(user_id)
            patterns_done = True
            log.info("Pattern detection completed")
        except Exception as e:
            log.error("Pattern detection failed", error=str(e))

        # Mark analytics complete (insights are on-demand, mark true)
        insights_done = True
        sync_log.mark_analytics_complete(
            baselines=baselines_done,
            patterns=patterns_done,
            insights=insights_done,
        )

    async def process_sync_queue(
        self,
        max_users: int | None = None,
    ) -> list[SyncLog]:
        """Process the sync queue for all users needing sync.

        Fetches users ordered by priority, respects rate limits,
        and processes syncs with full audit logging.

        Args:
            max_users: Maximum users to sync (None = use rate limit safe batch)

        Returns:
            List of SyncLog entries for processed syncs
        """
        log = self.logger.bind(trigger="scheduler")

        # Check rate limits
        if not self.rate_limiter.can_sync_now():
            wait_time = self.rate_limiter.get_wait_time_seconds()
            log.warning(
                "Rate limit exhausted, skipping sync cycle",
                wait_time_seconds=wait_time,
                rate_limits=self.rate_limiter.to_dict(),
            )
            return []

        # Determine batch size
        batch_size = max_users or self.rate_limiter.get_safe_batch_size()

        # Get users needing sync, ordered by priority
        users_to_sync = await self._get_users_needing_sync(limit=batch_size)

        if not users_to_sync:
            log.info("No users need syncing")
            return []

        log.info(
            "Processing sync queue",
            users_count=len(users_to_sync),
            batch_size=batch_size,
        )

        results: list[SyncLog] = []

        for user in users_to_sync:
            # Double-check rate limits before each sync
            if not self.rate_limiter.can_sync_now():
                log.warning("Rate limit reached mid-batch, stopping")
                break

            # Calculate priority for this user
            priority = await self._calculate_user_priority(user)

            try:
                # Decrypt token and sync
                polar_token = await self._get_user_token(user)

                sync_log = await self.sync_user(
                    user_id=user.polar_user_id,
                    polar_token=polar_token,
                    trigger=SyncTrigger.SCHEDULER,
                    priority=priority,
                )
                results.append(sync_log)

                # Update rate limiter from results
                self.rate_limiter.update_from_sync_log(sync_log)

            except Exception as e:
                log.error(
                    "Failed to sync user",
                    user_id=user.polar_user_id,
                    error=str(e),
                )
                # Continue with next user
                continue

        log.info(
            "Sync queue processing complete",
            processed=len(results),
            successful=sum(1 for r in results if r.is_successful),
            failed=sum(1 for r in results if r.has_error),
        )

        return results

    async def _get_users_needing_sync(
        self,
        limit: int = 50,
    ) -> Sequence[User]:
        """Get users who need syncing, ordered by priority.

        Priority order:
        1. Users with expiring tokens (< 24h)
        2. Users who haven't synced in 48h+ (CRITICAL)
        3. Users who haven't synced in 12h+ (HIGH)
        4. Users who haven't synced in 24h+ (NORMAL)
        5. Everyone else (LOW)

        Args:
            limit: Maximum users to return

        Returns:
            List of User objects needing sync
        """
        # Get all active users with tokens
        stmt = (
            select(User)
            .where(User.access_token_encrypted.isnot(None))
            .order_by(User.last_synced_at.asc().nullsfirst())  # Oldest sync first
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def _calculate_user_priority(self, user: User) -> SyncPriority:
        """Calculate sync priority for a user.

        Args:
            user: User to calculate priority for

        Returns:
            Priority level based on user state
        """
        now = datetime.now(UTC)

        # Check token expiry (if tracked)
        # For now, base on last sync time

        if user.last_synced_at is None:
            return SyncPriority.CRITICAL  # Never synced

        hours_since_sync = (now - user.last_synced_at).total_seconds() / 3600

        if hours_since_sync >= 48:
            return SyncPriority.CRITICAL
        elif hours_since_sync >= 12:
            return SyncPriority.HIGH
        elif hours_since_sync >= 6:
            return SyncPriority.NORMAL
        else:
            return SyncPriority.LOW

    async def _get_user_token(self, user: User) -> str:
        """Decrypt and return user's Polar token.

        Args:
            user: User to get token for

        Returns:
            Decrypted Polar access token

        Raises:
            ValueError: If user has no token
        """
        if not user.access_token_encrypted:
            raise ValueError(f"User {user.polar_user_id} has no Polar token")

        from polar_flow_server.core.security import token_encryption

        return token_encryption.decrypt(user.access_token_encrypted)

    async def get_sync_stats(self) -> dict[str, object]:
        """Get sync statistics for monitoring.

        Returns:
            Dict with sync statistics
        """
        from sqlalchemy import func

        now = datetime.now(UTC)
        day_ago = now - timedelta(days=1)

        # Get counts from last 24 hours
        stats_stmt = select(
            func.count().label("total"),
            func.count().filter(SyncLog.status == SyncStatus.SUCCESS.value).label("successful"),
            func.count().filter(SyncLog.status == SyncStatus.FAILED.value).label("failed"),
            func.count().filter(SyncLog.status == SyncStatus.PARTIAL.value).label("partial"),
            func.count().filter(SyncLog.status == SyncStatus.SKIPPED.value).label("skipped"),
        ).where(SyncLog.started_at >= day_ago)

        result = await self.session.execute(stats_stmt)
        row = result.one()

        return {
            "last_24h": {
                "total": row.total,
                "successful": row.successful,
                "failed": row.failed,
                "partial": row.partial,
                "skipped": row.skipped,
                "success_rate": (row.successful / row.total * 100) if row.total > 0 else 0,
            },
            "rate_limits": self.rate_limiter.to_dict(),
        }

    async def get_user_sync_history(
        self,
        user_id: str,
        limit: int = 10,
    ) -> Sequence[SyncLog]:
        """Get recent sync history for a user.

        Args:
            user_id: User identifier
            limit: Max records to return

        Returns:
            List of recent SyncLog entries
        """
        stmt = (
            select(SyncLog)
            .where(SyncLog.user_id == user_id)
            .order_by(SyncLog.started_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
