"""A second factor's secrets are credentials, encrypted at rest like every
other (ADMIN-09, TARGET's "credentials are encrypted at rest"): the TOTP key
and the recovery codes' seed go through ai/crypto.py's keys
(`accounts.adapter.MFAAdapter`), sign-in still works, `rotate_ai_credentials`
moves them to the newest key, one stored in the clear before this still reads
(and is encrypted by the next rotation), and the Django admin never shows
them."""

import pytest
from allauth.mfa.models import Authenticator
from allauth.mfa.totp.internal.auth import TOTP
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, override_settings
from django.urls import reverse

from .conftest import totp
from .test_mfa import set_up_totp

pytestmark = pytest.mark.django_db

LEGACY = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"  # a base32 TOTP key, as allauth stored one without an adapter


def test_a_totp_secret_is_encrypted_at_rest_and_sign_in_still_works(browser, person):
    browser.sign_in()
    secret = set_up_totp(browser)
    stored = Authenticator.objects.get(user=person, type=Authenticator.Type.TOTP).data["secret"]
    assert stored != secret and secret not in stored and stored.startswith("gAAAAA")
    seed = Authenticator.objects.get(user=person, type=Authenticator.Type.RECOVERY_CODES).data["seed"]
    assert seed.startswith("gAAAAA")
    browser.delete("/auth/session")
    assert browser.sign_in().status_code == 401  # the second factor is asked for
    assert browser.post("/auth/2fa/authenticate", {"code": totp(secret)}).status_code == 200


def test_rotation_moves_the_secrets_to_the_newest_key_and_encrypts_a_legacy_one(browser, person):
    browser.sign_in()
    secret = set_up_totp(browser)
    other = get_user_model().objects.create_user("grace", password="x")
    legacy = Authenticator.objects.create(user=other, type=Authenticator.Type.TOTP, data={"secret": LEGACY})
    assert TOTP(legacy).validate_code(totp(LEGACY))  # stored in the clear before: it still reads

    newest = Fernet.generate_key().decode()
    with override_settings(AI_CREDENTIAL_KEYS=[newest]):
        call_command("rotate_ai_credentials", stdout=None)
    only_newest = Fernet(newest)
    mine = Authenticator.objects.get(user=person, type=Authenticator.Type.TOTP).data["secret"]
    assert only_newest.decrypt(mine.encode()).decode() == secret
    legacy.refresh_from_db()
    assert only_newest.decrypt(legacy.data["secret"].encode()).decode() == LEGACY
    seed = Authenticator.objects.get(user=person, type=Authenticator.Type.RECOVERY_CODES).data["seed"]
    assert only_newest.decrypt(seed.encode())


def test_the_django_admin_never_shows_a_second_factors_secret(person):
    authenticator = Authenticator.objects.create(user=person, type=Authenticator.Type.TOTP, data={"secret": LEGACY})
    admin = Client()
    admin.force_login(get_user_model().objects.create_superuser("root", password="pw"))
    page = admin.get(reverse("admin:mfa_authenticator_change", args=[authenticator.pk]))
    assert page.status_code == 200
    assert LEGACY not in page.content.decode() and "secret" not in page.content.decode()
    listed = admin.get(reverse("admin:mfa_authenticator_changelist"))
    assert listed.status_code == 200 and LEGACY not in listed.content.decode()
