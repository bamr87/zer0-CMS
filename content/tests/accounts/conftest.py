"""What the accounts tests share: the studio as allauth's headless browser API
sees it, people with a verified address, and a TOTP code as an authenticator
app would show it. Nothing here reaches a network; the IdPs are recorded
(fixtures/fake_idp.json, test_providers.py)."""

import re
import time

import pytest
from allauth.account.models import EmailAddress
from allauth.mfa.totp.internal.auth import format_hotp_value, hotp_value
from django.contrib.auth import get_user_model
from django.test import Client

HEADLESS = "/_allauth/browser/v1"
PASSWORD = "a long passphrase, not a common one"


class Browser:
    """A browser on the studio: a session, and the CSRF token on every unsafe
    request (`X-CSRFToken`, as web/studio/src/auth.tsx sends it). CSRF is
    enforced, as it is for a real browser."""

    def __init__(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.get("/api/v2/me")  # the CSRF cookie, as the studio gets it on load

    @property
    def csrf(self) -> str:
        return self.client.cookies["csrftoken"].value

    def get(self, path, **kwargs):
        return self.client.get(HEADLESS + path, **kwargs)

    def post(self, path, body=None, **kwargs):
        return self.client.post(
            HEADLESS + path, body or {}, content_type="application/json", HTTP_X_CSRFTOKEN=self.csrf, **kwargs
        )

    def put(self, path, body=None):
        return self.client.put(HEADLESS + path, body or {}, content_type="application/json", HTTP_X_CSRFTOKEN=self.csrf)

    def delete(self, path, body=None):
        return self.client.delete(
            HEADLESS + path, body or {}, content_type="application/json", HTTP_X_CSRFTOKEN=self.csrf
        )

    def sign_in(self, login="ada", password=PASSWORD):
        field = "email" if "@" in login else "username"
        return self.post("/auth/login", {field: login, "password": password})

    def reauthenticate(self, password=PASSWORD):
        """Confirm the password again — what allauth asks before a factor or a password changes."""
        answer = self.post("/auth/reauthenticate", {"password": password})
        assert answer.status_code == 200, answer.json()
        return answer


@pytest.fixture
def browser(db):
    return Browser()


def make_person(username="ada", email="ada@example.com", password=PASSWORD, verified=True, **fields):
    user = get_user_model().objects.create_user(username, email=email, password=password, **fields)
    if email:
        EmailAddress.objects.create(user=user, email=email, verified=verified, primary=True)
    return user


@pytest.fixture
def person(db):
    """Ada: a local account with a password and a verified address."""
    return make_person()


def totp(secret: str, at: float | None = None) -> str:
    """The code an authenticator app shows for `secret` now (or at `at`)."""
    return format_hotp_value(hotp_value(secret, int((at or time.time()) // 30)))


def code_in(message) -> str:
    """The code allauth put in an email (a verification, sign-in or password-reset code)."""
    found = re.search(r"^\s*([A-Z0-9]{4}-[A-Z0-9]{4}|\d{6})\s*$", message.body, re.MULTILINE)
    assert found, f"no code in {message.subject!r}"
    return found.group(1)


def flows(response) -> dict:
    """allauth's pending and offered flows in a 401, by id."""
    return {flow["id"]: flow for flow in response.json()["data"]["flows"]}
