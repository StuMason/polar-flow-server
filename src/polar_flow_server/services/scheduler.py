"""Background sync scheduler using APScheduler.

This module provides automatic background syncing for all users at
configurable intervals. It integrates with the SyncOrchestrator to
respect rate limits and maintain audit trails.

Architecture:
    The scheduler runs as a background service that periodically
    triggers sync operations via the SyncOrchestrator.

    ┌──────────────────────────────────────────────────────────────────┐
    │                       SyncScheduler                               │
    │                                                                   │
    │  ┌──────────────┐    ┌──────────────────────────────────────────┐ │
    │  │ APScheduler  │ -> │ sync_all_users job                       │ │
    │  │ (cron/       │    │                                          │ │
    │  │  interval)   │    │  ┌────────────────────────────────────┐  │ │
    │  └──────────────┘    │  │ SyncOrchestrator                   │  │ │
    │                      │  │ - Rate limit aware                 │  │ │
    │                      │  │ - Priority queue                   │  │ │
    │                      │  │ - Full audit logging               │  │ │
    │                      │  └────────────────────────────────────┘  │ │
    │                      └──────────────────────────────────────────┘ │
    └──────────────────────────────────────────────────────────────────┘

Configuration:
    SYNC_ENABLED: Enable/disable automatic syncing
    SYNC_INTERVAL_MINUTES: How often to run sync (default: 60)
    SYNC_ON_STARTUP: Whether to sync immediately on startup
    SYNC_MAX_USERS_PER_RUN: Maximum users per sync cycle (rate limit aware)

Usage:
    # In app startup
    scheduler = SyncScheduler(db_session_factory)
    await scheduler.start()

    # In app shutdown
    await scheduler.stop()
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from polar_flow_server.core.config import settings
from polar_flow_server.models.sync_log import SyncTrigger
from polar_flow_server.services.sync_orchestrator import SyncOrchestrator

if TYPE_CHECKING:
    from apscheduler.job import Job

logger = structlog.get_logger()


class SyncScheduler:
    """Background sync scheduler for automatic user syncing.

    Manages APScheduler to periodically trigger sync operations
    for all users while respecting rate limits.

    Attributes:
        session_factory: Async session factory for database access
        scheduler: APScheduler instance
        is_running: Whether scheduler is currently running
        last_run_at: Timestamp of last sync run
        last_run_stats: Stats from last sync run
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Initialize sync scheduler.

        Args:
            session_factory: SQLAlchemy async session factory
        """
        self.session_factory = session_factory
        self.scheduler = AsyncIOScheduler()
        self.is_running = False
        self.last_run_at: datetime | None = None
        self.last_run_stats: dict[str, object] | None = None
        self._sync_job: Job | None = None
        self.logger = logger.bind(component="sync_scheduler")

    async def start(self) -> None:
        """Start the background scheduler.

        Configures and starts APScheduler with the sync job.
        If SYNC_ON_STARTUP is enabled, triggers an immediate sync.
        """
        if not settings.sync_enabled:
            self.logger.info("Sync scheduler disabled by configuration")
            return

        if self.is_running:
            self.logger.warning("Scheduler already running")
            return

        self.logger.info(
            "Starting sync scheduler",
            interval_minutes=settings.sync_interval_minutes,
            sync_on_startup=settings.sync_on_startup,
        )

        # Add the sync job
        self._sync_job = self.scheduler.add_job(
            self._run_sync_cycle,
            trigger=IntervalTrigger(minutes=settings.sync_interval_minutes),
            id="sync_all_users",
            name="Sync all Polar users",
            replace_existing=True,
            max_instances=1,  # Prevent overlapping runs
        )

        # Start the scheduler
        self.scheduler.start()
        self.is_running = True

        self.logger.info("Sync scheduler started")

        # Run immediately if configured
        if settings.sync_on_startup:
            self.logger.info("Running startup sync")
            # Run in background to not block startup
            asyncio.create_task(self._run_startup_sync())

    async def stop(self) -> None:
        """Stop the background scheduler gracefully."""
        if not self.is_running:
            return

        self.logger.info("Stopping sync scheduler")

        self.scheduler.shutdown(wait=True)
        self.is_running = False

        self.logger.info("Sync scheduler stopped")

    async def _run_startup_sync(self) -> None:
        """Run sync immediately on startup."""
        try:
            await self._run_sync_cycle(trigger=SyncTrigger.STARTUP)
        except Exception as e:
            self.logger.error("Startup sync failed", error=str(e))

    async def _run_sync_cycle(
        self,
        trigger: SyncTrigger = SyncTrigger.SCHEDULER,
    ) -> None:
        """Execute a sync cycle for all users.

        This is the main job that APScheduler calls periodically.
        It creates a new database session and uses SyncOrchestrator
        to process the sync queue.

        Args:
            trigger: What triggered this sync cycle
        """
        start_time = datetime.now(UTC)
        self.logger.info("Starting sync cycle", trigger=trigger.value)

        try:
            async with self.session_factory() as session:
                orchestrator = SyncOrchestrator(session)

                # Process sync queue
                results = await orchestrator.process_sync_queue(
                    max_users=settings.sync_max_users_per_run,
                )

                # Get stats
                stats = await orchestrator.get_sync_stats()

            # Update instance state
            end_time = datetime.now(UTC)
            duration_ms = int((end_time - start_time).total_seconds() * 1000)

            self.last_run_at = end_time
            self.last_run_stats = {
                "trigger": trigger.value,
                "users_processed": len(results),
                "successful": sum(1 for r in results if r.is_successful),
                "failed": sum(1 for r in results if r.has_error),
                "duration_ms": duration_ms,
                **stats,
            }

            self.logger.info(
                "Sync cycle complete",
                users_processed=len(results),
                successful=self.last_run_stats["successful"],
                failed=self.last_run_stats["failed"],
                duration_ms=duration_ms,
            )

        except Exception as e:
            self.logger.exception("Sync cycle failed", error=str(e))
            self.last_run_stats = {
                "trigger": trigger.value,
                "error": str(e),
                "timestamp": datetime.now(UTC).isoformat(),
            }

    async def trigger_manual_sync(self) -> dict[str, object]:
        """Manually trigger a sync cycle outside the schedule.

        Returns:
            Dict with sync results
        """
        self.logger.info("Manual sync triggered")

        await self._run_sync_cycle(trigger=SyncTrigger.MANUAL)

        return self.last_run_stats or {"status": "completed"}

    def get_status(self) -> dict[str, object]:
        """Get scheduler status for monitoring.

        Returns:
            Dict with scheduler state and stats
        """
        next_run = None
        if self._sync_job and self.is_running:
            next_run_time = self._sync_job.next_run_time
            if next_run_time:
                next_run = next_run_time.isoformat()

        return {
            "enabled": settings.sync_enabled,
            "is_running": self.is_running,
            "interval_minutes": settings.sync_interval_minutes,
            "next_run_at": next_run,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "last_run_stats": self.last_run_stats,
        }


# Global scheduler instance (initialized in app startup)
_scheduler: SyncScheduler | None = None


def get_scheduler() -> SyncScheduler | None:
    """Get the global scheduler instance.

    Returns:
        Scheduler instance or None if not initialized
    """
    return _scheduler


def set_scheduler(scheduler: SyncScheduler) -> None:
    """Set the global scheduler instance.

    Args:
        scheduler: Scheduler instance to set as global
    """
    global _scheduler
    _scheduler = scheduler
