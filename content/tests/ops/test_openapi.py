"""The committed OpenAPI document matches what the code generates, whichever
database generates it, is served at /api/v2/openapi.json, and the docs UI is
mounted where it is enabled (UPS-BE-12, BE-31)."""

import json
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command
from django.db import connection

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


def bounds(node):
    """Every integer `maximum` and `minimum` in a JSON Schema tree."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("maximum", "minimum") and isinstance(value, int):
                yield value
            else:
                yield from bounds(value)
    elif isinstance(node, list):
        for item in node:
            yield from bounds(item)


def test_no_bound_in_the_document_is_a_databases_integer_range():
    # A ModelSerializer gives a writable integer field the bounds Django reads
    # from the database (connection.ops.integer_field_range: 64-bit on SQLite,
    # 16- or 32-bit on Postgres), so a document holding one is generated
    # differently on each, and only the Postgres job notices. Make such a field
    # read-only, or declare it with the bounds the API means.
    ops = connection.ops
    ranges = {*ops.integer_field_ranges.values(), *(ops.integer_field_range(kind) for kind in ops.integer_field_ranges)}
    database = {bound for pair in ranges for bound in pair if bound != 0}
    found = sorted(set(bounds(json.loads(COMMITTED.read_text()))) & database)
    assert found == [], f"bounds that come from the database, not the API: {found}"


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
