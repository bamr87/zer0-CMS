"""The platform's distribution (`distribution/` models, services, API, tools
and the published-page consumer): channels with encrypted, write-only
credentials and LinkedIn's OAuth with state and PKCE; the queue's compose →
brand guard → approve → publish, every gate checked by the server and again by
the worker; the ledger keyed by canonical URL — the same key a site's own lane
computes — and written byte-compatible with the extension's; statistics; the
registry's tools and the consumer that drafts (never publishes).

Every LinkedIn request is recorded HTTP (respx); the worker runs what a
request queued after it commits (`worker`).
"""

import io
import json
import shutil
from datetime import timedelta

import httpx
import pytest
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.utils import timezone
from wagtail.models import GroupPagePermission, Page

from agents.models import AgentDefinition, AgentRun
from agents.registry import ToolContext, ToolError, registry
from distribution import services
from distribution.lane.pipeline import Pipeline
from distribution.lane.site import Config
from distribution.ledger import Ledger, entry_for, serialize
from distribution.models import Channel, DistributionPost, LedgerEntry, Statistic
from ops.errors import Conflict
from outbox.consumers import handle_envelope
from outbox.models import OutboxEvent

from ..conftest import make_article
from .conftest import AUTHOR, FIXTURE, MCP_POST, MCP_URL, TOKEN

REST = "https://api.linkedin.com/rest"
API = "/api/v2/distribution"
LINKEDIN_APP = {"LINKEDIN_CLIENT_ID": "cid", "LINKEDIN_CLIENT_SECRET": "csecret-abcdef"}


def grant(user, group_name: str, *codenames):
    """Page rights on every page, through a group of their own."""
    group, _ = Group.objects.get_or_create(name=group_name)
    for codename in codenames:
        GroupPagePermission.objects.get_or_create(
            group=group,
            page=Page.get_first_root_node(),
            permission=Permission.objects.get(content_type__app_label="wagtailcore", codename=codename),
        )
    user.groups.add(group)
    return get_user_model().objects.get(pk=user.pk)


@pytest.fixture
def carol(db):
    """Edits every page and may publish none: she may change a post's text, never approve it."""
    user = get_user_model().objects.create_user("carol", password="pw")
    return grant(user, "editors who do not publish", "add_page", "change_page")


def imported(tmp_path, settings, *, at=None):
    """The fixture site copied to `at` (default: inside the repository, REPO_ROOT = tmp_path) and imported."""
    from importers.jekyll import import_site

    settings.REPO_ROOT, settings.SITES_DIR = tmp_path, ""
    at = at or tmp_path / "site"
    shutil.copytree(FIXTURE, at)
    import_site(at, "fixture", repo_root=tmp_path)
    return at, {p.legacy_path: p for p in Page.objects.specific() if getattr(p, "legacy_path", "")}


@pytest.fixture
def manager(alice):
    """alice, who edits and publishes every page, and also manages channels."""
    alice.user_permissions.add(
        *Permission.objects.filter(content_type__app_label="distribution", codename__endswith="_channel")
    )
    return get_user_model().objects.get(pk=alice.pk)


@pytest.fixture
def article(site_root):
    """A live page with a description (a LinkedIn card needs one) and tags (the default commentary's hashtags)."""
    page = make_article(
        site_root,
        "Nightly backups",
        search_description="Why we copy the site every night.",
        body=[{"type": "markdown", "value": "We copy the site to a second disk every night."}],
    )
    page.tags.add("backups", "ops")
    page.save_revision().publish()
    return page.specific


@pytest.fixture
def channel(article):
    found = Channel.objects.create(
        site=article.get_site(), kind="linkedin", name="The page", settings={"author": AUTHOR}, armed=True
    )
    found.set_credentials({"access_token": TOKEN})
    found.save()
    return found


def approved(post, user):
    return services.approve(post, user)


# ── channels and their credentials ──────────────────────────────────────────


def test_a_credential_is_encrypted_write_only_and_forgotten_when_the_channel_points_elsewhere(api, manager, article):
    site = article.get_site().pk
    made = api(manager).post(
        f"{API}/channels/",
        {
            "site": site,
            "kind": "wordpress",
            "name": "Blog",
            "settings": {"url": "https://blog.example.com", "username": "ed"},
            "credentials": {"application_password": "abcd efgh ijkl mnop"},
        },
        format="json",
    )
    assert made.status_code == 201, made.content
    assert "credentials" not in made.json() and made.json()["has_credential"] is True
    assert made.json()["secret_fields"] == ["application_password"]
    row = Channel.objects.get(public_id=made.json()["id"])
    assert "abcd efgh" not in row.credential_encrypted and row.credentials() == {
        "application_password": "abcd efgh ijkl mnop"
    }
    assert "abcd efgh" not in api(manager).get(f"{API}/channels/{row.public_id}/").content.decode()
    moved = api(manager).patch(
        f"{API}/channels/{row.public_id}/",
        {"settings": {"url": "https://other.example.com", "username": "ed"}},
        format="json",
    )
    assert moved.status_code == 200 and moved.json()["has_credential"] is False, (
        "a channel that points elsewhere forgets"
    )
    wrong = api(manager).post(
        f"{API}/channels/", {"site": site, "kind": "github_pr", "name": "x", "settings": {"author": "y"}}, format="json"
    )
    assert wrong.status_code == 422


def test_rotating_the_ai_keys_carries_every_channels_credential(channel):
    """A channel's credential is under the AI layer's keys: the one command that rotates them rotates it too, and
    one no key can read stops the rotation, named."""
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    with override_settings(AI_CREDENTIAL_KEYS=[old]):
        channel.set_credentials({"access_token": "under-the-old-key"})
        channel.set_pending({"code": "c", "verifier": "v", "redirect_uri": "http://127.0.0.1/"})
        channel.save()
    out = io.StringIO()
    with override_settings(AI_CREDENTIAL_KEYS=[new, old]):
        call_command("rotate_ai_credentials", stdout=out)
    assert "1 credential(s) re-encrypted" in out.getvalue()
    with override_settings(AI_CREDENTIAL_KEYS=[new], SECRET_KEY="another-secret"):
        rotated = Channel.objects.get(pk=channel.pk)
        assert rotated.credentials() == {"access_token": "under-the-old-key"} and rotated.pending()["code"] == "c"
    with override_settings(AI_CREDENTIAL_KEYS=[old], SECRET_KEY="another-secret"):
        with pytest.raises(CommandError, match="the channel 'The page'"):
            call_command("rotate_ai_credentials", stdout=io.StringIO())


def test_only_people_who_manage_channels_set_them_up_and_everyone_on_the_site_sees_them(api, alice, bob, channel):
    assert (
        api(alice)
        .post(f"{API}/channels/", {"site": channel.site_id, "kind": "linkedin", "name": "x"}, format="json")
        .status_code
        == 403
    )
    assert [c["id"] for c in api(alice).get(f"{API}/channels/").json()["results"]] == [str(channel.public_id)]
    assert api(bob).get(f"{API}/channels/").json()["results"] == [], "bob edits no site"
    assert api(bob).get(f"{API}/channels/{channel.public_id}/").status_code == 404
    assert api(alice).patch(f"{API}/channels/{channel.public_id}/", {"armed": False}, format="json").status_code == 403


@override_settings(**LINKEDIN_APP)
def test_connecting_linkedin_is_state_and_pkce_one_use_and_the_code_is_exchanged_on_the_worker(
    api, manager, channel, web, worker
):
    from urllib.parse import parse_qsl, urlsplit

    client = api(manager)
    started = client.post(f"{API}/channels/{channel.public_id}/connect/")
    assert started.status_code == 200
    query = dict(parse_qsl(urlsplit(started.json()["url"]).query))
    assert (
        query["client_id"] == "cid"
        and query["code_challenge_method"] == "S256"
        and "csecret" not in started.json()["url"]
    )
    assert query["redirect_uri"] == "http://testserver/api/v2/distribution/oauth/linkedin/"
    assert query["scope"] == "w_organization_social r_organization_social rw_organization_admin"
    assert client.get(f"{API}/oauth/linkedin/", {"state": "forged", "code": "C"}).status_code == 403
    token = web.post("https://www.linkedin.com/oauth/v2/accessToken").respond(
        200,
        json={
            "access_token": "AT-secret-token-value",
            "expires_in": 5184000,
            "scope": "w_organization_social,r_organization_social",
        },
    )
    channel.forget_credentials()
    channel.save()
    back = worker(client.get, f"{API}/oauth/linkedin/", {"state": query["state"], "code": "C"})
    assert (
        back.status_code == 302
        and back["Location"] == f"/studio/distribution/channels/{channel.public_id}?connecting=1"
    )
    form = dict(parse_qsl(token.calls.last.request.content.decode()))
    assert form["code"] == "C" and len(form["code_verifier"]) >= 43 and form["grant_type"] == "authorization_code"
    channel.refresh_from_db()
    assert channel.connected and channel.credentials()["access_token"] == "AT-secret-token-value"
    assert "AT-secret" not in channel.credential_encrypted and not channel.pending_encrypted
    assert channel.expires_at is not None
    assert client.get(f"{API}/oauth/linkedin/", {"state": query["state"], "code": "C"}).status_code == 403, "single use"
    out = client.post(f"{API}/channels/{channel.public_id}/disconnect/").json()
    assert out["has_credential"] is False and out["armed"] is False


# ── the canonical URL: the key every lane uses ──────────────────────────────


def test_a_jekyll_sites_page_is_keyed_by_the_url_its_own_lane_computes(db, tmp_path, settings):
    site, pages = imported(tmp_path, settings)
    expected = {s.entry.relative: s.url for s in Pipeline(Config(site, env={})).sources()}
    assert {path: services.canonical_url(pages[path]) for path in expected} == expected
    assert services.canonical_url(pages["about.md"]) == "https://example.test/about/"


def test_a_site_outside_the_repository_is_keyed_only_where_its_checkout_may_be_read(db, tmp_path, settings, alice):
    """The importer records an absolute source_root for a site outside the repository (compose's /sites). Its pages
    are keyed from that checkout's own `_config.yml` — exactly as its lane keys them — where the platform may read
    it (SITES_DIR), and refused with a sentence, never keyed by a URL Jekyll does not build, anywhere else or when
    the checkout is not here (a process without the mount). A source_root a person changed to leave those places is
    not followed, for the `_config.yml` or the ledger file."""
    (tmp_path / "app").mkdir()
    site, pages = imported(tmp_path / "app", settings, at=tmp_path / "sites" / "site")
    expected = {s.entry.relative: s.url for s in Pipeline(Config(site, env={})).sources()}
    mcp = pages[MCP_POST]
    channel = Channel.objects.create(
        site=mcp.get_site(), kind="linkedin", name="Page", settings={"author": AUTHOR, "ledger_file": "log.json"}
    )
    with pytest.raises(Conflict, match="needs the site's _config.yml, which cannot be read here"):
        services.compose(channel, user=alice, page=mcp)
    settings.SITES_DIR = str(tmp_path / "sites")
    assert {path: services.canonical_url(pages[path]) for path in expected} == expected
    post = services.compose(channel, user=alice, page=mcp, commentary="The plug.")
    assert post.link == MCP_URL and isinstance(services.site_ledger(channel), Ledger)
    shutil.move(site, tmp_path / "elsewhere")
    with pytest.raises(Conflict, match="cannot be read here"):
        services.canonical_url(mcp)
    assert "ledger_unreadable" in [b.kind for b in services.preview(post).blockers]
    shutil.move(tmp_path / "elsewhere", site)
    root = mcp.get_site().root_page.specific
    root.source_root = "../.."  # a person who edits the root may change it; it is not followed out of those places
    root.save()
    channel = Channel.objects.get(pk=channel.pk)
    assert services.site_ledger(channel).readable is False
    with pytest.raises(Conflict, match="outside this repository and SITES_DIR"):
        services.canonical_url(mcp)


# ── the queue ───────────────────────────────────────────────────────────────


def test_compose_runs_the_brand_guard_and_approval_needs_a_clean_text_and_the_publish_right(
    api, alice, bob, channel, article
):
    made = api(alice).post(
        f"{API}/posts/",
        {"channel": str(channel.public_id), "page": article.pk, "commentary": "Our world-class backups."},
        format="json",
    )
    assert made.status_code == 201, made.content
    post = made.json()
    assert post["status"] == "draft" and post["link"] == "http://localhost/nightly-backups/"
    assert any(f["level"] == "error" and "world-class" in f["message"] for f in post["guard"])
    assert {b["kind"] for b in post["blockers"]} >= {"guard_error", "status_not_accepted", "publish_disabled"}
    refused = api(alice).post(f"{API}/posts/{post['id']}/approve/")
    assert refused.status_code == 409 and "brand guard" in refused.json()["error"]["message"]
    fixed = api(alice).patch(
        f"{API}/posts/{post['id']}/", {"commentary": "We copy the site every night."}, format="json"
    )
    assert fixed.json()["guard"][-1]["level"] == "info"
    assert api(bob).post(f"{API}/posts/{post['id']}/approve/").status_code == 404, "bob cannot see the channel"
    ok = api(alice).post(f"{API}/posts/{post['id']}/approve/")
    assert ok.status_code == 200 and ok.json()["status"] == "approved" and ok.json()["approved_by"] == "alice"
    again = api(alice).patch(
        f"{API}/posts/{post['id']}/", {"commentary": "We copy the site every night, twice."}, format="json"
    )
    assert again.json()["status"] == "draft", "approval is of the exact text"
    nobody = get_user_model().objects.create_user("dave")
    with pytest.raises(Exception, match="edit"):
        services.compose(channel, user=nobody, page=article)


def test_the_gates_compare_the_text_with_the_text_a_person_approved(alice, channel, article):
    post = approved(services.compose(channel, user=alice, page=article, commentary="Approved words."), alice)
    assert "status_not_accepted" not in [b.kind for b in services.preview(post).blockers]
    DistributionPost.objects.filter(pk=post.pk).update(commentary="Words changed behind the services' back.")
    post.refresh_from_db()
    [blocker] = [b for b in services.preview(post).blockers if b.kind == "status_not_accepted"]
    assert blocker.message == "the text is not the text a person approved: a person approves it again"


@override_settings(DISTRIBUTION_ARMED={"linkedin"})
def test_a_failed_posts_changed_text_needs_a_new_approval_before_anything_goes(
    api, alice, carol, channel, article, web, worker
):
    """A post that failed was approved; its approval is of the text that failed. Someone who may only edit the page
    changes it: it is a draft again, refused even with force until a person who may publish approves it — and what
    then goes is the text they approved."""
    route = web.post(f"{REST}/posts").mock(
        side_effect=[
            httpx.Response(422, json={"message": "Unprocessable"}),
            httpx.Response(201, headers={"x-restli-id": "urn:li:share:8"}),
        ]
    )
    post = approved(services.compose(channel, user=alice, page=article, commentary="The text alice approved."), alice)
    worker(services.request_publish, post, alice)
    post.refresh_from_db()
    assert post.status == "failed"
    changed = api(carol).patch(f"{API}/posts/{post.public_id}/", {"commentary": "Words carol wrote."}, format="json")
    assert changed.status_code == 200 and (changed.json()["status"], changed.json()["approved_by"]) == ("draft", None)
    refused = api(alice).post(f"{API}/posts/{post.public_id}/publish/", {"force": True}, format="json")
    assert refused.status_code == 409 and "status_not_accepted" in refused.json()["error"]["message"]
    assert api(carol).post(f"{API}/posts/{post.public_id}/approve/").status_code == 403
    assert route.call_count == 1
    assert api(alice).post(f"{API}/posts/{post.public_id}/approve/").status_code == 200
    assert worker(api(alice).post, f"{API}/posts/{post.public_id}/publish/", {}, format="json").status_code == 202
    post.refresh_from_db()
    assert (post.status, post.approved_by) == ("published", alice)
    assert json.loads(route.calls.last.request.content)["commentary"] == "Words carol wrote."


@override_settings(DISTRIBUTION_ARMED={"linkedin"})
def test_publish_checks_every_gate_in_the_request_and_again_on_the_worker(api, alice, channel, article, web, worker):
    route = web.post(f"{REST}/posts").respond(201, headers={"x-restli-id": "urn:li:share:77"})
    post = services.compose(channel, user=alice, page=article, commentary="We copy the site every night.")
    blocked = api(alice).post(f"{API}/posts/{post.public_id}/publish/", {}, format="json")
    assert blocked.status_code == 409 and "status_not_accepted" in blocked.json()["error"]["message"]
    approved(post, alice)
    with override_settings(DISTRIBUTION_ARMED=set()):
        unarmed = api(alice).post(f"{API}/posts/{post.public_id}/publish/", {}, format="json")
    assert unarmed.status_code == 409 and "ZER0_LINKEDIN_PUBLISH" in unarmed.json()["error"]["message"]
    Channel.objects.filter(pk=channel.pk).update(armed=False)
    assert (
        "not armed"
        in api(alice).post(f"{API}/posts/{post.public_id}/publish/", {}, format="json").json()["error"]["message"]
    )
    Channel.objects.filter(pk=channel.pk).update(armed=True)
    assert route.call_count == 0
    went = worker(api(alice).post, f"{API}/posts/{post.public_id}/publish/", {}, format="json")
    assert went.status_code == 202 and went.json()["status"] == "publishing"
    post.refresh_from_db()
    assert (post.status, post.external_id) == ("published", "urn:li:share:77")
    assert post.external_url == "https://www.linkedin.com/feed/update/urn:li:share:77/"
    payload = json.loads(route.calls.last.request.content)
    assert (
        payload["author"] == AUTHOR and payload["content"]["article"]["source"] == "http://localhost/nightly-backups/"
    )
    entry = LedgerEntry.objects.get(channel=channel)
    assert (entry.key, entry.urn, entry.state) == (post.link, "urn:li:share:77", "published")
    with pytest.raises(Exception, match="already distributed"):
        services.compose(channel, user=alice, page=article)


@override_settings(DISTRIBUTION_ARMED={"linkedin"})
def test_an_unconfirmed_publish_blocks_until_a_person_records_it_or_forces_past_it(
    api, alice, channel, article, web, worker
):
    route = web.post(f"{REST}/posts").respond(503, json={"message": "down"})
    post = approved(services.compose(channel, user=alice, page=article, commentary="Nightly, always."), alice)
    worker(services.request_publish, post, alice)
    post.refresh_from_db()
    assert post.status == "failed" and "HTTP 503" in post.error and "may have published" in post.error
    doubt = LedgerEntry.objects.get(channel=channel)
    assert (doubt.urn, doubt.state) == ("", "unconfirmed")
    again = api(alice).post(f"{API}/posts/{post.public_id}/publish/", {}, format="json")
    assert again.status_code == 409 and "publish_unconfirmed" in again.json()["error"]["message"]
    assert route.call_count == 1, "a post that may exist is never sent again by a run"
    recorded = api(alice).post(f"{API}/posts/{post.public_id}/record/", {"urn": "urn:li:share:42"}, format="json")
    assert recorded.json()["status"] == "published"
    assert LedgerEntry.objects.get(channel=channel).urn == "urn:li:share:42"


@override_settings(DISTRIBUTION_ARMED={"linkedin"})
def test_a_delivery_never_sends_a_post_another_delivery_claimed(alice, channel, article, web):
    """Acks are late, so the task of a worker that died mid-send is delivered again: the claim committed before the
    send keeps a second delivery from sending the post twice."""
    route = web.post(f"{REST}/posts").respond(201, headers={"x-restli-id": "urn:li:share:5"})
    post = approved(services.compose(channel, user=alice, page=article, commentary="Nightly, always."), alice)
    services.request_publish(post, alice)  # queued; no worker runs it here
    DistributionPost.objects.filter(pk=post.pk).update(attempted_at=timezone.now())  # a worker is sending it now
    assert services.deliver(post.pk).status == "publishing" and route.call_count == 0
    with pytest.raises(Conflict, match="being sent now"):
        services.request_publish(post, alice)
    DistributionPost.objects.filter(pk=post.pk).update(attempted_at=timezone.now() - timedelta(hours=1))  # it died
    dead = services.deliver(post.pk)
    assert (dead.status, route.call_count) == ("failed", 0) and "may have published" in dead.error
    assert LedgerEntry.objects.get(channel=channel).state == "unconfirmed"
    blocked = [b.kind for b in services.preview(dead).blockers]
    assert "publish_unconfirmed" in blocked, "nothing sends it again until a person records it or forces"


@override_settings(DISTRIBUTION_ARMED={"linkedin"})
def test_two_deliveries_that_read_the_post_at_once_send_it_once(alice, channel, article, web, monkeypatch):
    """`select_for_update` does nothing on SQLite, so two workers may both read the post unclaimed: the claim is a
    conditional update, and the delivery whose claim another made first sends nothing."""
    route = web.post(f"{REST}/posts").respond(201, headers={"x-restli-id": "urn:li:share:5"})
    post = approved(services.compose(channel, user=alice, page=article, commentary="Nightly, always."), alice)
    services.request_publish(post, alice)  # queued; no worker runs it here
    gates_of = services.preview

    def meanwhile(row, **kwargs):  # the other worker claims it between this one's read and its claim
        DistributionPost.objects.filter(pk=row.pk).update(attempted_at=timezone.now())
        return gates_of(row, **kwargs)

    monkeypatch.setattr(services, "preview", meanwhile)
    assert services.deliver(post.pk).status == "publishing" and route.call_count == 0


@override_settings(DISTRIBUTION_ARMED={"linkedin"})
def test_a_post_is_queued_once_and_one_no_worker_took_is_given_back(api, alice, channel, article, web, worker):
    """A second Publish while the first waits for a worker is refused, not queued again; a post no worker took
    within the send's time limit goes back to approved by the beat's sweep — nothing was sent — and publishes."""
    from distribution.tasks import settle_posts

    route = web.post(f"{REST}/posts").respond(201, headers={"x-restli-id": "urn:li:share:6"})
    post = approved(services.compose(channel, user=alice, page=article, commentary="Nightly, always."), alice)
    assert api(alice).post(f"{API}/posts/{post.public_id}/publish/", {}, format="json").status_code == 202
    again = api(alice).post(f"{API}/posts/{post.public_id}/publish/", {}, format="json")
    assert again.status_code == 409 and "queued for the worker" in again.json()["error"]["message"]
    assert settle_posts() == 0, "a queued post is the worker's for the send's time limit"
    DistributionPost.objects.filter(pk=post.pk).update(updated_at=timezone.now() - timedelta(hours=1))
    assert settle_posts() == 1
    post.refresh_from_db()
    assert (post.status, post.error) == ("approved", "no worker took it: publish it again")
    assert not LedgerEntry.objects.exists() and route.call_count == 0
    assert worker(api(alice).post, f"{API}/posts/{post.public_id}/publish/", {}, format="json").status_code == 202
    post.refresh_from_db()
    assert post.status == "published" and route.call_count == 1


@override_settings(DISTRIBUTION_ARMED={"linkedin"})
def test_an_attempt_whose_worker_died_is_settled_by_the_next_request_and_by_the_sweep(
    api, alice, channel, article, site_root, web
):
    """A task that raised, or whose worker was killed, is acknowledged and never delivered again: the claim is all
    that is left. The next request settles it — the post comes back failed and doubted, and force is not applied to
    an attempt nobody has checked yet — and so does the beat's sweep, so the studio never waits on it forever."""
    from distribution.tasks import settle_posts

    route = web.post(f"{REST}/posts").respond(201, headers={"x-restli-id": "urn:li:share:5"})
    hours_ago = timezone.now() - timedelta(hours=6)
    post = approved(services.compose(channel, user=alice, page=article, commentary="Nightly, always."), alice)
    services.request_publish(post, alice)  # queued; its worker claims it and dies
    DistributionPost.objects.filter(pk=post.pk).update(attempted_at=hours_ago)
    settled = api(alice).post(f"{API}/posts/{post.public_id}/publish/", {"force": True}, format="json")
    assert settled.status_code == 202 and settled.json()["status"] == "failed"
    assert "never finished, so it may have published" in settled.json()["error"]
    assert "publish_unconfirmed" in [b["kind"] for b in settled.json()["blockers"]] and route.call_count == 0
    other = make_article(site_root, "Restores tested", search_description="Test your restores.")
    second = approved(services.compose(channel, user=alice, page=other, commentary="Restores."), alice)
    services.request_publish(second, alice)
    DistributionPost.objects.filter(pk=second.pk).update(attempted_at=hours_ago)
    assert settle_posts() == 1
    second.refresh_from_db()
    assert second.status == "failed" and LedgerEntry.objects.get(key=second.link).state == "unconfirmed"
    edited = api(alice).patch(f"{API}/posts/{second.public_id}/", {"commentary": "Restores, tested."}, format="json")
    assert edited.status_code == 200 and edited.json()["status"] == "draft"
    assert services.reject(second, alice, "not this week").status == "rejected"


@override_settings(DISTRIBUTION_ARMED={"linkedin"})
def test_an_error_nobody_expected_fails_the_post_as_one_that_may_have_published(
    alice, channel, article, monkeypatch, worker
):
    """An exception the transports do not turn into a sentence — an unreadable image, a library's own network
    error, the soft time limit, the database — leaves the outcome unknown: the post is failed and doubted, never
    left publishing."""

    def broken(post, page):
        raise OSError("the preview image could not be read")

    monkeypatch.setattr(services, "_send_linkedin", broken)
    post = approved(services.compose(channel, user=alice, page=article, commentary="Nightly."), alice)
    worker(services.request_publish, post, alice)
    post.refresh_from_db()
    assert post.status == "failed" and "stopped on an unexpected error (OSError)" in post.error
    assert LedgerEntry.objects.get(channel=channel).state == "unconfirmed"
    assert "publish_unconfirmed" in [b.kind for b in services.preview(post).blockers]


def test_a_send_stops_from_the_inside_before_its_worker_is_killed():
    from distribution.tasks import SEND_TIME_LIMIT, publish_post

    assert publish_post.soft_time_limit < publish_post.time_limit == SEND_TIME_LIMIT


@override_settings(DISTRIBUTION_ARMED={"linkedin"})
def test_force_lifts_the_ledger_but_never_approval(api, alice, channel, article, web, worker):
    web.post(f"{REST}/posts").respond(201, headers={"x-restli-id": "urn:li:share:9"})
    post = services.compose(channel, user=alice, page=article, commentary="Nightly.")
    LedgerEntry.objects.create(channel=channel, key=post.link, state="unconfirmed", error="timeout")
    forced = api(alice).post(f"{API}/posts/{post.public_id}/publish/", {"force": True}, format="json")
    assert forced.status_code == 409 and "status_not_accepted" in forced.json()["error"]["message"]
    approved(post, alice)
    went = worker(api(alice).post, f"{API}/posts/{post.public_id}/publish/", {"force": True}, format="json")
    assert went.status_code == 202
    post.refresh_from_db()
    assert post.status == "published"


# ── the ledger, byte-compatible with every lane's ───────────────────────────


def test_the_ledger_round_trips_a_lanes_file_byte_for_byte_and_imported_keys_are_never_published_again(
    api, manager, channel, article
):
    other = {
        article.get_full_url(): {
            "linkedin_urn": "urn:li:share:5",
            "urn": "urn:li:share:5",
            "posted_at": "2026-07-30T17:29:20Z",
            "target": "linkedin",
            "type": "article",
            "source_file": "pages/x.md",
        },
        "https://example.test/u/": {
            "state": "unconfirmed",
            "attempted_at": "2026-08-01T00:00:00Z",
            "error": "HTTP 503",
            "target": "linkedin",
            "type": "article",
            "lane": "ci",
        },
        "_meta": {"token": "kept by its lane"},
    }
    text = serialize(other)
    counts = (
        api(manager).post(f"{API}/channels/{channel.public_id}/ledger-file/", {"content": text}, format="json").json()
    )
    assert counts == {"added": 2, "kept": 0, "skipped": 1}
    exported = api(manager).get(f"{API}/channels/{channel.public_id}/ledger-file/").json()["content"]
    assert exported == serialize({k: v for k, v in other.items() if not k.startswith("_")}), (
        "byte for byte, sorted keys, ASCII"
    )
    with pytest.raises(Exception, match="already distributed"):
        services.compose(channel, user=manager, page=article)
    assert (
        api(manager)
        .post(f"{API}/channels/{channel.public_id}/ledger-file/", {"content": "{ nope"}, format="json")
        .status_code
        == 422
    )
    entries = api(manager).get(f"{API}/ledger/", {"channel": str(channel.public_id)}).json()["results"]
    assert {e["state"] for e in entries} == {"published", "unconfirmed"}


@override_settings(DISTRIBUTION_ARMED={"linkedin"})
def test_a_site_ledger_file_is_read_before_and_written_after_a_publish(tmp_path, settings, alice, web, worker):
    """The extension and the site's CI write the site's own ledger file: what they published blocks the platform,
    and what the platform publishes lands there for them."""
    from importers.jekyll import import_site

    settings.REPO_ROOT = tmp_path
    shutil.copytree(FIXTURE, tmp_path / "site")
    import_site(tmp_path / "site", "fixture", repo_root=tmp_path)
    page = next(
        p for p in Page.objects.specific() if getattr(p, "legacy_path", "") == "pages/_posts/tech/2026-07-10-moved.md"
    )
    mcp = next(
        p for p in Page.objects.specific() if getattr(p, "legacy_path", "").endswith("mcp-for-the-back-office.md")
    )
    channel = Channel.objects.create(
        site=page.get_site(),
        kind="linkedin",
        name="Page",
        armed=True,
        settings={"author": AUTHOR, "ledger_file": ".github/linkedin-log.json"},
    )
    channel.set_credentials({"access_token": TOKEN})
    channel.save()
    file = Ledger(tmp_path / "site" / ".github" / "linkedin-log.json")
    file.record(
        "https://example.test/news/moved-elsewhere/", entry_for(urn="urn:li:share:1", kind="article", target="linkedin")
    )
    with pytest.raises(Exception, match="already distributed"):
        services.compose(channel, user=alice, page=page)
    web.post(f"{REST}/posts").respond(201, headers={"x-restli-id": "urn:li:share:2"})
    post = approved(services.compose(channel, user=alice, page=mcp, commentary="The plug."), alice)
    worker(services.request_publish, post, alice)
    post.refresh_from_db()
    assert post.status == "published", post.error
    written = file.entry("https://example.test/posts/2026/07/06/mcp-for-the-back-office/")
    assert written["urn"] == written["linkedin_urn"] == "urn:li:share:2"
    assert written["source_file"] == "pages/_posts/tech/2026-07-06-mcp-for-the-back-office.md"
    assert (tmp_path / "site" / ".github" / "linkedin-log.json").read_text() == serialize(file.raw())
    (tmp_path / "site" / ".github" / "linkedin-log.json").write_text("{ broken")
    assert "ledger_unreadable" in [b.kind for b in services.preview(post).blockers]
    # A file that cannot take an entry never undoes the platform's own: the post exists at the target.
    services.record(post, "urn:li:share:3")
    assert LedgerEntry.objects.get(channel=channel, key=post.ledger_key).urn == "urn:li:share:3"
    assert (tmp_path / "site" / ".github" / "linkedin-log.json").read_text() == "{ broken"
    # A ledger file the channel names but cannot reach is refused too, never read as "nothing published".
    shutil.rmtree(tmp_path / "site")
    [blocker] = [b for b in services.preview(post).blockers if b.kind == "ledger_unreadable"]
    assert "checkout is not here" in blocker.message


# ── statistics ──────────────────────────────────────────────────────────────


def test_statistics_are_ingested_per_post_and_day_and_shown_with_the_ledger(api, alice, channel, web, worker):
    from distribution.tasks import ingest_statistics

    LedgerEntry.objects.create(channel=channel, key="https://example.test/a/", urn="urn:li:share:1", author=AUTHOR)
    LedgerEntry.objects.create(
        channel=channel, key="https://example.test/b/", urn="urn:li:share:2", author="urn:li:organization:9"
    )
    web.get(url__startswith=f"{REST}/organizationalEntityShareStatistics?").respond(
        200,
        json={
            "elements": [
                {
                    "share": "urn:li:share:1",
                    "totalShareStatistics": {
                        "impressionCount": 90,
                        "clickCount": 4,
                        "likeCount": 5,
                        "commentCount": 1,
                        "shareCount": 0,
                    },
                }
            ]
        },
    )
    assert ingest_statistics() == 1, "another author's post is not read as this channel's"
    stat = Statistic.objects.get()
    assert (stat.impressions, stat.engagements) == (90, 6)
    entries = api(alice).get(f"{API}/ledger/").json()["results"]
    latest = {e["key"]: e["latest"] for e in entries}
    assert latest["https://example.test/a/"]["impressions"] == 90 and latest["https://example.test/b/"] is None
    assert worker(api(alice).post, f"{API}/channels/{channel.public_id}/statistics/").status_code == 202


# ── the tools, MCP and the published-page consumer ──────────────────────────


def test_an_agent_composes_through_the_registry_and_publishing_stays_armed_off(agent, article, channel):
    distributor = agent("distribution")
    ctx = ToolContext(user=get_user_model().objects.get(username=distributor.username), agent=distributor)
    made = registry.call("distribution.compose", {"channel": str(channel.public_id), "page_id": article.pk}, ctx)
    post = DistributionPost.objects.get(public_id=made["post"])
    assert (post.status, post.origin) == ("draft", "agent") and post.commentary
    with pytest.raises(ToolError) as refused:
        registry.call("distribution.publish", {"post": made["post"], "page_id": article.pk}, ctx)
    assert refused.value.code == "policy", "publish needs the page and the agent at auto"
    article.agent_policy = "off"
    article.save()
    with pytest.raises(ToolError):
        registry.call("distribution.compose", {"channel": str(channel.public_id), "page_id": article.pk}, ctx)


@override_settings(DISTRIBUTION_ARMED={"linkedin"})
def test_the_armed_agent_publishes_only_what_a_person_approved_and_never_forces(
    agent, alice, carol, channel, site_root, web, worker
):
    """`distribution.publish` once every switch is set on purpose — the agent and the page at auto, the agent's group
    given the page's publish right, the channel and the deployment armed: a post a person approved goes; a draft, a
    rejected post and a failed one whose text was changed since do not; nor does one an earlier attempt may have
    published, because an agent never forces."""
    route = web.post(f"{REST}/posts").mock(
        side_effect=[
            httpx.Response(201, headers={"x-restli-id": "urn:li:share:31"}),
            httpx.Response(422, json={"message": "Unprocessable"}),
        ]
    )
    distributor = agent("distribution")
    distributor.policy = "auto"  # this call's definition only: the row stays at suggest
    robot = grant(
        get_user_model().objects.get(username=distributor.username),
        "agents that publish",
        "change_page",
        "publish_page",
    )
    ctx = ToolContext(user=robot, agent=distributor)
    pages = [
        make_article(site_root, f"Page {n}", search_description="Why it matters.", agent_policy="auto")
        for n in range(4)
    ]

    def publish(post):
        return worker(
            registry.call, "distribution.publish", {"post": str(post.public_id), "page_id": post.page_id}, ctx
        )

    def refused(post):
        with pytest.raises(ToolError) as e:
            publish(post)
        assert e.value.code == "not_allowed"
        return e.value.message

    went = approved(services.compose(channel, user=alice, page=pages[0], commentary="Approved by alice."), alice)
    assert publish(went)["status"] == "publishing"
    went.refresh_from_db()
    assert (went.status, went.external_id, went.published_by) == ("published", "urn:li:share:31", robot)
    draft = services.compose(channel, user=alice, page=pages[1], commentary="Only a draft.")
    assert "status_not_accepted" in refused(draft)
    assert "status_not_accepted" in refused(services.reject(draft, alice, "not this one"))
    failed = approved(services.compose(channel, user=alice, page=pages[2], commentary="Approved, then failed."), alice)
    publish(failed)
    failed.refresh_from_db()
    assert failed.status == "failed"
    services.edit(failed, carol, commentary="Words nobody approved.")
    assert "status_not_accepted" in refused(failed)
    doubted = approved(services.compose(channel, user=alice, page=pages[3], commentary="Approved, doubted."), alice)
    LedgerEntry.objects.create(channel=channel, key=doubted.link, state="unconfirmed", error="HTTP 503")
    assert "publish_unconfirmed" in refused(doubted)
    assert route.call_count == 2, "only the approved post and the attempt that failed reached LinkedIn"


def test_an_mcp_client_with_the_distribution_token_drafts_and_cannot_publish(channel, article):
    from tests.mcp.test_mcp import rpc, token_for

    raw = token_for("distribution")
    names = [t["name"] for t in rpc(raw, "tools/list").json()["result"]["tools"]]
    assert names == ["distribution.compose", "distribution.publish"]
    compose = {"name": "distribution.compose", "arguments": {"channel": str(channel.public_id), "page_id": article.pk}}
    made = rpc(raw, "tools/call", compose).json()["result"]
    assert made["isError"] is False, made
    post = DistributionPost.objects.get(public_id=made["structuredContent"]["post"])
    assert (post.status, post.origin) == ("draft", "agent")
    publish = {"name": "distribution.publish", "arguments": {"post": str(post.public_id), "page_id": article.pk}}
    refused = rpc(raw, "tools/call", publish).json()["result"]
    assert refused["isError"] is True and refused["structuredContent"]["error"] == "policy"
    assert AgentRun.objects.filter(trigger="mcp", agent__slug="distribution").count() == 2


def test_a_published_page_drafts_a_post_for_each_auto_channel_never_a_publish(
    alice, channel, article, site_root, worker
):
    Channel.objects.filter(pk=channel.pk).update(auto_draft=True)
    quiet = Channel.objects.create(
        site=channel.site, kind="linkedin", name="Not automatic", settings={"author": AUTHOR}
    )
    page = make_article(site_root, "Restores tested", publish=False, search_description="Test your restores.")
    worker(lambda: page.save_revision().publish())
    event = OutboxEvent.objects.filter(type="content.page.published", subject=f"page:{page.pk}").latest("id")
    assert worker(handle_envelope, event.envelope()) == ["distribution.auto-draft"]
    posts = DistributionPost.objects.filter(page=page)
    assert [(p.channel_id, p.status, p.origin) for p in posts] == [(channel.pk, "draft", "agent")]
    assert not posts.filter(channel=quiet).exists()
    run = AgentRun.objects.filter(agent__slug="distribution", trigger="event").latest("id")
    assert run.status == "succeeded" and run.output["json"]["drafted"] == 1
    assert worker(handle_envelope, event.envelope()) == [], "an event is handled once"
    second = make_article(site_root, "Off limits", publish=False, search_description="No agents here.")
    second.agent_policy = "off"
    second.save()
    worker(lambda: second.save_revision().publish())
    event = OutboxEvent.objects.filter(type="content.page.published", subject=f"page:{second.pk}").latest("id")
    worker(handle_envelope, event.envelope())
    assert not DistributionPost.objects.filter(page=second).exists(), "a page at policy off gets nothing"


def test_the_agents_definition_is_live_and_gated(db, agent):
    definition = agent("distribution")
    assert definition.live and definition.policy == "suggest"
    assert set(definition.tools) == {"distribution.compose", "distribution.publish"}
    assert AgentDefinition.objects.get(slug="distribution").live
