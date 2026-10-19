"""Bedrock Agents action-group event parsing and response building (OpenAPI schema style).

An agent invokes the Lambda with an event like::

    {"messageVersion": "1.0", "actionGroup": "...", "apiPath": "/daily-metrics",
     "httpMethod": "GET", "parameters": [{"name": "date", "type": "string", "value": "2026-10-19"}],
     "requestBody": {"content": {"application/json": {"properties": [...]}}},
     "sessionAttributes": {...}, "promptSessionAttributes": {...}, ...}

Every value arrives as a string, so typed values are coerced here using the
`type` the agent sends alongside each one.
"""

import json
from typing import Any

from common.ddb import from_dynamo


def _coerce(kind: str, value: Any) -> Any:
    if value is None:
        return None
    if kind in ("integer",):
        return int(value)
    if kind in ("number",):
        return float(value)
    if kind == "boolean":
        return str(value).lower() == "true"
    if kind in ("array", "object") and isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def parameters(event: dict) -> dict[str, Any]:
    """Merge path/query parameters and JSON request-body properties into one dict."""
    merged = {p["name"]: _coerce(p.get("type", "string"), p.get("value")) for p in event.get("parameters") or []}
    body = (event.get("requestBody") or {}).get("content", {}).get("application/json", {})
    for prop in body.get("properties") or []:
        merged[prop["name"]] = _coerce(prop.get("type", "string"), prop.get("value"))
    return merged


def respond(event: dict, body: Any, status: int = 200) -> dict:
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event.get("actionGroup"),
            "apiPath": event.get("apiPath"),
            "httpMethod": event.get("httpMethod"),
            "httpStatusCode": status,
            "responseBody": {"application/json": {"body": json.dumps(from_dynamo(body))}},
        },
        "sessionAttributes": event.get("sessionAttributes") or {},
        "promptSessionAttributes": event.get("promptSessionAttributes") or {},
    }


def error(event: dict, message: str, status: int = 400) -> dict:
    return respond(event, {"error": message}, status)
