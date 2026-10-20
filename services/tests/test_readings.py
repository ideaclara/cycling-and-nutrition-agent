import json
from datetime import UTC, datetime

import pytest

from tests.conftest import http_event


def call(event):
    from coach.readings import handler

    result = handler.handler(event, None)
    return result["statusCode"], json.loads(result["body"])


BP = {"type": "BP", "measured_at": "2026-10-19T07:00", "systolic_mmhg": 118, "diastolic_mmhg": 76, "pulse_bpm": 52}


def test_bp_reading_is_stored_in_utc_and_listed_by_local_day(aws):
    status, item = call(http_event("POST /readings", body=BP))
    assert status == 201
    # 07:00 London in October is BST (UTC+1)
    assert item["measured_at"] == "2026-10-19T06:00:00Z"
    assert item["sk"] == "BP#2026-10-19T06:00:00Z"
    assert item["local_date"] == "2026-10-19"

    status, body = call(http_event("GET /readings", query={"from": "2026-10-19", "to": "2026-10-19"}))
    assert status == 200
    assert [(i["type"], i["systolic_mmhg"]) for i in body["items"]] == [("BP", 118)]


def test_late_evening_reading_belongs_to_the_local_day(aws):
    # 00:30 local on the 20th is 23:30 UTC on the 19th
    call(http_event("POST /readings", body={"type": "TEMP", "measured_at": "2026-10-20T00:30", "temp_c": 36.84}))
    _, day19 = call(http_event("GET /readings", query={"from": "2026-10-19", "to": "2026-10-19"}))
    _, day20 = call(http_event("GET /readings", query={"from": "2026-10-20", "to": "2026-10-20", "type": "TEMP"}))
    assert day19["items"] == []
    assert day20["items"][0]["temp_c"] == 36.8


def test_delete_reading(aws):
    call(http_event("POST /readings", body=BP))
    ts = "2026-10-19T06%3A00%3A00Z"
    status, _ = call(http_event("DELETE /readings/{type}/{ts}", {"type": "BP", "ts": ts}))
    assert status == 200
    status, _ = call(http_event("DELETE /readings/{type}/{ts}", {"type": "BP", "ts": ts}))
    assert status == 404


@pytest.mark.parametrize(
    "changes,field",
    [
        ({"diastolic_mmhg": 120, "systolic_mmhg": 118}, "diastolic_mmhg"),
        ({"systolic_mmhg": 260}, "systolic_mmhg"),
        ({"pulse_bpm": 52.5}, "pulse_bpm"),
        ({"pulse_bpm": None}, "pulse_bpm"),
        ({"measured_at": "2099-01-01T07:00"}, "measured_at"),
        ({"measured_at": "yesterday"}, "measured_at"),
        ({"weight": 70}, "weight"),
    ],
)
def test_invalid_bp_rejected(aws, changes, field):
    status, body = call(http_event("POST /readings", body={**BP, **changes}))
    assert status == 400
    assert field in body["errors"]


def test_temperature_range_and_unknown_type(aws):
    status, body = call(
        http_event("POST /readings", body={"type": "TEMP", "measured_at": "2026-10-19T07:00", "temp_c": 45})
    )
    assert status == 400 and "temp_c" in body["errors"]
    status, body = call(http_event("POST /readings", body={"type": "GLUCOSE", "measured_at": "2026-10-19T07:00"}))
    assert status == 400 and "type" in body["errors"]


def test_schema_lists_both_types(aws):
    status, body = call(http_event("GET /readings/schema"))
    assert status == 200
    assert body["types"]["BP"]["systolic_mmhg"]["maximum"] == 250
    assert body["types"]["TEMP"]["temp_c"]["decimals"] == 1


def test_offset_timestamps_are_accepted():
    from common.readings_schema import parse_local_time

    assert parse_local_time("2026-01-10T07:00") == datetime(2026, 1, 10, 7, 0, tzinfo=UTC)  # GMT in winter
    assert parse_local_time("2026-10-19T06:00:00Z") == datetime(2026, 10, 19, 6, 0, tzinfo=UTC)
