"""Read-side view of every data source, shared by the agent actions, the daily
advice and the analysis API.

- DailyFitnessLog: manual entries (one row per day)
- IntervalsDaily: Intervals.icu wellness and fitness/fatigue (one row per day)
- ManualReadings: blood pressure and temperature (timestamped)
- WithingsTelemetry: scale sessions (timestamped)
- StravaActivities: activities (summaries only, never the raw payload)
- IntervalsActivities: per-ride TSS, IF, normalized power and the other Intervals metrics
"""

import os
from datetime import date, datetime, timedelta

import boto3
from boto3.dynamodb.conditions import Key

from common import daily_log_repo, intervals_repo, readings_repo
from common.dates import day_bounds_epoch, local_tz
from common.ddb import from_dynamo

ACTIVITY_SUMMARY_FIELDS = (
    "activityId",
    "name",
    "sport_type",
    "start_date_local",
    "distance",
    "moving_time",
    "elapsed_time",
    "total_elevation_gain",
    "average_watts",
    "weighted_average_watts",
    "kilojoules",
    "average_heartrate",
    "max_heartrate",
    "suffer_score",
    "trainer",
    # Time in zones (seconds per bucket; bounds are [min, max], max -1 = open-ended)
    "hr_zone_seconds",
    "hr_zone_bounds",
    "power_zone_seconds",
    "power_zone_bounds",
)

WITHINGS_FIELDS = (
    "timestamp",
    "weight_kg",
    "fat_ratio_pct",
    "fat_mass_weight_kg",
    "muscle_mass_kg",
    "hydration_kg",
    "heart_pulse_bpm",
    "pulse_wave_velocity_normalized_ms",
    "vascular_age_yrs",
    "systolic_blood_pressure_mmhg",
    "diastolic_blood_pressure_mmhg",
)

_ddb = boto3.resource("dynamodb")


def _athlete_id() -> str:
    return os.environ["ATHLETE_ID"]


def _withings_key():
    return Key("PK").eq(f"USER#{os.environ['WITHINGS_USER_ID']}")


def _withings_summary(item: dict) -> dict:
    return {k: item[k] for k in WITHINGS_FIELDS if k in item}


def latest_withings(day: date) -> dict | None:
    """The most recent Withings session on or before `day`."""
    _, end_epoch = day_bounds_epoch(day)
    table = _ddb.Table(os.environ["WITHINGS_TABLE"])
    result = table.query(
        KeyConditionExpression=_withings_key()
        & Key("SK").between("WITHINGS#MEAS#0000000000", f"WITHINGS#MEAS#{end_epoch - 1:010d}"),
        ScanIndexForward=False,
        Limit=1,
    )
    items = result.get("Items", [])
    return _withings_summary(from_dynamo(items[0])) if items else None


def withings_range(start: date, end: date) -> list[dict]:
    """Withings sessions whose local date is between `start` and `end`, oldest first, with `local_date`."""
    lower, _ = day_bounds_epoch(start)
    _, upper = day_bounds_epoch(end)
    table = _ddb.Table(os.environ["WITHINGS_TABLE"])
    kwargs = {
        "KeyConditionExpression": _withings_key()
        & Key("SK").between(f"WITHINGS#MEAS#{lower:010d}", f"WITHINGS#MEAS#{upper - 1:010d}")
    }
    sessions: list[dict] = []
    tz = local_tz()
    while True:
        page = table.query(**kwargs)
        for item in from_dynamo(page.get("Items", [])):
            summary = _withings_summary(item)
            if "timestamp" in summary:
                summary["local_date"] = datetime.fromtimestamp(summary["timestamp"], tz).date().isoformat()
            sessions.append(summary)
        if "LastEvaluatedKey" not in page:
            return sessions
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def activities_range(start: date, end: date) -> list[dict]:
    """Activities whose local start date is between `start` and `end`, oldest first.

    The sort key uses the UTC start time, so query a day either side and filter
    on start_date_local.
    """
    table = _ddb.Table(os.environ["ACTIVITIES_TABLE"])
    kwargs = {
        "KeyConditionExpression": Key("athleteId").eq(_athlete_id())
        & Key("sk").between((start - timedelta(days=1)).isoformat(), (end + timedelta(days=2)).isoformat()),
        "ProjectionExpression": ", ".join(f"#{i}" for i in range(len(ACTIVITY_SUMMARY_FIELDS))),
        "ExpressionAttributeNames": {f"#{i}": name for i, name in enumerate(ACTIVITY_SUMMARY_FIELDS)},
    }
    found: list[dict] = []
    while True:
        page = table.query(**kwargs)
        found.extend(from_dynamo(page.get("Items", [])))
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    lo, hi = start.isoformat(), end.isoformat()
    return [a for a in found if lo <= str(a.get("start_date_local", ""))[:10] <= hi]


def activities_on(day: date) -> list[dict]:
    return activities_range(day, day)


def day_snapshot(day: date) -> dict:
    """Everything known about one day, as the agent's get_daily_metrics returns it."""
    log = daily_log_repo.get(_athlete_id(), day.isoformat())
    return {
        "date": day.isoformat(),
        "daily_log": log,
        "daily_log_missing": log is None,
        "intervals": intervals_repo.get(_athlete_id(), day.isoformat()),
        "readings": readings_repo.query(_athlete_id(), day, day) if os.environ.get("READINGS_TABLE") else [],
        "withings_latest": latest_withings(day),
        "strava_activities": activities_on(day),
        "intervals_activities": [
            intervals_repo.activity_summary(a)
            for a in intervals_repo.activities_range(_athlete_id(), day.isoformat(), day.isoformat())
        ],
    }
