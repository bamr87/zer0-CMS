"""Directives become briefs (sites/services.py `pull_directives`, the `directives` job, `manage.py site_job
directives`): a managed site reads the open `editorial:directive` issues of its GitHub pull-request channel's
repository — the issues bamr87/bamr87's content atlas files — and makes one brief per new `write` or `refresh`
directive, once; it fails with a sentence and no request when the site has no such channel; a brief keeps its
directive through generation and through the brief API; nothing is published. PyGithub's HTTP is recorded
(`responses`), as distribution's tests do it: nothing reaches GitHub."""

import json
from io import StringIO

import pytest
import responses
from django.core.management import call_command
from responses import matchers
from rest_framework.test import APIClient
from wagtail.models import Site

from ai import services as ai
from ai.models import Assistant, Brief, Visibility
from distribution.models import Channel
from sites import services
from sites.models import ManagedSite
from tests.ai.test_services import DETAIL

REPO = "bash-365/bash-365.com"
GITHUB = f"https://api.github.com:443/repos/{REPO}"  # what PyGithub requests
NARRATIVE = "Practical IT for small firms, from people who run it."

pytestmark = pytest.mark.django_db


def body(key, kind="write", *, path="", pillar="smb-strategy"):
    """An issue body exactly as the hub's `content_atlas.issue_body` writes it."""
    lines = [
        f"<!-- editorial-directive key={key} site=bash-365.com -->",
        "",
        f"**Editorial directive** · kind `{kind}` · priority `P2`" + (f" · pillar `{pillar}`" if pillar else ""),
        "",
        f"Write the piece {key} asks for.",
        "",
    ]
    if path:
        lines += [f"Document: `{path}`", ""]
    lines += [
        "### The narrative this serves",
        "",
        f"> {NARRATIVE}",
        "",
        "---",
        "_Filed by the hub's content atlas from an approved entry in `bamr87/bamr87` `_data/editorial.yml`._",
    ]
    return "\n".join(lines)


def issue(number, title, text, **extra):
    return {
        "number": number,
        "title": title,
        "body": text,
        "state": "open",
        "html_url": f"https://github.com/{REPO}/issues/{number}",
        "url": f"https://api.github.com/repos/{REPO}/issues/{number}",
        **extra,
    }


ISSUES = [
    issue(38, "[editorial] Backups for a five-person office", body("human:backups")),
    issue(39, "[editorial] Refresh the VPN guide", body("refresh:vpn", "refresh", path="pages/_posts/vpn.md")),
    issue(40, "[editorial] Fix descriptions", body("hygiene:description-length", "fix", pillar="")),
    issue(41, "Labelled by hand", "No marker here."),
    {
        **issue(42, "A pull request", body("human:pr")),
        "html_url": f"https://github.com/{REPO}/pull/42",
        "pull_request": {"url": f"https://api.github.com/repos/{REPO}/pulls/42"},
    },
]


def github(rsps, issues=ISSUES, *, status=200):
    rsps.add(
        responses.GET,
        GITHUB,
        status=status,
        json={"url": f"https://api.github.com/repos/{REPO}", "full_name": REPO, "message": "Bad credentials"},
    )
    if status == 200:
        rsps.add(
            responses.GET,
            f"{GITHUB}/issues",
            json=issues,
            match=[
                matchers.query_param_matcher({"state": "open", "labels": "editorial:directive"}, strict_match=False)
            ],
        )


@pytest.fixture
def managed(site_root):
    return ManagedSite.objects.create(site=Site.objects.get(root_page=site_root), key="bash-365", checkout="sites/x")


@pytest.fixture
def channel(managed):
    made = Channel.objects.create(site=managed.site, kind="github_pr", name="GitHub", settings={"repo": REPO})
    made.set_credentials({"token": "ghp_test_token"})
    made.save()
    return made


def test_the_hub_issue_body_is_read_back():
    found = services.parse_directive(body("refresh:vpn", "refresh", path="pages/_posts/vpn.md"))
    assert found == {
        "key": "refresh:vpn",
        "kind": "refresh",
        "priority": "P2",
        "pillar": "smb-strategy",
        "path": "pages/_posts/vpn.md",
        "brief": "Write the piece refresh:vpn asks for.",
        "narrative": NARRATIVE,
    }
    assert services.parse_directive("no marker") is None
    assert services.parse_directive(body("k", pillar="").replace("\n", "\r\n"))["pillar"] == ""


def test_a_pull_makes_one_brief_per_new_write_or_refresh_directive_once(alice, managed, channel):
    with responses.RequestsMock() as rsps:
        github(rsps)
        made = services.pull_directives(managed, user=alice)
        assert rsps.calls[-1].request.headers["Authorization"] == "token ghp_test_token"
    assert [b.title for b in made] == ["Backups for a five-person office", "Refresh the VPN guide"]
    backups, vpn = made
    assert backups.metadata["directive"] == {
        "url": f"https://github.com/{REPO}/issues/38",
        "number": 38,
        "title": "Backups for a five-person office",
        "key": "human:backups",
        "kind": "write",
        "priority": "P2",
        "pillar": "smb-strategy",
        "path": "",
    }
    assert (backups.owner, backups.site, backups.visibility) == (alice, managed.site, Visibility.SITE)
    assert (backups.status, backups.page, backups.page_type) == (Brief.DRAFT, None, "cms.ArticlePage")
    assert backups.parent_id == managed.site.root_page_id  # the fixture site has no posts collection
    assert "Write the piece human:backups asks for." in backups.prompt and NARRATIVE in backups.prompt
    assert "pages/_posts/vpn.md" in vpn.prompt and vpn.metadata["directive"]["kind"] == "refresh"

    with responses.RequestsMock() as rsps:  # pulled again: nothing new, the rest counted
        github(rsps)
        again = services.directives(managed, user=alice)
    assert (again["created"], again["skipped"], again["ignored"]) == ([], 2, 2)
    assert Brief.objects.filter(metadata__has_key="directive").count() == 2


def test_a_site_without_a_github_channel_fails_cleanly_and_asks_nothing(alice, managed):
    Channel.objects.create(site=managed.site, kind="github_pr", name="no token", settings={"repo": REPO})
    with responses.RequestsMock() as rsps, pytest.raises(services.SiteError, match="no GitHub pull-request channel"):
        services.pull_directives(managed, user=alice)
    assert not rsps.calls and not Brief.objects.exists()


def test_github_refusing_is_a_sentence(alice, managed, channel):
    with responses.RequestsMock() as rsps, pytest.raises(services.SiteError, match="401"):
        github(rsps, status=401)
        services.pull_directives(managed, user=alice)


def test_a_brief_belongs_only_to_a_site_its_owner_edits(bob, managed, channel):
    with responses.RequestsMock() as rsps, pytest.raises(services.SiteError, match="site its owner edits"):
        github(rsps)
        services.pull_directives(managed, user=bob)
    assert not Brief.objects.exists()


def run_command(*args):
    out = StringIO()
    try:
        call_command("site_job", "directives", "--site", "bash-365", *args, stdout=out)
    except SystemExit as e:
        return e.code, out.getvalue()
    return 0, out.getvalue()


def test_the_command_reports_what_it_created_and_skipped(alice, managed, channel, fake):
    writer = Assistant.objects.create(owner=alice, name="Writer")
    with responses.RequestsMock() as rsps:
        github(rsps)
        code, out = run_command("--user", "alice", "--generate", "--assistant", str(writer.public_id))
    assert code == 0, out
    assert "2 created, 0 already pulled, 2 not a write or refresh directive, 2 generating" in out
    assert set(Brief.objects.values_list("status", flat=True)) == {Brief.GENERATING}  # written, never applied

    with responses.RequestsMock() as rsps:
        github(rsps)
        code, out = run_command("--user", "alice")
    assert code == 0 and "0 created, 2 already pulled" in out


def test_the_command_without_a_channel_exits_non_zero_with_the_reason(alice, managed):
    code, out = run_command("--user", "alice")
    assert code == 1 and "no GitHub pull-request channel" in out


def test_a_brief_keeps_its_directive_through_generation_and_the_api(alice, managed, fake, worker):
    directive = {"url": f"https://github.com/{REPO}/issues/38", "number": 38, "title": "Backups"}
    brief = Brief.objects.create(
        owner=alice, site=managed.site, source_text="A text.", metadata={"directive": directive}
    )
    fake.script.append({"text": json.dumps(DETAIL)})
    worker(ai.generate_brief, brief, user=alice)
    brief.refresh_from_db()
    assert brief.status == Brief.READY and brief.metadata["directive"] == directive
    assert brief.metadata["slug"] == "cats-rule-the-sofa"  # the model's metadata, beside it

    client = APIClient()
    client.force_authenticate(alice)
    forged = {"directive": {"url": f"https://github.com/{REPO}/issues/1"}, "note": "mine"}
    answer = client.patch(f"/api/v2/ai/briefs/{brief.public_id}/", {"metadata": forged}, format="json")
    assert answer.status_code == 200, answer.json()
    assert answer.json()["metadata"] == {"note": "mine", "directive": directive}, "a request neither sets nor drops it"
    made = client.post("/api/v2/ai/briefs/", {"prompt": "x", "metadata": forged}, format="json")
    assert made.status_code == 201 and made.json()["metadata"] == {"note": "mine"}

    listed = client.get("/api/v2/ai/briefs/", {"site": managed.site.pk, "directive": "true"}).json()
    assert [b["id"] for b in listed["results"]] == [str(brief.public_id)]
    others = client.get("/api/v2/ai/briefs/", {"directive": "false"}).json()
    assert str(brief.public_id) not in [b["id"] for b in others["results"]]
