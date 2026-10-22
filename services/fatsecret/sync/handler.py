"""Copy the FatSecret food diary into FatSecretDaily, one item per day.

Triggered by the EventBridge schedule or by ``POST /fatsecret/sync``.

- Empty table: backfill from BACKFILL_START_DATE.
- Otherwise: re-fetch the last LOOKBACK_DAYS days, because diary entries are
  often added or corrected a day or two later.
- ``food_entries.get_month`` lists the days that have entries (one call per
  month); only those days are fetched with ``food_entries.get``, which gives
  the full nutrients (fibre, sugar, sodium, ...) of every entry.
- Only days that changed are written, so a repeat run writes nothing. A stored
  day whose entries were all deleted in FatSecret is deleted here too.

An HTTP body or direct invocation may pass {"oldest": "YYYY-MM-DD", "newest": "YYYY-MM-DD"}.
"""

import json
import logging
import os
from datetime import UTC, date, datetime, timedelta

import boto3
from boto3.dynamodb.conditions import Key

from common import fatsecret_api
from common.dates import today
from common.ddb import from_dynamo, to_dynamo
from common.http import is_http_event, json_body, response

logger = logging.getLogger()
logger.setLevel(logging.INFO)

LOOKBACK_DAYS = 7
BOOKKEEPING = {"athleteId", "date", "source", "fetched_at"}

# Our name -> FatSecret food_entry field. Units: kcal, grams, except sodium (mg).
NUTRIENTS = {
    "calories_kcal": "calories",
    "carbohydrate_g": "carbohydrate",
    "protein_g": "protein",
    "fat_g": "fat",
    "fiber_g": "fiber",
    "sugar_g": "sugar",
    "saturated_fat_g": "saturated_fat",
    "sodium_mg": "sodium",
}
MEAL_NUTRIENTS = ("calories_kcal", "carbohydrate_g", "protein_g", "fat_g", "fiber_g")

_ddb = boto3.resource("dynamodb")


def _table():
    return _ddb.Table(os.environ["FATSECRET_TABLE"])


def _athlete_id() -> str:
    return os.environ["ATHLETE_ID"]


def stored(oldest: str, newest: str) -> dict[str, dict]:
    items: dict[str, dict] = {}
    kwargs = {"KeyConditionExpression": Key("athleteId").eq(_athlete_id()) & Key("date").between(oldest, newest)}
    while True:
        page = _table().query(**kwargs)
        for item in from_dynamo(page.get("Items", [])):
            items[item["date"]] = item
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def table_is_empty() -> bool:
    return not _table().query(KeyConditionExpression=Key("athleteId").eq(_athlete_id()), Limit=1).get("Items")


def _number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sum(rows: list[dict], name: str) -> float | None:
    values = [r[name] for r in rows if r.get(name) is not None]
    return round(sum(values), 1) if values else None


def to_entry(record: dict) -> dict:
    entry = {
        "meal": str(record.get("meal") or "other").lower(),
        "name": record.get("food_entry_name"),
        "description": record.get("food_entry_description"),
        "food_id": record.get("food_id"),
        "serving_id": record.get("serving_id"),
        "number_of_units": _number(record.get("number_of_units")),
        **{name: _number(record.get(key)) for name, key in NUTRIENTS.items()},
    }
    return {k: v for k, v in entry.items() if v is not None and v != ""}


def to_item(day: date, records: list[dict]) -> dict:
    """Totals, per-meal totals and the entries for one day."""
    entries = [to_entry(r) for r in records]
    totals = {name: _sum(entries, name) for name in NUTRIENTS}
    meals = {}
    for meal in sorted({e["meal"] for e in entries}):
        rows = [e for e in entries if e["meal"] == meal]
        meals[meal] = {k: v for k, v in ((n, _sum(rows, n)) for n in MEAL_NUTRIENTS) if v is not None}
    return {
        "athleteId": _athlete_id(),
        "date": day.isoformat(),
        "source": "fatsecret",
        "totals": {k: v for k, v in totals.items() if v is not None},
        "meals": meals,
        "entries_count": len(entries),
        "entries": entries,
    }


def _unchanged(before: dict, item: dict) -> bool:
    return {k: v for k, v in before.items() if k not in BOOKKEEPING} == from_dynamo(
        to_dynamo({k: v for k, v in item.items() if k not in BOOKKEEPING})
    )


def _months(oldest: date, newest: date):
    month = oldest.replace(day=1)
    while month <= newest:
        yield month
        month = (month + timedelta(days=32)).replace(day=1)


def sync(oldest: date | None = None, newest: date | None = None) -> dict:
    try:
        creds = fatsecret_api.credentials()
    except fatsecret_api.NotConfiguredError as err:
        logger.warning("FatSecret not configured yet: %s", err)
        return {"skipped": str(err)}

    newest = newest or today()
    if oldest is None:
        if table_is_empty():
            oldest = date.fromisoformat(os.environ["BACKFILL_START_DATE"])
        else:
            oldest = newest - timedelta(days=LOOKBACK_DAYS)

    diary_days = set()
    for month in _months(oldest, newest):
        for row in fatsecret_api.month_days(creds, month):
            day = fatsecret_api.from_date_int(row["date_int"])
            if oldest <= day <= newest:
                diary_days.add(day)

    existing = stored(oldest.isoformat(), newest.isoformat())
    fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
    written = deleted = 0
    with _table().batch_writer() as batch:
        for day in sorted(diary_days):
            item = to_item(day, fatsecret_api.food_entries(creds, day))
            if _unchanged(existing.get(day.isoformat(), {}), item):
                continue
            batch.put_item(Item=to_dynamo({**item, "fetched_at": fetched_at}))
            written += 1
        for day in sorted(set(existing) - {d.isoformat() for d in diary_days}):
            batch.delete_item(Key={"athleteId": _athlete_id(), "date": day})
            deleted += 1

    result = {
        "oldest": oldest.isoformat(),
        "newest": newest.isoformat(),
        "days_with_entries": len(diary_days),
        "written": written,
        "deleted": deleted,
    }
    logger.info("fatsecret sync %s", result)
    return result


def handler(event, _context):
    try:
        params = json_body(event) if is_http_event(event) else (event or {})
        oldest = date.fromisoformat(params["oldest"]) if params.get("oldest") else None
        newest = date.fromisoformat(params["newest"]) if params.get("newest") else None
    except (ValueError, json.JSONDecodeError) as err:
        return response(400, {"message": str(err)}) if is_http_event(event) else {"error": str(err)}

    try:
        result = sync(oldest, newest)
    except fatsecret_api.FatSecretError as err:
        logger.error("FatSecret call failed: %s", err)
        if is_http_event(event):
            return response(502, {"message": str(err)})
        raise
    if is_http_event(event):
        return response(503 if "skipped" in result else 200, result)
    return result
