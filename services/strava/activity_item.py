"""Turn a Strava DetailedActivity payload into a StravaActivities item."""

import gzip
import json
from datetime import datetime
from decimal import Decimal

# Compressed payloads above this go to S3 instead (DynamoDB's item limit is 400 KB,
# and the item also carries the queryable attributes).
MAX_INLINE_BYTES = 350_000

# Every scalar top-level field of the payload becomes its own attribute; nested
# objects and arrays live only in the raw payload. These names are set by us and
# are never overwritten by a payload field.
RESERVED = {"athleteId", "sk", "activityId", "start_epoch", "raw_gzip", "raw_s3_key", "raw_bytes", "fetched_at"}


def sort_key(start_date: str, activity_id: str) -> str:
    return f"{start_date}#{activity_id}"


def start_epoch(start_date: str) -> int:
    return int(datetime.fromisoformat(start_date.replace("Z", "+00:00")).timestamp())


def _scalar(value):
    if isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return None


def build_item(athlete_id: str, raw: bytes, fetched_at: str) -> tuple[dict, bytes]:
    """Return ``(item, compressed_payload)``.

    The caller decides whether ``compressed_payload`` fits inline (``raw_gzip``)
    or must be written to S3 (``raw_s3_key``).
    """
    activity = json.loads(raw.decode("utf-8"))
    activity_id = str(activity.get("id_str") or activity["id"])

    item: dict = {
        "athleteId": athlete_id,
        "sk": sort_key(activity["start_date"], activity_id),
        "activityId": activity_id,
        "start_epoch": start_epoch(activity["start_date"]),
        "fetched_at": fetched_at,
        "raw_bytes": len(raw),
    }
    for key, value in activity.items():
        if key in RESERVED or value is None:
            continue
        scalar = _scalar(value)
        if scalar is not None and scalar != "":
            item[key] = scalar

    # A few useful nested values, flattened so the coach can read them cheaply.
    gear = activity.get("gear") or {}
    if gear.get("name"):
        item["gear_name"] = gear["name"]
    item["segment_effort_count"] = len(activity.get("segment_efforts") or [])
    item["lap_count"] = len(activity.get("laps") or [])

    return item, gzip.compress(raw, compresslevel=9)


def decode_raw(compressed: bytes) -> dict:
    return json.loads(gzip.decompress(compressed).decode("utf-8"))
