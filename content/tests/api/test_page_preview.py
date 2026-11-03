"""A page's preview through the studio's API: its latest revision as the very
file a write-back writes — the path the exporter gives it and its text byte for
byte, marked not built while the page is not live — beside the file at that
path as the platform last read or wrote it, and its body as HTML held to what
the Markdown renders. It needs what opening the page needs, a person's token
reaches it with no session, and a page with no file of its own (a site's root,
a collection) has no preview."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from django.test import Client
from wagtail.models import Page

from accounts import services
from cms.models import ArticlePage, CollectionPage, SiteRootPage
from exporters.jekyll import path_for
from tests.api.test_pages import PAGES, person, save, signed_in
from tests.sites.test_sites import HELLO, admin, api, checkout, page_at, registered, start  # noqa: F401 — fixtures

pytestmark = pytest.mark.django_db


@pytest.fixture
def site(admin, api, registered, checkout, django_capture_on_commit_callbacks):  # noqa: F811 — the shared fixtures
    """The fixture site registered from a checkout, and its superuser in a session (`client`) and by `api`."""

    def write_back_with_drafts():
        job = start(
            api, registered["site"]["id"], "export", django_capture_on_commit_callbacks, {"include_drafts": True}
        )
        assert job.status == "succeeded", job.error

    return SimpleNamespace(admin=admin, client=signed_in(admin), checkout=checkout, write_back=write_back_with_drafts)


def preview(client, page):
    return client.get(f"{PAGES}{page.pk}/preview/")


def fixture_root():
    return SiteRootPage.objects.get(site_key="fixture")


def fixture_posts():
    return CollectionPage.objects.get(collection="posts", path__startswith=Page.objects.get(slug="fixture").path)


def test_the_preview_is_the_file_a_write_back_writes(site):
    hello = page_at(HELLO)
    indexed = (site.checkout / HELLO).read_text()
    assert save(site.client, hello, {"fields": {"title": "Hello, nightly backups"}}).status_code == 200  # a draft

    shown = preview(site.client, hello)
    assert shown.status_code == 200, shown.content
    data = shown.json()
    assert data["path"] == HELLO == path_for(page_at(HELLO).get_latest_revision_as_object(), fixture_root())
    assert data["indexed"] == indexed  # the file there as the platform last read it, to diff against
    assert 'title: "Hello, nightly backups"\n' in data["text"] and data["text"] != indexed
    assert "published: false" not in data["text"]  # the page is live: its file is built

    site.write_back()
    assert (site.checkout / HELLO).read_text() == data["text"]  # byte for byte what the write-back wrote
    again = preview(site.client, hello).json()
    assert again["text"] == again["indexed"] == data["text"]  # and now the index has it: nothing to write


def test_a_draft_never_published_previews_as_the_new_file_marked_not_built(site):
    page = ArticlePage(title="A draft", slug="a-draft", date=datetime(2026, 9, 2, tzinfo=UTC), body=[], live=False)
    fixture_posts().add_child(instance=page)
    page.save_revision()

    data = preview(site.client, page).json()
    rel = "pages/_posts/2026-09-02-a-draft.md"
    assert data["path"] == rel and data["indexed"] is None  # a write-back would create it
    assert data["text"].startswith("---\ntitle: A draft\ndate: 2026-09-02 00:00:00 +0000\npublished: false\n---\n")
    site.write_back()
    assert (site.checkout / rel).read_text() == data["text"]


def test_the_html_is_the_body_held_to_what_the_markdown_renders(site):
    hello = page_at(HELLO)
    body = [
        {"type": "markdown", "value": "## Restores\n\nCopy it [nightly](https://example.com/n) and *test* it."},
        {"type": "raw_html", "value": '<script>alert(1)</script><a href="javascript:alert(2)">click</a>'},
    ]
    assert save(site.client, hello, {"body": body}).status_code == 200
    html = preview(site.client, hello).json()["html"]
    assert "<h2>Restores</h2>" in html and '<a href="https://example.com/n">nightly</a>' in html
    assert "<em>test</em>" in html
    assert "title:" not in html  # the front matter is the file's, not the page's text
    assert "<script" not in html and "javascript:" not in html  # raw HTML is unwrapped to its text, a bad link dropped


def test_a_page_with_no_file_of_its_own_has_no_preview(site):
    for page in (fixture_root(), fixture_posts()):
        answer = preview(site.client, page)
        assert answer.status_code == 404, page
        assert answer.json()["error"]["code"] == "resource.not_found"
        assert "no file of its own" in answer.json()["error"]["message"]


def test_the_preview_needs_what_opening_the_page_needs_and_no_session(site):
    hello = page_at(HELLO)
    assert preview(signed_in(person("reader")), hello).status_code == 404  # finds nothing it may edit or publish
    agent = person("agent:previewer")
    assert preview(signed_in(agent), hello).status_code == 403  # an agent reads through the tool registry
    _, raw = services.issue(site.admin, name="VS Code", superuser=True)  # the extension's token, and no session
    by_token = Client().get(f"{PAGES}{hello.pk}/preview/", HTTP_AUTHORIZATION=f"Bearer {raw}")
    assert by_token.status_code == 200 and by_token.json()["path"] == HELLO
