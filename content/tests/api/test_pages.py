"""The studio's content endpoints (api/pages.py): sites, pages across sites,
creating and saving drafts, publishing, scheduling, and revisions with diff
and revert — each behind Wagtail's page permissions, each failure the
envelope, and no draft ever reaching the live page."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client
from django.utils import timezone
from wagtail.models import GroupPagePermission, Page, Revision

from agents.models import AgentToken
from cms.models import ArticlePage, Category
from cms.tasks import publish_scheduled
from tests.conftest import make_article

PAGES = "/api/v2/content/pages/"


def signed_in(user):
    client = Client()
    client.force_login(user)
    return client


def person(username, *codenames, page=None):
    """A person with the given page permissions on `page` (default: the tree root)."""
    user = get_user_model().objects.create_user(username, password="pw")
    if codenames:
        group = Group.objects.create(name=f"{username} group")
        for codename in codenames:
            GroupPagePermission.objects.create(
                group=group,
                page=page or Page.get_first_root_node(),
                permission=Permission.objects.get(content_type__app_label="wagtailcore", codename=codename),
            )
        user.groups.add(group)
    return user


def patch(client, pk, data):
    return client.patch(f"{PAGES}{pk}/", data, content_type="application/json")


def post(client, path, data=None):
    return client.post(path, data or {}, content_type="application/json")


@pytest.fixture
def draft(site_root):
    return make_article(site_root, "A draft", body=[{"type": "markdown", "value": "Not yet."}], publish=False)


@pytest.mark.django_db
def test_sites_lists_the_sites_a_person_can_work_in(site_root, editor):
    found = signed_in(editor).get("/api/v2/sites/").json()
    assert [s["root_page_id"] for s in found] == [site_root.pk]
    assert signed_in(person("stranger")).get("/api/v2/sites/").json() == []


@pytest.mark.django_db
def test_the_page_list_spans_every_status_and_filters(site_root, article, draft, editor):
    client = signed_in(editor)
    listing = client.get(PAGES).json()
    ids = {p["id"]: p for p in listing["results"]}
    assert {site_root.pk, article.pk, draft.pk} <= set(ids) and listing["count"] == len(ids)
    assert ids[draft.pk]["status"] == "draft" and ids[article.pk]["status"] == "live"
    assert ids[site_root.pk]["children"] == 2 and ids[article.pk]["children"] == 0
    assert [p["id"] for p in client.get(PAGES, {"status": "draft"}).json()["results"]] == [draft.pk]
    typed = client.get(PAGES, {"type": "cms.ArticlePage"}).json()["results"]
    assert {p["id"] for p in typed} == {article.pk, draft.pk} and typed[0]["type"] == "cms.ArticlePage"
    assert [p["id"] for p in client.get(PAGES, {"q": "nightly"}).json()["results"]] == [article.pk]
    assert {p["id"] for p in client.get(PAGES, {"parent": site_root.pk}).json()["results"]} == {article.pk, draft.pk}
    assert [p["id"] for p in client.get(PAGES, {"can_have_children": "true"}).json()["results"]] == [site_root.pk]
    paged = client.get(PAGES, {"page_size": 1, "ordering": "title"}).json()
    assert len(paged["results"]) == 1 and paged["next"] and paged["count"] == len(ids)
    bad = client.get(PAGES, {"status": "lost"})
    assert bad.status_code == 422 and bad.json()["error"]["details"][0]["field"] == "status"


@pytest.mark.django_db
def test_the_studio_endpoints_are_for_signed_in_people_not_agents(article, editor):
    assert Client().get(PAGES).status_code == 401
    assert signed_in(person("stranger")).get(PAGES).json()["count"] == 0
    assert signed_in(person("stranger2")).get(f"{PAGES}{article.pk}/").status_code == 404
    _, raw = AgentToken.issue(get_user_model().objects.get(username="agent:seo"), name="t")
    refused = Client().get(PAGES, HTTP_AUTHORIZATION=f"Bearer {raw}")
    assert refused.status_code == 403 and "tool registry" in refused.json()["error"]["message"]


@pytest.mark.django_db
def test_page_detail_has_fields_blocks_markdown_and_what_the_person_may_do(article, editor):
    category = Category.objects.create(name="Ops", slug="ops")
    body = signed_in(editor).get(f"{PAGES}{article.pk}/").json()
    assert body["title"] == "Nightly backups" and body["type"] == "cms.ArticlePage" and body["status"] == "live"
    assert [b["type"] for b in body["body"]] == ["heading", "markdown"] and all(b["id"] for b in body["body"])
    assert body["markdown"] == "## How it works\n\nWe copy the site to a second disk every night.\n"
    assert body["fields"]["title"] == "Nightly backups" and body["fields"]["tags"] == []
    specs = {s["name"]: s for s in body["field_specs"]}
    assert specs["date"]["kind"] == "datetime" and specs["search_description"]["group"] == "seo"
    assert specs["agent_policy"]["kind"] == "choice" and specs["agent_policy"]["group"] == "settings"
    assert specs["categories"]["choices"] == [{"value": str(category.pk), "label": "Ops"}]
    perms = body["permissions"]
    assert (perms["edit"], perms["publish"], perms["unpublish"], perms["add_subpage"]) == (True, True, True, False)
    assert body["latest_revision"]["id"] == body["live_revision_id"] and body["preview_url"].endswith("/view_draft/")


@pytest.mark.django_db
def test_creatable_types_follow_the_tree_rules_and_permissions(site_root, article, editor):
    client = signed_in(editor)
    every = {t["type"]: t["label"] for t in client.get("/api/v2/content/types/").json()}
    assert every["cms.ArticlePage"] == "Article page" and "wagtailcore.Page" not in every
    under_site = {t["type"] for t in client.get(f"{PAGES}{site_root.pk}/types/").json()}
    assert under_site == {"cms.CollectionPage", "cms.ArticlePage", "cms.StandardPage", "cms.BookPage"}
    assert client.get(f"{PAGES}{article.pk}/types/").json() == []
    reader = person("reader", "change_page")
    assert signed_in(reader).get(f"{PAGES}{site_root.pk}/types/").json() == []


@pytest.mark.django_db
def test_creating_a_page_makes_one_draft_revision_and_publishes_nothing(site_root, editor):
    client = signed_in(editor)
    created = post(
        client,
        PAGES,
        {
            "parent": site_root.pk,
            "type": "cms.ArticlePage",
            "fields": {"title": "Fresh idea", "author": "Ed", "tags": ["ideas"]},
            "body": [{"type": "brief", "value": {"topic": "Why backups matter", "audience": "", "notes": ""}}],
        },
    )
    assert created.status_code == 201, created.json()
    page = created.json()
    assert page["status"] == "draft" and page["slug"] == "fresh-idea" and page["fields"]["tags"] == ["ideas"]
    assert page["body"][0]["type"] == "brief" and page["parent"]["id"] == site_root.pk
    stored = ArticlePage.objects.get(pk=page["id"])
    assert not stored.live and stored.owner == editor
    assert Revision.page_revisions.filter(object_id=str(stored.pk)).count() == 1

    nested = post(client, PAGES, {"parent": page["id"], "type": "cms.ArticlePage", "fields": {"title": "No"}})
    assert nested.status_code == 403
    unknown = post(client, PAGES, {"parent": site_root.pk, "type": "cms.Nope", "fields": {"title": "x"}})
    assert unknown.status_code == 422
    nameless = post(client, PAGES, {"parent": site_root.pk, "type": "cms.ArticlePage", "fields": {"title": ""}})
    assert nameless.status_code == 422 and nameless.json()["error"]["details"][0]["field"] == "title"


@pytest.mark.django_db
def test_saving_a_draft_never_touches_the_live_page(article, editor):
    client = signed_in(editor)
    loaded = client.get(f"{PAGES}{article.pk}/").json()
    heading, markdown = loaded["body"]
    saved = patch(
        client,
        article.pk,
        {
            "base_revision_id": loaded["latest_revision"]["id"],
            "fields": {"title": "Nightly backups, revised", "tags": ["ops"], "seo_title": "Backups"},
            "body": [
                heading,
                {**markdown, "value": "We copy the site twice a night."},
                {"type": "markdown", "value": "New."},
            ],
        },
    )
    assert saved.status_code == 200, saved.json()
    body = saved.json()
    assert body["status"] == "changed" and body["title"] == "Nightly backups, revised"
    assert [b["id"] for b in body["body"][:2]] == [heading["id"], markdown["id"]] and body["body"][2]["id"]
    assert body["fields"]["tags"] == ["ops"] and body["fields"]["seo_title"] == "Backups"
    live = ArticlePage.objects.get(pk=article.pk)
    assert live.title == "Nightly backups" and live.has_unpublished_changes
    assert [t.name for t in live.tags.all()] == [] and live.body[1].value.startswith("We copy the site to")

    stale = patch(client, article.pk, {"base_revision_id": loaded["latest_revision"]["id"], "fields": {"title": "x"}})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "resource.conflict"
    bad_block = patch(client, article.pk, {"body": [{"type": "heading", "value": {"level": "9", "text": "x"}}]})
    assert bad_block.status_code == 422 and bad_block.json()["error"]["details"][0]["field"] == "body.0"
    bad_field = patch(client, article.pk, {"fields": {"legacy_path": "x.md", "date": "not a date"}})
    assert {d["field"] for d in bad_field.json()["error"]["details"]} == {"legacy_path", "date"}


@pytest.mark.django_db
def test_saving_needs_the_csrf_token_and_edit_rights(article, editor):
    client = Client(enforce_csrf_checks=True)
    client.force_login(editor)
    client.get("/api/v2/me")
    refused = patch(client, article.pk, {"fields": {"title": "x"}})
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "auth.csrf_failed"
    token = client.cookies["csrftoken"].value
    ok = client.patch(
        f"{PAGES}{article.pk}/", {"fields": {"title": "y"}}, content_type="application/json", HTTP_X_CSRFTOKEN=token
    )
    assert ok.status_code == 200
    writer = person("writer", "add_page")  # may create pages, and edit only their own
    assert patch(signed_in(writer), article.pk, {"fields": {"title": "z"}}).status_code == 403


@pytest.mark.django_db
def test_publish_unpublish_and_who_may(draft, editor):
    writer = person("writer", "add_page", "change_page")
    assert post(signed_in(writer), f"{PAGES}{draft.pk}/publish/").status_code == 403
    client = signed_in(editor)
    published = post(client, f"{PAGES}{draft.pk}/publish/").json()
    assert published["status"] == "live" and ArticlePage.objects.get(pk=draft.pk).live
    down = post(client, f"{PAGES}{draft.pk}/unpublish/").json()
    assert down["status"] == "draft" and not ArticlePage.objects.get(pk=draft.pk).live


@pytest.mark.django_db
def test_schedule_sets_go_live_at_and_beat_publishes_when_it_is_due(draft, editor):
    client = signed_in(editor)
    soon = timezone.now() + timedelta(hours=2)
    scheduled = post(client, f"{PAGES}{draft.pk}/schedule/", {"go_live_at": soon.isoformat()}).json()
    assert scheduled["status"] == "scheduled" and not ArticlePage.objects.get(pk=draft.pk).live
    revision = Revision.page_revisions.get(object_id=str(draft.pk), approved_go_live_at__isnull=False)
    assert abs(revision.approved_go_live_at - soon) < timedelta(seconds=1)
    assert listing_status(client, draft.pk, "scheduled")

    past = post(client, f"{PAGES}{draft.pk}/schedule/", {"go_live_at": (timezone.now() - timedelta(1)).isoformat()})
    assert past.status_code == 422

    due = timezone.now() - timedelta(minutes=1)  # the clock reaches go_live_at
    revision.content["go_live_at"] = due.isoformat()
    revision.approved_go_live_at = due
    revision.save(update_fields=["content", "approved_go_live_at"])
    publish_scheduled()
    assert ArticlePage.objects.get(pk=draft.pk).live


@pytest.mark.django_db
def test_unschedule_cancels_and_publish_now_clears_a_future_go_live(draft, editor):
    client = signed_in(editor)
    post(client, f"{PAGES}{draft.pk}/schedule/", {"go_live_at": (timezone.now() + timedelta(days=1)).isoformat()})
    assert post(client, f"{PAGES}{draft.pk}/unschedule/").json()["status"] == "draft"
    post(client, f"{PAGES}{draft.pk}/schedule/", {"go_live_at": (timezone.now() + timedelta(days=1)).isoformat()})
    now = post(client, f"{PAGES}{draft.pk}/publish/").json()
    assert now["status"] == "live" and now["go_live_at"] is None


def listing_status(client, pk, status):
    return pk in {p["id"] for p in client.get(PAGES, {"status": status}).json()["results"]}


@pytest.mark.django_db
def test_revisions_compare_and_revert_as_a_new_draft(article, editor):
    client = signed_in(editor)
    first = client.get(f"{PAGES}{article.pk}/").json()["latest_revision"]["id"]
    patch(client, article.pk, {"fields": {"title": "Second title"}})
    revisions = client.get(f"{PAGES}{article.pk}/revisions/").json()
    assert revisions["count"] == 2 and revisions["results"][0]["is_latest"] and revisions["results"][1]["is_live"]
    second = revisions["results"][0]["id"]

    diff = client.get(f"{PAGES}{article.pk}/revisions/compare/", {"a": first, "b": second}).json()
    assert diff["changed"] == ["title"] and diff["a"]["fields"]["title"] == "Nightly backups"
    assert diff["b"]["fields"]["title"] == "Second title" and diff["a"]["markdown"] == diff["b"]["markdown"]
    assert client.get(f"{PAGES}{article.pk}/revisions/compare/", {"a": first, "b": 999999}).status_code == 404

    reverted = post(client, f"{PAGES}{article.pk}/revisions/{first}/revert/").json()
    assert reverted["title"] == "Nightly backups" and reverted["status"] == "changed"
    assert client.get(f"{PAGES}{article.pk}/revisions/").json()["count"] == 3
    assert reverted["latest_revision"]["id"] not in (first, second)
    assert ArticlePage.objects.get(pk=article.pk).live_revision_id == first  # a revert is a draft, never a publish
