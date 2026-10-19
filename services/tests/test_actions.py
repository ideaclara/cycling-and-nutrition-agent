import json
from datetime import date

import boto3

from tests.conftest import agent_body, agent_event


def put_log(day, **fields):
    from common import daily_log_repo

    daily_log_repo.update("3634905", day, fields, set())


def test_agent_response_envelope(aws):
    from coach.actions.get_daily_metrics import handler

    event = agent_event("/daily-metrics", parameters=[{"name": "date", "type": "string", "value": "2026-10-19"}])
    result = handler.handler(event, None)
    assert result["messageVersion"] == "1.0"
    assert result["response"]["actionGroup"] == "coach-actions"
    assert result["response"]["apiPath"] == "/daily-metrics"
    assert result["response"]["httpStatusCode"] == 200


def test_get_daily_metrics_joins_sources(aws):
    from coach.actions.get_daily_metrics import handler

    put_log("2026-10-19", waist_cm=84.5, hrv_overnight_avg_ms=52.0)
    ddb = boto3.resource("dynamodb")
    ddb.Table("WithingsTelemetry").put_item(
        Item={"PK": "USER#31179536", "SK": "WITHINGS#MEAS#1760850000", "timestamp": 1760850000, "weight_kg": 78}
    )
    ddb.Table("StravaActivities").put_item(
        Item={
            "athleteId": "3634905",
            "sk": "2026-10-19T06:30:00Z#111",
            "activityId": "111",
            "name": "Morning ride",
            "start_date_local": "2026-10-19T07:30:00Z",
            "kilojoules": 900,
            "raw_gzip": b"ignored",
        }
    )
    ddb.Table("StravaActivities").put_item(
        Item={"athleteId": "3634905", "sk": "2026-10-20T06:30:00Z#222", "start_date_local": "2026-10-20T07:30:00Z"}
    )

    event = agent_event("/daily-metrics", parameters=[{"name": "date", "type": "string", "value": "2026-10-19"}])
    body = agent_body(handler.handler(event, None))
    assert body["daily_log"]["waist_cm"] == 84.5
    assert body["withings_latest"]["weight_kg"] == 78
    assert [a["activityId"] for a in body["strava_activities"]] == ["111"]
    assert "raw_gzip" not in body["strava_activities"][0]


def test_log_dqs_entry_accumulates(aws):
    from coach.actions.log_dqs_entry import handler

    items = [{"description": "porridge", "category": "whole_grains", "servings": 1}]
    event = agent_event(
        "/dqs-entries",
        "POST",
        body_properties=[
            {"name": "date", "type": "string", "value": "2026-10-19"},
            {"name": "food_items", "type": "array", "value": json.dumps(items)},
        ],
    )
    first = agent_body(handler.handler(event, None))
    second = agent_body(handler.handler(event, None))
    assert first["dqs_total"] == 2
    assert second["dqs_total"] == 4  # 2nd serving of whole grains = +2
    assert second["dqs_change"] == 2
    assert second["servings_today"] == {"whole_grains": 2}


def test_log_dqs_entry_rejects_unknown_category(aws):
    from coach.actions.log_dqs_entry import handler

    event = agent_event(
        "/dqs-entries",
        "POST",
        body_properties=[{"name": "food_items", "type": "array", "value": '[{"category": "pizza", "servings": 1}]'}],
    )
    result = handler.handler(event, None)
    assert result["response"]["httpStatusCode"] == 400


def test_ramp_rate_compute():
    from coach.actions.calculate_ramp_rate.handler import classify, compute

    rows = [
        {"date": "2026-10-12", "tp_ctl": 60.0, "tp_atl": 65, "tp_tsb": -5},
        {"date": "2026-10-15", "tp_ctl": 63.0},
        {"date": "2026-10-19", "tp_ctl": 66.0, "tp_atl": 80, "tp_tsb": -14},
    ]
    result = compute(rows, date(2026, 10, 12), date(2026, 10, 19))
    assert result["ramp_per_week"] == 6.0
    assert result["assessment"] == "high"
    assert len(result["trend"]) == 3
    assert classify(9) == "aggressive" and classify(-1) == "detraining" and classify(0) == "maintaining"


def test_ramp_rate_handler_uses_nearest_earlier_value(aws):
    from coach.actions.calculate_ramp_rate import handler

    put_log("2026-10-10", tp_ctl=60.0)  # before the window start (2026-10-12)
    put_log("2026-10-19", tp_ctl=62.0)
    event = agent_event(
        "/ramp-rate",
        parameters=[
            {"name": "days", "type": "integer", "value": "7"},
            {"name": "end_date", "type": "string", "value": "2026-10-19"},
        ],
    )
    body = agent_body(handler.handler(event, None))
    assert body["window"] == {"start": "2026-10-10", "end": "2026-10-19", "days": 9}
    assert body["ramp_per_week"] == round(2 * 7 / 9, 2)


def test_ramp_rate_not_enough_data(aws):
    from coach.actions.calculate_ramp_rate import handler

    result = handler.handler(agent_event("/ramp-rate"), None)
    assert result["response"]["httpStatusCode"] == 404
