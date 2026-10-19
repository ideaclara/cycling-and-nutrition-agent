"""Queue every stored Strava activity that has no zones yet.

The fetch worker sees the activity is already stored and makes only the
`GET /activities/{id}/zones` call, so each message costs one Strava read.
At 200 reads per 15 minutes, a few hundred activities finish within about
an hour. 429s are deferred by the worker as usual. Safe to rerun: activities
that already have `zones_fetched_at` are skipped here and in the worker.

    uv run --project services python scripts/backfill_strava_zones.py [--dry-run]
"""

import argparse
import json

import boto3

REGION = "us-east-1"
TABLE = "StravaActivities"
QUEUE = "strava-activity-fetch-queue"


def missing_zones(client):
    kwargs = {
        "TableName": TABLE,
        "ProjectionExpression": "athleteId, sk, activityId",
        "FilterExpression": "attribute_not_exists(zones_fetched_at)",
    }
    while True:
        page = client.scan(**kwargs)
        yield from page["Items"]
        if "LastEvaluatedKey" not in page:
            return
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def message(item) -> str:
    sk = item["sk"]["S"]
    activity_id = item["activityId"]["S"] if "activityId" in item else sk.rsplit("#", 1)[1]
    return json.dumps({"athleteId": item["athleteId"]["S"], "activityId": activity_id, "sk": sk})


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="count activities without queueing")
    args = parser.parse_args()

    items = list(missing_zones(boto3.client("dynamodb", region_name=REGION)))
    print(f"{len(items)} activities without zones")
    if args.dry_run or not items:
        return

    sqs = boto3.client("sqs", region_name=REGION)
    queue_url = sqs.get_queue_url(QueueName=QUEUE)["QueueUrl"]
    for start in range(0, len(items), 10):
        chunk = items[start : start + 10]
        entries = [{"Id": str(i), "MessageBody": message(item)} for i, item in enumerate(chunk)]
        result = sqs.send_message_batch(QueueUrl=queue_url, Entries=entries)
        if result.get("Failed"):
            raise RuntimeError(f"SQS batch send failed: {result['Failed']}")
    print(f"Queued {len(items)} messages on {QUEUE}")


if __name__ == "__main__":
    main()
