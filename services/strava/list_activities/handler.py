"""Find new Strava activities and queue each one for a detail fetch.

Triggered by the EventBridge schedule or by ``POST /strava/sync``.

1. Read the newest activity already stored (descending Query, Limit 1).
2. Page ``GET /athlete/activities?after=<its start epoch>`` (or BACKFILL_START
   when the table is empty) until an empty page comes back.
3. Send one SQS message per activity to the fetch worker.
"""

import json
import logging
import os

import boto3
from boto3.dynamodb.conditions import Key

from common import strava_api, strava_auth
from common.http import is_http_event, response
from strava.activity_item import sort_key

logger = logging.getLogger()
logger.setLevel(logging.INFO)

PER_PAGE = 200
MAX_PAGES = 20  # safety stop: 4,000 activities

_ddb = boto3.resource("dynamodb")
_sqs = boto3.client("sqs")


def latest_start_epoch(athlete_id: str) -> int | None:
    table = _ddb.Table(os.environ["ACTIVITIES_TABLE"])
    result = table.query(
        KeyConditionExpression=Key("athleteId").eq(athlete_id),
        ScanIndexForward=False,
        Limit=1,
        ProjectionExpression="start_epoch",
    )
    items = result.get("Items", [])
    return int(items[0]["start_epoch"]) if items else None


def list_new_activities(token: str, after: int) -> list[dict]:
    found: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        batch = strava_api.get(
            "/athlete/activities", token, {"after": after, "per_page": PER_PAGE, "page": page}
        ).json()
        if not batch:
            break
        found.extend(batch)
    return found


def enqueue(athlete_id: str, activities: list[dict]) -> int:
    queue_url = os.environ["FETCH_QUEUE_URL"]
    entries = [
        {
            "Id": str(i),
            "MessageBody": json.dumps(
                {
                    "athleteId": athlete_id,
                    "activityId": str(a.get("id_str") or a["id"]),
                    "sk": sort_key(a["start_date"], str(a.get("id_str") or a["id"])),
                }
            ),
        }
        for i, a in enumerate(activities)
    ]
    for start in range(0, len(entries), 10):
        chunk = entries[start : start + 10]
        result = _sqs.send_message_batch(QueueUrl=queue_url, Entries=chunk)
        if result.get("Failed"):
            raise RuntimeError(f"SQS batch send failed: {result['Failed']}")
    return len(entries)


def sync() -> dict:
    token, athlete_id = strava_auth.get_access_token()
    latest = latest_start_epoch(athlete_id)
    after = latest if latest is not None else int(os.environ["BACKFILL_START_EPOCH"])
    activities = list_new_activities(token, after)
    queued = enqueue(athlete_id, activities)
    logger.info("after=%s found=%s queued=%s", after, len(activities), queued)
    return {"after": after, "queued": queued}


def handler(event, _context):
    try:
        result = sync()
    except strava_auth.NotAuthorizedError as err:
        if is_http_event(event):
            return response(409, {"message": str(err)})
        raise
    if is_http_event(event):
        return response(202, {"message": "Sync started", **result})
    return result
