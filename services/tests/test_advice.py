import json
from datetime import date
from decimal import Decimal

import boto3
import pytest

from tests.conftest import http_event


def put_days(table, rows):
    for day, values in rows.items():
        table.put_item(Item={"athleteId": "3634905", "date": day, **values})


@pytest.fixture
def week(aws):
    ddb = boto3.resource("dynamodb")
    intervals = ddb.Table("IntervalsDaily")
    put_days(intervals, {f"2026-10-{d:02d}": {"hrv": 60, "restingHR": 45, "ctl": 60, "atl": 60} for d in range(12, 19)})
    put_days(intervals, {"2026-10-19": {"hrv": 48, "restingHR": 46, "sleepSecs": 25200, "ctl": 62, "atl": 70}})
    put_days(ddb.Table("DailyFitnessLog"), {"2026-10-19": {"xert_tp_w": 250}, "2026-10-18": {"dqs_total": 14}})
    return ddb


def test_features_compute_baselines_flags_and_levels(week):
    from coach.advice import features

    facts = features.build("3634905", date(2026, 10, 19))
    assert facts["recovery"]["hrv_7d_baseline_ms"] == 60
    assert facts["recovery"]["hrv_vs_baseline_pct"] == -20.0
    assert facts["recovery"]["sleep_h"] == 7.0
    assert facts["load"] == {"ctl": 62, "atl": 70, "tsb": -8, "ctl_change_7d": 2}
    assert facts["flags"] == ["hrv_below_baseline"]
    assert facts["status"] == "amber"
    assert facts["power_levels"][2] == {"level": 3, "name": "Tempo", "low_w": 190, "high_w": 225}
    assert facts["yesterday"]["dqs_total"] == 14
    assert facts["missing"] == []


def test_fever_reading_makes_status_red(week):
    from coach.advice import features

    week.Table("ManualReadings").put_item(
        Item={
            "athleteId": "3634905",
            "sk": "TEMP#2026-10-19T06:00:00Z",
            "type": "TEMP",
            "local_date": "2026-10-19",
            "local_time": "07:00",
            "measured_at": "2026-10-19T06:00:00Z",
            "temp_c": Decimal("38.2"),
        }
    )
    facts = features.build("3634905", date(2026, 10, 19))
    assert "possible_fever" in facts["flags"]
    assert facts["status"] == "red"


def test_no_data_is_unknown(aws):
    from coach.advice import features

    facts = features.build("3634905", date(2026, 10, 19))
    assert facts["status"] == "unknown"
    assert "HRV" in facts["missing"]


def test_refresh_stores_advice_and_latest_returns_it(week, monkeypatch):
    from coach.advice import handler

    monkeypatch.setenv("ADVICE_MODEL_ID", "global.anthropic.claude-haiku-5-5")
    monkeypatch.setenv("GUARDRAIL_ID", "gr-123")
    monkeypatch.setattr(handler, "today", lambda: date(2026, 10, 19))
    sent = {}

    def fake_converse(**request):
        sent.update(request)
        return {
            "output": {"message": {"content": [{"text": "**Today: amber.** Easy ride."}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 900, "outputTokens": 120},
            "metrics": {"latencyMs": 1500},
        }

    monkeypatch.setattr(handler._bedrock, "converse", fake_converse)
    result = handler.handler(http_event("POST /advice/refresh"), None)
    item = json.loads(result["body"])
    assert result["statusCode"] == 200
    assert item["status"] == "amber" and item["text"].startswith("**Today: amber.**")
    assert sent["guardrailConfig"]["guardrailIdentifier"] == "gr-123"
    assert json.loads(sent["messages"][0]["content"][0]["text"])["status"] == "amber"

    latest = handler.handler(http_event("GET /advice/latest"), None)
    assert json.loads(latest["body"])["date"] == "2026-10-19"
