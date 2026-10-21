"""Minimal Intervals.icu REST client (standard library only).

Personal API keys use HTTP Basic auth with the literal user name "API_KEY" and
the key as the password. The key and athlete ID live in the Secrets Manager
secret named by INTERVALS_SECRET_ID: {"athlete_id": "i12345", "api_key": "..."}.
"""

import base64
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

import boto3

API_BASE = "https://intervals.icu/api/v1"
# Cloudflare in front of intervals.icu rejects urllib's default "Python-urllib" agent (error 1010).
USER_AGENT = "cycling-coach/1.0 (+https://github.com/ideaclara/cycling-and-nutrition-agent)"

logger = logging.getLogger(__name__)

_secrets = boto3.client("secretsmanager")


class NotConfiguredError(RuntimeError):
    """The Intervals secret hasn't been created yet."""


class IntervalsHTTPError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"Intervals.icu HTTP {status}: {body[:500]}")
        self.status = status


@dataclass(frozen=True)
class Credentials:
    athlete_id: str
    api_key: str


def credentials() -> Credentials:
    try:
        raw = _secrets.get_secret_value(SecretId=os.environ["INTERVALS_SECRET_ID"])["SecretString"]
    except _secrets.exceptions.ResourceNotFoundException as err:
        raise NotConfiguredError(f"secret {os.environ['INTERVALS_SECRET_ID']} not found") from err
    value = json.loads(raw)
    if not value.get("api_key"):
        raise NotConfiguredError("secret has no api_key")
    # "0" means "the athlete who owns the key".
    return Credentials(athlete_id=str(value.get("athlete_id") or "0"), api_key=value["api_key"])


def get(path: str, creds: Credentials, params: dict | None = None):
    url = f"{API_BASE}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    token = base64.b64encode(f"API_KEY:{creds.api_key}".encode()).decode()
    req = urllib.request.Request(
        url, headers={"Authorization": f"Basic {token}", "Accept": "application/json", "User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        raise IntervalsHTTPError(err.code, err.read().decode("utf-8", errors="replace")) from err


def wellness(creds: Credentials, oldest: str, newest: str) -> list[dict]:
    """One record per day (``id`` = YYYY-MM-DD) with wellness and fitness/fatigue values."""
    return get(f"/athlete/{creds.athlete_id}/wellness", creds, {"oldest": oldest, "newest": newest})
