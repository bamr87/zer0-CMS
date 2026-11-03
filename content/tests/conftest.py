"""Shared fixtures for the content plane's tests.

The session database is migrated (which provisions the standard agent users)
and then gets every agent definition synced from agents/definitions/ and
published through its eval suite — the same `sync_agents --publish` a
deployment runs — so tests start from live, eval-passed agents. Each test then
runs in its own transaction, rolled back afterwards.
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from wagtail.models import GroupPagePermission, Page

from agents.models import AgentDefinition
from cms.models import ArticlePage, SiteRootPage


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("sync_agents", "--publish", verbosity=0)


@pytest.fixture(autouse=True)
def fresh_rate_limits():
    """Tool rates live in the cache; one test's calls must not spend another's."""
    from django.core.cache import cache

    cache.clear()
    yield


@pytest.fixture(autouse=True)
def wagtail_tree(request):
    """A transactional test (`django_db(transaction=True)`) starts from what
    the last one's flush left: the apps' post_migrate seeds come back by
    themselves, but not what Wagtail's own migrations create — the default
    locale, the page tree's root, the root collection — so those are made
    again here, whichever transactional test runs first."""
    marker = request.node.get_closest_marker("django_db")
    if marker is None or not (marker.kwargs.get("transaction") or "transactional_db" in request.fixturenames):
        return
    from django.conf import settings
    from wagtail.coreutils import get_supported_content_language_variant
    from wagtail.models import Collection, Locale

    request.getfixturevalue("transactional_db")
    Locale.objects.get_or_create(language_code=get_supported_content_language_variant(settings.LANGUAGE_CODE))
    if Page.get_first_root_node() is None:
        Page.add_root(instance=Page(title="Root", slug="root"))
    if Collection.get_first_root_node() is None:
        Collection.add_root(name="Root")


@pytest.fixture
def root_page(db):
    return Page.get_first_root_node()


@pytest.fixture
def site_root(root_page):
    from wagtail.models import Site

    page = SiteRootPage(title="Test site", slug="test-site", site_key="test-site")
    root_page.add_child(instance=page)
    page.save_revision().publish()
    # Serve it as the default site, so the Wagtail API (which lists one site's
    # pages) and URL routing see it.
    Site.objects.filter(is_default_site=True).update(root_page=page)
    return page


def make_article(parent, title="An article", body=None, publish=True, **fields):
    page = ArticlePage(title=title, slug=fields.pop("slug", title.lower().replace(" ", "-")), body=body or [], **fields)
    page.live = publish  # a Wagtail page is live by default; an unpublished draft is not
    parent.add_child(instance=page)
    revision = page.save_revision()
    if publish:
        revision.publish()
    page.refresh_from_db()
    return page.specific


@pytest.fixture
def article(site_root):
    return make_article(
        site_root,
        "Nightly backups",
        body=[
            {"type": "heading", "value": {"level": "2", "text": "How it works"}},
            {"type": "markdown", "value": "We copy the site to a second disk every night."},
        ],
    )


@pytest.fixture
def editor(db, root_page):
    """A person in a group with add/change/publish at the root."""
    user = get_user_model().objects.create_user("editor", password="pw", is_staff=True)
    group, _ = Group.objects.get_or_create(name="Test editors")
    group.permissions.add(Permission.objects.get(codename="access_admin"))
    for codename in ("add_page", "change_page", "publish_page"):
        GroupPagePermission.objects.get_or_create(
            group=group,
            page=root_page,
            permission=Permission.objects.get(content_type__app_label="wagtailcore", codename=codename),
        )
    user.groups.add(group)
    return user


@pytest.fixture
def agent():
    def get(slug):
        return AgentDefinition.objects.get(slug=slug)

    return get
