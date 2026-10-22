"""Minimal FatSecret Platform API client (standard library only).

Food diary methods act on one user's profile, so they need OAuth 1.0 with a
user access token ("3-legged"), signed with HMAC-SHA1. The keys live in the
Secrets Manager secret named by FATSECRET_SECRET_ID:

    {"consumer_key": "...", "consumer_secret": "...",
     "access_token": "...", "access_secret": "..."}

The consumer key and secret come from the FatSecret developer site; the access
token and secret are added by scripts/fatsecret_authorize.py after you approve
the app (documentation/labs/04-fatsecret.md). FatSecret access tokens don't expire.

Quirks handled here:
- Dates are "days since 1970-01-01" integers (`date_int`), not strings.
- Every number in the JSON is a string ("calories": "120").
- A list with one element comes back as a bare object, and an empty one as null.
- Errors come back as HTTP 200 with {"error": {"code": ..., "message": ...}}.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta

import boto3

API_URL = "https://platform.fatsecret.com/rest/server.api"
REQUEST_TOKEN_URL = "https://authentication.fatsecret.com/oauth/request_token"
AUTHORIZE_URL = "https://authentication.fatsecret.com/oauth/authorize"
ACCESS_TOKEN_URL = "https://authentication.fatsecret.com/oauth/access_token"
EPOCH = date(1970, 1, 1)

_secrets = boto3.client("secretsmanager")


class NotConfiguredError(RuntimeError):
    """The FatSecret secret, or its access token, doesn't exist yet."""


class FatSecretError(RuntimeError):
    def __init__(self, code, message: str):
        super().__init__(f"FatSecret error {code}: {message[:500]}")
        self.code = code


@dataclass(frozen=True)
class Credentials:
    consumer_key: str
    consumer_secret: str
    access_token: str = ""
    access_secret: str = ""


def credentials(require_access: bool = True) -> Credentials:
    try:
        raw = _secrets.get_secret_value(SecretId=os.environ["FATSECRET_SECRET_ID"])["SecretString"]
    except _secrets.exceptions.ResourceNotFoundException as err:
        raise NotConfiguredError(f"secret {os.environ['FATSECRET_SECRET_ID']} not found") from err
    value = json.loads(raw)
    if not value.get("consumer_key") or not value.get("consumer_secret"):
        raise NotConfiguredError("secret has no consumer_key/consumer_secret")
    if require_access and not value.get("access_token"):
        raise NotConfiguredError("secret has no access_token: run scripts/fatsecret_authorize.py")
    return Credentials(
        consumer_key=value["consumer_key"],
        consumer_secret=value["consumer_secret"],
        access_token=value.get("access_token", ""),
        access_secret=value.get("access_secret", ""),
    )


def date_int(day: date) -> int:
    return (day - EPOCH).days


def from_date_int(value) -> date:
    return EPOCH + timedelta(days=int(value))


def _encode(value) -> str:
    """RFC 3986 percent-encoding, as OAuth 1.0 requires."""
    return urllib.parse.quote(str(value), safe="-._~")


def signature(method: str, url: str, params: dict, consumer_secret: str, token_secret: str = "") -> str:
    """HMAC-SHA1 signature of the request (RFC 5849 section 3.4)."""
    normalized = "&".join(f"{k}={v}" for k, v in sorted((_encode(k), _encode(v)) for k, v in params.items()))
    base = "&".join([method.upper(), _encode(url), _encode(normalized)])
    key = f"{_encode(consumer_secret)}&{_encode(token_secret)}"
    return base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()


def signed_params(
    method: str,
    url: str,
    params: dict,
    consumer_key: str,
    consumer_secret: str,
    token: str = "",
    token_secret: str = "",
) -> dict:
    oauth = {
        "oauth_consumer_key": consumer_key,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_nonce": secrets.token_hex(16),
        "oauth_version": "1.0",
    }
    if token:
        oauth["oauth_token"] = token
    all_params = {**params, **oauth}
    all_params["oauth_signature"] = signature(method, url, all_params, consumer_secret, token_secret)
    return all_params


def call(api_method: str, creds: Credentials, **params) -> dict:
    """Call one server.api method as the user and return the decoded JSON."""
    query = signed_params(
        "GET",
        API_URL,
        {"method": api_method, "format": "json", **{k: str(v) for k, v in params.items()}},
        creds.consumer_key,
        creds.consumer_secret,
        creds.access_token,
        creds.access_secret,
    )
    req = urllib.request.Request(f"{API_URL}?{urllib.parse.urlencode(query)}", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            body = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as err:
        raise FatSecretError(err.code, err.read().decode("utf-8", errors="replace")) from err
    if "error" in body:
        raise FatSecretError(body["error"].get("code"), body["error"].get("message", ""))
    return body


def as_list(value) -> list:
    """FatSecret returns one element as an object and none as null."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def month_days(creds: Credentials, day: date) -> list[dict]:
    """Daily totals (calories, carbohydrate, protein, fat) for the month containing `day`.

    Days with no diary entries are left out.
    """
    body = call("food_entries.get_month.v2", creds, date=date_int(day))
    return as_list((body.get("month") or {}).get("day"))


def food_entries(creds: Credentials, day: date) -> list[dict]:
    """Every food diary entry for one day, with full nutrients (fiber, sugar, sodium, ...)."""
    body = call("food_entries.get.v2", creds, date=date_int(day))
    return as_list((body.get("food_entries") or {}).get("food_entry"))
