"""The MCP server (M15): one registry behind /mcp/ and stdio; tools/list is
exactly what the token's agent may call; a token cannot reach pages its agent
user has no permission on; every call is an audited run."""

import io
import json

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.test import Client
from wagtail.models import GroupPagePermission

from agents.models import AgentRun, AgentToken
from agents.registry import ToolContext, registry
from mcp_server.protocol import SUPPORTED_VERSIONS

from ..conftest import make_article


def token_for(slug, **kwargs):
    return AgentToken.issue(get_user_model().objects.get(username=f"agent:{slug}"), name="test", **kwargs)[1]


def rpc(raw, method, params=None, id_=1, **headers):
    body = {
        "jsonrpc": "2.0",
        "method": method,
        **({"params": params} if params is not None else {}),
        **({"id": id_} if id_ is not None else {}),
    }
    return Client().post(
        "/mcp/",
        data=json.dumps(body),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {raw}",
        HTTP_ACCEPT="application/json, text/event-stream",
        **headers,
    )


@pytest.mark.django_db
def test_initialize_negotiates_a_supported_version():
    reply = rpc(
        token_for("seo"),
        "initialize",
        {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
    ).json()
    assert reply["result"]["protocolVersion"] == "2025-06-18"
    assert reply["result"]["capabilities"] == {"tools": {"listChanged": False}}
    old = rpc(token_for("seo"), "initialize", {"protocolVersion": "1999-01-01"}).json()
    assert old["result"]["protocolVersion"] == SUPPORTED_VERSIONS[0]
    assert rpc(token_for("seo"), "notifications/initialized", id_=None).status_code == 202


@pytest.mark.django_db
def test_tools_list_matches_the_registry_for_the_tokens_agent(agent):
    tools = rpc(token_for("seo"), "tools/list").json()["result"]["tools"]
    seo = agent("seo")
    expected = [t.name for t in registry.for_context(ToolContext(user=None, agent=seo))]
    assert [t["name"] for t in tools] == expected == sorted(seo.tools)
    by_name = {t["name"]: t for t in tools}
    assert by_name["content.get_page"]["annotations"]["readOnlyHint"] is True
    assert by_name["content.get_page"]["inputSchema"] == registry.get("content.get_page").input_schema
    narrowed = rpc(token_for("seo", tools=["content.get_page"]), "tools/list").json()["result"]["tools"]
    assert [t["name"] for t in narrowed] == ["content.get_page"]


@pytest.mark.django_db
def test_an_seo_token_cannot_propose_on_pages_outside_its_permissions(site_root, root_page):
    allowed_section = make_article(site_root, "Allowed")
    elsewhere = make_article(site_root, "Elsewhere")
    group = Group.objects.get(name="agent:seo")
    GroupPagePermission.objects.filter(group=group).delete()
    GroupPagePermission.objects.create(
        group=group,
        page=allowed_section,
        permission=Permission.objects.get(content_type__app_label="wagtailcore", codename="change_page"),
    )
    raw = token_for("seo")
    args = {"op": "meta", "field": "seo_title", "value": "New title", "rationale": "shorter"}
    denied = rpc(
        raw, "tools/call", {"name": "content.propose_edit", "arguments": {"page_id": elsewhere.pk, **args}}
    ).json()
    assert denied["result"]["isError"] is True
    assert denied["result"]["structuredContent"]["error"] == "permission_denied"
    ok = rpc(
        raw, "tools/call", {"name": "content.propose_edit", "arguments": {"page_id": allowed_section.pk, **args}}
    ).json()
    assert ok["result"]["isError"] is False and ok["result"]["structuredContent"]["status"] == "pending"
    runs = AgentRun.objects.filter(trigger="mcp", agent__slug="seo").order_by("id")
    assert [r.status for r in runs] == ["refused", "succeeded"]
    assert all(r.steps.count() == 1 for r in runs)


@pytest.mark.django_db
def test_protocol_and_transport_errors():
    raw = token_for("seo")
    assert rpc(raw, "tools/call", {"name": "no.such.tool", "arguments": {}}).json()["error"]["code"] == -32602
    assert rpc(raw, "resources/list").json()["error"]["code"] == -32601
    assert Client().post("/mcp/", data="{}", content_type="application/json").status_code == 401
    assert Client().get("/mcp/", HTTP_AUTHORIZATION=f"Bearer {raw}").status_code == 405
    assert rpc(raw, "ping", HTTP_ORIGIN="https://evil.example").status_code == 403
    assert rpc(raw, "ping", HTTP_MCP_PROTOCOL_VERSION="1999-01-01").status_code == 400
    batch = Client().post(
        "/mcp/",
        data=json.dumps([{"jsonrpc": "2.0", "id": 1, "method": "ping"}]),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {raw}",
    )
    assert batch.status_code == 400


@pytest.mark.django_db
def test_stdio_serves_the_same_registry(article, monkeypatch, capsys):
    lines = (
        "\n".join(
            json.dumps(m)
            for m in [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "content.get_page", "arguments": {"page_id": article.pk}},
                },
            ]
        )
        + "\n"
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(lines))
    call_command("mcp_stdio", "--agent", "seo")
    replies = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [r["id"] for r in replies] == [1, 2]
    assert replies[1]["result"]["structuredContent"]["title"] == "Nightly backups"
