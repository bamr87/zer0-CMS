"""The committed OpenAPI document matches what the code generates, is served
at /api/v2/openapi.json, and the docs UI is mounted where it is enabled
(UPS-BE-12, BE-31)."""

import json
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command

COMMITTED = Path(settings.REPO_ROOT) / "schemas" / "openapi" / "openapi.json"
REGENERATE = (
    "cd content && python manage.py spectacular --format openapi-json --urlconf ops.openapi "
    "--fail-on-warn --file ../schemas/openapi/openapi.json"
)


def test_the_committed_openapi_document_has_not_drifted(tmp_path):
    out = tmp_path / "openapi.json"
    call_command(
        "spectacular", "--format", "openapi-json", "--urlconf", "ops.openapi", "--fail-on-warn", "--file", str(out)
    )
    assert out.read_bytes() == COMMITTED.read_bytes(), f"the document drifted; regenerate it: {REGENERATE}"


@pytest.mark.django_db
def test_openapi_is_served_as_json_and_matches(client):
    response = client.get("/api/v2/openapi.json")
    assert response.status_code == 200
    document = json.loads(response.content)
    assert document["openapi"].startswith("3.1")
    assert document == json.loads(COMMITTED.read_text())


@pytest.mark.django_db
def test_the_docs_ui_is_mounted_in_testing(client):
    assert client.get("/api/v2/docs/").status_code == 200
