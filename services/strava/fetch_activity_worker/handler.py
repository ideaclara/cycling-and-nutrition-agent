"""SQS consumer: fetch one Strava activity in full and store it.

Calls ``GET /activities/{id}?include_all_efforts=true`` and writes the item to
StravaActivities (gzip payload inline, or in S3 if it is too big).

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
from strava.activity_item import MAX_INLINE_BYTES, build_item

logger = logging.getLogger()
logger.setLevel(logging.INFO)

RATE_LIMIT_BACKOFF_SECONDS = 900

_ddb = boto3.resource("dynamodb")
_s3 = boto3.client("s3")
_sqs = boto3.client("sqs")


def already_stored(athlete_id: str, sk: str) -> bool:
    table = _ddb.Table(os.environ["ACTIVITIES_TABLE"])
    result = table.get_item(Key={"athleteId": athlete_id, "sk": sk}, ProjectionExpression="sk")
    return "Item" in result


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


def process(record: dict) -> None:
    message = json.loads(record["body"])
    athlete_id, activity_id, sk = message["athleteId"], message["activityId"], message["sk"]

    if already_stored(athlete_id, sk):
        logger.info("Skipping %s: already stored", activity_id)
        return

    token, _ = strava_auth.get_access_token()
    try:
        resp = strava_api.get(f"/activities/{activity_id}", token, {"include_all_efforts": "true"})
    except strava_api.RateLimitedError:
        _sqs.change_message_visibility(
            QueueUrl=os.environ["FETCH_QUEUE_URL"],
            ReceiptHandle=record["receiptHandle"],
            VisibilityTimeout=RATE_LIMIT_BACKOFF_SECONDS,
        )
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


def handler(event, _context):
    for record in event["Records"]:
        process(record)
