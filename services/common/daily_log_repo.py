"""Read/write access to the DailyFitnessLog table."""

import os
from datetime import UTC, datetime

import boto3
from boto3.dynamodb.conditions import Key

from common import dqs_table
from common.ddb import from_dynamo, to_dynamo

_ddb = boto3.resource("dynamodb")


def _table():
    return _ddb.Table(os.environ["DAILY_LOG_TABLE"])


def get(athlete_id: str, day: str) -> dict | None:
    item = _table().get_item(Key={"athleteId": athlete_id, "date": day}).get("Item")
    return from_dynamo(item) if item else None


def query_range(athlete_id: str, start: str, end: str) -> list[dict]:
    """Items with start <= date <= end (inclusive, YYYY-MM-DD strings)."""
    items: list[dict] = []
    kwargs = {"KeyConditionExpression": Key("athleteId").eq(athlete_id) & Key("date").between(start, end)}
    while True:
        page = _table().query(**kwargs)
        items.extend(page.get("Items", []))
        if "LastEvaluatedKey" not in page:
            return from_dynamo(items)
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def update(athlete_id: str, day: str, to_set: dict, to_remove: set[str]) -> dict:
    """Upsert the given fields. Recomputes the DQS score whenever servings change."""
    to_set = dict(to_set)
    if "dqs_servings" in to_set:
        scored = dqs_table.score(to_set["dqs_servings"])
        to_set["dqs_total"] = scored["total"]
        to_set["dqs_breakdown"] = scored["by_category"]
    if "dqs_servings" in to_remove:
        to_remove = to_remove | {"dqs_total", "dqs_breakdown"}
    to_set["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")

    names = {f"#f{i}": name for i, name in enumerate([*to_set, *to_remove])}
    by_name = {v: k for k, v in names.items()}
    values = {f":v{i}": to_dynamo(value) for i, value in enumerate(to_set.values())}
    expression = "SET " + ", ".join(f"{by_name[name]} = :v{i}" for i, name in enumerate(to_set))
    if to_remove:
        expression += " REMOVE " + ", ".join(by_name[name] for name in to_remove)

    result = _table().update_item(
        Key={"athleteId": athlete_id, "date": day},
        UpdateExpression=expression,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
        ReturnValues="ALL_NEW",
    )
    return from_dynamo(result["Attributes"])
