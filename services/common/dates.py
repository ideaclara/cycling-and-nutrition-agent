"""Calendar-day helpers. The athlete's day is defined in their local timezone."""

import os
from datetime import UTC, date, datetime, timedelta, tzinfo


def local_tz() -> tzinfo:
    name = os.environ.get("ATHLETE_TIMEZONE", "Europe/London")
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # tz database unavailable: fall back rather than fail
        return UTC


def today() -> date:
    return datetime.now(local_tz()).date()


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def day_bounds_epoch(day: date) -> tuple[int, int]:
    """Epoch seconds for local midnight at the start of `day` and of the next day."""
    tz = local_tz()
    start = datetime(day.year, day.month, day.day, tzinfo=tz)
    end = start + timedelta(days=1)
    return int(start.timestamp()), int(end.timestamp())
