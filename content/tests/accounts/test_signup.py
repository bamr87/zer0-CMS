"""parodynews's account capabilities, on allauth: email sign-up with its
address verified by a code before the first sign-in (only where sign-up is
open), signing in by a code sent to one's address, and a password reset by
code — each finished in the screen that started it, mail through Django's
locmem backend."""

import pytest
from django.contrib.auth import get_user_model

from .authenticator import Passkey
from .conftest import PASSWORD, code_in, flows

pytestmark = pytest.mark.django_db

NEW = {"username": "lin", "email": "lin@example.com", "password": "a different long passphrase"}


def test_sign_up_is_refused_while_it_is_closed(browser):
    assert browser.post("/auth/signup", NEW).status_code == 403
    assert not get_user_model().objects.filter(username="lin").exists()


def test_an_email_sign_up_verifies_its_address_before_the_first_sign_in(browser, settings, mailoutbox):
    settings.SIGNUP_OPEN = True
    assert browser.get("/config").json()["data"]["account"]["is_open_for_signup"] is True
    weak = browser.post("/auth/signup", {**NEW, "password": "lin12345"})
    assert weak.status_code == 400 and {e["param"] for e in weak.json()["errors"]} == {"password"}
    signed_up = browser.post("/auth/signup", NEW)
    assert signed_up.status_code == 401 and flows(signed_up)["verify_email"]["is_pending"] is True
    assert browser.client.get("/api/v2/me").json()["authenticated"] is False
    assert mailoutbox[-1].to == ["lin@example.com"] and mailoutbox[-1].subject.startswith("[zer0-CMS] ")
    assert browser.post("/auth/email/verify", {"key": "AAAA-BBBB"}).status_code == 400
    verified = browser.post("/auth/email/verify", {"key": code_in(mailoutbox[-1])})
    assert verified.status_code == 200 and verified.json()["data"]["user"]["username"] == "lin"
    lin = get_user_model().objects.get(username="lin")
    assert lin.emailaddress_set.get().verified and not lin.is_staff and not lin.groups.exists()


def test_a_passkey_sign_up_verifies_the_address_then_makes_the_passkey(browser, settings, mailoutbox):
    settings.SIGNUP_OPEN = True
    settings.MFA_WEBAUTHN_ALLOW_INSECURE_ORIGIN = True  # the test server is http://testserver
    started = browser.post("/auth/webauthn/signup", {"email": "kim@example.com", "username": "kim"})
    assert started.status_code == 401 and flows(started)["verify_email"]["is_pending"] is True
    verified = browser.post("/auth/email/verify", {"key": code_in(mailoutbox[-1])})
    assert verified.status_code == 401 and flows(verified)["mfa_signup_webauthn"]["is_pending"] is True
    passkey = Passkey()
    options = browser.get("/auth/webauthn/signup").json()["data"]["creation_options"]
    made = browser.put("/auth/webauthn/signup", {"name": "Phone", "credential": passkey.create(options)})
    assert made.status_code == 200, made.json()
    kim = get_user_model().objects.get(username="kim")
    assert not kim.has_usable_password() and kim.authenticator_set.get().wrap().name == "Phone"
    browser.delete("/auth/session")
    request = browser.get("/auth/webauthn/login").json()["data"]["request_options"]
    assert browser.post("/auth/webauthn/login", {"credential": passkey.get(request)}).status_code == 200


def test_a_person_without_a_password_sets_one(browser, person, mailoutbox):
    person.set_unusable_password()
    person.save()
    browser.post("/auth/code/request", {"email": "ada@example.com"})
    browser.post("/auth/code/confirm", {"code": code_in(mailoutbox[-1])})
    assert browser.get("/auth/session").json()["data"]["user"]["has_usable_password"] is False
    set_now = browser.post("/account/password/change", {"new_password": "a password at last, long"})
    assert set_now.status_code == 200, set_now.json()
    person.refresh_from_db()
    assert person.check_password("a password at last, long")


def test_a_person_signs_in_with_a_code_sent_to_their_address(browser, person, mailoutbox):
    asked = browser.post("/auth/code/request", {"email": "ada@example.com"})
    assert asked.status_code == 401 and flows(asked)["login_by_code"]["is_pending"] is True
    signed_in = browser.post("/auth/code/confirm", {"code": code_in(mailoutbox[-1])})
    assert signed_in.status_code == 200
    assert signed_in.json()["data"]["methods"][0]["method"] == "code"


def test_a_password_is_reset_by_a_code(browser, person, mailoutbox):
    asked = browser.post("/auth/password/request", {"email": "ada@example.com"})
    assert asked.status_code == 401 and flows(asked)["password_reset_by_code"]["is_pending"] is True
    code = code_in(mailoutbox[-1])
    weak = browser.post("/auth/password/reset", {"key": code, "password": "short"})
    assert weak.status_code == 400
    reset = browser.post("/auth/password/reset", {"key": code, "password": "a brand new passphrase"})
    assert reset.status_code in (200, 401), reset.json()
    person.refresh_from_db()
    assert person.check_password("a brand new passphrase") and not person.check_password(PASSWORD)


def test_asking_for_a_reset_says_nothing_about_whether_an_account_exists(person):
    from .conftest import Browser

    known = Browser().post("/auth/password/request", {"email": "ada@example.com"})
    unknown = Browser().post("/auth/password/request", {"email": "nobody@example.com"})
    assert (known.status_code, flows(known).keys()) == (unknown.status_code, flows(unknown).keys())
