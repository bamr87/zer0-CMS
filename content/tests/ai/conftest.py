"""Fixtures for the AI content layer's tests: people with and without page
rights (and staff who configure providers), a scripted `fake` provider in place
of the default, runs executed the way the worker would after the request
commits, and an API client. No test reaches a provider: the fake answers, or a
test-made SDK stand-in does."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from rest_framework.test import APIClient
from wagtail.models import GroupPagePermission

from ai import providers
from ai.providers.fake import FakeProvider


def _person(username, *, staff=False, editor=False, perms=()):
    user = get_user_model().objects.create_user(username, password="pw", is_staff=staff)
    user.user_permissions.add(*(Permission.objects.get(content_type__app_label="ai", codename=c) for c in perms))
    if editor:
        group, _ = Group.objects.get_or_create(name="AI test editors")
        from wagtail.models import Page

        for codename in ("add_page", "change_page", "publish_page"):
            GroupPagePermission.objects.get_or_create(
                group=group,
                page=Page.get_first_root_node(),
                permission=Permission.objects.get(content_type__app_label="wagtailcore", codename=codename),
            )
        user.groups.add(group)
    return user


@pytest.fixture
def alice(db):
    """A person who edits every page (and so every site), not staff."""
    return _person("alice", editor=True)


@pytest.fixture
def bob(db):
    """A person with no page rights, not staff."""
    return _person("bob")


@pytest.fixture
def staff(db):
    """Staff who configure providers (`ai.change_providerconfig`); plain staff do not."""
    return _person("staff", staff=True, perms=["change_providerconfig"])


@pytest.fixture
def fake():
    """The default provider in tests (`AI_DEFAULT_PROVIDER = "fake"`), scripted per test."""
    with providers.override(FakeProvider()) as provider:
        yield provider


@pytest.fixture
def worker(django_capture_on_commit_callbacks):
    """Run `fn` and then the Celery tasks it queued, as the worker does after commit."""

    def call(fn, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return fn(*args, **kwargs)

    return call


@pytest.fixture
def api():
    def client(user=None):
        c = APIClient()
        if user is not None:
            c.force_authenticate(user=user)
        return c

    return client
