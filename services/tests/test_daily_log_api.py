import json

from tests.conftest import http_event


def call(event):
    from coach.daily_log import handler

    result = handler.handler(event, None)
    return result["statusCode"], json.loads(result["body"])


def test_put_then_get_round_trips_waist(aws):
    status, item = call(
        http_event("PUT /daily-log/{date}", {"date": "2026-10-19"}, body={"waist_cm": 84.5, "xert_tp_w": 272})
    )
    assert status == 200
    assert item["waist_cm"] == 84.5

    status, item = call(http_event("GET /daily-log/{date}", {"date": "2026-10-19"}))
    assert status == 200
    assert item["waist_cm"] == 84.5
    assert item["xert_tp_w"] == 272


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


def test_intervals_values_are_returned_as_prefills(aws):
    import boto3

    boto3.resource("dynamodb").Table("IntervalsDaily").put_item(
        Item={"athleteId": "3634905", "date": "2026-10-20", "hrv": 58, "ctl": 60, "atl": 65}
    )
    status, item = call(http_event("GET /daily-log/{date}", {"date": "2026-10-20"}))
    assert status == 200
    assert item["intervals"] == {"hrv_overnight_avg_ms": 58}  # CTL/ATL are no longer form fields
    assert "hrv_overnight_avg_ms" not in item  # not copied into the manual log

    status, item = call(http_event("PUT /daily-log/{date}", {"date": "2026-10-20"}, body={"hrv_overnight_avg_ms": 55}))
    assert item["hrv_overnight_avg_ms"] == 55
    assert item["intervals"]["hrv_overnight_avg_ms"] == 58


def test_trainingpeaks_fields_are_no_longer_accepted(aws):
    status, body = call(http_event("PUT /daily-log/{date}", {"date": "2026-10-19"}, body={"tp_tss": 80}))
    assert status == 400 and "tp_tss" in json.dumps(body)
