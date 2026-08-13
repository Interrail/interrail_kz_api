"""
KPI Utilities for Inquiry Management

This module provides utilities for calculating KPI metrics including:
- Business hours calculation (excluding weekends)
- KPI grade calculations
- Timezone handling for accurate time tracking
"""

from datetime import datetime, timedelta

import pandas as pd
import pytz
from django.utils import timezone


def get_business_hours_between(start_date: datetime, end_date: datetime) -> timedelta:
    """
    Calculate business hours between two dates using pandas, excluding weekends.

    Args:
        start_date: Starting datetime (timezone-aware)
        end_date: Ending datetime (timezone-aware)

    Returns:
        timedelta: Business hours between the dates
    """
    if not start_date or not end_date:
        return timedelta()

    # Set target timezone (can be configured later)
    target_tz = pytz.timezone("Asia/Almaty")  # Kazakhstan timezone

    # Ensure both dates are timezone-aware in target timezone
    if start_date.tzinfo is None:
        start_date = timezone.make_aware(start_date, target_tz)
    if end_date.tzinfo is None:
        end_date = timezone.make_aware(end_date, target_tz)

    # Convert both to target timezone if they're in a different timezone
    start_date = timezone.localtime(start_date, target_tz)
    end_date = timezone.localtime(end_date, target_tz)

    # Ensure start_date is before end_date
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    # Create a date range excluding weekends
    try:
        business_days = pd.bdate_range(start=start_date, end=end_date)
    except Exception:
        # Fallback to basic calculation if pandas fails
        return _calculate_business_hours_basic(start_date, end_date)

    if len(business_days) == 0:
        return timedelta()

    total_time = timedelta()

    for day in business_days:
        day_dt = day.to_pydatetime()
        if day_dt.tzinfo is None:
            day_dt = timezone.make_aware(day_dt, target_tz)
        else:
            day_dt = timezone.localtime(day_dt, target_tz)

        # Calculate time for this business day
        if day_dt.date() == start_date.date():
            # First day: from start_date to end of day (or end_date if same day)
            end_of_day = timezone.make_aware(
                datetime.combine(day_dt.date(), datetime.max.time()), target_tz
            )
            day_time = min(end_of_day, end_date) - start_date
            total_time += day_time

        elif day_dt.date() == end_date.date():
            # Last day: from start of day to end_date
            start_of_day = timezone.make_aware(
                datetime.combine(day_dt.date(), datetime.min.time()), target_tz
            )
            day_time = end_date - max(start_of_day, start_date)
            total_time += day_time

        else:
            # Full business day
            total_time += timedelta(days=1)

    return total_time


def _calculate_business_hours_basic(
    start_date: datetime, end_date: datetime
) -> timedelta:
    """
    Fallback business hours calculation without pandas.

    Args:
        start_date: Starting datetime
        end_date: Ending datetime

    Returns:
        timedelta: Business hours between the dates
    """
    if start_date.date() == end_date.date():
        # Same day
        if start_date.weekday() < 5:  # Monday = 0, Friday = 4
            return end_date - start_date
        else:
            return timedelta()

    total_time = timedelta()
    current_date = start_date.date()

    while current_date <= end_date.date():
        if current_date.weekday() < 5:  # Business day
            if current_date == start_date.date():
                # First day
                end_of_day = datetime.combine(current_date, datetime.max.time())
                end_of_day = timezone.make_aware(end_of_day, start_date.tzinfo)
                total_time += end_of_day - start_date
            elif current_date == end_date.date():
                # Last day
                start_of_day = datetime.combine(current_date, datetime.min.time())
                start_of_day = timezone.make_aware(start_of_day, end_date.tzinfo)
                total_time += end_date - start_of_day
            else:
                # Full business day
                total_time += timedelta(days=1)

        current_date += timedelta(days=1)

    return total_time


def calculate_quote_grade(quote_time: timedelta) -> str | None:
    """
    Calculate quote grade based on response time.

    Args:
        quote_time: Duration from inquiry creation to quote

    Returns:
        str: Grade (A, B, or C) or None if no quote_time
    """
    if not quote_time or quote_time == timedelta():
        return None

    if quote_time <= timedelta(hours=60):  # ~2.5 business days
        return "A"
    elif quote_time <= timedelta(hours=84):  # ~3.5 business days
        return "B"
    else:
        return "C"


def calculate_completion_grade(resolution_time: timedelta) -> str | None:
    """
    Calculate completion grade based on resolution time.

    Args:
        resolution_time: Duration from quote to resolution

    Returns:
        str: Grade (A, B, or C) or None if no resolution_time
    """
    if not resolution_time or resolution_time == timedelta():
        return None

    if resolution_time <= timedelta(hours=120):  # 5 business days
        return "A"
    elif resolution_time <= timedelta(hours=168):  # 7 business days
        return "B"
    else:
        return "C"


def get_grade_points(grade: str | None) -> int:
    """
    Convert grade to point value for KPI calculations.

    Args:
        grade: Grade (A, B, C) or None

    Returns:
        int: Points (A=3, B=2, C=-1, None=0)
    """
    grade_points = {"A": 3, "B": 2, "C": -1}
    return grade_points.get(grade, 0)


def calculate_conversion_percentage(success_count: int, total_processed: int) -> float:
    """
    Calculate conversion rate percentage.

    Args:
        success_count: Number of successful inquiries
        total_processed: Total processed inquiries (excluding pending)

    Returns:
        float: Conversion rate percentage
    """
    if total_processed == 0:
        return 0.0
    return (success_count / total_processed) * 100


def calculate_kpi_target_percentage(
    actual_value: float, multiplier: float = 10.0, max_target: float = 100.0
) -> float:
    """
    Calculate KPI target percentage using standard formula.

    Args:
        actual_value: Actual KPI value
        multiplier: Multiplier for target calculation
        max_target: Maximum target percentage

    Returns:
        float: Target percentage (capped at max_target)
    """
    return min(multiplier * actual_value, max_target)
