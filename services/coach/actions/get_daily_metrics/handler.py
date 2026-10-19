"""Action group: GET /daily-metrics?date=YYYY-MM-DD

Returns one consolidated picture of a day for the coach agent:
- the DailyFitnessLog entry (Garmin, Xert, TrainingPeaks, DQS, waist)
- the most recent Withings scale session on or before that day
- a summary of that day's Strava activities (without the raw payload)
"""

import logging
import os
from datetime import date, timedelta

import boto3
from boto3.dynamodb.conditions import Key

from common import agent_io, daily_log_repo
from common.dates import day_bounds_epoch, today
from common.ddb import from_dynamo

logger = logging.getLogger()
logger.setLevel(logging.INFO)

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
)

_ddb = boto3.resource("dynamodb")


def latest_withings(day: date) -> dict | None:
    _, end_epoch = day_bounds_epoch(day)
    table = _ddb.Table(os.environ["WITHINGS_TABLE"])
    result = table.query(
        KeyConditionExpression=Key("PK").eq(f"USER#{os.environ['WITHINGS_USER_ID']}")
        & Key("SK").between("WITHINGS#MEAS#0000000000", f"WITHINGS#MEAS#{end_epoch - 1:010d}"),
        ScanIndexForward=False,
        Limit=1,
    )
    items = result.get("Items", [])
    if not items:
        return None
    item = from_dynamo(items[0])
    return {k: item[k] for k in WITHINGS_FIELDS if k in item}


def activities_on(day: date) -> list[dict]:
    """Activities whose local start date is `day`.

    The sort key uses the UTC start time, so query a window a day either side
    and filter on start_date_local.
    """
    table = _ddb.Table(os.environ["ACTIVITIES_TABLE"])
    lower = (day - timedelta(days=1)).isoformat()
    upper = (day + timedelta(days=2)).isoformat()
    result = table.query(
        KeyConditionExpression=Key("athleteId").eq(os.environ["ATHLETE_ID"]) & Key("sk").between(lower, upper),
        ProjectionExpression=", ".join(f"#{i}" for i in range(len(ACTIVITY_SUMMARY_FIELDS))),
        ExpressionAttributeNames={f"#{i}": name for i, name in enumerate(ACTIVITY_SUMMARY_FIELDS)},
    )
    wanted = day.isoformat()
    return [
        from_dynamo(item)
        for item in result.get("Items", [])
        if str(item.get("start_date_local", "")).startswith(wanted)
    ]


def handler(event, _context):
    params = agent_io.parameters(event)
    try:
        day = date.fromisoformat(params["date"]) if params.get("date") else today()
    except ValueError:
        return agent_io.error(event, "date must be in YYYY-MM-DD format")

    log = daily_log_repo.get(os.environ["ATHLETE_ID"], day.isoformat())
    body = {
        "date": day.isoformat(),
        "daily_log": log,
        "daily_log_missing": log is None,
        "withings_latest": latest_withings(day),
        "strava_activities": activities_on(day),
    }
    return agent_io.respond(event, body)
