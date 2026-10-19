"""Step 1 of the Withings pipeline: return a valid access token.

Ported unchanged in behaviour from the eu-west-2 `token_refresher`: refreshes
when within 5 minutes of expiry and writes the new tokens back to the secret.

Withings rotates the refresh token on every refresh, so only ONE pipeline may
use a given secret: disable the eu-west-2 schedule before this one runs.
"""

import json
import os
import time
import urllib.parse
import urllib.request

import boto3

TOKEN_URL = "https://wbsapi.withings.net/v2/oauth2"
REFRESH_MARGIN_SECONDS = 300

_secrets = boto3.client("secretsmanager")


def _refresh(credentials: dict, now: int) -> dict:
    data = urllib.parse.urlencode(
        {
            "action": "requesttoken",
            "grant_type": "refresh_token",
            "client_id": credentials["client_id"],
            "client_secret": credentials["client_secret"],
            "refresh_token": credentials["refresh_token"],
        }
    ).encode("utf-8")
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    if body.get("status") != 0:
        raise RuntimeError(f"Withings token refresh error: status {body.get('status')}")

    token = body["body"]
    credentials.update(
        access_token=token["access_token"],
        refresh_token=token["refresh_token"],
        expires_at=now + int(token.get("expires_in", 10800)),
    )
    if "userid" in token:
        credentials["userid"] = str(token["userid"])
    return credentials


def handler(event, _context):
    secret_name = event.get("secret_name") or os.environ["WITHINGS_SECRET_ID"]
    credentials = json.loads(_secrets.get_secret_value(SecretId=secret_name)["SecretString"])

    now = int(time.time())
    if now >= int(credentials.get("expires_at", 0)) - REFRESH_MARGIN_SECONDS:
        credentials = _refresh(credentials, now)
        _secrets.put_secret_value(SecretId=secret_name, SecretString=json.dumps(credentials))

    return {"access_token": credentials["access_token"], "userid": str(credentials.get("userid", ""))}
