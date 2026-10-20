"""Read/write access to the ManualReadings table.

SK = "<TYPE>#<ISO-8601 UTC>", e.g. "BP#2026-10-21T06:45:00Z", so one type over a
time range is a single Query.
"""

import os
from datetime import UTC, date, datetime, timedelta

import boto3
from boto3.dynamodb.conditions import Key

from common.dates import local_tz
from common.ddb import from_dynamo, to_dynamo
from common.readings_schema import TYPES, iso_utc

_ddb = boto3.resource("dynamodb")


def _table():
    return _ddb.Table(os.environ["READINGS_TABLE"])


def sort_key(kind: str, measured_at: datetime) -> str:
    return f"{kind}#{iso_utc(measured_at)}"


def local_day_bounds_utc(start: date, end: date) -> tuple[str, str]:
    """UTC ISO bounds covering local midnight at `start` up to (not including) local midnight after `end`."""
    tz = local_tz()
    lower = datetime(start.year, start.month, start.day, tzinfo=tz)
    upper = datetime(end.year, end.month, end.day, tzinfo=tz) + timedelta(days=1) - timedelta(seconds=1)
    return iso_utc(lower), iso_utc(upper)


def put(athlete_id: str, kind: str, measured_at: datetime, values: dict) -> dict:
    tz = local_tz()
    item = {
        "athleteId": athlete_id,
        "sk": sort_key(kind, measured_at),
        "type": kind,
        "measured_at": iso_utc(measured_at),
        "local_date": measured_at.astimezone(tz).date().isoformat(),
        "local_time": measured_at.astimezone(tz).strftime("%H:%M"),
        "source": "manual",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        **values,
    }
    _table().put_item(Item=to_dynamo(item))
    return item


def query(athlete_id: str, start: date, end: date, kinds: list[str] | None = None) -> list[dict]:
    """Readings whose local date is between `start` and `end` (inclusive), oldest first."""
    lower, upper = local_day_bounds_utc(start, end)
    items: list[dict] = []
    for kind in kinds or list(TYPES):
        kwargs = {
            "KeyConditionExpression": Key("athleteId").eq(athlete_id)
            & Key("sk").between(f"{kind}#{lower}", f"{kind}#{upper}")
        }
        while True:
            page = _table().query(**kwargs)
            items.extend(page.get("Items", []))
            if "LastEvaluatedKey" not in page:
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    return sorted(from_dynamo(items), key=lambda i: i["measured_at"])


def delete(athlete_id: str, kind: str, measured_at: datetime) -> bool:
    result = _table().delete_item(
        Key={"athleteId": athlete_id, "sk": sort_key(kind, measured_at)},
        ReturnValues="ALL_OLD",
    )
    return "Attributes" in result
