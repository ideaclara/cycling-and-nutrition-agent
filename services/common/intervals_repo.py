"""Read access to IntervalsDaily, and the mapping onto DailyFitnessLog fields.

Intervals.icu's wellness record mixes Garmin-synced values (HRV, resting HR,
sleep, readiness) with its own fitness model (ctl = fitness, atl = fatigue).
The daily-log form shows these as prefills; a manually entered value wins.
"""

import os

import boto3
from boto3.dynamodb.conditions import Key

from common.daily_log_schema import FIELDS
from common.ddb import from_dynamo

_ddb = boto3.resource("dynamodb")

# DailyFitnessLog field -> (Intervals wellness key, multiplier)
FIELD_SOURCES: dict[str, tuple[str, float]] = {
    "training_readiness": ("readiness", 1),
    "hrv_overnight_avg_ms": ("hrv", 1),
    "resting_hr_bpm": ("restingHR", 1),
    "sleep_duration_h": ("sleepSecs", 1 / 3600),
    "sleep_score": ("sleepScore", 1),
    "tp_ctl": ("ctl", 1),
    "tp_atl": ("atl", 1),
}


def configured() -> bool:
    return bool(os.environ.get("INTERVALS_TABLE"))


def _table():
    return _ddb.Table(os.environ["INTERVALS_TABLE"])


def get(athlete_id: str, day: str) -> dict | None:
    if not configured():
        return None
    item = _table().get_item(Key={"athleteId": athlete_id, "date": day}).get("Item")
    return from_dynamo(item) if item else None


def query_range(athlete_id: str, start: str, end: str) -> list[dict]:
    if not configured():
        return []
    items: list[dict] = []
    kwargs = {"KeyConditionExpression": Key("athleteId").eq(athlete_id) & Key("date").between(start, end)}
    while True:
        page = _table().query(**kwargs)
        items.extend(page.get("Items", []))
        if "LastEvaluatedKey" not in page:
            return from_dynamo(items)
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _round(field: str, value: float) -> float | int:
    spec = FIELDS[field]
    if spec.integer:
        return round(value)
    return round(value, spec.decimals if spec.decimals is not None else 1)


def as_daily_fields(record: dict | None) -> dict:
    """Intervals values renamed to DailyFitnessLog fields, with TSB derived as CTL - ATL."""
    if not record:
        return {}
    values = {}
    for field, (key, factor) in FIELD_SOURCES.items():
        if isinstance(record.get(key), (int, float)) and not isinstance(record.get(key), bool):
            values[field] = _round(field, record[key] * factor)
    if "tp_ctl" in values and "tp_atl" in values:
        values["tp_tsb"] = _round("tp_tsb", record["ctl"] - record["atl"])
    return values
