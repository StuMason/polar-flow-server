"""Polar data sync service."""

from datetime import date, timedelta

import structlog
from polar_flow import PolarFlow
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.core.config import settings
from polar_flow_server.models.activity import Activity
from polar_flow_server.models.exercise import Exercise
from polar_flow_server.models.recharge import NightlyRecharge
from polar_flow_server.models.sleep import Sleep

logger = structlog.get_logger()


class SyncService:
    """Service for syncing data from Polar API.

    Accepts user_id and polar_token - doesn't assume single user.
    Works for both self-hosted (one user) and SaaS (many users).
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize sync service.

        Args:
            session: Database session
        """
        self.session = session
        self.logger = logger.bind(service="sync")

    async def sync_user(
        self,
        user_id: str,
        polar_token: str,
        days: int | None = None,
    ) -> dict[str, int]:
        """Sync all data for a user from Polar API.

        Args:
            user_id: User identifier (Polar user ID or Laravel UUID)
            polar_token: Polar API access token
            days: Number of days to sync (default from config)

        Returns:
            Dict with counts of synced records per data type

        Example:
            # Self-hosted mode
            await sync_service.sync_user(
                user_id="12345",  # From Polar API
                polar_token=load_token_from_file(),
            )

            # SaaS mode
            await sync_service.sync_user(
                user_id="uuid-from-laravel",
                polar_token=decrypt(user.polar_token),
            )
        """
        if days is None:
            days = settings.sync_days_lookback

        self.logger.info("Starting sync", user_id=user_id, days=days)

        results = {
            "sleep": 0,
            "recharge": 0,
            "activity": 0,
            "exercises": 0,
        }

        async with PolarFlow(access_token=polar_token) as client:
            # Sync sleep data
            results["sleep"] = await self._sync_sleep(client, user_id, days)

            # Sync nightly recharge
            results["recharge"] = await self._sync_recharge(client, user_id)

            # Sync daily activity
            results["activity"] = await self._sync_activity(client, user_id, days)

            # Sync exercises
            results["exercises"] = await self._sync_exercises(client, user_id)

        self.logger.info("Sync completed", user_id=user_id, results=results)
        return results

    async def _sync_sleep(
        self,
        client: PolarFlow,
        user_id: str,
        days: int,
    ) -> int:
        """Sync sleep data.

        Args:
            client: Polar Flow client
            user_id: User identifier
            days: Number of days to fetch

        Returns:
            Number of sleep records synced
        """
        self.logger.debug("Syncing sleep data", user_id=user_id, days=days)

        # Calculate since date
        since_date = date.today() - timedelta(days=days)

        # Fetch from Polar API
        sleep_data = await client.sleep.list(
            user_id="self",  # Polar API uses "self" for authenticated user
            since=str(since_date),
        )

        count = 0
        for sleep in sleep_data:
            # Convert to dict for processing
            sleep_dict = sleep.model_dump()

            # Upsert (insert or update if exists)
            stmt = insert(Sleep).values(
                user_id=user_id,
                **sleep_dict,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "date"],
                set_=sleep_dict,
            )

            await self.session.execute(stmt)
            count += 1

        return count

    async def _sync_recharge(
        self,
        client: PolarFlow,
        user_id: str,
    ) -> int:
        """Sync nightly recharge data.

        Args:
            client: Polar Flow client
            user_id: User identifier

        Returns:
            Number of recharge records synced
        """
        self.logger.debug("Syncing recharge data", user_id=user_id)

        # Fetch from Polar API (last 28 days)
        recharge_data = await client.recharge.list()

        count = 0
        for recharge in recharge_data:
            recharge_dict = recharge.model_dump()

            stmt = insert(NightlyRecharge).values(user_id=user_id, **recharge_dict)
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "date"],
                set_=recharge_dict,
            )

            await self.session.execute(stmt)
            count += 1

        return count

    async def _sync_activity(
        self,
        client: PolarFlow,
        user_id: str,
        days: int,
    ) -> int:
        """Sync daily activity data.

        Args:
            client: Polar Flow client
            user_id: User identifier
            days: Number of days to fetch

        Returns:
            Number of activity records synced
        """
        self.logger.debug("Syncing activity data", user_id=user_id, days=days)

        # Calculate date range
        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        # Fetch from Polar API
        activity_data = await client.activity.list(
            from_date=str(start_date),
            to_date=str(end_date),
        )

        count = 0
        for activity in activity_data:
            activity_dict = activity.model_dump()

            stmt = insert(Activity).values(user_id=user_id, **activity_dict)
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "date"],
                set_=activity_dict,
            )

            await self.session.execute(stmt)
            count += 1

        return count

    async def _sync_exercises(
        self,
        client: PolarFlow,
        user_id: str,
    ) -> int:
        """Sync exercises/workouts.

        Args:
            client: Polar Flow client
            user_id: User identifier

        Returns:
            Number of exercise records synced
        """
        self.logger.debug("Syncing exercises", user_id=user_id)

        # Fetch from Polar API (last 30 days)
        exercises = await client.exercises.list()

        count = 0
        for exercise in exercises:
            # Get detailed exercise data
            detailed = await client.exercises.get(exercise_id=exercise.id)
            exercise_dict = detailed.model_dump()

            polar_exercise_id = exercise_dict.pop("id")  # Remove id, use polar_exercise_id

            stmt = insert(Exercise).values(
                user_id=user_id,
                polar_exercise_id=polar_exercise_id,
                **exercise_dict,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "polar_exercise_id"],
                set_=exercise_dict,
            )

            await self.session.execute(stmt)
            count += 1

        return count
