"""Strava OAuth endpoints.

GET /strava/authorize  -> 302 to Strava's consent screen (with a one-time `state`)
GET /strava/callback   -> exchanges the code and stores tokens in Secrets Manager

Ported from the Node `strava-auth-callback`, with two changes: tokens go to
Secrets Manager instead of DynamoDB, and a `state` nonce stops anyone else from
completing the flow with their own Strava account and overwriting the tokens.
"""

import html
import logging
import secrets
import urllib.parse

from common import strava_auth
from common.http import html as html_response

logger = logging.getLogger()
logger.setLevel(logging.INFO)

AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
SCOPE = "read,activity:read_all"


def _redirect_uri(event: dict) -> str:
    domain = event["requestContext"]["domainName"]
    return f"https://{domain}/strava/callback"


def authorize(event: dict) -> dict:
    bundle = strava_auth.load_bundle()
    state = secrets.token_urlsafe(24)
    bundle["pending_state"] = state
    strava_auth.save_bundle(bundle)

    query = urllib.parse.urlencode(
        {
            "client_id": bundle["client_id"],
            "redirect_uri": _redirect_uri(event),
            "response_type": "code",
            "approval_prompt": "auto",
            "scope": SCOPE,
            "state": state,
        }
    )
    return {"statusCode": 302, "headers": {"Location": f"{AUTHORIZE_URL}?{query}"}, "body": ""}


def callback(event: dict) -> dict:
    params = event.get("queryStringParameters") or {}
    if params.get("error") or not params.get("code"):
        reason = html.escape(params.get("error") or "No code provided")
        return html_response(400, f"<h1>Authorization failed</h1><p>{reason}</p>")

    bundle = strava_auth.load_bundle()
    expected = bundle.pop("pending_state", None)
    if not expected or not secrets.compare_digest(expected, params.get("state", "")):
        return html_response(
            400, "<h1>Authorization failed</h1><p>State mismatch: start again at /strava/authorize.</p>"
        )
    strava_auth.save_bundle(bundle)

    granted = params.get("scope", "")
    if "activity:read_all" not in granted.split(","):
        return html_response(
            400,
            "<h1>Missing permission</h1><p>Tick “View data about your private activities” and try again.</p>",
        )

    bundle = strava_auth.exchange_code(params["code"], scope=granted)
    logger.info("Stored Strava tokens for athlete %s", bundle["athlete_id"])
    name = html.escape(bundle.get("athlete_name", ""))
    return html_response(
        200,
        f"<h1>Connected</h1><p>{name} (athlete {html.escape(bundle['athlete_id'])}) authorized. "
        "Tokens are stored in Secrets Manager.</p>",
    )


def handler(event, _context):
    path = event.get("rawPath", "")
    try:
        if path.endswith("/authorize"):
            return authorize(event)
        return callback(event)
    except Exception:
        logger.exception("Strava OAuth error")
        return html_response(500, "<h1>Server error</h1><p>See CloudWatch logs.</p>")
