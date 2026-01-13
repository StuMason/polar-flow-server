"""Polar data sync service."""

from datetime import date, timedelta

import structlog
from polar_flow import PolarFlow
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.core.config import settings
from polar_flow_server.models.activity import Activity
from polar_flow_server.models.activity_samples import ActivitySamples
from polar_flow_server.models.cardio_load import CardioLoad
from polar_flow_server.models.continuous_hr import ContinuousHeartRate
from polar_flow_server.models.ecg import ECG
from polar_flow_server.models.exercise import Exercise
from polar_flow_server.models.recharge import NightlyRecharge
from polar_flow_server.models.sleep import Sleep
from polar_flow_server.models.sleepwise_alertness import SleepWiseAlertness
from polar_flow_server.models.sleepwise_bedtime import SleepWiseBedtime
from polar_flow_server.models.spo2 import SpO2
from polar_flow_server.models.temperature import BodyTemperature, SkinTemperature
from polar_flow_server.services.baseline import BaselineService
from polar_flow_server.transformers import (
    ActivitySamplesTransformer,
    ActivityTransformer,
    BodyTemperatureTransformer,
    CardioLoadTransformer,
    ContinuousHRTransformer,
    ECGTransformer,
    ExerciseTransformer,
    RechargeTransformer,
    SkinTemperatureTransformer,
    SleepTransformer,
    SleepWiseAlertnessTransformer,
    SleepWiseBedtimeTransformer,
    SpO2Transformer,
)

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
        recalculate_baselines: bool = True,
    ) -> dict[str, int]:
        """Sync all data for a user from Polar API.

        Args:
            user_id: User identifier (Polar user ID or Laravel UUID)
            polar_token: Polar API access token
            days: Number of days to sync (default from config)
            recalculate_baselines: Whether to recalculate baselines after sync

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
            "cardio_load": 0,
            "sleepwise_alertness": 0,
            "sleepwise_bedtime": 0,
            "activity_samples": 0,
            "continuous_hr": 0,
            # Biosensing (requires compatible devices)
            "spo2": 0,
            "ecg": 0,
            "body_temperature": 0,
            "skin_temperature": 0,
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

            # Sync cardio load (requires SDK >= 1.3.0)
            if hasattr(client, "cardio_load"):
                results["cardio_load"] = await self._sync_cardio_load(client, user_id)

            # Sync SleepWise alertness (requires SDK >= 1.3.0)
            if hasattr(client, "sleepwise"):
                results["sleepwise_alertness"] = await self._sync_sleepwise_alertness(
                    client, user_id
                )
                results["sleepwise_bedtime"] = await self._sync_sleepwise_bedtime(client, user_id)

            # Sync activity samples (requires SDK >= 1.3.0)
            if hasattr(client, "activity_samples"):
                results["activity_samples"] = await self._sync_activity_samples(
                    client, user_id, days
                )

            # Sync continuous heart rate (requires SDK >= 1.3.0)
            if hasattr(client, "continuous_hr"):
                results["continuous_hr"] = await self._sync_continuous_hr(client, user_id, days)

            # Sync biosensing data (requires SDK >= 1.4.0 and compatible devices)
            if hasattr(client, "biosensing"):
                results["spo2"] = await self._sync_spo2(client, user_id)
                results["ecg"] = await self._sync_ecg(client, user_id)
                results["body_temperature"] = await self._sync_body_temperature(client, user_id)
                results["skin_temperature"] = await self._sync_skin_temperature(client, user_id)

        # Commit all changes to database
        await self.session.commit()

        # Recalculate baselines with new data
        if recalculate_baselines:
            self.logger.info("Recalculating baselines after sync", user_id=user_id)
            baseline_service = BaselineService(self.session)
            baseline_results = await baseline_service.calculate_all_baselines(user_id)
            self.logger.info(
                "Baseline recalculation complete", user_id=user_id, baselines=baseline_results
            )

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

        # Sleep endpoint has 28-day limit, cap it
        sleep_days = min(days, 28)

        # Calculate since date (subtract days-1 to get inclusive range)
        since_date = date.today() - timedelta(days=sleep_days - 1)

        # Fetch from Polar API
        sleep_data = await client.sleep.list(
            user_id=user_id,
            since=str(since_date),
        )

        count = 0
        for sleep in sleep_data:
            # Use transformer for type-safe SDK -> DB mapping
            sleep_dict = SleepTransformer.transform(sleep, user_id)

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
            # Use transformer for type-safe SDK -> DB mapping
            recharge_dict = RechargeTransformer.transform(recharge, user_id)

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

        # Activity endpoint has 28-day limit, cap it
        activity_days = min(days, 28)

        # Calculate date range (subtract days-1 to get inclusive range)
        end_date = date.today()
        start_date = end_date - timedelta(days=activity_days - 1)

        # Fetch from Polar API
        activity_data = await client.activity.list(
            from_date=str(start_date),
            to_date=str(end_date),
        )

        count = 0
        for activity in activity_data:
            # Use transformer for type-safe SDK -> DB mapping
            activity_dict = ActivityTransformer.transform(activity, user_id)

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

            # Use transformer for type-safe SDK -> DB mapping
            exercise_dict = ExerciseTransformer.transform(detailed, user_id)

            # Upsert
            stmt = insert(Exercise).values(user_id=user_id, **exercise_dict)
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "polar_exercise_id"],
                set_=exercise_dict,
            )

            await self.session.execute(stmt)
            count += 1

        return count

    async def _sync_cardio_load(
        self,
        client: PolarFlow,
        user_id: str,
    ) -> int:
        """Sync cardio load data."""
        self.logger.debug("Syncing cardio load", user_id=user_id)

        cardio_data = await client.cardio_load.list()

        count = 0
        for cardio in cardio_data:
            cardio_dict = CardioLoadTransformer.transform(cardio, user_id)

            stmt = insert(CardioLoad).values(user_id=user_id, **cardio_dict)
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "date"],
                set_=cardio_dict,
            )

            await self.session.execute(stmt)
            count += 1

        return count

    async def _sync_sleepwise_alertness(
        self,
        client: PolarFlow,
        user_id: str,
    ) -> int:
        """Sync SleepWise alertness predictions."""
        self.logger.debug("Syncing sleepwise alertness", user_id=user_id)

        alertness_data = await client.sleepwise.get_alertness()

        count = 0
        for alertness in alertness_data:
            alertness_dict = SleepWiseAlertnessTransformer.transform(alertness, user_id)

            stmt = insert(SleepWiseAlertness).values(user_id=user_id, **alertness_dict)
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "period_start_time"],
                set_=alertness_dict,
            )

            await self.session.execute(stmt)
            count += 1

        return count

    async def _sync_sleepwise_bedtime(
        self,
        client: PolarFlow,
        user_id: str,
    ) -> int:
        """Sync SleepWise circadian bedtime recommendations."""
        self.logger.debug("Syncing sleepwise bedtime", user_id=user_id)

        bedtime_data = await client.sleepwise.get_bedtime()

        count = 0
        for bedtime in bedtime_data:
            bedtime_dict = SleepWiseBedtimeTransformer.transform(bedtime, user_id)

            stmt = insert(SleepWiseBedtime).values(user_id=user_id, **bedtime_dict)
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "period_start_time"],
                set_=bedtime_dict,
            )

            await self.session.execute(stmt)
            count += 1

        return count

    async def _sync_activity_samples(
        self,
        client: PolarFlow,
        user_id: str,
        days: int,
    ) -> int:
        """Sync activity samples (minute-by-minute step data)."""
        self.logger.debug("Syncing activity samples", user_id=user_id, days=days)

        # Activity samples only returns last few days of data
        sample_days = min(days, 7)
        samples_data = await client.activity_samples.list(days=sample_days)

        count = 0
        for samples in samples_data:
            samples_dict = ActivitySamplesTransformer.transform(samples, user_id)

            stmt = insert(ActivitySamples).values(user_id=user_id, **samples_dict)
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "date"],
                set_=samples_dict,
            )

            await self.session.execute(stmt)
            count += 1

        return count

    async def _sync_continuous_hr(
        self,
        client: PolarFlow,
        user_id: str,
        days: int,
    ) -> int:
        """Sync continuous heart rate data."""
        self.logger.debug("Syncing continuous HR", user_id=user_id, days=days)

        # Continuous HR requires fetching day by day
        hr_days = min(days, 7)
        count = 0

        for i in range(hr_days):
            fetch_date = date.today() - timedelta(days=i)
            try:
                hr_data = await client.continuous_hr.get(target_date=str(fetch_date))

                # SDK returns None if no data available
                if hr_data is None:
                    self.logger.debug(
                        "No continuous HR for date",
                        date=str(fetch_date),
                    )
                    continue

                hr_dict = ContinuousHRTransformer.transform(hr_data, user_id)

                stmt = insert(ContinuousHeartRate).values(user_id=user_id, **hr_dict)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["user_id", "date"],
                    set_=hr_dict,
                )

                await self.session.execute(stmt)
                count += 1
            except Exception as e:
                # Skip days with errors
                self.logger.debug(
                    "Error fetching continuous HR for date",
                    date=str(fetch_date),
                    error=str(e),
                )

        return count

    # =========================================================================
    # Biosensing Sync Methods
    # (Requires compatible devices like Vantage V3 with Elixir sensor platform)
    # =========================================================================

    async def _sync_spo2(
        self,
        client: PolarFlow,
        user_id: str,
    ) -> int:
        """Sync SpO2 (blood oxygen) data.

        Note: Requires a device with SpO2 capability (e.g., Vantage V3).
        Returns 0 if no data available or device doesn't support SpO2.
        """
        self.logger.debug("Syncing SpO2 data", user_id=user_id)

        try:
            spo2_data = await client.biosensing.get_spo2()
        except Exception as e:
            self.logger.debug("SpO2 sync skipped", error=str(e))
            return 0

        count = 0
        for spo2 in spo2_data:
            spo2_dict = SpO2Transformer.transform(spo2, user_id)

            stmt = insert(SpO2).values(user_id=user_id, **spo2_dict)
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "test_time"],
                set_=spo2_dict,
            )

            await self.session.execute(stmt)
            count += 1

        return count

    async def _sync_ecg(
        self,
        client: PolarFlow,
        user_id: str,
    ) -> int:
        """Sync ECG (electrocardiogram) data.

        Note: Requires a device with ECG capability (e.g., Vantage V3).
        Returns 0 if no data available or device doesn't support ECG.
        """
        self.logger.debug("Syncing ECG data", user_id=user_id)

        try:
            ecg_data = await client.biosensing.get_ecg()
        except Exception as e:
            self.logger.debug("ECG sync skipped", error=str(e))
            return 0

        count = 0
        for ecg in ecg_data:
            ecg_dict = ECGTransformer.transform(ecg, user_id)

            stmt = insert(ECG).values(user_id=user_id, **ecg_dict)
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "test_time"],
                set_=ecg_dict,
            )

            await self.session.execute(stmt)
            count += 1

        return count

    async def _sync_body_temperature(
        self,
        client: PolarFlow,
        user_id: str,
    ) -> int:
        """Sync body temperature data.

        Note: Requires a device with temperature sensors.
        Returns 0 if no data available or device doesn't support temperature.
        """
        self.logger.debug("Syncing body temperature", user_id=user_id)

        try:
            temp_data = await client.biosensing.get_body_temperature()
        except Exception as e:
            self.logger.debug("Body temperature sync skipped", error=str(e))
            return 0

        count = 0
        for temp in temp_data:
            temp_dict = BodyTemperatureTransformer.transform(temp, user_id)

            stmt = insert(BodyTemperature).values(user_id=user_id, **temp_dict)
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "start_time"],
                set_=temp_dict,
            )

            await self.session.execute(stmt)
            count += 1

        return count

    async def _sync_skin_temperature(
        self,
        client: PolarFlow,
        user_id: str,
    ) -> int:
        """Sync skin temperature data.

        Note: Requires a device with skin temperature sensors.
        Returns 0 if no data available or device doesn't support this.
        """
        self.logger.debug("Syncing skin temperature", user_id=user_id)

        try:
            temp_data = await client.biosensing.get_skin_temperature()
        except Exception as e:
            self.logger.debug("Skin temperature sync skipped", error=str(e))
            return 0

        count = 0
        for temp in temp_data:
            temp_dict = SkinTemperatureTransformer.transform(temp, user_id)

            stmt = insert(SkinTemperature).values(user_id=user_id, **temp_dict)
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "sleep_date"],
                set_=temp_dict,
            )

            await self.session.execute(stmt)
            count += 1

        return count
