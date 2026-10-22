"""A person's API token (accounts.UserToken), as the VS Code extension sends
it: the studio's people-facing endpoints answer it as that person, without a
session or CSRF; an expired, revoked or unknown one is refused; an agent token
still reaches the agent authenticator; and only the hash is ever stored."""

from datetime import timedelta
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client
from django.utils import timezone

from accounts.models import UserToken
from agents.models import AgentToken


def bearer(raw):
    return {"HTTP_AUTHORIZATION": f"Bearer {raw}"}


@pytest.mark.django_db
def test_a_token_is_its_person_on_the_studio_endpoints(editor, article):
    token, raw = UserToken.issue(editor, name="VS Code")
    me = Client().get("/api/v2/me", **bearer(raw)).json()
    assert me["authenticated"] and me["user"]["username"] == "editor"
    listing = Client().get("/api/v2/content/pages/", **bearer(raw))
    assert listing.status_code == 200 and article.pk in {p["id"] for p in listing.json()["results"]}
    # A write needs no CSRF token: nothing a browser sends by itself carries the header.
    client = Client(enforce_csrf_checks=True)
    saved = client.post(f"/api/v2/content/pages/{article.pk}/unpublish/", content_type="application/json", **bearer(raw))
    assert saved.status_code == 200 and saved.json()["live"] is False
    token.refresh_from_db()
    assert token.last_used_at is not None
    assert raw not in {token.key_hash, token.prefix} and token.key_hash == UserToken.digest(raw)


@pytest.mark.django_db
def test_an_unknown_expired_or_revoked_token_is_refused(editor):
    expired, old = UserToken.issue(editor, name="old", expires_at=timezone.now() - timedelta(minutes=1))
    revoked, gone = UserToken.issue(editor, name="gone")
    revoked.revoked_at = timezone.now()
    revoked.save()
    for raw in (old, gone, UserToken.PREFIX + "nope"):
        answer = Client().get("/api/v2/content/pages/", **bearer(raw))
        assert answer.status_code in (401, 403) and answer.json()["error"]["code"].startswith("auth")


@pytest.mark.django_db
def test_an_agent_token_still_reaches_the_agent_authenticator_and_never_the_studio(db):
    user = get_user_model().objects.get(username="agent:seo")
    _, raw = AgentToken.issue(user, name="mcp")
    assert Client().get("/api/v2/me", **bearer(raw)).json()["user"]["username"] == "agent:seo"
    assert Client().get("/api/v2/content/pages/", **bearer(raw)).status_code == 403
    with pytest.raises(ValueError):
        UserToken.issue(user, name="no")


@pytest.mark.django_db
def test_the_command_issues_lists_and_revokes(editor):
    out, err = StringIO(), StringIO()
    call_command("user_token", "editor", "--name", "VS Code", "--days", "30", stdout=out, stderr=err)
    raw = out.getvalue().strip()
    assert raw.startswith(UserToken.PREFIX) and "not shown again" in err.getvalue()
    token = UserToken.objects.get(user=editor)
    assert token.expires_at is not None and UserToken.authenticate(raw) == token
    listed = StringIO()
    call_command("user_token", "editor", "--list", stdout=listed)
    assert token.prefix in listed.getvalue() and raw not in listed.getvalue()
    call_command("user_token", "editor", "--revoke", token.prefix, stderr=StringIO())
    assert UserToken.authenticate(raw) is None
    with pytest.raises(CommandError):
        call_command("user_token", "editor", stdout=StringIO())
