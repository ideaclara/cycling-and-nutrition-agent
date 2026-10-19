"""DynamoDB <-> JSON conversion helpers.

boto3's resource layer rejects floats and returns Decimals, so values are
converted at the boundary in both directions.
"""

import json
from decimal import Decimal
from typing import Any


def to_dynamo(value: Any) -> Any:
    """Recursively convert floats to Decimal (via str, to avoid binary noise)."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: to_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_dynamo(v) for v in value]
    return value


def from_dynamo(value: Any) -> Any:
    """Recursively convert Decimals back to int or float."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: from_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [from_dynamo(v) for v in value]
    return value


def dumps(value: Any) -> str:
    return json.dumps(from_dynamo(value), separators=(",", ":"))
