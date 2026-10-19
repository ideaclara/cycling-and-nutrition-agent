import json
import os

# Must be set before any handler module creates a boto3 client.
os.environ.update(
    AWS_DEFAULT_REGION="us-east-1",
    AWS_ACCESS_KEY_ID="testing",
    AWS_SECRET_ACCESS_KEY="testing",
    AWS_SESSION_TOKEN="testing",
    ATHLETE_ID="3634905",
    WITHINGS_USER_ID="31179536",
    ATHLETE_TIMEZONE="Europe/London",
    ACTIVITIES_TABLE="StravaActivities",
    DAILY_LOG_TABLE="DailyFitnessLog",
    WITHINGS_TABLE="WithingsTelemetry",
    DATA_BUCKET="test-data-bucket",
    STRAVA_SECRET_ID="strava/oauth",
    BACKFILL_START_EPOCH="1767225600",
)

import boto3  # noqa: E402
import pytest  # noqa: E402
from moto import mock_aws  # noqa: E402


def _table(ddb, name, pk, sk):
    ddb.create_table(
        TableName=name,
        KeySchema=[{"AttributeName": pk, "KeyType": "HASH"}, {"AttributeName": sk, "KeyType": "RANGE"}],
        AttributeDefinitions=[
            {"AttributeName": pk, "AttributeType": "S"},
            {"AttributeName": sk, "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


@pytest.fixture
def aws():
    with mock_aws():
        ddb = boto3.client("dynamodb")
        _table(ddb, "StravaActivities", "athleteId", "sk")
        _table(ddb, "DailyFitnessLog", "athleteId", "date")
        _table(ddb, "WithingsTelemetry", "PK", "SK")
        boto3.client("s3").create_bucket(Bucket="test-data-bucket")
        queue_url = boto3.client("sqs").create_queue(QueueName="strava-activity-fetch-queue")["QueueUrl"]
        os.environ["FETCH_QUEUE_URL"] = queue_url
        boto3.client("secretsmanager").create_secret(
            Name="strava/oauth",
            SecretString=json.dumps(
                {
                    "client_id": "123",
                    "client_secret": "shh",
                    "access_token": "old-access",
                    "refresh_token": "old-refresh",
                    "expires_at": 0,
                    "athlete_id": "3634905",
                }
            ),
        )
        yield {"queue_url": queue_url}


def agent_event(api_path: str, method: str = "GET", parameters=None, body_properties=None) -> dict:
    event = {
        "messageVersion": "1.0",
        "actionGroup": "coach-actions",
        "apiPath": api_path,
        "httpMethod": method,
        "parameters": parameters or [],
        "sessionAttributes": {},
        "promptSessionAttributes": {},
    }
    if body_properties is not None:
        event["requestBody"] = {"content": {"application/json": {"properties": body_properties}}}
    return event


def agent_body(result: dict) -> dict:
    return json.loads(result["response"]["responseBody"]["application/json"]["body"])


def http_event(route_key: str, path_params=None, query=None, body=None) -> dict:
    method, path = route_key.split(" ", 1)
    return {
        "routeKey": route_key,
        "rawPath": path,
        "pathParameters": path_params or {},
        "queryStringParameters": query,
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
        "requestContext": {"domainName": "api.example.com", "http": {"method": method, "path": path}},
    }
