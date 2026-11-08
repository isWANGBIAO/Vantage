"""Daily observations and calendar-week summaries for the sleep schedule chart.

Hours are already unwrapped by the primary-sleep parser. This module does not
read workbooks, infer missing observations, or persist personal records.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
import math
from numbers import Real
from statistics import median


MIN_WEEKLY_RECORDS = 4
MAX_DATE_SPAN_DAYS = 366 * 100


def _record_date(value):
    try:
        if isinstance(value, datetime):
            value = value.date()
        if isinstance(value, date):
            return date.fromisoformat(value.isoformat())
        if isinstance(value, str):
            return date.fromisoformat(value)
    except (TypeError, ValueError, OverflowError):
        pass
    return None


def _record_hour(value):
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    try:
        hour = float(value)
    except (ValueError, OverflowError):
        return None
    return hour if math.isfinite(hour) else None


def build_sleep_schedule_payload(records):
    """Build deterministic daily data and Monday-to-Sunday weekly medians.

    Only complete, finite primary-sleep observations are valid. For duplicate
    dates the last valid input record wins, so duplicate rows cannot satisfy the
    four-distinct-days minimum. ``duplicate_day_count`` counts distinct dates
    having more than one valid record, not the number of extra rows.
    """
    observations = {}
    duplicate_dates = set()
    for record in records:
        if not isinstance(record, Mapping):
            continue
        observed_date = _record_date(record.get("date"))
        bedtime = _record_hour(record.get("bedtime_hour"))
        wake = _record_hour(record.get("wake_hour"))
        if (
            observed_date is None
            or bedtime is None
            or wake is None
            or not 12 <= bedtime < 36
            or not 0 < wake - bedtime <= 18
        ):
            continue
        if observed_date in observations:
            duplicate_dates.add(observed_date)
        observations[observed_date] = (bedtime, wake)

    result = {
        "version": 1,
        "latest_date": None,
        "daily": [],
        "weeks": [],
        "duplicate_day_count": len(duplicate_dates),
    }
    if not observations:
        return result

    first_date, last_date = min(observations), max(observations)
    if (last_date - first_date).days > MAX_DATE_SPAN_DAYS:
        raise ValueError("Sleep schedule date range exceeds the supported 100-year span")

    result["latest_date"] = last_date.isoformat()
    current = first_date
    while current <= last_date:
        bedtime, wake = observations.get(current, (None, None))
        result["daily"].append({
            "date": current.isoformat(),
            "bedtime_hour": bedtime,
            "wake_hour": wake,
        })
        if current == last_date:
            break
        current += timedelta(days=1)

    week_start = first_date - timedelta(days=first_date.weekday())
    while week_start <= last_date:
        # Avoid overflowing date.max when the final supported week is partial.
        remaining_days = (date.max - week_start).days
        week_end = week_start + timedelta(days=min(6, remaining_days))
        observed_end = min(week_end, last_date)
        values = [
            observations[week_start + timedelta(days=offset)]
            for offset in range((observed_end - week_start).days + 1)
            if week_start + timedelta(days=offset) in observations
        ]
        enough = len(values) >= MIN_WEEKLY_RECORDS
        result["weeks"].append({
            "start": week_start.isoformat(),
            "end": observed_end.isoformat(),
            "record_count": len(values),
            "bedtime_hour": median(item[0] for item in values) if enough else None,
            "wake_hour": median(item[1] for item in values) if enough else None,
            "partial": week_start < first_date or (last_date - week_start).days < 6,
        })
        if (last_date - week_start).days < 7:
            break
        week_start += timedelta(days=7)

    return result
