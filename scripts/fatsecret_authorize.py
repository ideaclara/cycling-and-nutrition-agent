"""Authorize this app to read your FatSecret food diary (OAuth 1.0, 3-legged).

Run once, after creating the fatsecret/oauth secret with your consumer key and
secret (documentation/labs/04-fatsecret.md):

    uv run --project services python scripts/fatsecret_authorize.py

1. Gets a request token from FatSecret.
2. Prints a link: open it, sign in to FatSecret and allow access. FatSecret then
   shows a verification code.
3. Paste the code here. The script swaps it for an access token and adds the
   token to the secret. Nothing is printed or written to disk.
4. Reads this month's diary to check that it works.

FatSecret access tokens don't expire. Run it again only if you revoke access.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services"))
os.environ.setdefault("FATSECRET_SECRET_ID", "fatsecret/oauth")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from common import fatsecret_api  # noqa: E402

SECRET_ID = os.environ["FATSECRET_SECRET_ID"]


def _token_request(method: str, url: str, params: dict, creds, token: str = "", token_secret: str = "") -> dict:
    signed = fatsecret_api.signed_params(
        method, url, params, creds.consumer_key, creds.consumer_secret, token, token_secret
    )
    data = urllib.parse.urlencode(signed)
    if method == "POST":
        req = urllib.request.Request(url, data=data.encode(), method="POST")
    else:
        req = urllib.request.Request(f"{url}?{data}")
    with urllib.request.urlopen(req, timeout=25) as resp:
        return dict(urllib.parse.parse_qsl(resp.read().decode("utf-8")))


def main():
    creds = fatsecret_api.credentials(require_access=False)

    request = _token_request("POST", fatsecret_api.REQUEST_TOKEN_URL, {"oauth_callback": "oob"}, creds)
    print("1. Open this link, sign in to FatSecret and allow access:\n")
    print(f"   {fatsecret_api.AUTHORIZE_URL}?oauth_token={urllib.parse.quote(request['oauth_token'])}\n")
    verifier = input("2. Paste the verification code FatSecret shows you: ").strip()

    access = _token_request(
        "GET",
        fatsecret_api.ACCESS_TOKEN_URL,
        {"oauth_verifier": verifier},
        creds,
        request["oauth_token"],
        request["oauth_token_secret"],
    )

    sm = boto3.client("secretsmanager")
    value = json.loads(sm.get_secret_value(SecretId=SECRET_ID)["SecretString"])
    value.update(access_token=access["oauth_token"], access_secret=access["oauth_token_secret"])
    sm.put_secret_value(SecretId=SECRET_ID, SecretString=json.dumps(value))
    print(f"\nAccess token saved to the {SECRET_ID} secret.")

    days = fatsecret_api.month_days(fatsecret_api.credentials(), date.today())
    print(f"Check: {len(days)} day(s) with diary entries this month.")


if __name__ == "__main__":
    main()
