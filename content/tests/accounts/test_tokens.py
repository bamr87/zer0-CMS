"""A person's API token (accounts.UserToken), as the VS Code extension sends
it: the studio's people-facing endpoints answer it as that person, without a
session or CSRF; an expired, revoked or unknown one is refused; an agent token
still reaches the agent authenticator; only the hash is ever stored; a use is
recorded at most every few minutes and after the request commits, so a
client's parallel requests all answer; and the rules for issuing one —
an expiry by default, a superuser's only on purpose — hold. Since G3: a
token's scopes (a read-only one changes nothing, over REST or GraphQL), the
account menu's endpoints that issue (from a session only), list and revoke
them, and GraphQL answering a person's token."""

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
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


# ── G3: scopes, the account menu's endpoints, GraphQL ─────────────────────


def gql(raw, query, variables=None, client=None):
    return (client or Client(enforce_csrf_checks=True)).post(
        "/graphql/",
        data=json.dumps({"query": query, "variables": variables or {}}),
        content_type="application/json",
        **bearer(raw),
    )


@pytest.mark.django_db
def test_a_read_only_token_reads_and_changes_nothing(editor, article):
    token, raw = services.issue(editor, name="dashboard", scopes=("read",))
    assert token.scopes == ["read"] and token.allows("read") and not token.allows("write")
    assert Client().get("/api/v2/content/pages/", **bearer(raw)).status_code == 200
    refused = Client().post(
        f"/api/v2/content/pages/{article.pk}/unpublish/", content_type="application/json", **bearer(raw)
    )
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "auth.forbidden"
    assert "only read" in refused.json()["error"]["message"]
    article.refresh_from_db()
    assert article.live is True
    with pytest.raises(services.TokenError, match="read"):
        services.issue(editor, name="x", scopes=("write",))
    with pytest.raises(services.TokenError, match="unknown"):
        services.issue(editor, name="x", scopes=("read", "publish"))


@pytest.mark.django_db
def test_graphql_answers_a_persons_token_and_a_read_only_one_only_queries(editor, article):
    _, raw = services.issue(editor, name="scripts")
    query = gql(raw, "query($id: ID) { page(id: $id) { title } }", {"id": article.pk})
    assert query.status_code == 200 and query.json()["data"]["page"]["title"] == "Nightly backups"
    mutation = 'mutation($id: Int) { requestAgentRun(agent: "brand", pageId: $id) { runId } }'
    # A token needs no CSRF token: nothing a browser sends by itself carries it.
    started = gql(raw, mutation, {"id": article.pk})
    assert "errors" not in started.json(), started.json()

    _, read_only = services.issue(editor, name="reader", scopes=("read",))
    assert gql(read_only, "query($id: ID) { page(id: $id) { title } }", {"id": article.pk}).status_code == 200
    refused = gql(read_only, mutation, {"id": article.pk}).json()
    assert (
        refused["errors"][0]["extensions"]["code"] == "auth.forbidden"
        and "only read" in refused["errors"][0]["message"]
    )
    assert "data" not in refused or refused["data"] is None

    unknown = gql(UserToken.PREFIX + "nope", "{ __typename }")
    assert unknown.status_code == 401 and unknown.json()["errors"][0]["extensions"]["code"] == "auth.invalid_token"


def signed_in(user):
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    csrf = client.get("/api/v2/me").json()["csrf_token"]
    return client, {"HTTP_X_CSRFTOKEN": csrf}


@pytest.mark.django_db
def test_the_account_menu_issues_lists_and_revokes_a_persons_tokens(editor):
    client, csrf = signed_in(editor)
    issued = client.post(
        "/api/v2/account/tokens/",
        {"name": "VS Code on my laptop", "days": 30, "scopes": ["read"]},
        content_type="application/json",
        **csrf,
    )
    assert issued.status_code == 201, issued.json()
    body = issued.json()
    raw, shown = body["raw"], body["token"]
    assert raw.startswith(UserToken.PREFIX) and shown["prefix"] == raw[:14] and shown["scopes"] == ["read"]
    assert shown["state"] == "active" and shown["current"] is False
    assert timedelta(days=29) < datetime.fromisoformat(shown["expires_at"]) - timezone.now() <= timedelta(days=30)
    listed = client.get("/api/v2/account/tokens/").json()
    assert [t["id"] for t in listed] == [shown["id"]] and "raw" not in listed[0]
    assert raw not in json.dumps(listed)

    # The token itself lists them, knows which it is, and cannot issue another.
    as_token = Client().get("/api/v2/account/tokens/", **bearer(raw)).json()
    assert as_token[0]["current"] is True
    _, writer = services.issue(editor, name="writer")
    again = Client().post(
        "/api/v2/account/tokens/", {"name": "next"}, content_type="application/json", **bearer(writer)
    )
    assert again.status_code == 403 and again.json()["error"]["code"] == "auth.session_required"

    revoked = client.delete(f"/api/v2/account/tokens/{shown['id']}/", **csrf)
    assert revoked.status_code == 200 and revoked.json()["state"] == "revoked"
    assert UserToken.authenticate(raw) is None
    assert client.delete(f"/api/v2/account/tokens/{uuid.uuid4()}/", **csrf).status_code == 404


@pytest.mark.django_db
def test_a_token_revokes_itself_and_nobody_reaches_anothers(editor):
    _, raw = services.issue(editor, name="VS Code")
    mine = Client().get("/api/v2/account/tokens/", **bearer(raw)).json()[0]
    assert Client().delete(f"/api/v2/account/tokens/{mine['id']}/", **bearer(raw)).status_code == 200
    assert Client().get("/api/v2/me", **bearer(raw)).status_code == 401
    other = get_user_model().objects.create_user("other", password="pw")
    theirs, _ = services.issue(other, name="theirs")
    client, csrf = signed_in(editor)
    assert client.delete(f"/api/v2/account/tokens/{theirs.public_id}/", **csrf).status_code == 404
    theirs.refresh_from_db()
    assert theirs.revoked_at is None


@pytest.mark.django_db
def test_issuing_from_the_account_menu_keeps_the_rules(editor):
    client, csrf = signed_in(editor)

    def issue(**body):
        return client.post("/api/v2/account/tokens/", {"name": "t", **body}, content_type="application/json", **csrf)

    assert issue(days=0).status_code == 422  # never-expiring tokens are an operator's, on the command line
    assert issue(days=366).status_code == 422
    assert issue(scopes=["write"]).json()["error"]["code"] == "token.refused"
    assert issue(name="").status_code == 422
    admin = get_user_model().objects.create_superuser("root", password="pw")
    client, csrf = signed_in(admin)
    plain = client.post("/api/v2/account/tokens/", {"name": "t"}, content_type="application/json", **csrf)
    assert plain.status_code == 422 and "superuser" in plain.json()["error"]["message"]
    asked = client.post(
        "/api/v2/account/tokens/", {"name": "t", "superuser": True}, content_type="application/json", **csrf
    )
    assert asked.status_code == 201
    assert Client().post("/api/v2/account/tokens/", {"name": "t"}, content_type="application/json").status_code in (
        401,
        403,
    )
    agent = get_user_model().objects.get(username="agent:seo")
    _, agent_raw = AgentToken.issue(agent, name="mcp")
    assert Client().get("/api/v2/account/tokens/", **bearer(agent_raw)).status_code == 403


@pytest.mark.django_db
def test_the_command_issues_a_read_only_token(editor):
    out = StringIO()
    call_command("user_token", "editor", "--name", "reader", "--read-only", stdout=out, stderr=StringIO())
    assert UserToken.authenticate(out.getvalue().strip()).scopes == ["read"]
    listed = StringIO()
    call_command("user_token", "editor", "--list", stdout=listed)
    assert "reader" in listed.getvalue() and "  read  " in listed.getvalue()
