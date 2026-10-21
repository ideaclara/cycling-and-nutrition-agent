import json
from decimal import Decimal

import boto3

from tests.conftest import http_event


def call(query):
    from coach.analysis import handler

    result = handler.handler(http_event("GET /analysis/series", query=query), None)
    return result["statusCode"], json.loads(result["body"])


def test_series_merges_every_source_per_day(aws):
    ddb = boto3.resource("dynamodb")
    ddb.Table("DailyFitnessLog").put_item(Item={"athleteId": "3634905", "date": "2026-10-18", "waist_cm": 84})
    ddb.Table("IntervalsDaily").put_item(
        Item={"athleteId": "3634905", "date": "2026-10-19", "ctl": 62, "comments": "x"}
    )
    # 2026-10-19 07:00 BST = 06:00 UTC
    ddb.Table("WithingsTelemetry").put_item(
        Item={"PK": "USER#31179536", "SK": "WITHINGS#MEAS#1792389600", "timestamp": 1792389600, "weight_kg": 70}
    )
    for i, kj in enumerate((900, 600)):
        ddb.Table("StravaActivities").put_item(
            Item={
                "athleteId": "3634905",
                "sk": f"2026-10-19T0{6 + i}:00:00Z#{i}",
                "activityId": str(i),
                "start_date_local": f"2026-10-19T0{7 + i}:00:00Z",
                "kilojoules": kj,
                "moving_time": 3600,
            }
        )
    ddb.Table("ManualReadings").put_item(
        Item={
            "athleteId": "3634905",
            "sk": "TEMP#2026-10-19T06:05:00Z",
            "type": "TEMP",
            "local_date": "2026-10-19",
            "local_time": "07:05",
            "measured_at": "2026-10-19T06:05:00Z",
            "temp_c": Decimal("36.7"),
        }
    )

    ddb.Table("IntervalsActivities").put_item(
        Item={
            "athleteId": "3634905",
            "sk": "2026-10-19T07:00:00#i9",
            "start_date_local": "2026-10-19T07:00:00",
            "icu_training_load": 95,
            "icu_intensity": Decimal("81.2"),
            "icu_weighted_avg_watts": 228,
        }
    )

    status, body = call({"from": "2026-10-17", "to": "2026-10-19"})
    assert status == 200
    days = {d["date"]: d for d in body["days"]}
    assert list(days) == ["2026-10-17", "2026-10-18", "2026-10-19"]
    assert days["2026-10-17"] == {"date": "2026-10-17"}
    assert days["2026-10-18"]["log"] == {"waist_cm": 84}
    assert days["2026-10-19"]["intervals"] == {"ctl": 62}
    assert days["2026-10-19"]["withings"]["weight_kg"] == 70
    assert days["2026-10-19"]["strava"]["activities"] == 2
    assert days["2026-10-19"]["strava"]["kilojoules"] == 1500
    assert days["2026-10-19"]["temp"] == [{"time": "07:05", "temp_c": 36.7}]
    assert days["2026-10-19"]["rides"] == {
        "tss": 95,
        "rides": [
            {
                "start_date_local": "2026-10-19T07:00:00",
                "tss": 95,
                "intensity_factor": 0.81,
                "normalized_power_w": 228,
            }
        ],
    }


def test_range_limits(aws):
    assert call({"from": "2026-10-19", "to": "2026-10-01"})[0] == 400
    assert call({"from": "2025-01-01", "to": "2026-10-01"})[0] == 400
    status, body = call({"to": "2026-10-19"})
    assert status == 200 and len(body["days"]) == 90
