"""Read access to FatSecretDaily: one item per day of the FatSecret food diary.

Each item holds the day's nutrient totals, the totals per meal and the
individual entries. The nutrition totals are prefills on the daily-log form,
where a manually typed value wins.
"""

import os

import boto3
from boto3.dynamodb.conditions import Key

from common.ddb import from_dynamo

_ddb = boto3.resource("dynamodb")

# DailyFitnessLog field -> FatSecretDaily total
FIELD_SOURCES: dict[str, str] = {
    "protein_g": "protein_g",
    "carbs_g": "carbohydrate_g",
    "fat_g": "fat_g",
    "fibre_g": "fiber_g",
}


def configured() -> bool:
    return bool(os.environ.get("FATSECRET_TABLE"))


def _table():
    return _ddb.Table(os.environ["FATSECRET_TABLE"])


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


def as_daily_fields(record: dict | None) -> dict:
    """FatSecret totals renamed to the daily-log nutrition fields they prefill (whole grams)."""
    if not record:
        return {}
    totals = record.get("totals") or {}
    return {field: round(totals[key]) for field, key in FIELD_SOURCES.items() if totals.get(key) is not None}


def day_summary(record: dict | None) -> dict | None:
    """Totals and per-meal totals without the individual entries, for the agent and charts."""
    if not record:
        return None
    return {k: record[k] for k in ("totals", "meals", "entries_count") if k in record}
