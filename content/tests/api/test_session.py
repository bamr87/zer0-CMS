"""The studio's session (api/session.py): who am I, sign in, sign out — each
POST behind the CSRF token, with the platform's error codes."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client


def csrf_client():
    client = Client(enforce_csrf_checks=True)
    token = client.get("/api/v2/me").json()["csrf_token"]
    return client, token


@pytest.mark.django_db
def test_me_answers_anonymous_callers_with_a_csrf_token_and_sets_the_cookie():
    response = Client().get("/api/v2/me")
    body = response.json()
    assert response.status_code == 200
    assert body["authenticated"] is False and body["user"] is None and body["permissions"] == []
    assert body["csrf_token"] and "csrftoken" in response.cookies


@pytest.mark.django_db
def test_me_describes_the_person_signed_in(editor):
    client = Client()
    client.force_login(editor)
    body = client.get("/api/v2/me").json()
    assert body["authenticated"] is True
    assert body["user"]["username"] == "editor" and body["user"]["is_staff"] is True
    assert "wagtailadmin.access_admin" in body["permissions"]


@pytest.mark.django_db
def test_login_needs_the_csrf_token(editor):
    client = Client(enforce_csrf_checks=True)
    client.get("/api/v2/me")
    response = client.post(
        "/api/v2/session/login", {"username": "editor", "password": "pw"}, content_type="application/json"
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "auth.csrf_failed"


@pytest.mark.django_db
def test_login_starts_a_session_and_logout_ends_it(editor):
    client, token = csrf_client()
    response = client.post(
        "/api/v2/session/login",
        {"username": "editor", "password": "pw"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert response.status_code == 200, response.json()
    signed_in = response.json()
    assert signed_in["authenticated"] is True and signed_in["user"]["username"] == "editor"
    assert signed_in["csrf_token"] != token  # Django rotates the token on login
    assert client.get("/api/v2/me").json()["authenticated"] is True

    out = client.post("/api/v2/session/logout", HTTP_X_CSRFTOKEN=signed_in["csrf_token"])
    assert out.status_code == 200 and out.json()["authenticated"] is False
    assert client.get("/api/v2/me").json()["authenticated"] is False


@pytest.mark.django_db
def test_a_wrong_password_and_an_agent_principal_are_refused(editor):
    client, token = csrf_client()
    wrong = client.post(
        "/api/v2/session/login",
        {"username": "editor", "password": "nope"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert wrong.status_code == 400 and wrong.json()["error"]["code"] == "auth.invalid_credentials"
    agent = get_user_model().objects.get(username="agent:seo")
    agent.set_password("pw")
    agent.save()
    refused = client.post(
        "/api/v2/session/login",
        {"username": "agent:seo", "password": "pw"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "auth.invalid_credentials"
    missing = client.post("/api/v2/session/login", {}, content_type="application/json", HTTP_X_CSRFTOKEN=token)
    assert missing.status_code == 422
    assert {d["field"] for d in missing.json()["error"]["details"]} == {"username", "password"}
