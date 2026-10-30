"""Third-party sign-in from the environment (accounts/providers.py) against a
fake OpenID Connect IdP and a fake GitHub, both recorded
(fixtures/fake_idp.json, replayed with `responses`; nothing reaches a
network): the headless redirect with state and PKCE, the callback that signs a
person in (and provisions them, for an IdP), their groups synced from the
IdP's claims (`OIDC_GROUP_MAP`) at every sign-in, GitHub following
`SIGNUP_OPEN`, and the environment parsed — or refused, naming the variable."""

import json
import logging
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import responses
from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ImproperlyConfigured

from accounts.providers import group_map, oidc_apps, socialaccount_providers

from .conftest import make_person

pytestmark = pytest.mark.django_db

FAKE = json.loads((Path(__file__).parent / "fixtures" / "fake_idp.json").read_text())
CALLBACK = "/studio/account/provider/callback"
CORP = {
    "OIDC_PROVIDERS": "corp",
    "OIDC_CORP_NAME": "Corp SSO",
    "OIDC_CORP_SERVER_URL": FAKE["issuer"],
    "OIDC_CORP_CLIENT_ID": "zer0-cms",
    "OIDC_CORP_CLIENT_SECRET": "the-fake-idps-client-secret",
    "OIDC_CORP_SCOPES": "groups",
}
GITHUB = {"GITHUB_LOGIN_CLIENT_ID": "gh-client", "GITHUB_LOGIN_CLIENT_SECRET": "gh-secret"}


@pytest.fixture
def idp(settings):
    """The fake IdP, configured as the environment would, answering from its recording."""
    settings.SOCIALACCOUNT_PROVIDERS = socialaccount_providers({**CORP, **GITHUB})
    discovery = FAKE["discovery"]
    with responses.RequestsMock(assert_all_requests_are_fired=False) as recorded:
        recorded.get(FAKE["issuer"] + "/.well-known/openid-configuration", json=discovery)
        recorded.post(discovery["token_endpoint"], json=FAKE["token"])
        recorded.get(discovery["userinfo_endpoint"], json=FAKE["userinfo"])
        recorded.post("https://github.com/login/oauth/access_token", json=FAKE["github"]["token"])
        recorded.get("https://api.github.com/user", json=FAKE["github"]["user"])
        recorded.get("https://api.github.com/user/emails", json=FAKE["github"]["emails"])
        yield recorded


def through(browser, provider, callback_path, process="login"):
    """The studio's provider button (a form POST to allauth), the IdP's consent, and its return."""
    started = browser.client.post(
        "/_allauth/browser/v1/auth/provider/redirect",
        {"provider": provider, "callback_url": CALLBACK, "process": process},
        HTTP_X_CSRFTOKEN=browser.csrf,
    )
    assert started.status_code == 302, started.content
    authorize = urlparse(started["Location"])
    query = parse_qs(authorize.query)
    returned = browser.client.get(callback_path, {"code": "the-idps-code", "state": query["state"][0]})
    return authorize, query, returned


def test_the_sign_in_screen_offers_each_idp_and_github(browser, idp):
    providers = browser.get("/config").json()["data"]["socialaccount"]["providers"]
    assert {(p["id"], p["name"]) for p in providers} == {("corp", "Corp SSO"), ("github", "GitHub")}


def test_an_idp_signs_a_new_person_in_with_state_and_pkce(browser, idp):
    authorize, query, returned = through(browser, "corp", "/accounts/oidc/corp/login/callback/")
    assert f"{authorize.scheme}://{authorize.netloc}{authorize.path}" == FAKE["discovery"]["authorization_endpoint"]
    assert query["client_id"] == ["zer0-cms"] and query["code_challenge_method"] == ["S256"]
    assert set(query["scope"][0].split()) == {"openid", "profile", "email", "groups"}
    assert returned.status_code == 302 and returned["Location"] == CALLBACK
    token_request = next(c.request for c in idp.calls if c.request.url == FAKE["discovery"]["token_endpoint"])
    sent = parse_qs(token_request.body)
    assert sent["code"] == ["the-idps-code"] and "code_verifier" in sent
    session = browser.get("/auth/session").json()
    assert session["meta"]["is_authenticated"] is True
    grace = get_user_model().objects.get(username="grace")
    assert (grace.email, grace.first_name, grace.last_name) == ("grace@example.com", "Grace", "Hopper")
    assert grace.emailaddress_set.get().verified is True  # the IdP said so
    assert SocialAccount.objects.get(user=grace).provider == "corp"
    # The access token is not kept (SOCIALACCOUNT_STORE_TOKENS = False).
    assert not grace.socialaccount_set.get().socialtoken_set.exists()


def test_the_idps_groups_claim_sets_the_mapped_wagtail_groups_at_every_sign_in(browser, idp, settings, caplog):
    editors, moderators, hand_picked = (
        Group.objects.get_or_create(name=n)[0] for n in ("Editors", "Moderators", "Picked")
    )
    settings.OIDC_GROUP_MAP = group_map(
        '{"cms-editors": "Editors", "cms-leads": ["Moderators", "Editors"], "cms-gone": "No such group"}'
    )
    grace = make_person("grace", "grace@example.com")
    grace.groups.add(moderators, hand_picked)
    SocialAccount.objects.create(user=grace, provider="corp", uid="u-1001", extra_data={})
    with caplog.at_level(logging.WARNING, logger="accounts.groups"):
        through(browser, "corp", "/accounts/oidc/corp/login/callback/")
    assert set(grace.groups.values_list("name", flat=True)) == {"Editors", "Picked"}
    assert "No such group" in caplog.text and not Group.objects.filter(name="No such group").exists()
    assert not grace.is_staff and not grace.is_superuser

    browser.delete("/auth/session")
    idp.replace(
        responses.GET, FAKE["discovery"]["userinfo_endpoint"], json={**FAKE["userinfo"], "groups": ["cms-leads"]}
    )
    through(browser, "corp", "/accounts/oidc/corp/login/callback/")
    assert set(grace.groups.values_list("name", flat=True)) == {"Editors", "Moderators", "Picked"}

    browser.delete("/auth/session")
    idp.replace(responses.GET, FAKE["discovery"]["userinfo_endpoint"], json={**FAKE["userinfo"], "groups": []})
    through(browser, "corp", "/accounts/oidc/corp/login/callback/")
    assert set(grace.groups.values_list("name", flat=True)) == {"Picked"}
    assert editors.pk and moderators.pk


def test_a_password_sign_in_changes_no_group(browser, idp, settings):
    settings.OIDC_GROUP_MAP = group_map('{"cms-editors": "Editors"}')
    person = make_person()
    browser.sign_in()
    assert not person.groups.exists()


def test_github_follows_signup_open_and_signs_in_a_person_it_knows(browser, idp, settings):
    _, _, closed = through(browser, "github", "/accounts/github/login/callback/")
    assert closed.status_code == 302 and closed["Location"].startswith(CALLBACK)
    assert "error=" in closed["Location"]
    assert browser.get("/auth/session").json()["meta"]["is_authenticated"] is False
    assert not get_user_model().objects.filter(email="octo-ada@example.com").exists()

    settings.SIGNUP_OPEN = True
    _, _, opened = through(browser, "github", "/accounts/github/login/callback/")
    assert opened["Location"] == CALLBACK
    octo = get_user_model().objects.get(email="octo-ada@example.com")
    assert octo.username == "octo-ada" and octo.emailaddress_set.get().verified is True

    settings.SIGNUP_OPEN = False
    browser.delete("/auth/session")
    _, _, again = through(browser, "github", "/accounts/github/login/callback/")
    assert again["Location"] == CALLBACK  # a person GitHub already knows signs in, sign-up closed or not
    assert browser.client.get("/api/v2/me").json()["user"]["username"] == "octo-ada"


def test_a_person_connects_github_to_their_account_and_lists_it(browser, idp, person):
    browser.sign_in()
    _, _, connected = through(browser, "github", "/accounts/github/login/callback/", process="connect")
    assert connected.status_code == 302
    accounts = browser.get("/account/providers").json()["data"]
    assert [(a["provider"]["id"], a["uid"]) for a in accounts] == [("github", "583231")]


def test_the_environment_configures_the_idps_or_refuses_naming_the_variable():
    assert socialaccount_providers({}) == {"openid_connect": {"APPS": []}, "github": {"APPS": []}}
    entra_env = {"OIDC_ENTRA_ID_SERVER_URL": "https://login.example/v2", "OIDC_ENTRA_ID_CLIENT_ID": "c"}
    apps = oidc_apps({**CORP, **entra_env, "OIDC_PROVIDERS": "corp, entra-id"})
    assert [a["provider_id"] for a in apps] == ["corp", "entra-id"]
    with pytest.raises(ImproperlyConfigured, match="OIDC_ENTRA_ID_CLIENT_ID"):
        oidc_apps({**CORP, "OIDC_PROVIDERS": "corp,entra-id", "OIDC_ENTRA_ID_SERVER_URL": "https://login.example"})
    entra = oidc_apps({"OIDC_PROVIDERS": "entra-id", "OIDC_ENTRA_ID_SERVER_URL": "u", "OIDC_ENTRA_ID_CLIENT_ID": "c"})[
        0
    ]
    assert entra["name"] == "entra-id" and entra["settings"] == {"server_url": "u", "oauth_pkce_enabled": True}
    with pytest.raises(ImproperlyConfigured, match="not an id"):
        oidc_apps({"OIDC_PROVIDERS": "Corp SSO"})
    with pytest.raises(ImproperlyConfigured, match="GITHUB_LOGIN_CLIENT_SECRET") as refused:
        socialaccount_providers({"GITHUB_LOGIN_CLIENT_ID": "gh-client"})
    assert "gh-client" not in str(refused.value)
    assert group_map("") == {}
    assert group_map('{"a": "A", "b": ["B", "C"]}') == {"a": ["A"], "b": ["B", "C"]}
    for bad in ("[1]", '{"a": 1}', '{"a": [""]}', "{nope"):
        with pytest.raises(ImproperlyConfigured, match="OIDC_GROUP_MAP"):
            group_map(bad)
