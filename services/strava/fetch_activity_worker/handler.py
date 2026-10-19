"""SQS consumer: fetch one Strava activity in full and store it.

Each message is completed in two idempotent stages, so a retry resumes where
the previous attempt stopped:

1. Detail: ``GET /activities/{id}?include_all_efforts=true`` -> new item
   (gzip payload inline, or in S3 if it is too big). Skipped if already stored.
2. Zones: ``GET /activities/{id}/zones`` -> time in heart-rate and power zones
   merged into the item. Skipped once ``zones_fetched_at`` is set.

Rate limits: on HTTP 429 the message is hidden for 15 minutes (the length of
Strava's rate-limit window) and the invocation fails, so the retry lands in a
fresh window without burning extra receive attempts too quickly.
"""

import json
import logging
import os
from datetime import UTC, datetime

import boto3
from botocore.exceptions import ClientError

from common import strava_api, strava_auth
from strava import zones
from strava.activity_item import MAX_INLINE_BYTES, build_item

logger = logging.getLogger()
logger.setLevel(logging.INFO)

RATE_LIMIT_BACKOFF_SECONDS = 900

_ddb = boto3.resource("dynamodb")
_s3 = boto3.client("s3")
_sqs = boto3.client("sqs")


# Zones are a subscription feature; these mean "not available", not "retry".
ZONES_UNAVAILABLE_STATUSES = {402, 403, 404}


def stored_state(athlete_id: str, sk: str) -> dict | None:
    """The stored item's progress markers, or None if it isn't stored yet."""
    table = _ddb.Table(os.environ["ACTIVITIES_TABLE"])
    result = table.get_item(Key={"athleteId": athlete_id, "sk": sk}, ProjectionExpression="sk, zones_fetched_at")
    return result.get("Item")


def store(athlete_id: str, raw: bytes) -> dict:
    fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
    item, compressed = build_item(athlete_id, raw, fetched_at)

    if len(compressed) <= MAX_INLINE_BYTES:
        item["raw_gzip"] = compressed
    else:
        key = f"strava/activities/{item['activityId']}.json.gz"
        _s3.put_object(
            Bucket=os.environ["DATA_BUCKET"],
            Key=key,
            Body=compressed,
            ContentType="application/json",
            ContentEncoding="gzip",
        )
        item["raw_s3_key"] = key

    table = _ddb.Table(os.environ["ACTIVITIES_TABLE"])
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(sk)")
    except ClientError as err:
        if err.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        logger.info("Activity %s already stored", item["activityId"])
    return item


def store_zones(athlete_id: str, sk: str, attributes: dict) -> None:
    attributes = {**attributes, "zones_fetched_at": datetime.now(UTC).isoformat(timespec="seconds")}
    names = {f"#a{i}": name for i, name in enumerate(attributes)}
    values = {f":v{i}": value for i, value in enumerate(attributes.values())}
    _ddb.Table(os.environ["ACTIVITIES_TABLE"]).update_item(
        Key={"athleteId": athlete_id, "sk": sk},
        UpdateExpression="SET " + ", ".join(f"#a{i} = :v{i}" for i in range(len(attributes))),
        ConditionExpression="attribute_exists(sk)",
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


def _defer(record: dict) -> None:
    _sqs.change_message_visibility(
        QueueUrl=os.environ["FETCH_QUEUE_URL"],
        ReceiptHandle=record["receiptHandle"],
        VisibilityTimeout=RATE_LIMIT_BACKOFF_SECONDS,
    )


def process(record: dict) -> None:
    message = json.loads(record["body"])
    athlete_id, activity_id, sk = message["athleteId"], message["activityId"], message["sk"]

    state = stored_state(athlete_id, sk)
    if state and state.get("zones_fetched_at"):
        logger.info("Skipping %s: already complete", activity_id)
        return

    token, _ = strava_auth.get_access_token()

    if state is None:
        try:
            resp = strava_api.get(f"/activities/{activity_id}", token, {"include_all_efforts": "true"})
        except strava_api.RateLimitedError:
            _defer(record)
            raise
        except strava_api.StravaHTTPError as err:
            if err.status == 404:  # deleted on Strava since it was listed
                logger.warning("Activity %s no longer exists; dropping", activity_id)
                return
            raise
        item = store(athlete_id, resp.body)
        logger.info(
            "Stored %s (%s bytes raw, %s)",
            activity_id,
            item["raw_bytes"],
            "s3" if "raw_s3_key" in item else "inline",
        )

    try:
        resp = strava_api.get(f"/activities/{activity_id}/zones", token)
        attributes = zones.build_attributes(resp.body)
    except strava_api.RateLimitedError:
        _defer(record)  # the retry skips the detail fetch: the item is stored
        raise
    except strava_api.StravaHTTPError as err:
        if err.status not in ZONES_UNAVAILABLE_STATUSES:
            raise
        logger.warning("Zones unavailable for %s (HTTP %s)", activity_id, err.status)
        attributes = {"zones_unavailable": True}
    store_zones(athlete_id, sk, attributes)
    logger.info("Stored zones for %s: %s", activity_id, sorted(k for k in attributes if k.endswith("_seconds")))


def handler(event, _context):
    for record in event["Records"]:
        process(record)
