"""The studio served by the platform (api/studio.py) and the demo it opens on
(cms seed_demo): every /studio/ path answers the built index.html with a
fresh CSP nonce, an unbuilt studio says how to build it, and the seed gives a
person something to write, review and publish."""

import re

import pytest
from django.core.management import call_command
from django.test import Client, override_settings

from cms.models import ArticlePage
from suggestions.models import Suggestion

INDEX = (
    '<!doctype html><html><head><meta property="csp-nonce" nonce="__CSP_NONCE__">'
    '<script type="module" nonce="__CSP_NONCE__" src="/static/studio/assets/index.js"></script></head>'
    '<body><div id="root"></div></body></html>'
)


@pytest.mark.django_db
def test_every_studio_path_is_the_index_with_a_fresh_nonce(tmp_path):
    (tmp_path / "index.html").write_text(INDEX)
    with override_settings(STUDIO_DIST=tmp_path):
        first = Client().get("/studio/")
        deep = Client().get("/studio/write/pages/42")
    for response in (first, deep):
        assert response.status_code == 200 and b'<div id="root">' in response.content
        assert b"__CSP_NONCE__" not in response.content
        nonce = re.search(r"'nonce-([^']+)'", response["Content-Security-Policy"]).group(1)
        assert f'nonce="{nonce}"'.encode() in response.content
        assert "script-src 'self';" in response["Content-Security-Policy"]
        assert "unsafe-inline" not in response["Content-Security-Policy"]
    assert first["Content-Security-Policy"] != deep["Content-Security-Policy"]


@pytest.mark.django_db
def test_the_studio_may_post_only_to_itself_and_the_configured_idps(tmp_path, settings):
    from accounts.providers import socialaccount_providers

    (tmp_path / "index.html").write_text(INDEX)
    settings.STUDIO_DIST = tmp_path
    assert "form-action 'self';" in Client().get("/studio/")["Content-Security-Policy"]
    settings.SOCIALACCOUNT_PROVIDERS = socialaccount_providers(
        {
            "OIDC_PROVIDERS": "corp",
            "OIDC_CORP_SERVER_URL": "https://login.corp.example/realms/staff",
            "OIDC_CORP_CLIENT_ID": "zer0-cms",
            "GITHUB_LOGIN_CLIENT_ID": "id",
            "GITHUB_LOGIN_CLIENT_SECRET": "secret",
        }
    )
    policy = Client().get("/studio/")["Content-Security-Policy"]
    assert "form-action 'self' https://login.corp.example https://github.com;" in policy
    assert "secret" not in policy and "zer0-cms" not in policy


@pytest.mark.django_db
def test_an_unbuilt_studio_says_how_to_build_it(tmp_path):
    with override_settings(STUDIO_DIST=tmp_path / "missing"):
        response = Client().get("/studio")
    assert response.status_code == 503 and b"npm run build" in response.content


@pytest.mark.django_db
def test_seed_demo_makes_a_site_a_person_and_pending_suggestions():
    with override_settings(DEBUG=True):
        call_command("seed_demo", verbosity=0)
        call_command("seed_demo", verbosity=0)  # idempotent: nothing doubles
    welcome = ArticlePage.objects.get(slug="welcome")
    assert welcome.live and ArticlePage.objects.get(slug="nightly-backups").live is False
    assert Suggestion.objects.filter(target_id=welcome.pk, status="pending").count() == 2
    client = Client()
    assert client.login(username="editor", password="zer0-demo")
    sites = client.get("/api/v2/sites/").json()
    assert "Demo site" in [s["name"] for s in sites]


@pytest.mark.django_db
def test_seed_demo_wants_a_password_outside_debug():
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="password"):
        call_command("seed_demo", verbosity=0)
