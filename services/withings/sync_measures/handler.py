"""Step 2 of the Withings pipeline: fetch scale measurements and store sessions.

Ported from the `measures` branch of the eu-west-2 `router` Lambda. Withings
returns one measure group per sensor packet; groups sharing a timestamp are
consolidated into a single MEASUREMENT_SESSION item:

    PK = USER#<userid>   SK = WITHINGS#MEAS#<epoch, 10 digits>

Writes are idempotent upserts, so re-reading the last 30 days each run is safe.
"""

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from decimal import Decimal

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MEASURE_URL = "https://wbsapi.withings.net/measure"
DEFAULT_LOOKBACK_DAYS = 30

# Withings meastype IDs -> attribute names (same names as the eu-west-2 table).
TYPE_FIELD_MAP = {
    1: "weight_kg",
    4: "height_m",
    5: "fat_free_mass_kg",
    6: "fat_ratio_pct",
    8: "fat_mass_weight_kg",
    9: "diastolic_blood_pressure_mmhg",
    10: "systolic_blood_pressure_mmhg",
    11: "heart_pulse_bpm",
    12: "temperature_celsius",
    54: "spo2_pct",
    71: "body_temperature_celsius",
    73: "skin_temperature_celsius",
    76: "muscle_mass_kg",
    77: "hydration_kg",
    88: "bone_mass_kg",
    123: "vo2_max_ml_min_kg",
    130: "afib_result",
    155: "vascular_age_yrs",
    168: "extracellular_water_kg",
    169: "intracellular_water_kg",
    170: "visceral_fat_index",
    226: "bmr_kcal",
    227: "metabolic_age_years",
}
PWV_TYPE = 91
VASCULAR_AGE_TYPE = 155

_ddb = boto3.resource("dynamodb")


def decode(value: int, unit: int) -> Decimal:
    return Decimal(str(value)) * (Decimal("10") ** Decimal(str(unit)))


def consolidate(userid: str, measuregrps: list[dict]) -> list[dict]:
    """Merge measure groups that share a timestamp into session items."""
    sessions: dict[int, dict] = {}
    for grp in measuregrps:
        timestamp = int(grp["date"])
        session = sessions.setdefault(
            timestamp,
            {
                "PK": f"USER#{userid}",
                "SK": f"WITHINGS#MEAS#{timestamp:010d}",
                "entity_type": "MEASUREMENT_SESSION",
                "timestamp": timestamp,
                "measure_group_ids": set(),
                "device_model": grp.get("model", "unknown"),
            },
        )
        session["measure_group_ids"].add(int(grp["grpid"]))

        measures = grp.get("measures", [])
        # A PWV reading in a group that also reports vascular age is the
        # heart-rate-normalised value; otherwise it is the raw transit speed.
        normalised = any(m["type"] == VASCULAR_AGE_TYPE for m in measures)
        for m in measures:
            value = decode(m["value"], m["unit"])
            if m["type"] == PWV_TYPE:
                key = "pulse_wave_velocity_normalized_ms" if normalised else "pulse_wave_velocity_raw_ms"
            else:
                key = TYPE_FIELD_MAP.get(m["type"], f"type_{m['type']}")
            session[key] = value

    items = []
    for session in sessions.values():
        session["measure_group_ids"] = sorted(session["measure_group_ids"])
        items.append(session)
    return items


def fetch_measuregrps(access_token: str, start_date: int) -> list[dict]:
    groups: list[dict] = []
    offset = 0
    while True:
        params = {"action": "getmeas", "category": 1, "startdate": start_date}
        if offset:
            params["offset"] = offset
        req = urllib.request.Request(
            MEASURE_URL,
            data=urllib.parse.urlencode(params).encode("utf-8"),
            headers={"Authorization": f"Bearer {access_token}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            res = json.loads(resp.read().decode("utf-8"))
        if res.get("status") != 0:
            raise RuntimeError(f"Withings getmeas failed: status {res.get('status')}")
        body = res.get("body", {})
        groups.extend(body.get("measuregrps", []))
        if not body.get("more"):
            return groups
        offset = body.get("offset", 0)


def handler(event, _context):
    config = event.get("endpoint_config") or {}
    lookback = int(config.get("lookback_days", DEFAULT_LOOKBACK_DAYS))
    start_date = int(config.get("startdate", int(time.time()) - lookback * 86400))

    groups = fetch_measuregrps(event["access_token"], start_date)
    items = consolidate(str(event["userid"]), groups)

    table = _ddb.Table(os.environ["WITHINGS_TABLE"])
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)

    logger.info("groups=%s sessions=%s", len(groups), len(items))
    return {"endpoint": "measures", "persisted_items": len(items)}
