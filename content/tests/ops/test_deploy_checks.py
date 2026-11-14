"""`manage.py check --deploy` is where a deployment learns what development
tolerates (SEC-01, OPS-04, AI-09): a placeholder or short SECRET_KEY is the
error ops.E002, and four warnings name the AI settings a deployment should not
keep — no AI_CREDENTIAL_KEYS (ops.W001), a recorded or fake LLM_BACKEND
(ops.W002), a fake or recorded provider enabled (ops.W003), a default provider
with no credential (ops.W004). A plain `check` — the one `migrate` runs at
every boot — reports none of them: refusing to boot is the owner's call
(OD-17). And SECRET_KEY_FALLBACKS is read from the environment, as the
platform's own error messages tell an operator to use it (SEC-09)."""

import os
import subprocess
import sys

import pytest
from cryptography.fernet import Fernet
from django.conf import settings
from django.core.checks import run_checks
from django.test import override_settings

from ai.crypto import _derived
from ai.models import ProviderConfig
from ai.services import ensure_providers

STRONG = "Zx9-" + "q7Wm3vR8tLp2Kd5N" * 4  # 68 characters, many of them different
CLEAN = {"AI_CREDENTIAL_KEYS": [Fernet.generate_key().decode()], "LLM_BACKEND": "litellm"}


def found(deploy=True, databases=None) -> set[str]:
    return {m.id for m in run_checks(include_deployment_checks=deploy, databases=databases) if m.id.startswith("ops.")}


@pytest.mark.parametrize(
    "key",
    ["change-me-in-production", "change-me", "insecure-development-key-change-me", "build-only", "django-insecure-" + "x" * 50, "too-short-but-random-Zx9q7Wm3"],
)
def test_a_placeholder_or_short_key_is_an_error_only_under_deploy(key):
    with override_settings(SECRET_KEY=key, **CLEAN):
        assert "ops.E002" in found()
        assert "ops.E002" not in found(deploy=False)
        errors = [m for m in run_checks(include_deployment_checks=True) if m.id == "ops.E002"]
        assert errors[0].is_serious() and key not in errors[0].msg  # the key is never echoed


def test_a_strong_key_with_its_own_credential_keys_and_a_real_backend_is_clean():
    with override_settings(SECRET_KEY=STRONG, **CLEAN):
        assert found() == set()


def test_the_ai_settings_a_deployment_should_not_keep_are_warnings():
    with override_settings(SECRET_KEY=STRONG, AI_CREDENTIAL_KEYS=[], LLM_BACKEND="recorded"):
        assert {"ops.W001", "ops.W002"} <= found()
        assert found(deploy=False) == set()
        messages = {m.id: m for m in run_checks(include_deployment_checks=True)}
        assert not messages["ops.W001"].is_serious() and not messages["ops.W002"].is_serious()
    with override_settings(SECRET_KEY=STRONG, **{**CLEAN, "LLM_BACKEND": "fake"}):
        assert found() == {"ops.W002"}


@pytest.mark.django_db
def test_the_provider_rows_are_read_when_a_database_is_named(monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    ensure_providers()
    with override_settings(SECRET_KEY=STRONG, **CLEAN):
        assert found() == set()  # without --database, a check reads no table (Django's rule)
        assert found(databases=["default"]) == {"ops.W003"}  # fake and recorded are seeded enabled
        ProviderConfig.objects.filter(slug__in=["fake", "recorded"]).update(enabled=False)
        assert found(databases=["default"]) == set()
        anthropic = ProviderConfig.objects.get(slug="anthropic")
        anthropic.is_default, anthropic.enabled = True, True
        anthropic.save()
        assert found(databases=["default"]) == {"ops.W004"}
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-the-environment")
        assert found(databases=["default"]) == set()
        monkeypatch.delenv("ANTHROPIC_API_KEY")
        anthropic.set_credential("sk-ant-stored-encrypted")
        anthropic.save()
        assert found(databases=["default"]) == set()


def test_a_fallback_from_the_environment_still_decrypts():
    """A credential encrypted under a key derived from an old SECRET_KEY reads once that key is listed in the
    environment's SECRET_KEY_FALLBACKS — through the settings module, in a process of its own."""
    old = "the-key-this-platform-had-before-it-rotated-" + "x" * 20
    token = Fernet(_derived(old)).encrypt(b"a channel's token").decode()
    script = (
        "import django; django.setup(); from django.conf import settings; from ai.crypto import decrypt; "
        f"print(settings.SECRET_KEY_FALLBACKS == [{old!r}], decrypt({token!r}))"
    )
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.testing", "SECRET_KEY_FALLBACKS": old}
    out = subprocess.run(
        [sys.executable, "-c", script], cwd=settings.BASE_DIR, env=env, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "True a channel's token"
