"""The studio's content endpoints (api/pages.py): sites, pages across sites,
creating and saving drafts, publishing, scheduling, and revisions with diff
and revert — each behind Wagtail's page permissions and locks, each failure
the envelope, and no draft ever reaching the live page."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from wagtail.models import GroupApprovalTask, GroupPagePermission, Page, Revision, Workflow, WorkflowTask

from agents.models import AgentToken
from cms.models import ArticlePage, Category, CollectionPage
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


def save(client, page, data):
    """A save from the page's latest revision, as the studio sends it."""
    base = Page.objects.get(pk=page.pk).latest_revision_id
    return patch(client, page.pk, {"base_revision_id": base, **data})


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
def test_a_page_without_a_revision_sorts_last_and_wagtails_placeholder_is_no_page(site_root, article, editor):
    unsaved = ArticlePage(title="Never saved", slug="never-saved", live=False)
    site_root.add_child(instance=unsaved)  # no revision: latest_revision_created_at is NULL
    client = signed_in(editor)
    for ordering in ("latest_revision_created_at", "-latest_revision_created_at"):
        listed = [p["id"] for p in client.get(PAGES, {"ordering": ordering}).json()["results"]]
        assert listed[-1] == unsaved.pk, ordering  # Postgres sorts NULLs first descending, SQLite ascending
    placeholder = Page.objects.get(depth=2, content_type=ContentType.objects.get_for_model(Page))
    assert placeholder.title == "Welcome to your new Wagtail site!"  # made by Wagtail's first migration
    assert placeholder.pk not in {p["id"] for p in client.get(PAGES, {"page_size": 100}).json()["results"]}
    assert client.get(f"{PAGES}{placeholder.pk}/").status_code == 404  # it has no body or fields to open


@pytest.mark.django_db
def test_the_studio_endpoints_are_for_signed_in_people_not_agents(article, editor):
    assert Client().get(PAGES).status_code == 401
    assert signed_in(person("stranger")).get(PAGES).json()["count"] == 0
    assert signed_in(person("stranger2")).get(f"{PAGES}{article.pk}/").status_code == 404
    _, raw = AgentToken.issue(get_user_model().objects.get(username="agent:seo"), name="t")
    refused = Client().get(PAGES, HTTP_AUTHORIZATION=f"Bearer {raw}")
    assert refused.status_code == 403 and "tool registry" in refused.json()["error"]["message"]


@pytest.mark.django_db
def test_a_page_a_person_may_only_pass_through_is_listed_but_never_opened(site_root, editor):
    sections = []
    for title in ("Posts", "Docs"):
        sections.append(CollectionPage(title=title, slug=title.lower(), collection=title.lower()))
        site_root.add_child(instance=sections[-1])
        sections[-1].save_revision(user=editor)
    section = sections[0]
    sectioned = person("sectioned", "add_page", "change_page", page=section)
    for codename in ("add_page", "change_page"):  # the same rights on the second section
        permission = Permission.objects.get(content_type__app_label="wagtailcore", codename=codename)
        GroupPagePermission.objects.create(group=sectioned.groups.get(), page=sections[1], permission=permission)
    root_draft = site_root.get_latest_revision_as_object()
    root_draft.body = [{"type": "markdown", "value": "EMBARGOED: launch on Friday"}]
    root_draft.save_revision(user=editor)
    writer = signed_in(sectioned)

    listed = {p["id"] for p in writer.get(PAGES).json()["results"]}
    assert {site_root.pk, *(s.pk for s in sections)} <= listed  # the way in, as Wagtail's explorer shows it
    for path in ("", "revisions/", f"revisions/compare/?a={site_root.latest_revision_id}&b=1"):
        refused = writer.get(f"{PAGES}{site_root.pk}/{path}")
        assert refused.status_code == 404 and "EMBARGOED" not in refused.content.decode(), path
    assert post(writer, f"{PAGES}{site_root.pk}/publish/").status_code == 404
    assert writer.get(f"{PAGES}{section.pk}/").json()["permissions"]["edit"] is True


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
    assert body["lock"] is None


@pytest.mark.django_db
def test_creatable_types_follow_the_tree_rules_and_permissions(site_root, article, editor):
    client = signed_in(editor)
    every = {t["type"]: t["label"] for t in client.get("/api/v2/content/types/").json()}
    assert every["cms.ArticlePage"] == "Article page" and "wagtailcore.Page" not in every
    under_site = {t["type"] for t in client.get(f"{PAGES}{site_root.pk}/types/").json()}
    assert under_site == {
        "cms.CollectionPage",
        "cms.ArticlePage",
        "cms.StandardPage",
        "cms.BookPage",
        "aieo.LandingPage",
    }
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
    bad_block = save(client, article, {"body": [{"type": "heading", "value": {"level": "9", "text": "x"}}]})
    assert bad_block.status_code == 422 and bad_block.json()["error"]["details"][0]["field"] == "body.0"
    bad_field = save(client, article, {"fields": {"legacy_path": "x.md", "date": "not a date"}})
    assert {d["field"] for d in bad_field.json()["error"]["details"]} == {"legacy_path", "date"}


@pytest.mark.django_db
def test_a_save_names_its_base_revision_and_takes_the_page_row_lock(article, editor):
    client = signed_in(editor)
    unnamed = patch(client, article.pk, {"fields": {"title": "Who edited what?"}})
    assert unnamed.status_code == 422 and unnamed.json()["error"]["details"][0]["field"] == "base_revision_id"
    with CaptureQueriesContext(connection) as queries:
        assert save(client, article, {"fields": {"title": "Named"}}).status_code == 200
    if connection.features.has_select_for_update:  # Postgres in CI; SQLite locks the whole database instead
        assert any("FOR UPDATE" in q["sql"] for q in queries.captured_queries)
    assert ArticlePage.objects.get(pk=article.pk).get_latest_revision_as_object().title == "Named"


@pytest.mark.django_db
def test_a_body_with_a_block_id_twice_is_refused(article, editor):
    client = signed_in(editor)
    heading, markdown = client.get(f"{PAGES}{article.pk}/").json()["body"]
    twice = save(client, article, {"body": [heading, {**markdown, "id": heading["id"]}]})
    assert twice.status_code == 422 and twice.json()["error"]["details"][0]["field"] == "body.1"
    new_ones = save(client, article, {"body": [{"type": "markdown", "value": "a"}, {"type": "markdown", "value": "b"}]})
    assert new_ones.status_code == 200 and len({b["id"] for b in new_ones.json()["body"]}) == 2


@pytest.mark.django_db
def test_a_changed_paragraph_keeps_its_internal_links(site_root, article, editor):
    target = make_article(site_root, "The docs")
    stored = (
        f'<p>See <a linktype="page" id="{target.pk}">the docs</a>, <a href="https://example.com">the site</a>'
        ' and <a href="mailto:ops@example.com">ops</a>, <b>bold</b> and <i>slanted</i>.</p>'
    )
    page = make_article(site_root, "Linked", body=[{"type": "paragraph", "value": stored}])
    client = signed_in(editor)
    block = client.get(f"{PAGES}{page.pk}/").json()["body"][0]
    assert block["value"] == stored  # the API speaks Wagtail's database format
    edited = block["value"].replace("bold", "bolder")
    assert save(client, page, {"body": [{**block, "value": edited}]}).status_code == 200
    kept = ArticlePage.objects.get(pk=page.pk).get_latest_revision_as_object().body[0]
    raw = kept.block.get_prep_value(kept.value)
    assert f'id="{target.pk}"' in raw and 'linktype="page"' in raw and "<b>bolder</b>" in raw
    assert 'href="https://example.com"' in raw and 'href="mailto:ops@example.com"' in raw
    script = save(client, page, {"body": [{**block, "value": '<p onclick="x()">Hi<script>alert(1)</script></p>'}]})
    assert script.status_code == 200 and script.json()["body"][0]["value"] == "<p>Hialert(1)</p>"  # still whitelisted


@pytest.mark.django_db
def test_saving_needs_the_csrf_token_and_edit_rights(article, editor):
    client = Client(enforce_csrf_checks=True)
    client.force_login(editor)
    client.get("/api/v2/me")
    refused = patch(client, article.pk, {"fields": {"title": "x"}})
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "auth.csrf_failed"
    token = client.cookies["csrftoken"].value
    ok = client.patch(
        f"{PAGES}{article.pk}/",
        {"base_revision_id": article.latest_revision_id, "fields": {"title": "y"}},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert ok.status_code == 200
    writer = person("writer", "add_page")  # may create pages, and edit only their own
    assert save(signed_in(writer), article, {"fields": {"title": "z"}}).status_code == 404  # not theirs to open
    publisher = person("publisher", "publish_page")  # may open it to publish, not edit it
    assert save(signed_in(publisher), article, {"fields": {"title": "z"}}).status_code == 403


def comes_due(page, field):
    """Move a scheduled time on `page` into the past, as the clock would: in
    the revisions that carry it and, for an expiry, on the live page."""
    past = timezone.now() - timedelta(minutes=1)
    for revision in Revision.page_revisions.filter(object_id=str(page.pk)):
        if revision.content.get(field):
            revision.content[field] = past.isoformat()
            revision.approved_go_live_at = past if revision.approved_go_live_at else None
            revision.save(update_fields=["content", "approved_go_live_at"])
    if field == "expire_at":
        Page.objects.filter(pk=page.pk).update(expire_at=past)


@pytest.mark.django_db
def test_publish_and_unpublish_now_or_on_a_schedule(draft, editor):
    client = signed_in(editor)
    live = lambda: ArticlePage.objects.get(pk=draft.pk).live  # noqa: E731

    published = post(client, f"{PAGES}{draft.pk}/publish/").json()
    assert published["status"] == "live" and live()
    down = post(client, f"{PAGES}{draft.pk}/unpublish/").json()
    assert down["status"] == "draft" and not live()

    soon, later = timezone.now() + timedelta(hours=2), timezone.now() + timedelta(days=2)
    both = {"go_live_at": soon.isoformat(), "expire_at": later.isoformat()}
    scheduled = post(client, f"{PAGES}{draft.pk}/schedule/", both).json()
    assert scheduled["status"] == "scheduled" and not live() and listing_status(client, draft.pk, "scheduled")
    revision = Revision.page_revisions.get(object_id=str(draft.pk), approved_go_live_at__isnull=False)
    assert abs(revision.approved_go_live_at - soon) < timedelta(seconds=1)
    comes_due(draft, "go_live_at")
    publish_scheduled()  # beat, a minute later
    page = ArticlePage.objects.get(pk=draft.pk)
    assert page.live and abs(page.expire_at - later) < timedelta(seconds=1)
    comes_due(draft, "expire_at")
    publish_scheduled()
    page = ArticlePage.objects.get(pk=draft.pk)
    assert not page.live and page.expired and listing_status(client, draft.pk, "expired")

    again = post(client, f"{PAGES}{draft.pk}/publish/").json()  # a past expiry is cleared, or the page would drop again
    assert again["status"] == "live" and again["expire_at"] is None
    publish_scheduled()
    assert live()
    take_down = post(client, f"{PAGES}{draft.pk}/schedule/", {"expire_at": later.isoformat()}).json()
    assert take_down["status"] == "live" and take_down["expire_at"]  # a live page, to come down at `later`


@pytest.mark.django_db
def test_who_may_publish_and_what_a_schedule_must_say(draft, editor):
    writer = person("writer", "add_page", "change_page")
    assert post(signed_in(writer), f"{PAGES}{draft.pk}/publish/").status_code == 403
    assert post(signed_in(writer), f"{PAGES}{draft.pk}/unpublish/").status_code == 403
    client = signed_in(editor)
    schedule = f"{PAGES}{draft.pk}/schedule/"
    past = post(client, schedule, {"go_live_at": (timezone.now() - timedelta(1)).isoformat()})
    assert past.status_code == 422 and past.json()["error"]["details"][0]["field"] == "go_live_at"
    assert post(client, schedule, {}).status_code == 422
    soon = timezone.now() + timedelta(hours=1)
    inverted = post(client, schedule, {"go_live_at": soon.isoformat(), "expire_at": soon.isoformat()})
    assert inverted.status_code == 422 and inverted.json()["error"]["details"][0]["field"] == "expire_at"


@pytest.mark.django_db
def test_a_scheduled_page_is_locked_until_the_schedule_is_cancelled(draft, editor):
    client = signed_in(editor)
    post(client, f"{PAGES}{draft.pk}/schedule/", {"go_live_at": (timezone.now() + timedelta(days=1)).isoformat()})
    detail = client.get(f"{PAGES}{draft.pk}/").json()
    assert detail["status"] == "scheduled" and "scheduled to go live" in detail["lock"]
    for refused in (save(client, draft, {"fields": {"title": "x"}}), post(client, f"{PAGES}{draft.pk}/publish/")):
        assert refused.status_code == 409 and refused.json()["error"]["code"] == "resource.locked"
    cancelled = post(client, f"{PAGES}{draft.pk}/unschedule/").json()
    assert cancelled["status"] == "draft" and cancelled["lock"] is None
    assert save(client, draft, {"fields": {"title": "Now editable"}}).status_code == 200


@pytest.mark.django_db
def test_publish_now_clears_a_future_go_live_on_the_latest_revision(draft, editor):
    later = draft.get_latest_revision_as_object()
    later.go_live_at = timezone.now() + timedelta(days=1)
    later.save_revision(user=editor)  # a draft that names a go-live time but was never scheduled
    now = post(signed_in(editor), f"{PAGES}{draft.pk}/publish/").json()
    assert now["status"] == "live" and now["go_live_at"] is None


@pytest.mark.django_db
def test_another_persons_lock_refuses_every_write(article, editor):
    other = person("other", "change_page", "publish_page", "lock_page")
    Page.objects.filter(pk=article.pk).update(locked=True, locked_by=other, locked_at=timezone.now())
    client = signed_in(editor)
    detail = client.get(f"{PAGES}{article.pk}/").json()
    assert "locked" in detail["lock"] and detail["permissions"]["edit"] is True
    first = Page.objects.get(pk=article.pk).latest_revision_id
    for refused in (
        save(client, article, {"fields": {"title": "Mine now"}}),
        post(client, f"{PAGES}{article.pk}/publish/"),
        post(client, f"{PAGES}{article.pk}/unpublish/"),
        post(client, f"{PAGES}{article.pk}/schedule/", {"go_live_at": (timezone.now() + timedelta(1)).isoformat()}),
        post(client, f"{PAGES}{article.pk}/revisions/{first}/revert/"),
    ):
        assert refused.status_code == 409 and refused.json()["error"]["code"] == "resource.locked"
    assert ArticlePage.objects.get(pk=article.pk).title == "Nightly backups"
    assert save(signed_in(other), article, {"fields": {"title": "The holder may"}}).status_code == 200


@pytest.mark.django_db
def test_a_page_in_moderation_is_locked_to_people_outside_the_task(draft, editor):
    reviewers = Group.objects.create(name="Reviewers")
    task = GroupApprovalTask.objects.create(name="Approve")
    task.groups.set([reviewers])
    workflow = Workflow.objects.create(name="Editorial")
    WorkflowTask.objects.create(workflow=workflow, task=task, sort_order=0)
    workflow.start(draft, editor)
    refused = save(signed_in(editor), draft, {"fields": {"title": "Around the review"}})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "resource.locked"
    assert "awaiting moderation" in signed_in(editor).get(f"{PAGES}{draft.pk}/").json()["lock"]


def listing_status(client, pk, status):
    return pk in {p["id"] for p in client.get(PAGES, {"status": status}).json()["results"]}


@pytest.mark.django_db
def test_revisions_compare_and_revert_as_a_new_draft(article, editor):
    client = signed_in(editor)
    first = client.get(f"{PAGES}{article.pk}/").json()["latest_revision"]["id"]
    save(client, article, {"fields": {"title": "Second title"}})
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
