"""Baseline calculation service for user health metrics."""

from datetime import UTC, date, datetime, timedelta
from statistics import mean, median, quantiles, stdev

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.models.baseline import BaselineStatus, MetricName, UserBaseline
from polar_flow_server.models.cardio_load import CardioLoad
from polar_flow_server.models.recharge import NightlyRecharge
from polar_flow_server.models.sleep import Sleep

logger = structlog.get_logger()

# Minimum samples required for different status levels
MIN_SAMPLES_READY = 21  # Full baseline (3 weeks)
MIN_SAMPLES_PARTIAL = 7  # Partial baseline (1 week)


class BaselineService:
    """Service for calculating and managing user baselines.

    Baselines are personal reference values computed from historical data.
    They enable anomaly detection and personalized insights.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize baseline service.

        Args:
            session: Database session
        """
        self.session = session
        self.logger = logger.bind(service="baseline")

    async def calculate_all_baselines(self, user_id: str) -> dict[str, str]:
        """Calculate all baselines for a user.

        Args:
            user_id: User identifier

        Returns:
            Dict mapping metric names to their status
        """
        self.logger.info("Calculating all baselines", user_id=user_id)

        results = {}

        # HRV baseline from nightly recharge
        hrv_status = await self.calculate_hrv_baseline(user_id)
        results[MetricName.HRV_RMSSD.value] = hrv_status

        # Sleep score baseline
        sleep_status = await self.calculate_sleep_score_baseline(user_id)
        results[MetricName.SLEEP_SCORE.value] = sleep_status

        # Resting heart rate baseline
        rhr_status = await self.calculate_resting_hr_baseline(user_id)
        results[MetricName.RESTING_HR.value] = rhr_status

        # Training load baselines
        load_status = await self.calculate_training_load_baseline(user_id)
        results[MetricName.TRAINING_LOAD.value] = load_status

        ratio_status = await self.calculate_training_load_ratio_baseline(user_id)
        results[MetricName.TRAINING_LOAD_RATIO.value] = ratio_status

        await self.session.commit()

        self.logger.info("Baseline calculation complete", user_id=user_id, results=results)
        return results

    async def calculate_hrv_baseline(self, user_id: str) -> str:
        """Calculate HRV RMSSD baseline from nightly recharge data.

        HRV data is right-skewed, so we use IQR-based statistics for
        robust anomaly detection rather than standard deviation.

        Args:
            user_id: User identifier

        Returns:
            Baseline status (ready, partial, insufficient)
        """
        self.logger.debug("Calculating HRV baseline", user_id=user_id)

        # Query last 90 days of HRV data
        since_date = datetime.now(UTC).date() - timedelta(days=90)

        stmt = (
            select(NightlyRecharge.date, NightlyRecharge.hrv_avg)
            .where(NightlyRecharge.user_id == user_id)
            .where(NightlyRecharge.date >= since_date)
            .where(NightlyRecharge.hrv_avg.isnot(None))
            .order_by(NightlyRecharge.date.desc())
        )

        result = await self.session.execute(stmt)
        rows = result.fetchall()

        # Extract values and dates
        values = [float(row.hrv_avg) for row in rows]
        dates = [row.date for row in rows]

        return await self._upsert_baseline(
            user_id=user_id,
            metric_name=MetricName.HRV_RMSSD,
            values=values,
            dates=dates,
        )

    async def calculate_sleep_score_baseline(self, user_id: str) -> str:
        """Calculate sleep score baseline.

        Args:
            user_id: User identifier

        Returns:
            Baseline status
        """
        self.logger.debug("Calculating sleep score baseline", user_id=user_id)

        since_date = datetime.now(UTC).date() - timedelta(days=90)

        stmt = (
            select(Sleep.date, Sleep.sleep_score)
            .where(Sleep.user_id == user_id)
            .where(Sleep.date >= since_date)
            .where(Sleep.sleep_score.isnot(None))
            .order_by(Sleep.date.desc())
        )

        result = await self.session.execute(stmt)
        rows = result.fetchall()

        values = [float(row.sleep_score) for row in rows]
        dates = [row.date for row in rows]

        return await self._upsert_baseline(
            user_id=user_id,
            metric_name=MetricName.SLEEP_SCORE,
            values=values,
            dates=dates,
        )

    async def calculate_resting_hr_baseline(self, user_id: str) -> str:
        """Calculate resting heart rate baseline from nightly recharge.

        Uses heart_rate_avg from nightly recharge which is measured
        during sleep and represents resting heart rate.

        Args:
            user_id: User identifier

        Returns:
            Baseline status
        """
        self.logger.debug("Calculating resting HR baseline", user_id=user_id)

        since_date = datetime.now(UTC).date() - timedelta(days=90)

        stmt = (
            select(NightlyRecharge.date, NightlyRecharge.heart_rate_avg)
            .where(NightlyRecharge.user_id == user_id)
            .where(NightlyRecharge.date >= since_date)
            .where(NightlyRecharge.heart_rate_avg.isnot(None))
            .order_by(NightlyRecharge.date.desc())
        )

        result = await self.session.execute(stmt)
        rows = result.fetchall()

        values = [float(row.heart_rate_avg) for row in rows]
        dates = [row.date for row in rows]

        return await self._upsert_baseline(
            user_id=user_id,
            metric_name=MetricName.RESTING_HR,
            values=values,
            dates=dates,
        )

    async def calculate_training_load_baseline(self, user_id: str) -> str:
        """Calculate training load baseline from cardio load data.

        Args:
            user_id: User identifier

        Returns:
            Baseline status
        """
        self.logger.debug("Calculating training load baseline", user_id=user_id)

        since_date = datetime.now(UTC).date() - timedelta(days=90)

        stmt = (
            select(CardioLoad.date, CardioLoad.cardio_load)
            .where(CardioLoad.user_id == user_id)
            .where(CardioLoad.date >= since_date)
            .where(CardioLoad.cardio_load.isnot(None))
            .where(CardioLoad.cardio_load > 0)  # Exclude -1.0 (not available)
            .order_by(CardioLoad.date.desc())
        )

        result = await self.session.execute(stmt)
        rows = result.fetchall()

        values = [float(row.cardio_load) for row in rows]
        dates = [row.date for row in rows]

        return await self._upsert_baseline(
            user_id=user_id,
            metric_name=MetricName.TRAINING_LOAD,
            values=values,
            dates=dates,
        )

    async def calculate_training_load_ratio_baseline(self, user_id: str) -> str:
        """Calculate training load ratio baseline.

        The load ratio (acute:chronic) is a key indicator of training readiness.

        Args:
            user_id: User identifier

        Returns:
            Baseline status
        """
        self.logger.debug("Calculating training load ratio baseline", user_id=user_id)

        since_date = datetime.now(UTC).date() - timedelta(days=90)

        stmt = (
            select(CardioLoad.date, CardioLoad.cardio_load_ratio)
            .where(CardioLoad.user_id == user_id)
            .where(CardioLoad.date >= since_date)
            .where(CardioLoad.cardio_load_ratio.isnot(None))
            .where(CardioLoad.cardio_load_ratio > 0)  # Exclude -1.0
            .order_by(CardioLoad.date.desc())
        )

        result = await self.session.execute(stmt)
        rows = result.fetchall()

        values = [float(row.cardio_load_ratio) for row in rows]
        dates = [row.date for row in rows]

        return await self._upsert_baseline(
            user_id=user_id,
            metric_name=MetricName.TRAINING_LOAD_RATIO,
            values=values,
            dates=dates,
        )

    async def _upsert_baseline(
        self,
        user_id: str,
        metric_name: MetricName,
        values: list[float],
        dates: list[date],
    ) -> str:
        """Calculate statistics and upsert baseline record.

        Uses IQR-based statistics which are more robust for non-normal
        distributions common in health metrics.

        Args:
            user_id: User identifier
            metric_name: Which metric this baseline is for
            values: List of metric values (most recent first)
            dates: Corresponding dates (most recent first)

        Returns:
            Baseline status
        """
        sample_count = len(values)

        # Determine status based on sample count
        if sample_count >= MIN_SAMPLES_READY:
            status = BaselineStatus.READY
        elif sample_count >= MIN_SAMPLES_PARTIAL:
            status = BaselineStatus.PARTIAL
        else:
            status = BaselineStatus.INSUFFICIENT

        # Initialize optional statistics
        median_value: float | None = None
        q1: float | None = None
        q3: float | None = None
        std_dev: float | None = None
        min_value: float | None = None
        max_value: float | None = None
        baseline_7d: float | None = None
        baseline_30d: float | None = None
        baseline_90d: float | None = None
        data_start_date: date | None = None
        data_end_date: date | None = None

        # Calculate statistics if we have enough data
        if sample_count >= MIN_SAMPLES_PARTIAL:
            baseline_value = mean(values)
            median_value = median(values)

            # Calculate quartiles (returns list with n-1 cut points)
            # quantiles with n=4 returns [Q1, Q2, Q3]
            if sample_count >= 4:
                qs = quantiles(values, n=4)
                q1 = qs[0]
                q3 = qs[2] if len(qs) > 2 else None

            # Standard deviation (requires at least 2 values)
            if sample_count >= 2:
                std_dev = stdev(values)

            min_value = min(values)
            max_value = max(values)

            # Calculate rolling averages
            if len(values) >= 7:
                baseline_7d = mean(values[:7])
            if len(values) >= 30:
                baseline_30d = mean(values[:30])
            if len(values) >= 90:
                baseline_90d = mean(values[:90])

            # Date range
            if dates:
                data_start_date = min(dates)
                data_end_date = max(dates)
        else:
            # Insufficient data - set minimal values
            baseline_value = mean(values) if values else 0.0
            if values:
                min_value = min(values)
                max_value = max(values)
            if dates:
                data_start_date = min(dates)
                data_end_date = max(dates)

        # Build the baseline record
        baseline_data = {
            "metric_name": metric_name.value,
            "baseline_value": baseline_value,
            "baseline_7d": baseline_7d,
            "baseline_30d": baseline_30d,
            "baseline_90d": baseline_90d,
            "std_dev": std_dev,
            "median_value": median_value,
            "q1": q1,
            "q3": q3,
            "min_value": min_value,
            "max_value": max_value,
            "sample_count": sample_count,
            "status": status.value,
            "data_start_date": data_start_date,
            "data_end_date": data_end_date,
            "calculated_at": datetime.now(UTC),
        }

        # Upsert the baseline
        stmt = insert(UserBaseline).values(user_id=user_id, **baseline_data)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_user_baseline",
            set_=baseline_data,
        )

        await self.session.execute(stmt)

        self.logger.debug(
            "Baseline upserted",
            user_id=user_id,
            metric=metric_name.value,
            status=status.value,
            sample_count=sample_count,
        )

        return status.value

    async def get_user_baselines(self, user_id: str) -> list[UserBaseline]:
        """Get all baselines for a user.

        Args:
            user_id: User identifier

        Returns:
            List of UserBaseline records
        """
        stmt = select(UserBaseline).where(UserBaseline.user_id == user_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_baseline(
        self,
        user_id: str,
        metric_name: MetricName,
    ) -> UserBaseline | None:
        """Get a specific baseline for a user.

        Args:
            user_id: User identifier
            metric_name: Which metric to get

        Returns:
            UserBaseline record or None if not found
        """
        stmt = (
            select(UserBaseline)
            .where(UserBaseline.user_id == user_id)
            .where(UserBaseline.metric_name == metric_name.value)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
