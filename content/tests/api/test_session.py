"""Who is signed in (api/session.py): the person and their permissions, and a
CSRF token for an anonymous browser. Signing in and out is allauth's headless
API now (tests/accounts/test_signin.py)."""

import pytest
from django.test import Client


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
