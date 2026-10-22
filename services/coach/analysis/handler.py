"""Analysis API (HTTP API, JWT-protected): one merged row per day for the charts.

GET /analysis/series?from=YYYY-MM-DD&to=YYYY-MM-DD   (inclusive, max 366 days; default last 90)

Each row keeps every source separate, so the page can label where a value came
from and choose which one wins:

    {"date": "2026-10-19",
     "log": {...manual DailyFitnessLog fields...},
     "intervals": {...Intervals.icu wellness and fitness...},
     "withings": {...last scale session that day...},
     "strava": {"activities": 1, "moving_time_s": 7200, "distance_m": 60000, "kilojoules": 1500, ...},
     "rides": {"tss": 120, "rides": [{"tss": 120, "intensity_factor": 0.77, "normalized_power_w": 217, ...}]},
     "fatsecret": {"totals": {"calories_kcal": 2650, "protein_g": 140, ...}, "meals": {...}, "entries_count": 9},
     "bp": [{"time": "07:00", "systolic_mmhg": 118, ...}], "temp": [{"time": "07:05", "temp_c": 36.7}]}

Days with no data at all are still returned, so charts get a continuous x-axis.
"""

import json
import logging
import os
from datetime import date, timedelta

from common import daily_log_repo, fatsecret_repo, intervals_repo, metrics_repo, readings_repo
from common.dates import today
from common.http import response

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MAX_RANGE_DAYS = 366
DEFAULT_DAYS = 90
LOG_SKIP = {"athleteId", "date", "updated_at", "notes", "dqs_entries"}
INTERVALS_SKIP = {"athleteId", "date", "source", "fetched_at", "sportInfo", "comments"}
STRAVA_SUMS = {"moving_time": "moving_time_s", "distance": "distance_m", "kilojoules": "kilojoules"}


def _range(params: dict) -> tuple[date, date]:
    end = date.fromisoformat(params.get("to") or today().isoformat())
    start = date.fromisoformat(params["from"]) if params.get("from") else end - timedelta(days=DEFAULT_DAYS - 1)
    if start > end:
        raise ValueError("'from' must not be after 'to'")
    if (end - start).days >= MAX_RANGE_DAYS:
        raise ValueError(f"range is limited to {MAX_RANGE_DAYS} days")
    return start, end


def _strava_day(activities: list[dict]) -> dict:
    day = {"activities": len(activities), "elevation_m": 0, "suffer_score": 0}
    day.update(dict.fromkeys(STRAVA_SUMS.values(), 0))
    for a in activities:
        for src, dst in STRAVA_SUMS.items():
            day[dst] += a.get(src) or 0
        day["elevation_m"] += a.get("total_elevation_gain") or 0
        day["suffer_score"] += a.get("suffer_score") or 0
    return day


def series(start: date, end: date) -> list[dict]:
    athlete = os.environ["ATHLETE_ID"]
    lo, hi = start.isoformat(), end.isoformat()
    rows = {
        (start + timedelta(days=i)).isoformat(): {"date": (start + timedelta(days=i)).isoformat()}
        for i in range((end - start).days + 1)
    }
    for item in daily_log_repo.query_range(athlete, lo, hi):
        rows[item["date"]]["log"] = {k: v for k, v in item.items() if k not in LOG_SKIP}
    for item in intervals_repo.query_range(athlete, lo, hi):
        values = {k: v for k, v in item.items() if k not in INTERVALS_SKIP and isinstance(v, (int, float))}
        rows[item["date"]]["intervals"] = values
    for session in metrics_repo.withings_range(start, end):
        if session.get("local_date") in rows:
            rows[session["local_date"]]["withings"] = session  # oldest first, so the last one wins
    by_day: dict[str, list[dict]] = {}
    for activity in metrics_repo.activities_range(start, end):
        by_day.setdefault(str(activity["start_date_local"])[:10], []).append(activity)
    for day, activities in by_day.items():
        rows[day]["strava"] = _strava_day(activities)
    for activity in intervals_repo.activities_range(athlete, lo, hi):
        day = rows[activity["start_date_local"][:10]].setdefault("rides", {"tss": 0, "rides": []})
        day["tss"] += activity.get("icu_training_load") or 0
        day["rides"].append(intervals_repo.activity_summary(activity))
    for item in fatsecret_repo.query_range(athlete, lo, hi):
        rows[item["date"]]["fatsecret"] = fatsecret_repo.day_summary(item)
    for reading in readings_repo.query(athlete, start, end):
        key = "bp" if reading["type"] == "BP" else "temp"
        values = {k: v for k, v in reading.items() if k.endswith(("_mmhg", "_bpm", "_c"))}
        rows[reading["local_date"]].setdefault(key, []).append({"time": reading["local_time"], **values})
    return list(rows.values())


def handler(event, _context):
    if event.get("routeKey") != "GET /analysis/series":
        return response(404, {"message": f"Unknown route {event.get('routeKey')}"})
    try:
        start, end = _range(event.get("queryStringParameters") or {})
    except (ValueError, json.JSONDecodeError) as err:
        return response(400, {"message": str(err)})
    return response(200, {"from": start.isoformat(), "to": end.isoformat(), "days": series(start, end)})
