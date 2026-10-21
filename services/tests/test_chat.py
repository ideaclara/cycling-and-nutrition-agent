import io
import json

import pytest

from tests.conftest import http_event

SESSION = "3f2b8c1e-0d4a-4c7e-9b1a-2f6d8e9c0a11"


def call(event):
    from coach.chat import handler

    result = handler.handler(event, None)
    return result["statusCode"], json.loads(result["body"])


def chat(body):
    return call(http_event("POST /chat", body=body))


def test_unconfigured_backends_return_503(aws, monkeypatch):
    monkeypatch.delenv("AGENT_ID", raising=False)
    monkeypatch.delenv("AGENT_RUNTIME_ARN", raising=False)
    assert chat({"message": "hi", "sessionId": SESSION})[0] == 503
    assert chat({"message": "hi", "sessionId": SESSION, "backend": "agentcore"})[0] == 503


@pytest.mark.parametrize(
    "body",
    [
        {"message": "", "sessionId": SESSION},
        {"message": "x" * 4001, "sessionId": SESSION},
        {"message": "hi", "sessionId": "abc"},
        {"message": "hi", "sessionId": SESSION, "backend": "openai"},
    ],
)
def test_invalid_requests(aws, body):
    assert chat(body)[0] == 400


def test_agent_answer_with_citations_and_trace_is_stored(aws, monkeypatch):
    from coach.chat import handler

    monkeypatch.setenv("AGENT_ID", "AGENT1")
    monkeypatch.setenv("AGENT_ALIAS_ID", "ALIAS1")
    sent = {}

    def fake_invoke_agent(**kwargs):
        sent.update(kwargs)
        ref = {
            "content": {"text": "Level 3 Tempo 76–90%"},
            "location": {"s3Location": {"uri": "s3://b/tables/x.md"}},
            "metadata": {"title": "Training and Racing with a Power Meter"},
        }
        return {
            "completion": [
                {
                    "trace": {
                        "trace": {
                            "orchestrationTrace": {
                                "invocationInput": {"actionGroupInvocationInput": {"apiPath": "/daily-metrics"}}
                            }
                        }
                    }
                },
                {"trace": {"trace": {"guardrailTrace": {"action": "NONE"}}}},
                {"chunk": {"bytes": b"Ride tempo at ", "attribution": {"citations": [{"retrievedReferences": [ref]}]}}},
                {"chunk": {"bytes": b"190-225 W."}},
            ]
        }

    monkeypatch.setattr(handler._agents, "invoke_agent", fake_invoke_agent)
    status, item = chat({"message": "What should I ride?", "sessionId": SESSION})
    assert status == 200
    assert item["text"] == "Ride tempo at 190-225 W."
    assert item["citations"][0]["source"] == "tables/x.md"
    assert item["steps"] == ["action:/daily-metrics"]
    assert item["guardrail"] is None
    assert sent["sessionState"]["promptSessionAttributes"]["timezone"] == "Europe/London"

    status, history = call(http_event("GET /chat/{sessionId}", {"sessionId": SESSION}))
    assert [m["role"] for m in history["items"]] == ["user", "assistant"]


def test_agentcore_json_and_event_stream(aws, monkeypatch):
    from coach.chat import handler

    monkeypatch.setenv("AGENT_RUNTIME_ARN", "arn:aws:bedrock-agentcore:us-east-1:1:runtime/coach-abc")

    class FakeCore:
        def __init__(self, body, content_type):
            self.body, self.content_type = body, content_type

        def invoke_agent_runtime(self, **kwargs):
            assert json.loads(kwargs["payload"])["prompt"] == "hi"
            return {"response": io.BytesIO(self.body), "contentType": self.content_type}

    monkeypatch.setattr(
        handler, "_agentcore", FakeCore(b'{"text": "Easy spin", "steps": ["tool:x"]}', "application/json")
    )
    status, item = chat({"message": "hi", "sessionId": SESSION, "backend": "agentcore"})
    assert (status, item["text"], item["steps"]) == (200, "Easy spin", ["tool:x"])

    monkeypatch.setattr(handler, "_agentcore", FakeCore(b'data: "Easy "\ndata: "spin"\n', "text/event-stream"))
    status, item = chat({"message": "hi", "sessionId": SESSION, "backend": "agentcore"})
    assert item["text"] == "Easy spin"
