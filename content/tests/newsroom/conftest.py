"""Fixtures for the newsroom's tests: a site with a news section, a desk with an
editor and a copy editor, a reporter who may write but not publish, someone
from outside, a desk on a second site whose editor works there only, an API
client, the scripted `fake` provider, and `advance()`, which walks a story
through the newsroom workflow the way people do."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from rest_framework.test import APIClient
from wagtail.models import GroupPagePermission, Page, Site

from ai import providers
from ai.providers.fake import FakeProvider
from cms.models import CollectionPage, SiteRootPage
from newsroom import services
from newsroom.models import Desk, Story

S = Story.Status


def person(username, *rights, **fields):
    """A person with Wagtail page rights (`add`, `change`, `publish`) on every site."""
    user = get_user_model().objects.create_user(username, password="pw", **fields)
    if rights:
        group, _ = Group.objects.get_or_create(name=f"newsroom test: {'+'.join(rights)}")
        for right in rights:
            GroupPagePermission.objects.get_or_create(
                group=group,
                page=Page.get_first_root_node(),
                permission=Permission.objects.get(content_type__app_label="wagtailcore", codename=f"{right}_page"),
            )
        user.groups.add(group)
    return user


@pytest.fixture
def site(site_root):
    return Site.objects.get(root_page=site_root)


@pytest.fixture
def section(site_root):
    page = CollectionPage(title="News", slug="news", collection="posts", output_dir="_posts")
    site_root.add_child(instance=page)
    page.save_revision().publish()
    return page


@pytest.fixture
def ed(db):
    return person("ed", "add", "change", "publish", first_name="Ed")


@pytest.fixture
def copyeditor(db):
    return person("copy", "add", "change", "publish")


@pytest.fixture
def reporter(db):
    return person("reporter", "add", "change")


@pytest.fixture
def outsider(db):
    return person("outsider")


@pytest.fixture
def desk(site, section, ed, copyeditor):
    desk = Desk.objects.create(site=site, name="Metro", slug="metro", section=section)
    desk.editors.add(ed)
    desk.copy_editors.add(copyeditor)
    return desk


@pytest.fixture
def elsewhere(root_page):
    """A desk on a second site, and its editor, `other_ed`, who has page rights on that site only."""
    root = SiteRootPage(title="Other site", slug="other-site", site_key="other-site")
    root_page.add_child(instance=root)
    root.save_revision().publish()
    news = CollectionPage(title="News", slug="news", collection="posts", output_dir="_posts")
    root.add_child(instance=news)
    news.save_revision().publish()
    other_ed = get_user_model().objects.create_user("other_ed", password="pw")
    group = Group.objects.create(name="newsroom test: the other site")
    for right in ("add", "change", "publish"):
        permission = Permission.objects.get(content_type__app_label="wagtailcore", codename=f"{right}_page")
        GroupPagePermission.objects.create(group=group, page=root, permission=permission)
    other_ed.groups.add(group)
    desk = Desk.objects.create(
        site=Site.objects.create(hostname="other.localhost", root_page=root), name="Other", slug="other", section=news
    )
    desk.editors.add(other_ed)
    return desk


@pytest.fixture
def advance(ed, copyeditor, reporter):
    """Pitch a story on `desk` and move it to `status` as the newsroom does."""

    def walk(desk, status, headline="Council votes on the bridge", **fields):
        story = services.pitch(desk, user=ed, headline=headline, **fields)
        steps = [
            (S.ASSIGNED, ed, {"assignee": reporter}),
            (S.DRAFTING, reporter, {}),
            (S.EDITING, reporter, {}),
            (S.COPY, ed, {}),
            (S.PUBLISHED, copyeditor, {}),
        ]
        for to, who, extra in steps:
            if story.status == status:
                break
            story = services.move(story, to, user=who, **extra)
        return story

    return walk


@pytest.fixture
def fake():
    with providers.override(FakeProvider()) as provider:
        yield provider


@pytest.fixture
def worker(django_capture_on_commit_callbacks):
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
