"""Manual readings API (HTTP API, JWT-protected): blood pressure and body temperature.

POST   /readings                      {type, measured_at (local "YYYY-MM-DDTHH:MM"), ...values}
GET    /readings?from=&to=&type=      inclusive local-date range (max 366 days)
DELETE /readings/{type}/{ts}          ts = the reading's measured_at (UTC ISO)
GET    /readings/schema               field definitions for the form
"""

import json
import logging
import os
from dataclasses import asdict
from datetime import date, timedelta
from urllib.parse import unquote

from common import readings_repo
from common.daily_log_schema import ValidationError
from common.dates import today
from common.http import json_body, response
from common.readings_schema import TYPES, parse_local_time, validate_reading

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MAX_RANGE_DAYS = 366


def _athlete_id() -> str:
    return os.environ["ATHLETE_ID"]


def get_schema() -> dict:
    return response(
        200,
        {"types": {kind: {name: asdict(f) for name, f in fields.items()} for kind, fields in TYPES.items()}},
    )


def get_range(params: dict) -> dict:
    end = date.fromisoformat(params.get("to") or today().isoformat())
    start = date.fromisoformat(params["from"]) if params.get("from") else end - timedelta(days=29)
    if start > end:
        raise ValueError("'from' must not be after 'to'")
    if (end - start).days > MAX_RANGE_DAYS:
        raise ValueError(f"range is limited to {MAX_RANGE_DAYS} days")
    kind = params.get("type")
    if kind and kind not in TYPES:
        raise ValueError(f"type must be one of {', '.join(TYPES)}")
    return response(200, {"items": readings_repo.query(_athlete_id(), start, end, [kind] if kind else None)})


def post_reading(event: dict) -> dict:
    kind, measured_at, values = validate_reading(json_body(event))
    return response(201, readings_repo.put(_athlete_id(), kind, measured_at, values))


def delete_reading(path_params: dict) -> dict:
    kind = path_params.get("type")
    if kind not in TYPES:
        raise ValueError(f"type must be one of {', '.join(TYPES)}")
    measured_at = parse_local_time(unquote(path_params.get("ts") or ""))
    if not readings_repo.delete(_athlete_id(), kind, measured_at):
        return response(404, {"message": "No such reading"})
    return response(200, {"deleted": readings_repo.sort_key(kind, measured_at)})


def handler(event, _context):
    route = event.get("routeKey", "")
    try:
        if route == "GET /readings/schema":
            return get_schema()
        if route == "GET /readings":
            return get_range(event.get("queryStringParameters") or {})
        if route == "POST /readings":
            return post_reading(event)
        if route == "DELETE /readings/{type}/{ts}":
            return delete_reading(event.get("pathParameters") or {})
        return response(404, {"message": f"Unknown route {route}"})
    except ValidationError as err:
        return response(400, {"message": "Validation failed", "errors": err.errors})
    except (ValueError, json.JSONDecodeError) as err:
        return response(400, {"message": str(err)})
