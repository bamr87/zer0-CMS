"""The content switches' GitHub surface (switches/github.py): every call declared, the guards that keep it to a
repository's own variables and files — never a secret, never a delete — and a client that refuses anything else
before a socket opens and never lets the credential into a message."""

import httpx
import pytest
import respx

from switches import github

from .conftest import API, TOKEN


@pytest.fixture
def gh():
    with respx.mock(base_url=API) as router:
        yield router


def test_the_plan_is_repository_scoped_never_a_secret_and_deletes_nothing():
    assert github.repository_scoped_only() and github.never_a_secret() and github.no_deletes()
    assert {c.id for c in github.CALLS if c.write} == {"variable_update", "variable_create"}
    text = github.describe()
    assert "No secrets are read or written" in text and "[write]" in text


def test_the_guards_refuse_what_the_plan_must_never_hold():
    secret = github.Call("s", "GET", "/repos/{owner}/{repo}/actions/secrets/{name}", "read a secret", "its own secret")
    issues = github.Call("i", "GET", "/repos/{owner}/{repo}/issues", "list issues", "the repository's own issues")
    delete = github.Call("d", "DELETE", "/repos/{owner}/{repo}/actions/variables/{name}", "remove", "its own")
    prefix = github.Call("p", "GET", "/repos/{owner}/{repo}/actions/variablesx", "x", "its own")
    member = github.Call("m", "GET", "/repos/{owner}/{repo}/actions/variables", "x", "the members' names")
    assert not github.never_a_secret([secret])
    assert not github.repository_scoped_only([issues]) and not github.repository_scoped_only([prefix])
    assert not github.repository_scoped_only([member])
    assert not github.no_deletes([delete])


def test_a_request_is_a_declared_call_with_one_segment_per_name(gh):
    route = gh.get("/repos/o/lh/actions/variables/WEEKLY_EPIC_ENABLED").respond(200, json={"value": "true"})
    with github.Client(TOKEN) as client:
        assert client.request("variable", owner="o", repo="lh", name="WEEKLY_EPIC_ENABLED").json()["value"] == "true"
        sent = route.calls.last.request
        assert sent.headers["Authorization"] == f"Bearer {TOKEN}" and sent.headers["X-GitHub-Api-Version"]
        with pytest.raises(github.Refused, match="not a declared"):
            client.request("secrets", owner="o", repo="lh")
        for name in ("../secrets", "A/B", "..", ""):
            with pytest.raises(github.Refused):
                client.request("variable", owner="o", repo="lh", name=name)
        with pytest.raises(github.Refused):
            client.request("hub_map", owner="o", repo="lh", path="_data/../../secrets")
    assert route.call_count == 1


def test_without_a_credential_no_authorization_is_sent(gh):
    route = gh.get("/repos/bamr87/bamr87/contents/_data/fleet.yml").respond(200, text="a: 1")
    with github.Client("") as client:
        client.request("hub_map", owner="bamr87", repo="bamr87", path="_data/fleet.yml")
    assert "Authorization" not in route.calls.last.request.headers


def test_an_error_names_the_status_and_never_the_credential(gh):
    gh.get("/repos/o/lh/actions/variables").respond(403, json={"message": f"token {TOKEN} lacks Variables"})
    gh.get("/repos/o/ij/actions/variables").respond(
        403,
        json={"message": "API rate limit exceeded"},
        headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1"},
    )
    gh.get("/repos/o/gone/actions/variables").mock(side_effect=httpx.ConnectError(f"refused {TOKEN}"))
    with github.Client(TOKEN) as client:
        with pytest.raises(github.Error) as refused:
            client.request("variables", owner="o", repo="lh")
        assert refused.value.status == 403 and TOKEN not in str(refused.value) and "[credential]" in str(refused.value)
        with pytest.raises(github.Error, match="rate limit is spent"):
            client.request("variables", owner="o", repo="ij")
        with pytest.raises(github.Error) as unreachable:
            client.request("variables", owner="o", repo="gone")
        assert unreachable.value.status is None and TOKEN not in str(unreachable.value)


def test_a_repository_is_owner_slash_name():
    assert github.split_repo("bamr87/lifehacker.dev") == ("bamr87", "lifehacker.dev")
    for bad in ("bamr87", "a/b/c", "../x", "", None):
        with pytest.raises(github.Refused):
            github.split_repo(bad)
