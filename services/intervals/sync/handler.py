"""Copy Intervals.icu daily wellness records into IntervalsDaily, and activities
(every calculated metric: TSS, IF, normalized power, ...) into IntervalsActivities.

Triggered by the EventBridge schedule or by ``POST /intervals/sync``.

- Empty table: backfill from BACKFILL_START_DATE.
- Otherwise: re-fetch the last LOOKBACK_DAYS days, because Intervals keeps
  updating recent days (late Garmin syncs, recalculated CTL/ATL).
- Only records that changed are written, so a repeat run writes nothing.
- Strava-imported activities are skipped: Intervals only returns a stub for them.

An HTTP body or direct invocation may pass {"oldest": "YYYY-MM-DD", "newest": "YYYY-MM-DD"}.
"""

import json
import logging
import os
from datetime import UTC, date, datetime, timedelta

import boto3
from boto3.dynamodb.conditions import Key

from common import intervals_api, intervals_repo
from common.dates import today
from common.ddb import from_dynamo, to_dynamo
from common.http import is_http_event, json_body, response

logger = logging.getLogger()
logger.setLevel(logging.INFO)

LOOKBACK_DAYS = 7
MAX_DAYS_PER_REQUEST = 120
BOOKKEEPING = {"athleteId", "date", "source", "fetched_at"}
ACTIVITY_BOOKKEEPING = {"athleteId", "sk", "date", "fetched_at"}

_ddb = boto3.resource("dynamodb")


def _table():
    return _ddb.Table(os.environ["INTERVALS_TABLE"])


def _athlete_id() -> str:
    return os.environ["ATHLETE_ID"]


def _activities_table():
    return _ddb.Table(os.environ["INTERVALS_ACTIVITIES_TABLE"])


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


def stored_activities(oldest: str, newest: str) -> dict[str, dict]:
    items: dict[str, dict] = {}
    kwargs = {"KeyConditionExpression": Key("athleteId").eq(_athlete_id()) & Key("sk").between(oldest, f"{newest}~")}
    while True:
        page = _activities_table().query(**kwargs)
        for item in from_dynamo(page.get("Items", [])):
            items[item["sk"]] = item
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def table_is_empty(table=None) -> bool:
    result = (table or _table()).query(KeyConditionExpression=Key("athleteId").eq(_athlete_id()), Limit=1)
    return not result.get("Items")


def to_item(record: dict) -> dict:
    """Keep every non-null value Intervals returns: the probe decides which ones matter."""
    values = {k: v for k, v in record.items() if v is not None and v != "" and k != "id"}
    return {"athleteId": _athlete_id(), "date": record["id"], "source": "intervals.icu", **values}


def to_activity_item(record: dict) -> dict | None:
    """Every non-null metric of one activity, or None for a Strava stub."""
    if record.get("_note") or not record.get("start_date_local"):
        return None
    values = {k: v for k, v in record.items() if v is not None and v != ""}
    return {
        "athleteId": _athlete_id(),
        "sk": intervals_repo.activity_sort_key(record),
        "date": record["start_date_local"][:10],
        **values,
    }


def _unchanged(before: dict, item: dict, bookkeeping: set) -> bool:
    return {k: v for k, v in before.items() if k not in bookkeeping} == from_dynamo(
        to_dynamo({k: v for k, v in item.items() if k not in bookkeeping})
    )


def _windows(oldest: date, newest: date):
    start = oldest
    while start <= newest:
        end = min(start + timedelta(days=MAX_DAYS_PER_REQUEST - 1), newest)
        yield start, end
        start = end + timedelta(days=1)


def sync(oldest: date | None = None, newest: date | None = None) -> dict:
    try:
        creds = intervals_api.credentials()
    except intervals_api.NotConfiguredError as err:
        logger.warning("Intervals.icu not configured yet: %s", err)
        return {"skipped": str(err)}

    newest = newest or today()
    backfill = date.fromisoformat(os.environ["BACKFILL_START_DATE"])
    recent = newest - timedelta(days=LOOKBACK_DAYS)
    if oldest is None:
        wellness_from = backfill if table_is_empty() else recent
        activities_from = backfill if table_is_empty(_activities_table()) else recent
    else:
        wellness_from = activities_from = oldest

    result = {"oldest": min(wellness_from, activities_from).isoformat(), "newest": newest.isoformat()}
    result["wellness"] = _sync_wellness(creds, wellness_from, newest)
    result["activities"] = _sync_activities(creds, activities_from, newest)
    logger.info("intervals sync %s", result)
    return result


def _sync_wellness(creds, oldest: date, newest: date) -> dict:
    fetched = written = 0
    fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
    for start, end in _windows(oldest, newest):
        records = intervals_api.wellness(creds, start.isoformat(), end.isoformat())
        existing = stored(start.isoformat(), end.isoformat())
        fetched += len(records)
        with _table().batch_writer() as batch:
            for record in records:
                item = to_item(record)
                if _unchanged(existing.get(item["date"], {}), item, BOOKKEEPING):
                    continue
                batch.put_item(Item=to_dynamo({**item, "fetched_at": fetched_at}))
                written += 1
    return {"fetched": fetched, "written": written}


def _sync_activities(creds, oldest: date, newest: date) -> dict:
    fetched = written = skipped = 0
    fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
    for start, end in _windows(oldest, newest):
        records = intervals_api.activities(creds, start.isoformat(), end.isoformat())
        existing = stored_activities(start.isoformat(), end.isoformat())
        fetched += len(records)
        with _activities_table().batch_writer() as batch:
            for record in records:
                item = to_activity_item(record)
                if item is None:
                    skipped += 1
                    continue
                if _unchanged(existing.get(item["sk"], {}), item, ACTIVITY_BOOKKEEPING):
                    continue
                batch.put_item(Item=to_dynamo({**item, "fetched_at": fetched_at}))
                written += 1
    return {"fetched": fetched, "written": written, "skipped_strava_stubs": skipped}


def handler(event, _context):
    try:
        params = json_body(event) if is_http_event(event) else (event or {})
        oldest = date.fromisoformat(params["oldest"]) if params.get("oldest") else None
        newest = date.fromisoformat(params["newest"]) if params.get("newest") else None
    except (ValueError, json.JSONDecodeError) as err:
        return response(400, {"message": str(err)}) if is_http_event(event) else {"error": str(err)}

    result = sync(oldest, newest)
    if is_http_event(event):
        return response(503 if "skipped" in result else 200, result)
    return result
