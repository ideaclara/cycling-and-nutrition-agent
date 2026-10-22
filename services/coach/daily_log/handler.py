"""Daily fitness log API (HTTP API, JWT-protected).

PUT /daily-log/{date}        partial upsert; `null` removes a field
GET /daily-log/{date}        one day
GET /daily-log?from=&to=     inclusive range (max 366 days)
GET /daily-log/schema        field definitions, so the form never drifts from the API

Single-day responses carry an `intervals` object (Intervals.icu wellness) and a
`fatsecret` object (food diary totals): values for that day, renamed to
daily-log fields. The form shows them as prefills; they are never written to
DailyFitnessLog unless the user saves them.
"""

import json
import logging
import os
from dataclasses import asdict
from datetime import date, timedelta

from common import daily_log_repo, dqs_table, fatsecret_repo, intervals_repo
from common.daily_log_schema import FIELDS, ValidationError, validate_update
from common.dates import today
from common.http import json_body, response

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MAX_RANGE_DAYS = 366


def _athlete_id() -> str:
    return os.environ["ATHLETE_ID"]


def _parse_day(value: str | None) -> str:
    if not value:
        raise ValueError("date is required (YYYY-MM-DD)")
    return date.fromisoformat(value).isoformat()


def get_schema() -> dict:
    return response(
        200,
        {
            "fields": {name: asdict(field) for name, field in FIELDS.items()},
            "dqs_categories": {
                "high_quality": list(dqs_table.HIGH_QUALITY),
                "low_quality": list(dqs_table.LOW_QUALITY),
            },
        },
    )


def _with_intervals(day: str, item: dict | None) -> dict | None:
    intervals = intervals_repo.as_daily_fields(intervals_repo.get(_athlete_id(), day))
    fatsecret = fatsecret_repo.as_daily_fields(fatsecret_repo.get(_athlete_id(), day))
    if not item and not intervals and not fatsecret:
        return None
    return {**(item or {"date": day}), "intervals": intervals, "fatsecret": fatsecret}


def get_day(day: str) -> dict:
    item = _with_intervals(day, daily_log_repo.get(_athlete_id(), day))
    if not item:
        return response(404, {"message": f"No entry for {day}"})
    return response(200, item)


def get_range(params: dict) -> dict:
    end = _parse_day(params.get("to") or today().isoformat())
    start = _parse_day(params.get("from") or (date.fromisoformat(end) - timedelta(days=29)).isoformat())
    if start > end:
        raise ValueError("'from' must not be after 'to'")
    if (date.fromisoformat(end) - date.fromisoformat(start)).days > MAX_RANGE_DAYS:
        raise ValueError(f"range is limited to {MAX_RANGE_DAYS} days")
    return response(200, {"items": daily_log_repo.query_range(_athlete_id(), start, end)})


def put_day(day: str, event: dict) -> dict:
    to_set, to_remove = validate_update(json_body(event))
    if not to_set and not to_remove:
        raise ValueError("request body has no fields to update")
    return response(200, _with_intervals(day, daily_log_repo.update(_athlete_id(), day, to_set, to_remove)))


def handler(event, _context):
    route = event.get("routeKey", "")
    path_params = event.get("pathParameters") or {}
    try:
        if route == "GET /daily-log/schema":
            return get_schema()
        if route == "GET /daily-log":
            return get_range(event.get("queryStringParameters") or {})
        if route == "GET /daily-log/{date}":
            return get_day(_parse_day(path_params.get("date")))
        if route == "PUT /daily-log/{date}":
            return put_day(_parse_day(path_params.get("date")), event)
        return response(404, {"message": f"Unknown route {route}"})
    except ValidationError as err:
        return response(400, {"message": "Validation failed", "errors": err.errors})
    except (ValueError, json.JSONDecodeError) as err:
        return response(400, {"message": str(err)})
