"""Copy WithingsTelemetry from eu-west-2 to us-east-1, item for item.

Uses the low-level DynamoDB client so numbers travel as their original strings
(no float rounding). Writes are idempotent puts, so it is safe to rerun.

    uv run --project services python scripts/migrate_withings.py [--dry-run]
"""

import argparse

import boto3

TABLE = "WithingsTelemetry"
SOURCE_REGION = "eu-west-2"
TARGET_REGION = "us-east-1"


def scan_all(client):
    kwargs = {"TableName": TABLE}
    while True:
        page = client.scan(**kwargs)
        yield from page["Items"]
        if "LastEvaluatedKey" not in page:
            return
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def write_batch(client, items):
    request = {TABLE: [{"PutRequest": {"Item": item}} for item in items]}
    while request:
        result = client.batch_write_item(RequestItems=request)
        request = result.get("UnprocessedItems") or {}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="count source items without writing")
    args = parser.parse_args()

    source = boto3.client("dynamodb", region_name=SOURCE_REGION)
    target = boto3.client("dynamodb", region_name=TARGET_REGION)

    copied, batch = 0, []
    for item in scan_all(source):
        batch.append(item)
        if len(batch) == 25:
            if not args.dry_run:
                write_batch(target, batch)
            copied += len(batch)
            batch = []
    if batch:
        if not args.dry_run:
            write_batch(target, batch)
        copied += len(batch)

    source_count = source.describe_table(TableName=TABLE)["Table"]["ItemCount"]
    verb = "Would copy" if args.dry_run else "Copied"
    print(f"{verb} {copied} items (source ItemCount ~{source_count}, refreshed every ~6h)")
    if not args.dry_run:
        target_count = sum(1 for _ in scan_all(target))
        print(f"Target now holds {target_count} items")


if __name__ == "__main__":
    main()
