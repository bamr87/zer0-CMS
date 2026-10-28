"""Second factors through allauth's headless API, as the studio's account menu
and sign-in use them: TOTP set up from its secret and asked for at the next
sign-in, recovery codes generated with it and each good once, a passkey added
and used as a second factor and to sign in on its own (a software
authenticator, tests/accounts/authenticator.py), and a factor removed."""

import pytest
from allauth.mfa.models import Authenticator
from django.core.cache import cache

from .authenticator import Passkey
from .conftest import flows, totp

pytestmark = pytest.mark.django_db


def set_up_totp(browser) -> str:
    offered = browser.get("/account/authenticators/totp")
    assert offered.status_code == 404  # not active yet: the answer carries a secret to activate
    meta = offered.json()["meta"]
    assert meta["totp_url"].startswith("otpauth://totp/") and meta["totp_url"].endswith("&issuer=zer0-CMS")
    first = browser.post("/account/authenticators/totp", {"code": totp(meta["secret"])})
    assert first.status_code == 401 and "reauthenticate" in flows(first)  # a sign-in a while ago is not enough
    browser.reauthenticate()
    assert browser.post("/account/authenticators/totp", {"code": "000000"}).status_code == 400
    activated = browser.post("/account/authenticators/totp", {"code": totp(meta["secret"])})
    assert activated.status_code == 200, activated.json()
    cache.clear()  # the code just used is spent for its 30 seconds; the next sign-in is a fresh window here
    return meta["secret"]


def test_totp_is_set_up_and_then_asked_for_at_every_sign_in(browser, person):
    browser.sign_in()
    secret = set_up_totp(browser)
    listed = {a["type"] for a in browser.get("/account/authenticators").json()["data"]}
    assert listed == {"totp", "recovery_codes"}  # recovery codes come with the first factor
    browser.delete("/auth/session")

    pending = browser.sign_in()
    assert pending.status_code == 401
    assert flows(pending)["mfa_authenticate"]["is_pending"] is True
    assert browser.client.get("/api/v2/me").json()["authenticated"] is False
    assert browser.post("/auth/2fa/authenticate", {"code": "123456"}).status_code == 400
    done = browser.post("/auth/2fa/authenticate", {"code": totp(secret)})
    assert done.status_code == 200
    assert [m["method"] for m in done.json()["data"]["methods"]] == ["password", "mfa"]
    assert browser.client.get("/api/v2/me").json()["user"]["username"] == "ada"


def test_a_recovery_code_signs_in_once(browser, person):
    browser.sign_in()
    set_up_totp(browser)
    answer = browser.get("/account/authenticators/recovery-codes")
    assert answer.status_code == 200, answer.json()
    codes = answer.json()["data"]
    assert codes["unused_code_count"] == codes["total_code_count"] == len(codes["unused_codes"]) == 10
    one = codes["unused_codes"][0]
    browser.delete("/auth/session")

    browser.sign_in()
    assert browser.post("/auth/2fa/authenticate", {"code": one}).status_code == 200
    listed = {a["type"]: a for a in browser.get("/account/authenticators").json()["data"]}
    assert listed["recovery_codes"]["unused_code_count"] == 9
    browser.delete("/auth/session")
    browser.sign_in()
    assert browser.post("/auth/2fa/authenticate", {"code": one}).status_code == 400


def test_totp_is_removed_and_no_longer_asked_for(browser, person):
    browser.sign_in()
    set_up_totp(browser)
    removed = browser.delete("/account/authenticators/totp")
    assert removed.status_code == 200, removed.json()
    browser.delete("/auth/session")
    assert browser.sign_in().status_code == 200


def test_a_passkey_is_a_second_factor_and_signs_in_on_its_own(browser, person, settings):
    settings.MFA_WEBAUTHN_ALLOW_INSECURE_ORIGIN = True  # the test server is http://testserver
    passkey = Passkey()
    browser.sign_in()
    browser.reauthenticate()
    options = browser.get("/account/authenticators/webauthn?passwordless").json()["data"]
    added = browser.post(
        "/account/authenticators/webauthn",
        {"name": "Laptop", "credential": passkey.create(options["creation_options"])},
    )
    assert added.status_code == 200, added.json()
    assert Authenticator.objects.get(user=person, type="webauthn").wrap().name == "Laptop"
    browser.delete("/auth/session")

    # As the second factor after a password.
    pending = browser.sign_in()
    assert "webauthn" in flows(pending)["mfa_authenticate"]["types"]
    request = browser.get("/auth/webauthn/authenticate").json()["data"]["request_options"]
    done = browser.post("/auth/webauthn/authenticate", {"credential": passkey.get(request)})
    assert done.status_code == 200, done.json()
    browser.delete("/auth/session")

    # On its own: no username, no password.
    request = browser.get("/auth/webauthn/login").json()["data"]["request_options"]
    signed_in = browser.post("/auth/webauthn/login", {"credential": passkey.get(request)})
    assert signed_in.status_code == 200, signed_in.json()
    assert signed_in.json()["data"]["user"]["username"] == "ada"

    # Someone else's key is not this passkey.
    browser.delete("/auth/session")
    request = browser.get("/auth/webauthn/login").json()["data"]["request_options"]
    forged = Passkey()
    forged.credential_id, forged.user_handle, forged.rp_id = passkey.credential_id, passkey.user_handle, passkey.rp_id
    assert browser.post("/auth/webauthn/login", {"credential": forged.get(request)}).status_code == 400
    assert browser.client.get("/api/v2/me").json()["authenticated"] is False
