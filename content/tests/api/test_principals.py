"""People-only by default (API-05): every operation in the committed OpenAPI
document, called with an agent's token, answers 403 `auth.forbidden` — an
agent changes content through the tool registry — except the operations
below, each with the reason an agent may reach it. A new endpoint an agent can
reach fails here until it is refused or listed."""

import json
import re
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from agents.models import AgentToken

DOCUMENT = json.loads((Path(settings.REPO_ROOT) / "schemas" / "openapi" / "openapi.json").read_text())

AGENTS_API = "the content plane's own API (api/views.py), for agents and people alike; its services refuse per row"
PUBLIC = "public by design (AllowAny): it answers anyone"
CATALOG = "a read-only catalog that declares no permission of its own yet (the IsPerson default is API-05's rest)"
ALLOWED = {
    ("GET", "/api/v2/agent-runs/"): AGENTS_API,
    ("POST", "/api/v2/agent-runs/"): AGENTS_API,
    ("GET", "/api/v2/agent-runs/{public_id}/"): AGENTS_API,
    ("GET", "/api/v2/agent-runs/{public_id}/stream/"): AGENTS_API,
    ("POST", "/api/v2/agents/{slug}/runs"): AGENTS_API,
    ("GET", "/api/v2/graph/neighbors/"): AGENTS_API,
    ("GET", "/api/v2/graph/path/"): AGENTS_API,
    ("GET", "/api/v2/graph/related/{page_id}/"): AGENTS_API,
    ("GET", "/api/v2/graph/search/"): AGENTS_API,
    ("GET", "/api/v2/suggestions/"): AGENTS_API,
    ("POST", "/api/v2/suggestions/{public_id}/{decision}/"): AGENTS_API,
    ("GET", "/api/v2/tools/"): AGENTS_API,
    ("GET", "/api/v2/me"): PUBLIC,
    ("POST", "/api/v2/automations/{public_id}/webhook/"): PUBLIC,
    ("POST", "/api/v2/newsroom/newsletters/{public_id}/subscribe/"): PUBLIC,
    ("POST", "/api/v2/newsroom/subscriptions/confirm/"): PUBLIC,
    ("POST", "/api/v2/newsroom/subscriptions/unsubscribe/"): PUBLIC,
    ("GET", "/api/v2/ai/providers/"): CATALOG,
    ("GET", "/api/v2/ai/providers/{public_id}/"): CATALOG,
    ("GET", "/api/v2/ai/models/"): CATALOG,
    ("GET", "/api/v2/ai/models/{public_id}/"): CATALOG,
}
SAMPLE = {"slug": "seo", "decision": "accept"}


def url_of(path: str, operation: dict) -> str:
    """The path with each parameter given a value of its declared type, so the request reaches the view."""
    kinds = {p["name"]: p.get("schema", {}) for p in operation.get("parameters", []) if p.get("in") == "path"}

    def value(match):
        name = match.group(1)
        schema = kinds.get(name, {})
        if schema.get("format") == "uuid" or "{36}" in schema.get("pattern", ""):  # a public id, either way
            return "6f1c2d3e-4b5a-4c6d-8e7f-9a0b1c2d3e4f"
        return "1" if schema.get("type") == "integer" else SAMPLE.get(name, "x")

    return re.sub(r"\{(\w+)\}", value, path)


@pytest.mark.django_db
def test_an_agent_token_is_refused_everywhere_but_the_allow_list():
    raw = AgentToken.issue(get_user_model().objects.get(username="agent:seo"), name="walk")[1]
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    reached = {}
    for path, operations in DOCUMENT["paths"].items():
        for method in ("get", "post", "put", "patch", "delete"):
            if method not in operations:
                continue
            target = url_of(path, operations[method])
            response = client.get(target) if method == "get" else getattr(client, method)(target, {}, format="json")
            refused = response.status_code == 403 and response.json()["error"]["code"] == "auth.forbidden"
            if not refused:
                reached[(method.upper(), path)] = response.status_code
    assert set(reached) - set(ALLOWED) == set(), "an agent reaches these; refuse them (IsPerson) or list them"
    assert set(ALLOWED) - set(reached) == set(), "listed, but an agent is refused: take them off the list"
