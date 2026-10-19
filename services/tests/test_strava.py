import gzip
import json
import os
from unittest.mock import patch

import boto3
import pytest

from common import strava_api
from tests.conftest import http_event

# A real activity response with location data (GPS, map, places) removed.
SAMPLE = os.path.join(os.path.dirname(__file__), "fixtures", "activity_redacted.json")


def sample_bytes() -> bytes:
    with open(SAMPLE, "rb") as f:
        return f.read()


def secret():
    raw = boto3.client("secretsmanager").get_secret_value(SecretId="strava/oauth")["SecretString"]
    return json.loads(raw)


# --- token refresh -----------------------------------------------------------


def test_expired_token_is_refreshed_and_saved(aws):
    from common import strava_auth

    fresh = {"access_token": "new-access", "refresh_token": "new-refresh", "expires_at": 2_000_000_000}
    with patch.object(strava_auth, "_post_token", return_value=fresh) as post:
        token, athlete = strava_auth.get_access_token(now=1_000_000_000)
    assert (token, athlete) == ("new-access", "3634905")
    assert post.call_args.args[0]["grant_type"] == "refresh_token"
    assert secret()["refresh_token"] == "new-refresh"


def test_valid_token_is_not_refreshed(aws):
    from common import strava_auth

    bundle = secret() | {"expires_at": 2_000_000_000}
    strava_auth.save_bundle(bundle)
    with patch.object(strava_auth, "_post_token") as post:
        token, _ = strava_auth.get_access_token(now=1_000_000_000)
    assert token == "old-access"
    post.assert_not_called()


# --- OAuth callback ----------------------------------------------------------


def test_callback_rejects_state_mismatch(aws):
    from strava.auth_callback import handler

    handler.handler(http_event("GET /strava/authorize"), None)
    event = http_event(
        "GET /strava/callback", query={"code": "abc", "state": "wrong", "scope": "read,activity:read_all"}
    )
    assert handler.handler(event, None)["statusCode"] == 400


def test_callback_stores_tokens(aws):
    from common import strava_auth
    from strava.auth_callback import handler

    redirect = handler.handler(http_event("GET /strava/authorize"), None)
    assert redirect["statusCode"] == 302
    assert "redirect_uri=https%3A%2F%2Fapi.example.com%2Fstrava%2Fcallback" in redirect["headers"]["Location"]
    state = secret()["pending_state"]

    tokens = {
        "access_token": "a",
        "refresh_token": "r",
        "expires_at": 2_000_000_000,
        "athlete": {"id": 3634905, "firstname": "Matt", "lastname": "T"},
    }
    event = http_event("GET /strava/callback", query={"code": "abc", "state": state, "scope": "read,activity:read_all"})
    with patch.object(strava_auth, "_post_token", return_value=tokens):
        assert handler.handler(event, None)["statusCode"] == 200
    stored = secret()
    assert stored["access_token"] == "a" and "pending_state" not in stored


# --- list → queue ------------------------------------------------------------


def summary(activity_id, start):
    return {"id": activity_id, "start_date": start}


def test_list_uses_backfill_start_then_latest(aws):
    from strava.list_activities import handler

    pages = [[summary(1, "2026-01-02T08:00:00Z"), summary(2, "2026-01-03T08:00:00Z")], []]
    calls = []

    def fake_get(path, token, params):
        calls.append(params)
        return strava_api.StravaResponse(200, {}, json.dumps(pages[params["page"] - 1]).encode())

    with (
        patch.object(handler.strava_auth, "get_access_token", return_value=("t", "3634905")),
        patch.object(handler.strava_api, "get", side_effect=fake_get),
    ):
        result = handler.handler({"source": "aws.events"}, None)
    assert result == {"after": 1767225600, "queued": 2}
    assert calls[0]["after"] == 1767225600

    boto3.resource("dynamodb").Table("StravaActivities").put_item(
        Item={"athleteId": "3634905", "sk": "2026-01-03T08:00:00Z#2", "start_epoch": 1767427200}
    )
    calls.clear()
    with (
        patch.object(handler.strava_auth, "get_access_token", return_value=("t", "3634905")),
        patch.object(handler.strava_api, "get", side_effect=fake_get),
    ):
        handler.handler({"source": "aws.events"}, None)
    assert calls[0]["after"] == 1767427200

    messages = boto3.client("sqs").receive_message(QueueUrl=aws["queue_url"], MaxNumberOfMessages=10)["Messages"]
    assert {json.loads(m["Body"])["activityId"] for m in messages} == {"1", "2"}


def test_list_via_http_returns_202(aws):
    from strava.list_activities import handler

    with (
        patch.object(handler.strava_auth, "get_access_token", return_value=("t", "3634905")),
        patch.object(handler.strava_api, "get", return_value=strava_api.StravaResponse(200, {}, b"[]")),
    ):
        result = handler.handler(http_event("POST /strava/sync"), None)
    assert result["statusCode"] == 202


# --- fetch worker ------------------------------------------------------------


def sqs_record(activity_id="19084710818", sk="2026-09-28T07:00:00Z#19084710818"):
    body = json.dumps({"athleteId": "3634905", "activityId": activity_id, "sk": sk})
    return {"Records": [{"body": body, "receiptHandle": "rh"}]}


def test_worker_stores_full_payload_compressed(aws):
    from strava.activity_item import decode_raw, sort_key
    from strava.fetch_activity_worker import handler

    raw = sample_bytes()
    activity = json.loads(raw)
    sk = sort_key(activity["start_date"], activity["id_str"])
    with (
        patch.object(handler.strava_auth, "get_access_token", return_value=("t", "3634905")),
        patch.object(handler.strava_api, "get", return_value=strava_api.StravaResponse(200, {}, raw)) as get,
    ):
        handler.handler(sqs_record(sk=sk), None)
    assert get.call_args.args[2] == {"include_all_efforts": "true"}

    item = boto3.resource("dynamodb").Table("StravaActivities").get_item(Key={"athleteId": "3634905", "sk": sk})["Item"]
    assert item["name"] == activity["name"]
    assert item["segment_effort_count"] == len(activity["segment_efforts"])
    assert decode_raw(item["raw_gzip"].value) == activity  # every field preserved
    assert len(item["raw_gzip"].value) < len(raw) / 4


def test_worker_skips_already_stored(aws):
    from strava.fetch_activity_worker import handler

    boto3.resource("dynamodb").Table("StravaActivities").put_item(
        Item={"athleteId": "3634905", "sk": "2026-09-28T07:00:00Z#19084710818"}
    )
    with patch.object(handler.strava_api, "get") as get:
        handler.handler(sqs_record(), None)
    get.assert_not_called()


def test_worker_large_payload_goes_to_s3(aws):
    from strava import activity_item
    from strava.fetch_activity_worker import handler

    raw = sample_bytes()
    with (
        patch.object(handler, "MAX_INLINE_BYTES", 10),
        patch.object(activity_item, "MAX_INLINE_BYTES", 10),
        patch.object(handler.strava_auth, "get_access_token", return_value=("t", "3634905")),
        patch.object(handler.strava_api, "get", return_value=strava_api.StravaResponse(200, {}, raw)),
    ):
        handler.handler(sqs_record(), None)

    key = "strava/activities/19084710818.json.gz"
    obj = boto3.client("s3").get_object(Bucket="test-data-bucket", Key=key)["Body"].read()
    assert json.loads(gzip.decompress(obj)) == json.loads(raw)


def test_worker_rate_limit_defers_message(aws):
    from strava.fetch_activity_worker import handler

    with (
        patch.object(handler.strava_auth, "get_access_token", return_value=("t", "3634905")),
        patch.object(handler.strava_api, "get", side_effect=strava_api.RateLimitedError("429")),
        patch.object(handler._sqs, "change_message_visibility") as change,
        pytest.raises(strava_api.RateLimitedError),
    ):
        handler.handler(sqs_record(), None)
    assert change.call_args.kwargs["VisibilityTimeout"] == 900


def test_worker_drops_deleted_activity(aws):
    from strava.fetch_activity_worker import handler

    with (
        patch.object(handler.strava_auth, "get_access_token", return_value=("t", "3634905")),
        patch.object(handler.strava_api, "get", side_effect=strava_api.StravaHTTPError(404, "not found")),
    ):
        handler.handler(sqs_record(), None)  # no exception: message is consumed
