"""GraphQL stands behind REST's doors (API-02, SEC-03): the anonymous and the
principal throttles answer 429 with `Retry-After` in GraphQL's own shape, a
query deeper than ten levels is refused before anything resolves, and an
anonymous caller cannot introspect the schema."""

import json

import pytest
from django.test import Client

from accounts import services as tokens
from ops.throttling import AnonThrottle

pytestmark = pytest.mark.django_db


def gql(client, query, **headers):
    return client.post("/graphql/", data=json.dumps({"query": query}), content_type="application/json", **headers)


def nested(depth: int) -> str:
    """`pages { children { … { id } } }`, `depth` fields deep."""
    inner = "id"
    for _ in range(depth - 1):
        inner = f"children {{ {inner} }}"
    return f"{{ pages {{ {inner} }} }}"


def test_the_third_anonymous_query_in_a_minute_is_429(monkeypatch):
    monkeypatch.setitem(AnonThrottle.THROTTLE_RATES, "anon", "2/min")
    for _ in range(2):
        assert gql(Client(), "{ aiSchema }").status_code == 200
    refused = gql(Client(), "{ aiSchema }")
    assert refused.status_code == 429
    wait = int(refused["Retry-After"])
    error = refused.json()["errors"][0]
    assert error["extensions"]["code"] == "rate.limited" and error["extensions"]["retry_after"] == wait >= 1
    assert error["extensions"]["request_id"] == refused["X-Request-Id"]


def test_a_tokens_queries_spend_its_own_bucket(monkeypatch, editor):
    monkeypatch.setitem(AnonThrottle.THROTTLE_RATES, "principal", "2/min")
    _, mine = tokens.issue(editor, name="one")
    _, other = tokens.issue(editor, name="two")
    for _ in range(2):
        assert gql(Client(), "{ aiSchema }", HTTP_AUTHORIZATION=f"Bearer {mine}").status_code == 200
    assert gql(Client(), "{ aiSchema }", HTTP_AUTHORIZATION=f"Bearer {mine}").status_code == 429
    # a person's two tokens are one person: the bucket is per person, an agent's per token
    assert gql(Client(), "{ aiSchema }", HTTP_AUTHORIZATION=f"Bearer {other}").status_code == 429
    assert gql(Client(), "{ aiSchema }").status_code == 200  # an anonymous caller's bucket is another


def test_a_query_deeper_than_ten_levels_is_refused_before_it_resolves():
    assert "errors" not in gql(Client(), nested(10)).json()
    refused = gql(Client(), nested(12))
    assert refused.status_code == 400
    body = refused.json()
    assert body.get("data") is None  # validation runs before execution: nothing resolved
    assert body["errors"][0]["extensions"]["code"] == "graphql.invalid"
    assert "maximum operation depth of 10" in body["errors"][0]["message"]


def test_an_anonymous_caller_cannot_introspect_and_a_signed_in_one_can(editor):
    query = "{ __schema { queryType { name } } }"
    refused = gql(Client(), query)
    assert refused.status_code == 400
    assert refused.json()["errors"][0]["extensions"]["code"] == "graphql.invalid"
    assert "introspection is disabled" in refused.json()["errors"][0]["message"]
    assert gql(Client(), "{ pages { __typename } }").status_code == 200  # a type's name is not introspection
    _, raw = tokens.issue(editor, name="introspect")
    allowed = gql(Client(), query, HTTP_AUTHORIZATION=f"Bearer {raw}")
    assert allowed.status_code == 200 and allowed.json()["data"]["__schema"]["queryType"]["name"] == "Query"
