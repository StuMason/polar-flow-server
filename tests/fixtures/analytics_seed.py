"""Analytics test data seeding fixtures.

Generates 90 days of realistic health data for testing baseline calculations.
Includes patterns like:
- Monday HRV dips (post-weekend recovery)
- Weekend sleep variations
- Training load periodization
- Occasional anomalies
"""

import random
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from polar_flow_server.models.activity import Activity
from polar_flow_server.models.cardio_load import CardioLoad
from polar_flow_server.models.recharge import NightlyRecharge
from polar_flow_server.models.sleep import Sleep

# Seed for reproducible tests
random.seed(42)


def _generate_hrv_value(day_of_week: int, base_hrv: float = 35.0) -> float:
    """Generate HRV with realistic weekly patterns.

    Monday tends to be lower (post-weekend recovery).
    Weekend might be slightly higher (more rest).
    """
    # Weekly pattern: Mon=0, Sun=6
    weekly_modifier = {
        0: -5.0,  # Monday dip
        1: -2.0,  # Tuesday recovering
        2: 0.0,  # Wednesday baseline
        3: 1.0,  # Thursday good
        4: 2.0,  # Friday peak
        5: 0.0,  # Saturday varies
        6: -1.0,  # Sunday slightly lower
    }

    # Add weekly pattern
    hrv = base_hrv + weekly_modifier.get(day_of_week, 0)

    # Add random variation (-3 to +3)
    hrv += random.uniform(-3.0, 3.0)

    # Ensure positive value
    return max(15.0, hrv)


def _generate_sleep_score(day_of_week: int, base_score: int = 72) -> int:
    """Generate sleep score with realistic patterns.

    Weekend sleep might be longer but not always better quality.
    """
    weekly_modifier = {
        0: -5,  # Monday (Sunday night)
        1: 0,
        2: 2,
        3: 3,
        4: -2,  # Friday night social
        5: -3,  # Saturday night
        6: 5,  # Sunday (catching up)
    }

    score = base_score + weekly_modifier.get(day_of_week, 0)
    score += random.randint(-8, 8)

    return max(0, min(100, score))


def _generate_resting_hr(day_of_week: int, base_hr: float = 58.0) -> float:
    """Generate resting heart rate with inverse HRV correlation."""
    # Lower HRV days tend to have higher resting HR
    weekly_modifier = {
        0: 3.0,  # Monday higher HR
        1: 1.5,
        2: 0.0,
        3: -1.0,
        4: -2.0,
        5: 0.5,
        6: 1.0,
    }

    hr = base_hr + weekly_modifier.get(day_of_week, 0)
    hr += random.uniform(-2.0, 2.0)

    return max(45.0, hr)


def _generate_training_load(day_of_week: int, week_num: int) -> tuple[float | None, float | None]:
    """Generate training load with periodization.

    Follows a 4-week cycle with building load then recovery.
    Returns (cardio_load, cardio_load_ratio).
    """
    # Week 1-3: building, Week 4: recovery
    week_in_cycle = week_num % 4
    base_load = {
        0: 50.0,  # Base week
        1: 70.0,  # Build week 1
        2: 85.0,  # Build week 2
        3: 40.0,  # Recovery week
    }.get(week_in_cycle, 50.0)

    # Training days (higher load on workout days)
    if day_of_week in [1, 3, 5]:  # Tue, Thu, Sat are workout days
        load = base_load * random.uniform(0.9, 1.3)
    elif day_of_week == 0:  # Monday rest
        load = base_load * 0.2
    else:
        load = base_load * random.uniform(0.3, 0.6)

    # 10% chance of rest day (no training)
    if random.random() < 0.1:
        return None, None

    # Calculate load ratio (acute:chronic)
    # During build: ratio increases, during recovery: decreases
    if week_in_cycle == 3:
        ratio = random.uniform(0.6, 0.85)
    elif week_in_cycle == 2:
        ratio = random.uniform(1.1, 1.4)
    else:
        ratio = random.uniform(0.9, 1.1)

    return load, ratio


def _generate_activity(day_of_week: int) -> tuple[int, int]:
    """Generate daily steps and active calories.

    Weekdays tend to have more structured activity.
    """
    # Base steps by day
    base_steps = {
        0: 8000,  # Monday
        1: 10000,  # Tuesday workout
        2: 7500,  # Wednesday
        3: 10500,  # Thursday workout
        4: 6500,  # Friday
        5: 12000,  # Saturday active
        6: 5000,  # Sunday rest
    }

    steps = base_steps.get(day_of_week, 8000)
    steps = int(steps * random.uniform(0.7, 1.3))

    # Calories roughly correlate with steps
    calories = int(steps * 0.04 + random.randint(-50, 100))

    return steps, max(100, calories)


async def seed_analytics_data(
    session: AsyncSession,
    user_id: str,
    days: int = 90,
    include_anomalies: bool = True,
) -> dict[str, int]:
    """Seed realistic health data for baseline testing.

    Args:
        session: Database session
        user_id: User identifier
        days: Number of days of data to generate
        include_anomalies: Whether to include occasional anomalous values

    Returns:
        Dict with counts of seeded records per data type
    """
    counts = {
        "sleep": 0,
        "recharge": 0,
        "activity": 0,
        "cardio_load": 0,
    }

    today = datetime.now(UTC).date()

    for i in range(days):
        current_date = today - timedelta(days=days - 1 - i)
        day_of_week = current_date.weekday()
        week_num = i // 7

        # Generate HRV (nightly recharge)
        hrv = _generate_hrv_value(day_of_week)
        resting_hr = _generate_resting_hr(day_of_week)

        # Inject anomaly occasionally (2% chance)
        if include_anomalies and random.random() < 0.02:
            hrv = hrv * random.choice([0.5, 1.8])  # Very low or very high
            resting_hr = resting_hr * random.choice([0.85, 1.2])

        recharge = NightlyRecharge(
            user_id=user_id,
            date=current_date,
            ans_charge=random.uniform(40, 80),
            ans_charge_status=random.randint(-1, 2),
            hrv_avg=hrv,
            hrv_status=0 if 25 <= hrv <= 45 else (-1 if hrv < 25 else 1),
            breathing_rate_avg=random.uniform(12, 16),
            breathing_rate_status=0,
            heart_rate_avg=resting_hr,
            heart_rate_status=0,
            sleep_score=_generate_sleep_score(day_of_week),
            sleep_charge=random.uniform(40, 80),
            sleep_charge_status=0,
        )
        session.add(recharge)
        counts["recharge"] += 1

        # Generate sleep data
        sleep_score = _generate_sleep_score(day_of_week)
        total_sleep_hours = random.uniform(5.5, 8.5)
        total_sleep_seconds = int(total_sleep_hours * 3600)

        sleep = Sleep(
            user_id=user_id,
            date=current_date,
            sleep_start_time=f"{current_date}T22:{random.randint(0, 59):02d}:00",
            sleep_end_time=f"{current_date + timedelta(days=1)}T06:{random.randint(0, 59):02d}:00",
            total_sleep_seconds=total_sleep_seconds,
            light_sleep_seconds=int(total_sleep_seconds * random.uniform(0.4, 0.5)),
            deep_sleep_seconds=int(total_sleep_seconds * random.uniform(0.15, 0.25)),
            rem_sleep_seconds=int(total_sleep_seconds * random.uniform(0.2, 0.3)),
            interruptions_seconds=random.randint(0, 1800),
            sleep_score=sleep_score,
            sleep_rating=random.randint(1, 5),
            hrv_avg=hrv + random.uniform(-2, 2),
            hrv_samples=random.randint(50, 200),
            heart_rate_avg=resting_hr + random.uniform(-3, 3),
            heart_rate_min=int(resting_hr - random.randint(5, 10)),
            heart_rate_max=int(resting_hr + random.randint(10, 20)),
            breathing_rate_avg=random.uniform(12, 16),
        )
        session.add(sleep)
        counts["sleep"] += 1

        # Generate activity data
        steps, calories = _generate_activity(day_of_week)

        activity = Activity(
            user_id=user_id,
            date=current_date,
            steps=steps,
            calories_active=calories,
            calories_total=calories + random.randint(1200, 1800),
            distance_meters=int(steps * 0.75),
            active_time_seconds=random.randint(1800, 7200),
            activity_score=random.randint(50, 100),
            inactivity_alerts=random.randint(0, 3),
        )
        session.add(activity)
        counts["activity"] += 1

        # Generate cardio load (not every day has training)
        load, ratio = _generate_training_load(day_of_week, week_num)

        if load is not None:
            cardio = CardioLoad(
                user_id=user_id,
                date=current_date,
                cardio_load=load,
                cardio_load_status="LOAD_STATUS_OK"
                if 0.8 <= (ratio or 1.0) <= 1.3
                else "LOAD_STATUS_WARNING",
                cardio_load_ratio=ratio,
                strain=load * 0.8,
                tolerance=load * 1.2 if week_num > 4 else -1.0,
                load_very_low=load * random.uniform(0.05, 0.1),
                load_low=load * random.uniform(0.15, 0.25),
                load_medium=load * random.uniform(0.3, 0.4),
                load_high=load * random.uniform(0.15, 0.25),
                load_very_high=load * random.uniform(0.05, 0.15),
            )
            session.add(cardio)
            counts["cardio_load"] += 1

    await session.commit()
    return counts


async def seed_minimal_data(
    session: AsyncSession,
    user_id: str,
    days: int = 7,
) -> dict[str, int]:
    """Seed minimal data for testing 'partial' baseline status.

    Args:
        session: Database session
        user_id: User identifier
        days: Number of days (default 7 for partial status)

    Returns:
        Dict with counts of seeded records
    """
    return await seed_analytics_data(session, user_id, days=days, include_anomalies=False)


async def seed_insufficient_data(
    session: AsyncSession,
    user_id: str,
    days: int = 3,
) -> dict[str, int]:
    """Seed very limited data for testing 'insufficient' baseline status.

    Args:
        session: Database session
        user_id: User identifier
        days: Number of days (default 3 for insufficient status)

    Returns:
        Dict with counts of seeded records
    """
    return await seed_analytics_data(session, user_id, days=days, include_anomalies=False)
