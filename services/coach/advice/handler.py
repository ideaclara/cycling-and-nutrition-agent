"""Daily advice (v1: Converse API).

Triggered by EventBridge Scheduler at 07:30 Europe/London, or on demand:

POST /advice/refresh     generate today's advice now (overwrites today's)
GET  /advice/latest      most recent advice

The facts are computed in code (features.py); the model only writes the text.
Later versions swap the Converse call for a Prompt Management prompt (Module E)
or a Flow (Module D) without changing what is stored.
"""

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Key

from coach.advice import features
from common.dates import today
from common.ddb import from_dynamo, to_dynamo
from common.http import is_http_event, response

logger = logging.getLogger()
logger.setLevel(logging.INFO)

PROMPT = (Path(__file__).parent / "prompt.md").read_text(encoding="utf-8")
MAX_TOKENS = 700

_ddb = boto3.resource("dynamodb")
_bedrock = boto3.client("bedrock-runtime")


def _table():
    return _ddb.Table(os.environ["ADVICE_TABLE"])


def _athlete_id() -> str:
    return os.environ["ATHLETE_ID"]


def generate(facts: dict) -> dict:
    request = {
        "modelId": os.environ["ADVICE_MODEL_ID"],
        "system": [{"text": PROMPT}],
        "messages": [{"role": "user", "content": [{"text": json.dumps(facts, indent=1)}]}],
        "inferenceConfig": {"maxTokens": MAX_TOKENS, "temperature": 0.3},
    }
    if os.environ.get("GUARDRAIL_ID"):
        request["guardrailConfig"] = {
            "guardrailIdentifier": os.environ["GUARDRAIL_ID"],
            "guardrailVersion": os.environ.get("GUARDRAIL_VERSION", "1"),
            "trace": "enabled",
        }
    result = _bedrock.converse(**request)
    text = "".join(block.get("text", "") for block in result["output"]["message"]["content"])
    return {
        "text": text,
        "model": request["modelId"],
        "stop_reason": result.get("stopReason"),
        "guardrail_intervened": result.get("stopReason") == "guardrail_intervened",
        "usage": result.get("usage", {}),
        "latency_ms": result.get("metrics", {}).get("latencyMs"),
    }


def refresh() -> dict:
    day = today()
    facts = features.build(_athlete_id(), day)
    item = {
        "athleteId": _athlete_id(),
        "date": day.isoformat(),
        "status": facts["status"],
        "facts": facts,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "version": "v1-converse",
        **generate(facts),
    }
    _table().put_item(Item=to_dynamo(item))
    logger.info("advice %s status=%s tokens=%s", item["date"], item["status"], item["usage"])
    return item


def latest() -> dict | None:
    result = _table().query(KeyConditionExpression=Key("athleteId").eq(_athlete_id()), ScanIndexForward=False, Limit=1)
    items = result.get("Items", [])
    return from_dynamo(items[0]) if items else None


def handler(event, _context):
    if not is_http_event(event):  # scheduled run
        item = refresh()
        return {"date": item["date"], "status": item["status"]}
    route = event.get("routeKey", "")
    if route == "GET /advice/latest":
        item = latest()
        return response(200, item) if item else response(404, {"message": "No advice yet"})
    if route == "POST /advice/refresh":
        return response(200, refresh())
    return response(404, {"message": f"Unknown route {route}"})
