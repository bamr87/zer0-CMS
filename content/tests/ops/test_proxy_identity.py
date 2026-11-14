"""Who an anonymous caller is (SEC-02): with no proxy declared (`NUM_PROXIES`
0, the default) the address is the socket's, so a forged `X-Forwarded-For`
spends the caller's own bucket; with `NUM_PROXIES=1` the last hop the proxy
added is the address. allauth's rate limits read the same count, and
production trusts `X-Forwarded-Proto` only when a proxy is declared."""

import os
import subprocess
import sys

import pytest
from django.conf import settings
from django.test import Client, override_settings

from ops.throttling import AnonThrottle

pytestmark = pytest.mark.django_db


@pytest.fixture
def two_a_minute(monkeypatch):
    monkeypatch.setitem(AnonThrottle.THROTTLE_RATES, "anon", "2/min")


def pages(forwarded):
    return Client().get("/api/v2/pages/", HTTP_X_FORWARDED_FOR=forwarded).status_code


def test_a_forged_forwarded_for_shares_the_callers_bucket(two_a_minute, site_root):
    assert settings.REST_FRAMEWORK["NUM_PROXIES"] == 0 == settings.ALLAUTH_TRUSTED_PROXY_COUNT
    assert [pages("203.0.113.1"), pages("203.0.113.2"), pages("203.0.113.3")] == [200, 200, 429]


def test_behind_one_proxy_the_last_hop_is_the_caller(two_a_minute, site_root):
    with override_settings(REST_FRAMEWORK={**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}):
        # the proxy appends the address it saw; what the client wrote before it is not trusted
        assert [pages("198.51.100.7, 203.0.113.1"), pages("198.51.100.8, 203.0.113.1")] == [200, 200]
        assert pages("198.51.100.9, 203.0.113.1") == 429
        assert pages("203.0.113.2") == 200  # another caller behind the same proxy


@pytest.mark.parametrize(("proxies", "header"), [("", "None"), ("0", "None"), ("1", "('HTTP_X_FORWARDED_PROTO', 'https')")])
def test_production_trusts_the_proxy_header_only_behind_a_proxy(proxies, header):
    script = "import django; django.setup(); from django.conf import settings as s; print(s.SECURE_PROXY_SSL_HEADER, s.ALLAUTH_TRUSTED_PROXY_COUNT)"
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.production",
        "SECRET_KEY": "a-key-only-this-test-process-uses-" + "x" * 30,
        "NUM_PROXIES": proxies,
    }
    out = subprocess.run(
        [sys.executable, "-c", script], cwd=settings.BASE_DIR, env=env, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == f"{header} {int(proxies or 0)}"
