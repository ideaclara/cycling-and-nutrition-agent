import json

import boto3
import pytest

from tests.conftest import http_event

WELLNESS = [
    {
        "id": "2026-10-18",
        "ctl": 61.24,
        "atl": 70.5,
        "rampRate": 3.1,
        "hrv": 54.0,
        "restingHR": 46,
        "sleepSecs": 27000,
        "sleepScore": 81,
        "readiness": None,
        "weight": 70.4,
        "comments": "",
    },
    {
        "id": "2026-10-19",
        "ctl": 62.0,
        "atl": 66.75,
        "hrv": 61.0,
        "restingHR": 45,
        "sleepSecs": 29880,
        "sleepScore": 88,
        "readiness": 74,
    },
]


@pytest.fixture
def intervals(aws, monkeypatch):
    boto3.client("secretsmanager").create_secret(
        Name="intervals/api", SecretString=json.dumps({"athlete_id": "i42", "api_key": "k"})
    )
    calls = []

    def fake_get(path, creds, params=None):
        calls.append((path, params))
        return [r for r in WELLNESS if params["oldest"] <= r["id"] <= params["newest"]]

    from common import intervals_api

    monkeypatch.setattr(intervals_api, "get", fake_get)
    monkeypatch.setenv("BACKFILL_START_DATE", "2026-10-01")
    return calls


def run(event):
    from intervals.sync import handler

    return handler.handler(event, None)


def test_backfill_then_repeat_writes_nothing(intervals, monkeypatch):
    from intervals.sync import handler

    monkeypatch.setattr(handler, "today", lambda: __import__("datetime").date(2026, 10, 19))
    first = run({})
    assert first == {"oldest": "2026-10-01", "newest": "2026-10-19", "fetched": 2, "written": 2}
    assert intervals[0] == ("/athlete/i42/wellness", {"oldest": "2026-10-01", "newest": "2026-10-19"})

    second = run({})
    assert second["oldest"] == "2026-10-12"  # lookback once the table has data
    assert second["written"] == 0

    item = (
        boto3.resource("dynamodb")
        .Table("IntervalsDaily")
        .get_item(Key={"athleteId": "3634905", "date": "2026-10-18"})["Item"]
    )
    assert "readiness" not in item and "comments" not in item  # nulls and blanks dropped
    assert float(item["ctl"]) == 61.24


def test_changed_day_is_rewritten(intervals):
    run({"oldest": "2026-10-18", "newest": "2026-10-19"})
    WELLNESS[1]["hrv"] = 63.0
    try:
        assert run({"oldest": "2026-10-18", "newest": "2026-10-19"})["written"] == 1
    finally:
        WELLNESS[1]["hrv"] = 61.0


def test_missing_secret_is_skipped_not_failed(aws):
    result = run({})
    assert "skipped" in result
    http = run(http_event("POST /intervals/sync"))
    assert http["statusCode"] == 503


def test_daily_fields_mapping():
    from common.intervals_repo import as_daily_fields

    assert as_daily_fields({**WELLNESS[1]}) == {
        "training_readiness": 74,
        "hrv_overnight_avg_ms": 61.0,
        "resting_hr_bpm": 45,
        "sleep_duration_h": 8.3,
        "sleep_score": 88,
        "tp_ctl": 62.0,
        "tp_atl": 66.8,
        "tp_tsb": -4.8,
    }
    assert as_daily_fields(None) == {}


def test_requests_send_a_user_agent(monkeypatch):
    """Cloudflare blocks urllib's default agent with a 403 (error 1010)."""
    from common import intervals_api

    sent = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"[]"

    def fake_urlopen(req, timeout):
        sent.update(req.headers)
        return Resp()

    monkeypatch.setattr(intervals_api.urllib.request, "urlopen", fake_urlopen)
    intervals_api.get("/athlete/0/wellness", intervals_api.Credentials("0", "k"))
    assert sent["User-agent"].startswith("cycling-coach/")
