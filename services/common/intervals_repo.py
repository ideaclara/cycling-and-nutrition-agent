"""Read access to IntervalsDaily and IntervalsActivities.

Intervals.icu's wellness record mixes Garmin-synced values (HRV, resting HR,
sleep, readiness) with its own fitness model (ctl = fitness, atl = fatigue).
The Garmin values are prefills on the daily-log form, where a manually entered
value wins. Fitness, fatigue and form come only from Intervals; older days
fall back to the TrainingPeaks values once typed into DailyFitnessLog.

IntervalsActivities holds one item per activity with every metric Intervals
calculates (training load = TSS, intensity = IF x 100, weighted average
watts = normalized power, ...).
"""

import os

import boto3
from boto3.dynamodb.conditions import Key

from common.daily_log_schema import FIELDS
from common.ddb import from_dynamo

_ddb = boto3.resource("dynamodb")

# DailyFitnessLog field -> (Intervals wellness key, multiplier)
FIELD_SOURCES: dict[str, tuple[str, float]] = {
    "training_readiness": ("readiness", 1),
    "hrv_overnight_avg_ms": ("hrv", 1),
    "resting_hr_bpm": ("restingHR", 1),
    "sleep_duration_h": ("sleepSecs", 1 / 3600),
    "sleep_score": ("sleepScore", 1),
}

# Legacy DailyFitnessLog fields (typed in from TrainingPeaks before Intervals).
LEGACY_LOAD_FIELDS = {"ctl": "tp_ctl", "atl": "tp_atl", "tsb": "tp_tsb"}

# Per-activity metrics the advice, agent and analysis page use. The table keeps everything.
ACTIVITY_SUMMARY_FIELDS = (
    "id",
    "name",
    "type",
    "start_date_local",
    "moving_time",
    "distance",
    "total_elevation_gain",
    "icu_training_load",
    "icu_intensity",
    "icu_weighted_avg_watts",
    "icu_average_watts",
    "icu_ftp",
    "icu_variability_index",
    "icu_efficiency_factor",
    "decoupling",
    "icu_joules",
    "carbs_used",
    "average_heartrate",
    "hr_load",
    "icu_rpe",
    "feel",
)


def configured() -> bool:
    return bool(os.environ.get("INTERVALS_TABLE"))


def _table():
    return _ddb.Table(os.environ["INTERVALS_TABLE"])


def activities_configured() -> bool:
    return bool(os.environ.get("INTERVALS_ACTIVITIES_TABLE"))


def activity_sort_key(record: dict) -> str:
    """Local start time first, so a day's activities sort together: "2026-10-21T09:52:14#i199894956"."""
    return f"{record['start_date_local']}#{record['id']}"


def get(athlete_id: str, day: str) -> dict | None:
    if not configured():
        return None
    item = _table().get_item(Key={"athleteId": athlete_id, "date": day}).get("Item")
    return from_dynamo(item) if item else None


def query_range(athlete_id: str, start: str, end: str) -> list[dict]:
    if not configured():
        return []
    items: list[dict] = []
    kwargs = {"KeyConditionExpression": Key("athleteId").eq(athlete_id) & Key("date").between(start, end)}
    while True:
        page = _table().query(**kwargs)
        items.extend(page.get("Items", []))
        if "LastEvaluatedKey" not in page:
            return from_dynamo(items)
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def activities_range(athlete_id: str, start: str, end: str) -> list[dict]:
    """Activity summaries whose local start date is between `start` and `end` (YYYY-MM-DD), oldest first."""
    if not activities_configured():
        return []
    table = _ddb.Table(os.environ["INTERVALS_ACTIVITIES_TABLE"])
    kwargs = {
        "KeyConditionExpression": Key("athleteId").eq(athlete_id) & Key("sk").between(start, f"{end}~"),
        "ProjectionExpression": ", ".join(f"#{i}" for i in range(len(ACTIVITY_SUMMARY_FIELDS))),
        "ExpressionAttributeNames": {f"#{i}": name for i, name in enumerate(ACTIVITY_SUMMARY_FIELDS)},
    }
    items: list[dict] = []
    while True:
        page = table.query(**kwargs)
        items.extend(page.get("Items", []))
        if "LastEvaluatedKey" not in page:
            return from_dynamo(items)
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def activity_summary(activity: dict) -> dict:
    """Readable names for one activity: TSS, IF (as a fraction) and normalized power."""
    a = activity
    summary = {
        "id": a.get("id"),
        "name": a.get("name"),
        "type": a.get("type"),
        "start_date_local": a.get("start_date_local"),
        "moving_time_s": a.get("moving_time"),
        "distance_m": a.get("distance"),
        "elevation_m": a.get("total_elevation_gain"),
        "tss": a.get("icu_training_load"),
        "intensity_factor": round(a["icu_intensity"] / 100, 2) if a.get("icu_intensity") is not None else None,
        "normalized_power_w": a.get("icu_weighted_avg_watts"),
        "average_power_w": a.get("icu_average_watts"),
        "ftp_w": a.get("icu_ftp"),
        "variability_index": _round2(a.get("icu_variability_index")),
        "efficiency_factor": _round2(a.get("icu_efficiency_factor")),
        "decoupling_pct": _round2(a.get("decoupling")),
        "kilojoules": round(a["icu_joules"] / 1000) if a.get("icu_joules") is not None else None,
        "carbs_used_g": a.get("carbs_used"),
        "average_hr_bpm": a.get("average_heartrate"),
        "hr_load": a.get("hr_load"),
        "rpe": a.get("icu_rpe"),
        "feel": a.get("feel"),
    }
    return {k: v for k, v in summary.items() if v is not None}


def _round2(value):
    return round(value, 2) if isinstance(value, (int, float)) else None


def _round(field: str, value: float) -> float | int:
    spec = FIELDS[field]
    if spec.integer:
        return round(value)
    return round(value, spec.decimals if spec.decimals is not None else 1)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def as_daily_fields(record: dict | None) -> dict:
    """Intervals wellness values renamed to the DailyFitnessLog fields they prefill."""
    if not record:
        return {}
    values = {}
    for field, (key, factor) in FIELD_SOURCES.items():
        if _is_number(record.get(key)):
            values[field] = _round(field, record[key] * factor)
    return values


def load_fields(record: dict | None, log: dict | None = None) -> dict:
    """Fitness (ctl), fatigue (atl) and form (tsb = ctl - atl) for one day.

    Intervals wins; days before Intervals fall back to the TrainingPeaks values in the log.
    """
    if record and _is_number(record.get("ctl")) and _is_number(record.get("atl")):
        return {
            "ctl": round(record["ctl"], 1),
            "atl": round(record["atl"], 1),
            "tsb": round(record["ctl"] - record["atl"], 1),
        }
    log = log or {}
    return {key: log[field] for key, field in LEGACY_LOAD_FIELDS.items() if _is_number(log.get(field))}
