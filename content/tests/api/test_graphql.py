"""Headless APIs (M5, M12): GraphQL returns StreamField JSON for a page, the
committed schema has not drifted, the Wagtail API serves live pages, and the
mutations go through the same gates as everything else — including CSRF for
a browser session."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client

from agents.models import AgentRun, AgentToken
from suggestions.models import Suggestion
from suggestions.services import propose

SCHEMA = Path(settings.REPO_ROOT) / "schemas" / "graphql" / "schema.graphql"


def gql(client, query, variables=None, **headers):
    return client.post(
        "/graphql/",
        data=json.dumps({"query": query, "variables": variables or {}}),
        content_type="application/json",
        **headers,
    ).json()


@pytest.mark.django_db
def test_a_graphql_query_returns_streamfield_json(client, article):
    data = gql(
        client,
        """query($id: ID) { page(id: $id) { title ... on ArticlePage {
        aiSummary agentPolicy bodyJson body { id field ... on TextBlock { value } } } } }""",
        {"id": article.pk},
    )
    assert "errors" not in data, data
    page = data["data"]["page"]
    assert page["title"] == "Nightly backups" and page["agentPolicy"] == "suggest"
    assert [b["type"] for b in page["bodyJson"]] == ["heading", "markdown"]
    assert page["bodyJson"][0]["value"] == {"level": "2", "text": "How it works"}
    assert page["body"][1]["field"] == "markdown" and page["body"][1]["value"].startswith("We copy")
    assert page["body"][0]["id"] == page["bodyJson"][0]["id"]


def test_the_committed_graphql_schema_has_not_drifted(tmp_path):
    out = tmp_path / "schema.graphql"
    subprocess.run(
        [sys.executable, "manage.py", "graphql_schema", "--out", str(out)],
        check=True,
        capture_output=True,
        cwd=settings.BASE_DIR,
        env={"DJANGO_SETTINGS_MODULE": "config.settings.testing", "PATH": "/usr/bin:/bin"},
    )
    assert out.read_text() == SCHEMA.read_text(), (
        "schemas/graphql/schema.graphql is stale: python manage.py graphql_schema --out ../schemas/graphql/schema.graphql"
    )


@pytest.mark.django_db
def test_the_wagtail_api_serves_live_pages_with_their_body(client, article):
    listing = client.get("/api/v2/pages/?type=cms.ArticlePage&fields=body,ai_summary")
    assert listing.status_code == 200
    item = next(i for i in listing.json()["items"] if i["id"] == article.pk)
    assert item["body"][0]["type"] == "heading"


@pytest.mark.django_db
def test_request_agent_run_needs_edit_rights_and_starts_a_run(article, editor, django_capture_on_commit_callbacks):
    anonymous = gql(Client(), 'mutation { requestAgentRun(agent: "brand") { runId } }')
    assert "sign in" in anonymous["errors"][0]["message"]
    client = Client(enforce_csrf_checks=True)
    client.force_login(editor)
    blocked = client.post(
        "/graphql/",
        data=json.dumps({"query": 'mutation { requestAgentRun(agent: "brand") { runId } }'}),
        content_type="application/json",
    )
    assert blocked.status_code == 403 and "CSRF" in blocked.json()["errors"][0]["message"]
    client.get("/admin/")  # sets the csrftoken cookie
    token = client.cookies["csrftoken"].value
    with django_capture_on_commit_callbacks(execute=True):
        data = gql(
            client,
            'mutation($id: Int) { requestAgentRun(agent: "brand", pageId: $id) { runId status traceId } }',
            {"id": article.pk},
            HTTP_X_CSRFTOKEN=token,
        )
    assert "errors" not in data, data
    run = AgentRun.objects.get(pk=data["data"]["requestAgentRun"]["runId"])
    run.refresh_from_db()
    assert run.trigger == "graphql" and run.started_by == editor and run.status == "succeeded"


@pytest.mark.django_db
def test_an_agent_token_starts_only_its_own_agent(article):
    token, raw = AgentToken.issue(get_user_model().objects.get(username="agent:seo"), name="rails")
    auth = {"HTTP_AUTHORIZATION": f"Bearer {raw}"}
    data = gql(
        Client(),
        'mutation($id: Int) { requestAgentRun(agent: "drafter", pageId: $id) { runId } }',
        {"id": article.pk},
        **auth,
    )
    assert "agent:seo may start runs of seo only" in data["errors"][0]["message"]
    bad = Client().post("/graphql/", data="{}", content_type="application/json", HTTP_AUTHORIZATION="Bearer zer0_nope")
    assert bad.status_code == 401


@pytest.mark.django_db
def test_accept_suggestion_mutation_and_the_suggestions_query(article, editor, agent):
    s = propose(
        target=article,
        user=get_user_model().objects.get(username="agent:seo"),
        run=None,
        agent=agent("seo"),
        op="meta",
        field="seo_title",
        payload={"value": "Through GraphQL"},
        rationale="r",
    )
    client = Client()
    client.force_login(editor)
    client.get("/admin/")
    headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}
    listed = gql(
        client, "query($id: Int!) { suggestions(pageId: $id) { id field payload } }", {"id": article.pk}, **headers
    )
    assert listed["data"]["suggestions"] == [
        {"id": s.pk, "field": "seo_title", "payload": {"value": "Through GraphQL"}}
    ]
    accepted = gql(
        client, "mutation($id: Int) { acceptSuggestion(id: $id) { ok revisionId } }", {"id": s.pk}, **headers
    )
    assert accepted["data"]["acceptSuggestion"]["ok"] is True
    assert Suggestion.objects.get(pk=s.pk).status == "accepted"


@pytest.mark.django_db
def test_rest_agent_runs_create_read_and_stream(article, editor, django_capture_on_commit_callbacks):
    client = Client()
    client.force_login(editor)
    client.get("/admin/")
    headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}
    with django_capture_on_commit_callbacks(execute=True):
        created = client.post(
            "/api/v2/agents/brand/runs", data={"page_id": article.pk}, content_type="application/json", **headers
        )
    assert created.status_code == 201, created.content
    run_id = created.json()["id"]
    detail = client.get(f"/api/v2/agent-runs/{run_id}/").json()
    assert detail["status"] == "succeeded" and detail["steps"][0]["name"] == "review.submit_verdict"
    stream = client.get(f"/api/v2/agent-runs/{run_id}/stream/")
    body = b"".join(stream.streaming_content).decode()
    assert stream["Content-Type"] == "text/event-stream"
    assert "event: step" in body and '"status": "succeeded"' in body and body.endswith("event: end\ndata: {}\n\n")
    assert client.get("/api/v2/agent-runs/").json()["results"][0]["id"] == run_id
    assert Client().get(f"/api/v2/agent-runs/{run_id}/").status_code == 401


@pytest.mark.django_db
def test_rest_tools_lists_what_a_token_may_call():
    _, raw = AgentToken.issue(get_user_model().objects.get(username="agent:seo"), name="t", tools=["content.get_page"])
    listed = Client().get("/api/v2/tools/", HTTP_AUTHORIZATION=f"Bearer {raw}").json()["tools"]
    assert [t["name"] for t in listed] == ["content.get_page"]
