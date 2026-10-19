"""Strava OAuth token storage and refresh, backed by one Secrets Manager secret.

The secret (default name ``strava/oauth``) holds a JSON bundle:

    {"client_id", "client_secret", "access_token", "refresh_token",
     "expires_at", "athlete_id", "scope"}

You seed ``client_id`` and ``client_secret`` by hand; the OAuth callback fills in
the rest and every Strava Lambda refreshes the token through ``get_access_token``.
"""

import json
import os
import time
import urllib.parse
import urllib.request

import boto3

TOKEN_URL = "https://www.strava.com/oauth/token"
REFRESH_MARGIN_SECONDS = 300

_secrets = None


class NotAuthorizedError(RuntimeError):
    """Raised when the secret has no token yet: complete the OAuth flow first."""


def _client():
    global _secrets
    if _secrets is None:
        _secrets = boto3.client("secretsmanager")
    return _secrets


def secret_id() -> str:
    return os.environ.get("STRAVA_SECRET_ID", "strava/oauth")


def load_bundle() -> dict:
    raw = _client().get_secret_value(SecretId=secret_id())["SecretString"]
    return json.loads(raw or "{}")


def save_bundle(bundle: dict) -> None:
    _client().put_secret_value(SecretId=secret_id(), SecretString=json.dumps(bundle))


def _post_token(params: dict) -> dict:
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def exchange_code(code: str, scope: str | None = None) -> dict:
    """Swap an authorization code for tokens and persist them. Returns the bundle."""
    bundle = load_bundle()
    tokens = _post_token(
        {
            "client_id": bundle["client_id"],
            "client_secret": bundle["client_secret"],
            "code": code,
            "grant_type": "authorization_code",
        }
    )
    bundle.update(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_at=int(tokens["expires_at"]),
        athlete_id=str(tokens["athlete"]["id"]),
        scope=scope or bundle.get("scope"),
        athlete_name=f"{tokens['athlete'].get('firstname', '')} {tokens['athlete'].get('lastname', '')}".strip(),
    )
    save_bundle(bundle)
    return bundle


def get_access_token(now: float | None = None) -> tuple[str, str]:
    """Return ``(access_token, athlete_id)``, refreshing first if near expiry."""
    bundle = load_bundle()
    if not bundle.get("refresh_token"):
        raise NotAuthorizedError("No Strava tokens stored: complete the OAuth flow at /strava/authorize")

    now = time.time() if now is None else now
    if int(bundle.get("expires_at", 0)) - now <= REFRESH_MARGIN_SECONDS:
        tokens = _post_token(
            {
                "client_id": bundle["client_id"],
                "client_secret": bundle["client_secret"],
                "refresh_token": bundle["refresh_token"],
                "grant_type": "refresh_token",
            }
        )
        bundle.update(
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            expires_at=int(tokens["expires_at"]),
        )
        save_bundle(bundle)

    return bundle["access_token"], str(bundle["athlete_id"])
