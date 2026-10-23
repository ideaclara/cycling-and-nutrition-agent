import boto3
import pytest

PARAMETER = "/cycling-coach/signup-allowlist"


def event(email: str, source: str = "PreSignUp_SignUp") -> dict:
    return {"triggerSource": source, "request": {"userAttributes": {"email": email}}, "response": {}}


@pytest.fixture
def allowlist(aws, monkeypatch):
    monkeypatch.setenv("ALLOWLIST_PARAMETER", PARAMETER)

    def put(value: str):
        boto3.client("ssm").put_parameter(Name=PARAMETER, Value=value, Type="String", Overwrite=True)

    return put


def run(e):
    from coach.auth.pre_signup import handler

    return handler.handler(e, None)


@pytest.mark.parametrize(
    "email, ok",
    [
        ("matt@example.com", True),
        ("Matt@Example.COM", True),  # case-insensitive
        ("dave.smith@club.org.uk", True),  # dave*@*.*
        ("davesmith@localhost", False),  # dave*@*.* needs a dot after the @
        ("anyone@gmail.com", True),
        ("anyone@googlemail.com", False),
        ("someone@example.org", False),
        ("", False),
    ],
)
def test_wildcard_patterns(allowlist, email, ok):
    allowlist("matt@example.com,\n dave*@*.*\n*@gmail.com")
    if ok:
        assert run(event(email))["triggerSource"] == "PreSignUp_SignUp"
    else:
        with pytest.raises(PermissionError, match="isn't allowed"):
            run(event(email))


def test_star_at_star_opens_sign_up(allowlist):
    allowlist("*@*")
    assert run(event("stranger@anywhere.net"))


def test_missing_or_empty_allowlist_rejects_everyone(allowlist, aws):
    with pytest.raises(PermissionError):
        run(event("matt@example.com"))
    allowlist(" , ")
    with pytest.raises(PermissionError):
        run(event("matt@example.com"))


def test_admin_created_users_are_not_checked(allowlist):
    assert run(event("new@elsewhere.com", source="PreSignUp_AdminCreateUser"))
