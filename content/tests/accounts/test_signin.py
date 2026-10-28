"""Signing in with a local account through django-allauth's headless API, as
the studio does: the configuration the sign-in screen reads, a password by
username or email, sign-out, CSRF on every unsafe request, an agent principal
refused at every route, the old session endpoints gone, and the Wagtail and
Django admins sending a signed-out person to the studio's sign-in (with where
they were going, never somewhere else) — so no form signs in around a second
factor. The password and session policy are settings, and hold."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from .conftest import PASSWORD, code_in, flows, make_person

pytestmark = pytest.mark.django_db


def test_the_sign_in_screen_reads_what_allauth_offers(browser):
    config = browser.get("/config").json()["data"]
    assert set(config["account"]["login_methods"]) == {"username", "email"}
    assert config["account"]["is_open_for_signup"] is False
    assert config["account"]["login_by_code_enabled"] is True
    assert set(config["mfa"]["supported_types"]) == {"totp", "recovery_codes", "webauthn"}
    assert config["mfa"]["passkey_login_enabled"] is True
    # No IdP in the environment: local accounts only.
    assert config["socialaccount"]["providers"] == []
    assert "usersessions" in config


def test_a_person_signs_in_by_username_or_email_and_out_again(browser, person):
    anonymous = browser.get("/auth/session")
    assert anonymous.status_code == 401 and "login" in flows(anonymous)
    signed_in = browser.sign_in("ada")
    assert signed_in.status_code == 200, signed_in.json()
    assert signed_in.json()["data"]["user"]["username"] == "ada"
    assert signed_in.json()["data"]["methods"][0]["method"] == "password"
    me = browser.client.get("/api/v2/me").json()
    assert me["authenticated"] and me["user"]["username"] == "ada"
    out = browser.delete("/auth/session")
    assert out.status_code == 401
    assert browser.client.get("/api/v2/me").json()["authenticated"] is False
    by_email = browser.sign_in("ada@example.com")
    assert by_email.status_code == 200 and by_email.json()["meta"]["is_authenticated"] is True


def test_every_unsafe_request_needs_the_csrf_token(browser, person):
    refused = browser.client.post(
        "/_allauth/browser/v1/auth/login", {"username": "ada", "password": PASSWORD}, content_type="application/json"
    )
    assert refused.status_code == 403
    assert browser.client.get("/api/v2/me").json()["authenticated"] is False


def test_a_wrong_password_and_an_agent_principal_are_refused(browser, person):
    wrong = browser.sign_in("ada", "not the password")
    assert wrong.status_code == 400 and wrong.json()["errors"][0]["code"] == "username_password_mismatch"
    agent = get_user_model().objects.get(username="agent:seo")
    agent.set_password(PASSWORD)
    agent.email = "seo-agent@example.com"
    agent.save()
    refused = browser.sign_in("agent:seo")
    assert refused.status_code == 400
    assert browser.client.get("/api/v2/me").json()["authenticated"] is False
    # By its address, too.
    assert browser.sign_in("seo-agent@example.com").status_code == 400


def test_an_unverified_address_must_be_verified_before_the_first_sign_in(browser, mailoutbox):
    make_person("bea", "bea@example.com", verified=False)
    pending = browser.sign_in("bea")
    assert pending.status_code == 401
    assert flows(pending)["verify_email"]["is_pending"] is True
    verified = browser.post("/auth/email/verify", {"key": code_in(mailoutbox[-1])})
    assert verified.status_code == 200 and verified.json()["data"]["user"]["username"] == "bea"


def test_the_admins_send_a_signed_out_person_to_the_studios_sign_in():
    client = Client()
    to_wagtail = client.get("/admin/pages/")
    assert to_wagtail.status_code == 302 and to_wagtail["Location"] == "/studio/?next=/admin/pages/"
    login = client.get("/admin/login/", {"next": "/admin/pages/3/"})
    assert login.status_code == 302 and login["Location"] == "/studio/?next=%2Fadmin%2Fpages%2F3%2F"
    # A `next` that leaves the platform is replaced by the admin's home.
    for offsite in ("https://evil.example/", "//evil.example/", "javascript:alert(1)"):
        assert client.get("/admin/login/", {"next": offsite})["Location"] == "/studio/?next=%2Fadmin%2F"
    django_admin = client.get("/django-admin/login/", {"next": "/django-admin/auth/"})
    assert django_admin.status_code == 302
    assert django_admin["Location"] == "/studio/?next=%2Fdjango-admin%2Fauth%2F"
    # The password forms never sign anyone in.
    posted = client.post("/admin/login/", {"username": "ada", "password": PASSWORD})
    assert posted.status_code == 302 and posted["Location"].startswith("/studio/")
    assert client.get("/api/v2/me").json()["authenticated"] is False


def test_signed_in_through_the_studio_a_person_reaches_the_admin(browser, editor):
    editor.set_password(PASSWORD)
    editor.email = "editor@example.com"
    editor.save()
    from allauth.account.models import EmailAddress

    EmailAddress.objects.create(user=editor, email=editor.email, verified=True, primary=True)
    assert browser.sign_in("editor").status_code == 200
    assert browser.client.get("/admin/").status_code == 200
    onward = browser.client.get("/admin/login/", {"next": "/admin/pages/"})
    assert onward.status_code == 302 and onward["Location"] == "/admin/pages/"


def test_the_password_policy_is_the_validators_in_settings(browser, person, settings):
    assert settings.PASSWORD_MIN_LENGTH == 12
    browser.sign_in("ada")
    short = browser.post("/account/password/change", {"current_password": PASSWORD, "new_password": "short1"})
    assert short.status_code == 400
    assert {e["param"] for e in short.json()["errors"]} == {"new_password"}
    common = browser.post("/account/password/change", {"current_password": PASSWORD, "new_password": "password1234"})
    assert common.status_code == 400
    changed = browser.post(
        "/account/password/change", {"current_password": PASSWORD, "new_password": "another long passphrase"}
    )
    assert changed.status_code == 200
    person.refresh_from_db()
    assert person.check_password("another long passphrase")


def test_the_session_policy_is_settings(browser, person, settings):
    settings.SESSION_COOKIE_AGE = 3600
    browser.sign_in("ada")
    cookie = browser.client.cookies[settings.SESSION_COOKIE_NAME]
    assert cookie["max-age"] == 3600 and cookie["httponly"] and cookie["samesite"] == "Lax"
    settings.SESSION_EXPIRE_AT_BROWSER_CLOSE = True
    other = Client(enforce_csrf_checks=True)
    other.get("/api/v2/me")
    other.post(
        "/_allauth/browser/v1/auth/login",
        {"username": "ada", "password": PASSWORD},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=other.cookies["csrftoken"].value,
    )
    assert other.cookies[settings.SESSION_COOKIE_NAME]["max-age"] == ""


def test_a_person_lists_their_sessions_and_ends_another(person):
    from .conftest import Browser

    laptop, phone = Browser(), Browser()
    laptop.sign_in("ada")
    phone.sign_in("ada")
    sessions = laptop.get("/auth/sessions").json()["data"]
    assert len(sessions) == 2 and sum(s["is_current"] for s in sessions) == 1
    other = next(s for s in sessions if not s["is_current"])
    ended = laptop.delete("/auth/sessions", {"sessions": [other["id"]]})
    assert ended.status_code == 200 and len(ended.json()["data"]) == 1
    assert phone.client.get("/api/v2/me").json()["authenticated"] is False
    assert laptop.client.get("/api/v2/me").json()["authenticated"] is True
