"""Cognito pre-sign-up trigger: only email addresses on the allowlist can create an account.

The allowlist is the SSM parameter named by ALLOWLIST_PARAMETER: patterns
separated by commas or new lines, matched without regard to case, where `*`
matches any run of characters:

    matt@example.com, dave*@*.*, *@gmail.com

`*@*` lets anyone sign up, and every account can read all of the athlete's
data, because the API serves one athlete.

Fails closed: a missing or empty parameter rejects every sign-up. Accounts an
administrator creates (AdminCreateUser) aren't checked.
"""

import fnmatch
import logging
import os
import re

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_ssm = boto3.client("ssm")


def patterns() -> list[str]:
    try:
        value = _ssm.get_parameter(Name=os.environ["ALLOWLIST_PARAMETER"])["Parameter"]["Value"]
    except _ssm.exceptions.ParameterNotFound:
        logger.warning("allowlist parameter %s not found: rejecting", os.environ["ALLOWLIST_PARAMETER"])
        return []
    return [p.strip().lower() for p in re.split(r"[,\n]", value) if p.strip()]


def allowed(email: str, allowlist: list[str]) -> bool:
    email = email.strip().lower()
    return bool(email) and any(fnmatch.fnmatchcase(email, pattern) for pattern in allowlist)


def handler(event, _context):
    if event.get("triggerSource") == "PreSignUp_AdminCreateUser":
        return event
    email = (event.get("request", {}).get("userAttributes") or {}).get("email", "")
    if not allowed(email, patterns()):
        logger.warning("sign-up rejected for a user at %s", email.rpartition("@")[2] or "(no email)")
        # Cognito shows this to the user as "PreSignUp failed with error <message>".
        raise PermissionError("This email address isn't allowed to sign up.")
    logger.info("sign-up allowed for a user at %s", email.rpartition("@")[2])
    return event
