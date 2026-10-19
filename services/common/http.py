"""Helpers for API Gateway HTTP API (payload v2.0) handlers."""

import json
from typing import Any

from common.ddb import from_dynamo


def response(status: int, body: Any, headers: dict[str, str] | None = None) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", **(headers or {})},
        "body": json.dumps(from_dynamo(body)),
    }


def html(status: int, body: str) -> dict:
    return {"statusCode": status, "headers": {"Content-Type": "text/html"}, "body": body}


def json_body(event: dict) -> dict:
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64

        raw = base64.b64decode(raw).decode("utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Request body must be a JSON object")
    return parsed


def is_http_event(event: dict) -> bool:
    return "requestContext" in event and "http" in event.get("requestContext", {})
