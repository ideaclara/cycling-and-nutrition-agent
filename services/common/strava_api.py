"""Minimal Strava REST client (standard library only)."""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

API_BASE = "https://www.strava.com/api/v3"

logger = logging.getLogger(__name__)


class RateLimitedError(RuntimeError):
    """HTTP 429 from Strava: back off until the next 15-minute window."""


class StravaHTTPError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"Strava HTTP {status}: {body[:500]}")
        self.status = status


@dataclass
class StravaResponse:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self):
        return json.loads(self.body.decode("utf-8"))


def _log_rate_limits(headers: dict[str, str]) -> None:
    usage = {k: v for k, v in headers.items() if k.lower().startswith(("x-ratelimit", "x-readratelimit"))}
    if usage:
        logger.info("strava rate limits %s", usage)


def get(path: str, token: str, params: dict | None = None) -> StravaResponse:
    url = f"{API_BASE}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            headers = {k.lower(): v for k, v in resp.headers.items()}
            _log_rate_limits(headers)
            return StravaResponse(resp.status, headers, resp.read())
    except urllib.error.HTTPError as err:
        headers = {k.lower(): v for k, v in (err.headers or {}).items()}
        _log_rate_limits(headers)
        body = err.read().decode("utf-8", errors="replace")
        if err.code == 429:
            raise RateLimitedError(body) from err
        raise StravaHTTPError(err.code, body) from err
