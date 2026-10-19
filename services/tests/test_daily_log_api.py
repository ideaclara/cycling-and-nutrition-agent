import json

from tests.conftest import http_event


def call(event):
    from coach.daily_log import handler

    result = handler.handler(event, None)
    return result["statusCode"], json.loads(result["body"])


def test_put_then_get_round_trips_waist(aws):
    status, item = call(
        http_event("PUT /daily-log/{date}", {"date": "2026-10-19"}, body={"waist_cm": 84.5, "tp_ctl": 72.3})
    )
    assert status == 200
    assert item["waist_cm"] == 84.5

    status, item = call(http_event("GET /daily-log/{date}", {"date": "2026-10-19"}))
    assert status == 200
    assert item["waist_cm"] == 84.5
    assert item["tp_ctl"] == 72.3


def test_waist_out_of_range_rejected(aws):
    for bad in (49.9, 150.1, "84"):
        status, body = call(http_event("PUT /daily-log/{date}", {"date": "2026-10-19"}, body={"waist_cm": bad}))
        assert status == 400
        assert "waist_cm" in body["errors"]


def test_partial_update_merges_and_null_removes(aws):
    call(http_event("PUT /daily-log/{date}", {"date": "2026-10-19"}, body={"waist_cm": 84.5, "sleep_score": 80}))
    status, item = call(http_event("PUT /daily-log/{date}", {"date": "2026-10-19"}, body={"waist_cm": None}))
    assert status == 200
    assert "waist_cm" not in item
    assert item["sleep_score"] == 80


def test_dqs_servings_are_scored(aws):
    status, item = call(
        http_event(
            "PUT /daily-log/{date}",
            {"date": "2026-10-19"},
            body={"dqs_servings": {"vegetables": 3, "sweets": 1}},
        )
    )
    assert status == 200
    assert item["dqs_total"] == 4


def test_unknown_field_and_bad_date(aws):
    status, body = call(http_event("PUT /daily-log/{date}", {"date": "2026-10-19"}, body={"vo2": 60}))
    assert status == 400 and "vo2" in body["errors"]
    status, _ = call(http_event("GET /daily-log/{date}", {"date": "19-10-2026"}))
    assert status == 400


def test_range_query(aws):
    for day in ("2026-10-17", "2026-10-18", "2026-10-19"):
        call(http_event("PUT /daily-log/{date}", {"date": day}, body={"sleep_score": 70}))
    status, body = call(http_event("GET /daily-log", query={"from": "2026-10-18", "to": "2026-10-19"}))
    assert status == 200
    assert [i["date"] for i in body["items"]] == ["2026-10-18", "2026-10-19"]


def test_schema_route_exposes_waist(aws):
    status, body = call(http_event("GET /daily-log/schema"))
    assert status == 200
    assert body["fields"]["waist_cm"]["minimum"] == 50
    assert body["fields"]["waist_cm"]["maximum"] == 150
