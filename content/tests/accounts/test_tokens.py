"""A person's API token (accounts.UserToken), as the VS Code extension sends
it: the studio's people-facing endpoints answer it as that person, without a
session or CSRF; an expired, revoked or unknown one is refused; an agent token
still reaches the agent authenticator; only the hash is ever stored; a use is
recorded at most every few minutes and after the request commits, so a
client's parallel requests all answer; and the rules for issuing one —
an expiry by default, a superuser's only on purpose — hold."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts import services
from accounts.models import UserToken
from agents.models import AgentToken


def bearer(raw):
    return {"HTTP_AUTHORIZATION": f"Bearer {raw}"}


@pytest.mark.django_db
def test_a_token_is_its_person_on_the_studio_endpoints(editor, article, django_capture_on_commit_callbacks):
    token, raw = services.issue(editor, name="VS Code")
    with django_capture_on_commit_callbacks(execute=True):
        me = Client().get("/api/v2/me", **bearer(raw)).json()
    assert me["authenticated"] and me["user"]["username"] == "editor"
    listing = Client().get("/api/v2/content/pages/", **bearer(raw))
    assert listing.status_code == 200 and article.pk in {p["id"] for p in listing.json()["results"]}
    # A write needs no CSRF token: nothing a browser sends by itself carries the header.
    client = Client(enforce_csrf_checks=True)
    saved = client.post(
        f"/api/v2/content/pages/{article.pk}/unpublish/", content_type="application/json", **bearer(raw)
    )
    assert saved.status_code == 200 and saved.json()["live"] is False
    token.refresh_from_db()
    assert token.last_used_at is not None
    assert raw not in {token.key_hash, token.prefix} and token.key_hash == UserToken.digest(raw)


@pytest.mark.django_db
def test_an_unknown_expired_or_revoked_token_is_refused(editor):
    _, old = UserToken.mint(name="old", user=editor, expires_at=timezone.now() - timedelta(minutes=1))
    revoked, gone = services.issue(editor, name="gone")
    services.revoke(editor, revoked.prefix)
    for raw in (old, gone, UserToken.PREFIX + "nope"):
        answer = Client().get("/api/v2/content/pages/", **bearer(raw))
        assert answer.status_code in (401, 403) and answer.json()["error"]["code"].startswith("auth")


@pytest.mark.django_db
def test_an_agent_token_still_reaches_the_agent_authenticator_and_never_the_studio(db):
    user = get_user_model().objects.get(username="agent:seo")
    _, raw = AgentToken.issue(user, name="mcp")
    assert Client().get("/api/v2/me", **bearer(raw)).json()["user"]["username"] == "agent:seo"
    assert Client().get("/api/v2/content/pages/", **bearer(raw)).status_code == 403
    with pytest.raises(services.TokenError):
        services.issue(user, name="no")


@pytest.mark.django_db
def test_a_token_expires_by_default_a_superusers_needs_asking_and_each_person_sees_their_own(editor):
    token, _ = services.issue(editor, name="laptop")
    assert timedelta(days=89) < token.expires_at - timezone.now() <= timedelta(days=services.DEFAULT_DAYS)
    assert services.issue(editor, name="ci", days=0)[0].expires_at is None
    admin = get_user_model().objects.create_superuser("admin", password="pw")
    with pytest.raises(services.TokenError, match="superuser"):
        services.issue(admin, name="laptop")
    services.issue(admin, name="laptop", superuser=True)
    other = get_user_model().objects.create_user("other", password="pw")
    assert set(UserToken.objects.visible_to(editor)) == set(services.tokens_of(editor)) == set(editor.user_tokens.all())
    assert not UserToken.objects.visible_to(other).exists()
    assert UserToken.objects.visible_to(admin).count() == 3
    assert token.public_id is not None and str(token.public_id) != str(token.pk)


@pytest.mark.django_db
def test_a_use_is_recorded_after_the_request_commits_and_at_most_every_few_minutes(editor):
    token, raw = services.issue(editor, name="VS Code")

    def writes():
        return [q["sql"] for q in queries.captured_queries if q["sql"].startswith("UPDATE")]

    with CaptureQueriesContext(connection) as queries:
        assert Client().get("/api/v2/me", **bearer(raw)).status_code == 200
    # The test runs inside a transaction, so the commit — and the write — has not happened yet.
    assert writes() == []
    token.last_used_at = timezone.now()
    token.save(update_fields=["last_used_at"])
    with CaptureQueriesContext(connection) as queries:
        assert UserToken.authenticate(raw) == token
    assert writes() == [], "a token used a moment ago was written again"


@pytest.mark.django_db(transaction=True)
def test_parallel_requests_with_one_token_all_answer(editor, article):
    """The extension's dashboard sends a burst of requests at once. A write on
    every request inside the request's transaction failed most of them with
    'database is locked' on SQLite (and ran them one at a time on Postgres)."""
    _, raw = services.issue(editor, name="VS Code")

    def get(_):
        try:
            return Client().get("/api/v2/content/pages/", **bearer(raw)).status_code
        finally:
            connection.close()

    with ThreadPoolExecutor(8) as pool:
        assert list(pool.map(get, range(16))) == [200] * 16


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
    get_user_model().objects.create_superuser("admin", password="pw")
    with pytest.raises(CommandError, match="--superuser"):
        call_command("user_token", "admin", "--name", "laptop", stdout=StringIO())
