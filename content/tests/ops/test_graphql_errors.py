"""GraphQL keeps its own `errors` array; every entry gains `extensions.code`
and `extensions.request_id`, and a resolver crash is `internal.error` with
the message replaced."""

import json

import pytest

pytestmark = pytest.mark.django_db


def gql(client, query, **headers):
    return client.post("/graphql/", data=json.dumps({"query": query}), content_type="application/json", **headers)


def test_an_invalid_document_is_graphql_invalid(client):
    response = gql(client, "{ notAField }")
    assert response.status_code == 400
    error = response.json()["errors"][0]
    assert error["extensions"]["code"] == "graphql.invalid"
    assert error["extensions"]["request_id"] == response["X-Request-Id"]


def test_a_bad_bearer_token_is_auth_invalid_token(client):
    response = gql(client, "{ aiSchema }", HTTP_AUTHORIZATION="Bearer zer0_nope")
    assert response.status_code == 401
    error = response.json()["errors"][0]
    assert error["extensions"]["code"] == "auth.invalid_token"
    assert error["extensions"]["request_id"] == response["X-Request-Id"]


def test_a_resolver_crash_is_internal_error_without_the_message(client, monkeypatch):
    def explode():
        raise RuntimeError("secret")

    monkeypatch.setattr("api.graphql.export", explode)
    response = gql(client, "{ aiSchema }")
    assert response.status_code == 200
    error = response.json()["errors"][0]
    assert error["message"] == "internal error"
    assert error["extensions"]["code"] == "internal.error"
    assert "secret" not in response.content.decode()
