import json
from datetime import date

import boto3
import pytest

from tests.conftest import http_event


def di(day: str) -> str:
    """FatSecret date_int (days since 1970-01-01) as the string the API returns."""
    return str((date.fromisoformat(day) - date(1970, 1, 1)).days)


# FatSecret quirks: numbers as strings, a single element as a bare object.
DIARY = {
    "2026-10-20": [
        {
            "food_entry_id": "1",
            "food_entry_name": "Porridge",
            "food_entry_description": "80 g oats",
            "meal": "Breakfast",
            "calories": "300",
            "carbohydrate": "54.0",
            "protein": "10.5",
            "fat": "5.6",
            "fiber": "8.0",
            "sodium": "5",
        },
        {
            "food_entry_id": "2",
            "food_entry_name": "Chicken salad",
            "meal": "Lunch",
            "calories": "450",
            "carbohydrate": "20",
            "protein": "45.2",
            "fat": "18",
            "fiber": "6.5",
        },
    ],
    "2026-10-21": {
        "food_entry_id": "3",
        "food_entry_name": "Pasta",
        "meal": "Dinner",
        "calories": "700",
        "carbohydrate": "120",
        "protein": "25",
        "fat": "12",
    },
}


@pytest.fixture
def fatsecret(aws, monkeypatch):
    boto3.client("secretsmanager").create_secret(
        Name="fatsecret/oauth",
        SecretString=json.dumps(
            {"consumer_key": "ck", "consumer_secret": "cs", "access_token": "at", "access_secret": "as"}
        ),
    )
    calls = []

    def fake_call(method, creds, **params):
        calls.append((method, params))
        assert creds.access_token == "at"
        if method == "food_entries.get_month.v2":
            days = [{"date_int": di(d), "calories": "1"} for d in DIARY]
            return {"month": {"day": days[0] if len(days) == 1 else days}}
        day = next((d for d in DIARY if di(d) == str(params["date"])), None)
        return {"food_entries": {"food_entry": DIARY[day]} if day else None}

    from common import fatsecret_api

    monkeypatch.setattr(fatsecret_api, "call", fake_call)
    monkeypatch.setenv("BACKFILL_START_DATE", "2026-10-01")
    return calls


def run(event):
    from fatsecret.sync import handler

    return handler.handler(event, None)


def stored(day):
    return (
        boto3.resource("dynamodb")
        .Table("FatSecretDaily")
        .get_item(Key={"athleteId": "3634905", "date": day})
        .get("Item")
    )


def test_signature_matches_the_oauth_spec_example():
    """The worked HMAC-SHA1 example from the OAuth 1.0 specification."""
    from common.fatsecret_api import signature

    params = {
        "file": "vacation.jpg",
        "size": "original",
        "oauth_consumer_key": "dpf43f3p2l4k3l03",
        "oauth_token": "nnch734d00sl2jdk",
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": "1191242096",
        "oauth_nonce": "kllo9940pd9333jh",
        "oauth_version": "1.0",
    }
    sig = signature("GET", "http://photos.example.net/photos", params, "kd94hf93k423kf44", "pfkkdhi9sl3r4s00")
    assert sig == "tR3+Ty81lMeYAr/Fid0kMTYa/WM="


def test_backfill_then_repeat_writes_nothing(fatsecret, monkeypatch):
    from fatsecret.sync import handler

    monkeypatch.setattr(handler, "today", lambda: date(2026, 10, 22))
    first = run({})
    assert first == {
        "oldest": "2026-10-01",
        "newest": "2026-10-22",
        "days_with_entries": 2,
        "written": 2,
        "deleted": 0,
    }
    # One month call, then one day call per diary day only.
    assert [m for m, _ in fatsecret] == [
        "food_entries.get_month.v2",
        "food_entries.get.v2",
        "food_entries.get.v2",
    ]

    second = run({})
    assert second["oldest"] == "2026-10-15" and second["written"] == 0


def test_day_totals_meals_and_entries(fatsecret):
    from common.ddb import from_dynamo

    run({"oldest": "2026-10-20", "newest": "2026-10-21"})
    day = from_dynamo(stored("2026-10-20"))
    assert day["totals"] == {
        "calories_kcal": 750,
        "carbohydrate_g": 74,
        "protein_g": 55.7,
        "fat_g": 23.6,
        "fiber_g": 14.5,
        "sodium_mg": 5,
    }
    assert day["meals"]["breakfast"] == {
        "calories_kcal": 300,
        "carbohydrate_g": 54,
        "protein_g": 10.5,
        "fat_g": 5.6,
        "fiber_g": 8,
    }
    assert day["entries_count"] == 2 and day["entries"][0]["name"] == "Porridge"
    # A single entry arrives as a bare object.
    assert from_dynamo(stored("2026-10-21"))["entries_count"] == 1


def test_day_emptied_in_fatsecret_is_deleted(fatsecret):
    run({"oldest": "2026-10-20", "newest": "2026-10-21"})
    removed = DIARY.pop("2026-10-21")
    try:
        result = run({"oldest": "2026-10-20", "newest": "2026-10-21"})
    finally:
        DIARY["2026-10-21"] = removed
    assert result["deleted"] == 1 and stored("2026-10-21") is None


def test_missing_secret_is_skipped_not_failed(aws):
    assert "skipped" in run({})
    assert run(http_event("POST /fatsecret/sync"))["statusCode"] == 503


def test_secret_without_access_token_is_not_configured(aws):
    boto3.client("secretsmanager").create_secret(
        Name="fatsecret/oauth", SecretString=json.dumps({"consumer_key": "ck", "consumer_secret": "cs"})
    )
    assert "fatsecret_authorize" in run({})["skipped"]


def test_api_error_in_a_200_body_raises():
    from unittest import mock

    from common import fatsecret_api

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"error": {"code": 8, "message": "Invalid signature"}}'

    with (
        mock.patch.object(fatsecret_api.urllib.request, "urlopen", return_value=Resp()),
        pytest.raises(fatsecret_api.FatSecretError, match="Invalid signature"),
    ):
        fatsecret_api.call("food_entries.get.v2", fatsecret_api.Credentials("ck", "cs", "at", "as"), date=1)


def test_daily_log_prefills_nutrition_and_typed_value_wins(fatsecret):
    from coach.daily_log import handler

    run({"oldest": "2026-10-20", "newest": "2026-10-21"})
    event = http_event("GET /daily-log/{date}", path_params={"date": "2026-10-20"})
    body = json.loads(handler.handler(event, None)["body"])
    assert body["fatsecret"] == {"protein_g": 56, "carbs_g": 74, "fat_g": 24, "fibre_g": 14}

    from coach.advice import features

    boto3.resource("dynamodb").Table("DailyFitnessLog").put_item(
        Item={"athleteId": "3634905", "date": "2026-10-20", "protein_g": 150}
    )
    yesterday = features.build("3634905", date(2026, 10, 21))["yesterday"]
    assert yesterday["protein_g"] == 150  # typed in the log
    assert yesterday["fibre_g"] == 14  # from FatSecret
    assert yesterday["calories_kcal"] == 750
