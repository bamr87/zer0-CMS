"""The channels that are not LinkedIn, published through the platform's queue
on recorded HTTP: WordPress (respx, at the address the research library's SSRF
guard pins the connection to — draft by default, the Yoast title and meta
description, readable 401/403/404s, a 5xx left unconfirmed), a GitHub pull
request through PyGithub (`responses`, which records `requests` the way respx
records httpx — barodybroject's 401/403/404/422 and "already open" cases), and
email through the newsroom's newsletters (Django's locmem backend). Nothing
reaches WordPress, GitHub or a mail server.
"""

import base64
import json

import pytest
import responses
from django.core import mail
from django.test import override_settings

from distribution import services
from distribution.models import Channel, LedgerEntry
from newsroom.models import Newsletter, Subscriber
from research import fetch

from ..conftest import make_article

PUBLIC = "93.184.216.34"
API_URL = "https://api.github.com/repos/bamr87/it-journey"
GITHUB = "https://api.github.com:443/repos/bamr87/it-journey"  # what PyGithub requests


@pytest.fixture(autouse=True)
def table_dns(monkeypatch):
    table = {"blog.example.com": [PUBLIC], "intranet.example.com": ["10.0.0.5"]}

    def resolve(host, port):
        if host not in table:
            raise OSError(f"{host} does not resolve in the tests")
        return table[host]

    monkeypatch.setattr(fetch, "resolve", resolve)


@pytest.fixture
def page(site_root):
    found = make_article(
        site_root,
        "Nightly backups",
        search_description="Why we copy the site every night.",
        seo_title="Nightly backups, explained",
        body=[{"type": "markdown", "value": "We copy the site to a **second disk** every night."}],
    )
    return found


def channel_for(page, kind, settings, credentials):
    made = Channel.objects.create(site=page.get_site(), kind=kind, name=kind, settings=settings, armed=True)
    made.set_credentials(credentials)
    made.save()
    return made


def ready(channel, page, user, **fields):
    return services.approve(services.compose(channel, user=user, page=page, **fields), user)


# ── WordPress ───────────────────────────────────────────────────────────────


@override_settings(DISTRIBUTION_ARMED={"wordpress"})
def test_wordpress_publishes_a_draft_with_the_yoast_fields_through_the_ssrf_guard(alice, page, web, worker):
    channel = channel_for(
        page, "wordpress", {"url": "https://blog.example.com", "username": "ed"}, {"application_password": "abcd efgh"}
    )
    route = web.post(f"https://{PUBLIC}/wp-json/wp/v2/posts").respond(
        201, json={"id": 12, "link": "https://blog.example.com/?p=12", "status": "draft"}
    )
    post = ready(channel, page, alice, commentary="Why we copy the site every night.")
    worker(services.request_publish, post, alice)
    post.refresh_from_db()
    assert (post.status, post.external_id, post.external_url) == (
        "published",
        "wp:12",
        "https://blog.example.com/?p=12",
    )
    request = route.calls.last.request
    assert request.headers["Host"] == "blog.example.com"
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"ed:abcd efgh").decode()
    body = json.loads(request.content)
    assert body["status"] == "draft" and body["title"] == "Nightly backups"
    assert (body["yoast_title"], body["yoast_metadesc"]) == (
        "Nightly backups, explained",
        "Why we copy the site every night.",
    )
    assert "<strong>second disk</strong>" in body["content"]
    assert LedgerEntry.objects.get(channel=channel).urn == "wp:12"


@override_settings(DISTRIBUTION_ARMED={"wordpress"})
@pytest.mark.parametrize(
    ("status", "says", "unconfirmed"),
    [
        (401, "WordPress rejected the credentials (401)", False),
        (403, "the user may not create posts", False),
        (404, "There is no WordPress REST API at https://blog.example.com/wp-json/ (404)", False),
        (502, "WordPress refused the post (502)", True),
    ],
)
def test_wordpress_errors_are_sentences_and_a_5xx_is_left_unconfirmed(
    alice, page, web, worker, status, says, unconfirmed
):
    channel = channel_for(
        page, "wordpress", {"url": "https://blog.example.com", "username": "ed"}, {"application_password": "abcd efgh"}
    )
    web.post(f"https://{PUBLIC}/wp-json/wp/v2/posts").respond(status, json={"code": "x", "message": "no"})
    post = ready(channel, page, alice)
    worker(services.request_publish, post, alice)
    post.refresh_from_db()
    assert post.status == "failed" and says in post.error
    assert LedgerEntry.objects.filter(channel=channel, urn="", state="unconfirmed").exists() is unconfirmed


@override_settings(DISTRIBUTION_ARMED={"wordpress"})
def test_wordpress_on_a_private_address_is_refused_before_a_socket(alice, page, web, worker):
    channel = channel_for(
        page, "wordpress", {"url": "https://intranet.example.com", "username": "ed"}, {"application_password": "x"}
    )
    post = ready(channel, page, alice)
    worker(services.request_publish, post, alice)
    post.refresh_from_db()
    assert post.status == "failed" and "not a public address" in post.error and not web.calls


def test_checking_a_wordpress_channel_names_the_account(alice, page, web, worker):
    channel = channel_for(
        page, "wordpress", {"url": "https://blog.example.com", "username": "ed"}, {"application_password": "x"}
    )
    web.get(f"https://{PUBLIC}/wp-json/wp/v2/users/me?context=edit").respond(
        200, json={"name": "Ed Editor", "roles": ["author"]}
    )
    services.check(channel)
    channel.refresh_from_db()
    assert channel.account == "Ed Editor" and channel.last_check["ok"] and channel.checked_at


# ── GitHub pull requests ────────────────────────────────────────────────────


def github(rsps, branch, *, pull=None, contents=404, repo=200):
    rsps.add(
        responses.GET,
        GITHUB,
        status=repo,
        json={
            "url": API_URL,
            "full_name": "bamr87/it-journey",
            "name": "it-journey",
            "message": "Bad credentials",
            "permissions": {"push": True},
        },
    )
    rsps.add(
        responses.GET,
        f"{GITHUB}/branches/main",
        json={"name": "main", "commit": {"sha": "abc123", "url": f"{GITHUB}/commits/abc123"}},
    )
    rsps.add(responses.GET, f"{GITHUB}/branches/{branch}", status=404, json={"message": "Branch not found"})
    rsps.add(
        responses.POST,
        f"{GITHUB}/git/refs",
        status=201,
        json={"ref": f"refs/heads/{branch}", "url": f"{GITHUB}/git/refs/x", "object": {"sha": "abc123"}},
    )
    rsps.add(
        responses.GET,
        f"{GITHUB}/contents/sites/news/nightly-backups.md",
        status=contents,
        json={"message": "API rate limit exceeded" if contents == 403 else "Not Found"},
    )
    rsps.add(
        responses.PUT,
        f"{GITHUB}/contents/sites/news/nightly-backups.md",
        status=201,
        json={"content": {"path": "sites/news/nightly-backups.md", "sha": "def"}, "commit": {"sha": "456"}},
    )
    rsps.add(
        responses.POST,
        f"{GITHUB}/pulls",
        **(
            pull
            or {
                "status": 201,
                "json": {
                    "number": 7,
                    "html_url": "https://github.com/bamr87/it-journey/pull/7",
                    "url": f"{GITHUB}/pulls/7",
                },
            }
        ),
    )


@override_settings(DISTRIBUTION_ARMED={"github_pr"})
def test_a_github_channel_opens_a_pull_request_with_the_pages_jekyll_file(alice, page, worker):
    channel = channel_for(
        page, "github_pr", {"repo": "bamr87/it-journey", "directory": "sites/news"}, {"token": "ghp_test_token"}
    )
    post = ready(channel, page, alice, commentary="Ready to merge.")
    branch = f"distribute/{post.public_id.hex[:12]}"
    with responses.RequestsMock() as rsps:
        github(rsps, branch)
        worker(services.request_publish, post, alice)
        put = next(c for c in rsps.calls if c.request.method == "PUT")
        pull = next(c for c in rsps.calls if c.request.method == "POST" and c.request.url.endswith("/pulls"))
    post.refresh_from_db()
    assert (post.status, post.external_url) == ("published", "https://github.com/bamr87/it-journey/pull/7")
    assert post.external_id == "pr:bamr87/it-journey#7"
    written = base64.b64decode(json.loads(put.request.body)["content"]).decode()
    assert written.startswith("---\ntitle: Nightly backups\n") and "second disk" in written
    assert json.loads(put.request.body)["branch"] == branch
    sent = json.loads(pull.request.body)
    assert (sent["head"], sent["base"], sent["title"]) == (branch, "main", "Nightly backups")
    assert "Ready to merge." in sent["body"] and put.request.headers["Authorization"] == "token ghp_test_token"


@override_settings(DISTRIBUTION_ARMED={"github_pr"})
def test_an_already_open_pull_request_is_named_with_its_link(alice, page, worker):
    channel = channel_for(
        page, "github_pr", {"repo": "bamr87/it-journey", "directory": "sites/news"}, {"token": "ghp_test_token"}
    )
    post = ready(channel, page, alice)
    branch = f"distribute/{post.public_id.hex[:12]}"
    with responses.RequestsMock() as rsps:
        github(rsps, branch, pull={"status": 422, "json": {"message": "A pull request already exists"}})
        rsps.add(
            responses.GET,
            f"{GITHUB}/pulls",
            json=[{"number": 3, "html_url": "https://github.com/bamr87/it-journey/pull/3", "head": {"ref": branch}}],
        )
        worker(services.request_publish, post, alice)
    post.refresh_from_db()
    assert post.status == "failed" and "already open: https://github.com/bamr87/it-journey/pull/3" in post.error
    assert post.external_url == "https://github.com/bamr87/it-journey/pull/3"


@override_settings(DISTRIBUTION_ARMED={"github_pr"})
@pytest.mark.parametrize(
    ("where", "says"),
    [("repo", "GitHub rejected the credential (401)"), ("contents", "API rate limit has been exceeded")],
)
def test_github_failures_are_reported_as_themselves_never_answered_with_another_write(alice, page, worker, where, says):
    channel = channel_for(
        page, "github_pr", {"repo": "bamr87/it-journey", "directory": "sites/news"}, {"token": "ghp_x"}
    )
    post = ready(channel, page, alice)
    branch = f"distribute/{post.public_id.hex[:12]}"
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        github(rsps, branch, repo=401 if where == "repo" else 200, contents=403 if where == "contents" else 404)
        worker(services.request_publish, post, alice)
        writes = [c for c in rsps.calls if c.request.method in ("PUT", "POST") and "/git/refs" not in c.request.url]
    post.refresh_from_db()
    assert post.status == "failed" and says in post.error
    assert writes == [], "a refused read is not answered by writing a file or opening a pull request"


# ── email: a newsroom newsletter ────────────────────────────────────────────


@override_settings(DISTRIBUTION_ARMED={"email"})
def test_an_email_channel_sends_the_story_as_an_issue_of_its_newsletter(desk, advance, ed, worker):
    story = advance(desk, "published", headline="Bridge reopens")
    newsletter = Newsletter.objects.create(site=desk.site, name="The Weekly", slug="weekly")
    Subscriber.objects.create(newsletter=newsletter, email="reader@example.com", status=Subscriber.Status.CONFIRMED)
    channel = Channel.objects.create(site=desk.site, kind="email", name="Weekly", newsletter=newsletter, armed=True)
    with pytest.raises(Exception, match="story"):
        services.compose(channel, user=ed, page=story.page)
    post = services.approve(services.compose(channel, user=ed, story=story, commentary="This week: the bridge."), ed)
    worker(services.request_publish, post, ed)
    post.refresh_from_db()
    assert post.status == "published" and post.external_id.startswith("issue:")
    assert [m.to for m in mail.outbox] == [["reader@example.com"]]
    assert "Bridge reopens" in mail.outbox[0].body and "This week: the bridge." in mail.outbox[0].body
    assert LedgerEntry.objects.get(channel=channel).urn == post.external_id
