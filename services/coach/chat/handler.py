"""Coach chat (HTTP API, JWT-protected), with two interchangeable backends.

POST /chat               {"message": "...", "sessionId": "<uuid>", "backend": "agent" | "agentcore"}
GET  /chat/{sessionId}   transcript of one session, oldest first

- agent:     a Bedrock Agent built in the console (Module C), via InvokeAgent
- agentcore: an agent on AgentCore Runtime (Module G), via InvokeAgentRuntime

Each backend returns 503 until its IDs are configured in CDK context. Turns are
stored in ChatMessages for 30 days.
"""

import json
import logging
import os
import re
import time
from datetime import UTC, datetime

import boto3
from boto3.dynamodb.conditions import Key

from common.dates import local_tz, today
from common.ddb import from_dynamo, to_dynamo
from common.http import json_body, response

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MAX_MESSAGE = 4000
TTL_DAYS = 30
SESSION_ID = re.compile(r"^[0-9a-fA-F-]{36}$")  # a UUID: also long enough for AgentCore (33+)

_ddb = boto3.resource("dynamodb")
_agents = boto3.client("bedrock-agent-runtime")
_agentcore = None  # created on first use: older boto3 runtimes may not know the service


class NotConfiguredError(RuntimeError):
    pass


def _table():
    return _ddb.Table(os.environ["CHAT_TABLE"])


def _citations(attribution: dict) -> list[dict]:
    found = []
    for citation in attribution.get("citations", []):
        for ref in citation.get("retrievedReferences", []):
            uri = ref.get("location", {}).get("s3Location", {}).get("uri", "")
            found.append(
                {
                    "source": uri.split("/", 3)[-1] if uri else ref.get("metadata", {}).get("title", "?"),
                    "title": ref.get("metadata", {}).get("title"),
                    "excerpt": " ".join(ref.get("content", {}).get("text", "").split())[:300],
                }
            )
    return found


def ask_agent(message: str, session_id: str) -> dict:
    agent_id, alias_id = os.environ.get("AGENT_ID"), os.environ.get("AGENT_ALIAS_ID")
    if not agent_id or not alias_id:
        raise NotConfiguredError("The Bedrock Agent isn't configured yet (Module C).")
    result = _agents.invoke_agent(
        agentId=agent_id,
        agentAliasId=alias_id,
        sessionId=session_id,
        inputText=message,
        enableTrace=True,
        sessionState={
            "promptSessionAttributes": {"today": today().isoformat(), "timezone": str(local_tz())},
        },
    )
    text, citations, steps, guardrail = [], [], [], None
    for event in result["completion"]:
        if "chunk" in event:
            text.append(event["chunk"].get("bytes", b"").decode("utf-8"))
            citations += _citations(event["chunk"].get("attribution", {}))
        trace = event.get("trace", {}).get("trace", {})
        if "guardrailTrace" in trace and trace["guardrailTrace"].get("action") == "INTERVENED":
            guardrail = "intervened"
        invocation = trace.get("orchestrationTrace", {}).get("invocationInput", {})
        if "actionGroupInvocationInput" in invocation:
            steps.append(f"action:{invocation['actionGroupInvocationInput'].get('apiPath', '?')}")
        if "knowledgeBaseLookupInput" in invocation:
            steps.append("knowledge base")
    return {"text": "".join(text), "citations": citations, "steps": steps, "guardrail": guardrail}


def ask_agentcore(message: str, session_id: str) -> dict:
    global _agentcore
    runtime_arn = os.environ.get("AGENT_RUNTIME_ARN")
    if not runtime_arn:
        raise NotConfiguredError("The AgentCore runtime isn't configured yet (Module G).")
    _agentcore = _agentcore or boto3.client("bedrock-agentcore")
    result = _agentcore.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        runtimeSessionId=session_id,
        payload=json.dumps({"prompt": message, "today": today().isoformat()}).encode(),
    )
    raw = result["response"].read().decode("utf-8")
    if "text/event-stream" in result.get("contentType", ""):
        raw = "".join(line[5:].strip().strip('"') for line in raw.splitlines() if line.startswith("data:"))
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        body = {"text": raw}
    return {
        "text": body.get("text") or body.get("result") or "",
        "citations": body.get("citations", []),
        "steps": body.get("steps", []),
        "guardrail": body.get("guardrail"),
    }


def _store(session_id: str, role: str, payload: dict) -> dict:
    now = datetime.now(UTC)
    item = {
        "sessionId": session_id,
        "ts": now.isoformat(timespec="milliseconds") + f"#{role}",
        "role": role,
        "at": now.isoformat(timespec="seconds"),
        "ttl": int(time.time()) + TTL_DAYS * 86400,
        **payload,
    }
    _table().put_item(Item=to_dynamo(item))
    return item


def post_chat(event: dict) -> dict:
    body = json_body(event)
    message, session_id, backend = body.get("message"), body.get("sessionId"), body.get("backend", "agent")
    if not isinstance(message, str) or not message.strip() or len(message) > MAX_MESSAGE:
        raise ValueError(f"message must be 1–{MAX_MESSAGE} characters")
    if not isinstance(session_id, str) or not SESSION_ID.match(session_id):
        raise ValueError("sessionId must be a UUID")
    if backend not in ("agent", "agentcore"):
        raise ValueError("backend must be 'agent' or 'agentcore'")

    ask = ask_agent if backend == "agent" else ask_agentcore
    started = time.monotonic()
    answer = ask(message.strip(), session_id)
    answer["latency_ms"] = int((time.monotonic() - started) * 1000)
    _store(session_id, "user", {"text": message.strip(), "backend": backend})
    return response(200, _store(session_id, "assistant", {**answer, "backend": backend}))


def get_session(session_id: str | None) -> dict:
    if not session_id or not SESSION_ID.match(session_id):
        raise ValueError("sessionId must be a UUID")
    result = _table().query(KeyConditionExpression=Key("sessionId").eq(session_id))
    return response(200, {"items": from_dynamo(result.get("Items", []))})


def handler(event, _context):
    route = event.get("routeKey", "")
    try:
        if route == "POST /chat":
            return post_chat(event)
        if route == "GET /chat/{sessionId}":
            return get_session((event.get("pathParameters") or {}).get("sessionId"))
        return response(404, {"message": f"Unknown route {route}"})
    except NotConfiguredError as err:
        return response(503, {"message": str(err)})
    except (ValueError, json.JSONDecodeError) as err:
        return response(400, {"message": str(err)})
