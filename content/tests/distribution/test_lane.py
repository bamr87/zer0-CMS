"""The LinkedIn lane over a site's own files (`distribution/lane/`), end to end
— ported from the Ruby lane's tests (`rails/test/zer0_cms/test_distribution.rb`)
and held to what the Ruby lane computed on the same checkout
(`golden/ruby-lane.json`). Recorded HTTP only: an unscripted request fails.
"""

import io
import json
import threading

import httpx
import pytest
from django.core.management import call_command

from distribution.lane import cli, drafts
from distribution.lane.pipeline import Pipeline, banned_patterns
from distribution.lane.site import Config, ConfigError, default_commentary, hashtags, slug
from distribution.ledger import Ledger, LedgerError, serialize
from distribution.linkedin.session import Credentials

from .conftest import AUTHOR, GOLDEN, MCP_POST, MCP_URL, NOW, TOKEN, tree

REST = "https://api.linkedin.com/rest"
ARMED = {"ZER0_LINKEDIN_PUBLISH": "1"}


def nosleep(_seconds):
    return None


def credentials(**values):
    return Credentials(**{"access_token": TOKEN, "refresh_token": "", "client_id": "", "client_secret": "", **values})


def pipeline(root, env=None, creds=None):
    return Pipeline(Config(root, env=env or {}), sleeper=nosleep, clock=lambda: NOW, credentials=creds or credentials())


def script_publish(web, urn="urn:li:share:7000"):
    web.post(f"{REST}/images?action=initializeUpload").respond(
        200, json={"value": {"uploadUrl": "https://www.linkedin.com/dms-uploads/abc/0", "image": "urn:li:image:IMG"}}
    )
    web.put("https://www.linkedin.com/dms-uploads/abc/0").respond(201)
    web.get(f"{REST}/images/urn%3Ali%3Aimage%3AIMG").respond(200, json={"status": "AVAILABLE"})
    return web.post(f"{REST}/posts").respond(201, headers={"x-restli-id": urn})


def approved_draft(pipe):
    draft = pipe.compose("tech/2026-07-06-mcp-for-the-back-office")
    assert pipe.approve(draft).state == "approved"
    return pipe.draft(draft.id)


# ── the ledger's bytes ──────────────────────────────────────────────────────


def test_ledger_bytes_are_python_json_dump_as_the_ruby_lane_wrote_them():
    data = {
        "https://bash-365.com/posts/2026/07/08/when-the-numbers/": {
            "linkedin_urn": "urn:li:share:7488646927748829184",
            "urn": "urn:li:share:7488646927748829184",
            "posted_at": "2026-07-30T17:29:20Z",
            "type": "article",
            "source_file": "pages/_posts/corp/x.md",
            "image_urn": "urn:li:image:D5610AQEvxKjg_zaDpg",
            "target": "linkedin",
        },
        "_meta": {"b": [1, 2.5, None, True], "a": {}},
    }
    expected = """{
  "_meta": {
    "a": {},
    "b": [
      1,
      2.5,
      null,
      true
    ]
  },
  "https://bash-365.com/posts/2026/07/08/when-the-numbers/": {
    "image_urn": "urn:li:image:D5610AQEvxKjg_zaDpg",
    "linkedin_urn": "urn:li:share:7488646927748829184",
    "posted_at": "2026-07-30T17:29:20Z",
    "source_file": "pages/_posts/corp/x.md",
    "target": "linkedin",
    "type": "article",
    "urn": "urn:li:share:7488646927748829184"
  }
}
"""
    assert serialize(data) == expected
    escapes = serialize({"café": '\u007f \U0001f680 "q" \\ \n\t\u0001', "z": [], "e": 1e-05, "big": 1e16, "f": 5.0})
    assert escapes == (
        '{\n  "big": 1e+16,\n  "caf\\u00e9": "\\u007f \\ud83d\\ude80 \\"q\\" \\\\ \\n\\t\\u0001",\n  "e": 1e-05,\n'
        '  "f": 5.0,\n  "z": []\n}\n'
    )


def test_the_ledger_reads_either_urn_name_and_writes_both_keeping_other_lanes_keys(tmp_path):
    path = tmp_path / "log.json"
    path.write_text(
        json.dumps(
            {
                "https://a.test/x/": {"linkedin_urn": "urn:li:share:1"},
                "_token": {"expires_at": "z"},
                "https://a.test/y/": {"type": "article"},
                "_schema": 2,
            }
        )
    )
    ledger = Ledger(path)
    assert ledger.urn_for("https://a.test/x/") == "urn:li:share:1"
    assert ledger.urn_for("https://a.test/y/") is None
    assert [k for k, _ in ledger.shares()] == ["https://a.test/x/"]
    from distribution.ledger import entry_for

    ledger.record(
        "https://a.test/z/",
        entry_for(urn="urn:li:share:2", kind="article", target="linkedin", author=AUTHOR, source_file="p.md", now=NOW),
    )
    data = json.loads(path.read_text())
    assert data["https://a.test/z/"] == {
        "linkedin_urn": "urn:li:share:2",
        "urn": "urn:li:share:2",
        "posted_at": "2026-09-14T12:00:00Z",
        "target": "linkedin",
        "type": "article",
        "author": AUTHOR,
        "source_file": "p.md",
    }
    assert path.read_text() == serialize(data), "the file is Python-formatted"
    assert "_token" in data and data["_schema"] == 2, "other lanes' keys survive a rewrite"


def test_an_unreadable_ledger_is_never_read_as_empty_or_rewritten(tmp_path):
    path = tmp_path / "log.json"
    path.write_text("{ not json")
    ledger = Ledger(path)
    assert not ledger.readable
    with pytest.raises(LedgerError):
        ledger.record("https://a.test/", {"urn": "urn:li:share:1"})
    assert path.read_text() == "{ not json"


def test_concurrent_records_keep_every_entry(tmp_path):
    ledger = Ledger(tmp_path / "log.json")
    threads = [
        threading.Thread(target=ledger.record, args=(f"https://a.test/{i}/", {"urn": f"urn:li:share:{i}"}))
        for i in range(10)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ledger.shares()) == 10


# ── the settings ────────────────────────────────────────────────────────────


def test_config_layers_and_what_a_file_cannot_do(checkout, make_checkout):
    config = Config(checkout, env={})
    assert (config.author, config.author_type, config.site_url) == (AUTHOR, "organization", "https://example.test")
    assert (config.queue, config.ledger) == ("drafts/linkedin", ".github/linkedin-log.json")
    assert config.problems == [] and not config.publish_armed
    override = Config(checkout, env={"LINKEDIN_ORG_URN": "urn:li:organization:1", "LINKEDIN_API_VERSION": "202607"})
    assert (override.author, override.api_version) == ("urn:li:organization:1", "202607")
    assert Config(checkout, env=ARMED).publish_armed
    sneaky = Config(make_checkout(linkedin={"publishAllow": True, "armed": True}), env={})
    assert not sneaky.publish_armed
    assert any("publishAllow is not a setting" in w for w in sneaky.warnings)


def test_config_falls_back_to_config_yml_and_refuses_paths_outside_the_repository(make_checkout):
    root = make_checkout(zer0={})
    with (root / "_config.yml").open("a") as out:
        out.write('linkedin:\n  org_urn: "urn:li:organization:42"\n')
    config = Config(root, env={})
    assert not config.configured
    assert (config.author, config.queue, config.accept_statuses) == (
        "urn:li:organization:42",
        ".zer0/drafts/linkedin",
        ["approved"],
    )
    for bad in ({"queue": "../elsewhere"}, {"ledger": "/etc/ledger.json"}):
        with pytest.raises(ConfigError):
            Config(make_checkout(linkedin=bad), env={})


def test_config_errors_and_jsonc(make_checkout):
    errors = "\n".join(
        Config(
            make_checkout(
                linkedin={"author": "urn:li:company:5", "apiVersion": "202401", "acceptStatuses": ["published"]}
            ),
            env={},
        ).errors
    )
    assert (
        "author must be" in errors
        and "support window" in errors
        and "acceptStatuses may hold pending and approved" in errors
    )
    root = make_checkout()
    (root / "zer0.json").write_text(
        '{\n  // comments, as the extension writes it\n  "distribution": {"linkedin": {"author": "urn:li:person:x",},},\n}\n'
    )
    assert Config(root, env={}).author == "urn:li:person:x"


# ── drafts ──────────────────────────────────────────────────────────────────


def test_a_new_draft_is_always_pending_and_never_overwrites(checkout):
    config = Config(checkout, env={})
    first = drafts.create(
        config,
        type="article",
        slug="2026-09-14-hello",
        body="Commentary.\n",
        meta={"status": "approved", "source": MCP_POST, "title": "Hello: world"},
    )
    assert first.status == "pending"
    assert (
        first.path.read_text()
        == f'---\ntype: article\nstatus: pending\nsource: {MCP_POST}\ntitle: "Hello: world"\n---\n\nCommentary.\n'
    )
    second = drafts.create(config, type="update", slug="2026-09-14-hello", body="Text")
    assert second.relative == "drafts/linkedin/2026-09-14-hello-2.md"
    with pytest.raises(ValueError):
        drafts.create(config, type="article", slug="../escape", body="x")


def test_the_queue_skips_readmes_and_nested_folders_and_status_changes_one_line(checkout):
    config = Config(checkout, env={})
    queue = checkout / "drafts" / "linkedin"
    (queue / "examples").mkdir(parents=True)
    (queue / "README.md").write_text("# The queue\n")
    (queue / "examples" / "2026-01-01-example.md").write_text("---\nstatus: pending\n---\nx\n")
    path = queue / "2026-01-02-b.md"
    path.write_text("---\n# reviewer: amr\ntype: text\nstatus: pending\nsource: x\n---\nBody status: ok\n")
    assert [d.id for d in drafts.all_drafts(config)] == ["2026-01-02-b"]
    draft = drafts.find_required(config, "2026-01-02-b.md")
    assert draft.type == "update"
    drafts.set_status(draft, "published", {"linkedin_urn": "urn:li:share:9"})
    assert (
        path.read_text()
        == "---\n# reviewer: amr\ntype: text\nstatus: published\nsource: x\nlinkedin_urn: urn:li:share:9\n---\nBody status: ok\n"
    )
    assert drafts.find(config, "../../zer0.json") is None, "a reference is reduced to a name inside the queue"
    with pytest.raises(ValueError):
        drafts.find(config, "..")


def test_a_patterns_file_adds_rules_and_a_broken_one_degrades_to_none(make_checkout):
    from suggestions.guard import guard_text

    root = make_checkout(linkedin={"bannedPatternsFile": "brand/bans.json"})
    (root / "brand").mkdir()
    (root / "brand" / "bans.json").write_text(
        '[{ "name": "synergize", "pattern": "\\\\bsynergi[sz]e\\\\b", "flags": "i" }]'
    )
    config = Config(root, env={})
    assert any(f["message"].endswith("(synergize)") for f in guard_text("We Synergize.", banned_patterns(config)))
    (root / "brand" / "bans.json").write_text('[{ "name": "broken", "pattern": "(" }]')
    assert banned_patterns(config) == []


# ── permalinks, sources and the first draft ─────────────────────────────────


def test_permalinks_follow_jekyll_as_the_ruby_lane_computed_them(checkout):
    from distribution.permalink import path_for, slugify

    pipe = pipeline(checkout)
    urls = {e.relative: path_for(pipe.catalog.config, e) for e in pipe.catalog.entries}
    assert urls == GOLDEN["permalinks"]
    assert slugify("The Value of  X!") == "the-value-of-x"
    assert slugify("Hello Wörld") == "hello-wörld"


def test_every_site_in_the_repository_gets_the_urls_the_ruby_lane_gave_it():
    """The Ruby catalog and this reader disagree only on which files are pages (`_drafts`, undated posts, HTML
    pages); on every page both read, the URL is the same."""
    from django.conf import settings

    from distribution.lane.site import catalog
    from distribution.permalink import path_for

    compared = 0
    for name, recorded in GOLDEN["sites"].items():
        found = catalog(settings.REPO_ROOT / "sites" / name, now=NOW)
        ours = {e.relative: e for e in found.entries}
        for relative, expected in recorded.items():
            if relative in ours:
                entry = ours[relative]
                assert path_for(found.config, entry) == expected["url"], f"{name}: {relative}"
                assert entry.kind == expected["kind"] and entry.live == expected["live"], f"{name}: {relative}"
                compared += 1
        assert len(ours) >= len(recorded) - 5, f"{name}: the reader lost pages the Ruby catalog had"
    assert compared > 500


def test_sources_are_live_titled_non_structural_pages_in_the_configured_collections(checkout):
    pipe = pipeline(checkout)
    found = pipe.sources()
    assert [s.entry.relative for s in found] == ["pages/_posts/tech/2026-07-10-moved.md", MCP_POST]
    assert next(s for s in found if s.entry.relative == MCP_POST).url == MCP_URL
    recorded = [{k: v for k, v in s.items() if k != "date"} for s in GOLDEN["sources"]]
    assert [{k: v for k, v in s.as_dict().items() if k != "date"} for s in found] == recorded
    for ref in ("tech/2026-07-06-mcp-for-the-back-office", MCP_POST, "mcp-for-the-back-office"):
        assert pipe.resolve_source(ref).relative == MCP_POST, ref
    assert pipe.resolve_source("https://elsewhere.test/") is None


def test_the_default_commentary_is_the_python_lanes(checkout):
    assert hashtags(["mcp", "back-office", "ai", "extra"]) == "#MCP #BackOffice #AI"
    for tags, limit, expected in GOLDEN["hashtags"]:
        assert hashtags(tags, limit) == expected
    entry = pipeline(checkout).resolve_source(MCP_POST)
    assert default_commentary(entry) == GOLDEN["default_commentary"]
    assert slug(entry.source_relative) == GOLDEN["slug"]


# ── preview, approve, publish ───────────────────────────────────────────────


def test_a_draft_and_its_preview_are_the_ruby_lanes_and_a_preview_touches_nothing(checkout, web):
    pipe = pipeline(checkout)
    draft = pipe.compose("tech/2026-07-06-mcp-for-the-back-office")
    assert draft.relative == GOLDEN["draft_relative"]
    assert draft.path.read_text() == GOLDEN["draft_file"]
    before = tree(checkout)
    preview = pipeline(checkout, creds=credentials(access_token="")).preview(draft)
    assert tree(checkout) == before and not web.calls
    assert preview.as_dict(checkout) == GOLDEN["preview"]
    assert [b.kind for b in preview.blockers] == ["status_not_accepted", "publish_disabled", "no_credential"]
    assert preview.problems == [], "a pending draft is waiting for approval, not broken"
    update = pipeline(checkout, creds=credentials(access_token="")).compose_update(
        "A plain update (with parens) that says a real thing.", slug="note"
    )
    assert (
        pipeline(checkout, creds=credentials(access_token="")).preview(update).as_dict(checkout)
        == GOLDEN["update_preview"]
    )
    status = pipeline(checkout, creds=credentials(access_token="")).status()
    status.pop("site")
    assert status == {**GOLDEN["status"], "drafts": {"pending": 2, "approved": 0, "published": 0}}


def test_approval_is_pending_only_and_the_guard_can_refuse_it(checkout):
    pipe = pipeline(checkout)
    draft = pipe.compose(MCP_POST)
    assert pipe.approve(draft).state == "approved"
    assert pipe.draft(draft.id).status == "approved"
    assert pipe.approve(pipe.draft(draft.id)).messages == ["draft is already approved"]
    bad = pipe.compose_update("Our world-class team.", slug="bad")
    assert pipe.approve(bad).state == "blocked"
    assert pipe.draft(bad.id).status == "pending"


def test_a_rehearsal_and_an_unarmed_live_run_send_nothing(checkout, web):
    draft = approved_draft(pipeline(checkout))
    before = tree(checkout)
    assert pipeline(checkout).publish(draft).state == "rehearsed"
    outcome = pipeline(checkout).publish(draft, live=True)
    assert outcome.state == "blocked" and "not armed" in " ".join(outcome.messages)
    assert not web.calls and tree(checkout) == before


def test_a_live_armed_publish_uploads_posts_records_and_marks_the_draft(checkout, web):
    post = script_publish(web)
    draft = approved_draft(pipeline(checkout))
    outcome = pipeline(checkout, ARMED).publish(draft, live=True)
    assert (outcome.state, outcome.urn) == ("published", "urn:li:share:7000"), outcome.messages
    assert [c.request.method for c in web.calls] == ["POST", "PUT", "GET", "POST"]
    payload = json.loads(post.calls.last.request.content)
    assert payload["content"]["article"]["thumbnail"] == "urn:li:image:IMG" and payload["author"] == AUTHOR
    assert payload["commentary"] == GOLDEN["default_commentary"]
    entry = json.loads((checkout / ".github/linkedin-log.json").read_text())[MCP_URL]
    assert [entry[k] for k in ("linkedin_urn", "urn", "source_file", "image_urn")] == [
        "urn:li:share:7000",
        "urn:li:share:7000",
        MCP_POST,
        "urn:li:image:IMG",
    ]
    published = pipeline(checkout).draft(draft.id)
    assert (published.status, published.meta["linkedin_urn"]) == ("published", "urn:li:share:7000")
    again = pipeline(checkout, ARMED).publish(published, live=True)
    assert again.state == "blocked" and len(web.calls) == 4, "a published draft never posts twice"
    with pytest.raises(ValueError):
        pipeline(checkout).compose(MCP_POST)


def test_a_run_that_died_after_the_ledger_is_finished_not_repeated(checkout, web):
    from distribution.ledger import entry_for

    draft = approved_draft(pipeline(checkout))
    Ledger(checkout / ".github/linkedin-log.json").record(
        MCP_URL, entry_for(urn="urn:li:share:55", kind="article", target="linkedin")
    )
    outcome = pipeline(checkout, ARMED).publish(draft, live=True)
    assert (outcome.state, outcome.urn) == ("skipped", "urn:li:share:55")
    assert not web.calls and pipeline(checkout).draft(draft.id).status == "published"


def test_an_unconfirmed_create_blocks_every_later_run_until_a_person_looks(checkout, web):
    route = web.post(f"{REST}/posts").respond(503, json={"message": "down"})
    pipe = pipeline(checkout)
    draft = pipe.compose(MCP_POST)
    drafts.set_status(draft, "approved", {"no_thumbnail": True})
    outcome = pipeline(checkout, ARMED).publish(pipe.draft(draft.id), live=True)
    text = " ".join(outcome.messages)
    assert outcome.state == "failed" and "HTTP 503" in text and "may exist" in text
    assert route.call_count == 1
    ledger = Ledger(checkout / ".github/linkedin-log.json")
    assert ledger.urn_for(MCP_URL) is None and ledger.unconfirmed(MCP_URL)["state"] == "unconfirmed"
    assert pipe.draft(draft.id).status == "approved"
    again = pipeline(checkout, ARMED).publish(pipe.draft(draft.id), live=True)
    assert again.state == "blocked" and "may have posted" in " ".join(again.messages)
    assert [o.state for o in pipeline(checkout, ARMED).publish_queue(live=True)] == ["blocked"]
    assert route.call_count == 1, "no run sends an unconfirmed post again"
    recorded = pipeline(checkout).record_post(pipe.draft(draft.id), "urn:li:share:42")
    assert recorded.state == "recorded" and ledger.urn_for(MCP_URL) == "urn:li:share:42"
    assert ledger.unconfirmed(MCP_URL) is None and pipe.draft(draft.id).status == "published"


def test_a_success_without_a_post_id_is_unconfirmed_and_force_lifts_it(checkout, web):
    pipe = pipeline(checkout)
    draft = pipe.compose(MCP_POST)
    drafts.set_status(draft, "approved", {"no_thumbnail": True})
    route = web.post(f"{REST}/posts").respond(201)
    assert pipeline(checkout, ARMED).publish(pipe.draft(draft.id), live=True).state == "failed"
    assert Ledger(checkout / ".github/linkedin-log.json").unconfirmed(MCP_URL)
    route.respond(422, json={"message": "bad"})
    assert pipeline(checkout, ARMED).publish(pipe.draft(draft.id), live=True, force=True).state == "failed"
    assert route.call_count == 2, "force lifts the unconfirmed gate for a person who checked"
    with pytest.raises(ValueError):
        pipeline(checkout, ARMED).publish_queue(live=True, force=True)


def test_pending_publishes_only_as_a_merged_draft(make_checkout):
    root = make_checkout(linkedin={"acceptStatuses": ["pending", "approved"]})
    draft = pipeline(root).compose(MCP_POST)
    local = next(b for b in pipeline(root, ARMED).preview(draft).blockers if b.kind == "status_not_accepted")
    assert "merged" in local.message
    merged = pipeline(root, {**ARMED, "ZER0_LINKEDIN_MERGED": "1"}).preview(draft)
    assert "status_not_accepted" not in [b.kind for b in merged.blockers]
    assert Config(root, env={}).publishable_statuses == ["approved"]
    assert len(pipeline(root, ARMED).publish_queue()) == 1, "a rehearsal still shows what CI would send"
    assert pipeline(root, ARMED).publish_queue(live=True) == [], "a live run here sends nothing pending"


def test_a_401_refreshes_once_and_repeats(checkout, web):
    token = web.post("https://www.linkedin.com/oauth/v2/accessToken").respond(
        200, json={"access_token": "new-token-123456", "expires_in": 5184000}
    )

    def create(request):
        if request.headers["Authorization"] == "Bearer new-token-123456":
            return httpx.Response(201, headers={"x-restli-id": "urn:li:share:8"})
        return httpx.Response(401, json={"message": "expired"})

    web.post(f"{REST}/posts").mock(side_effect=create)
    pipe = pipeline(checkout)
    draft = pipe.compose_update("A plain update that says a real thing.", slug="note")
    drafts.set_status(draft, "approved")
    creds = credentials(
        access_token="old-token-123456", refresh_token="RT-123456789", client_id="cid", client_secret="csecret-abcdef"
    )
    outcome = pipeline(checkout, ARMED, creds).publish(pipe.draft(draft.id), live=True)
    assert (outcome.state, outcome.urn) == ("published", "urn:li:share:8")
    assert [str(c.request.url).rsplit("/", 1)[-1] for c in web.calls] == ["posts", "accessToken", "posts"]
    assert dict(httpx.QueryParams(token.calls.last.request.content.decode()))["grant_type"] == "refresh_token"
    assert (
        Ledger(checkout / ".github/linkedin-log.json").urn_for("draft:drafts/linkedin/2026-09-14-note.md")
        == "urn:li:share:8"
    )


def test_force_lifts_the_guard_but_never_the_approval_or_arming_gates(checkout, web):
    route = web.post(f"{REST}/posts").respond(201, headers={"x-restli-id": "urn:li:share:3"})
    pipe = pipeline(checkout)
    draft = pipe.compose_update("Our world-class desk.", slug="loud")
    assert pipeline(checkout, ARMED).publish(draft, live=True, force=True).state == "blocked"
    drafts.set_status(draft, "approved")
    assert pipeline(checkout).publish(pipe.draft(draft.id), live=True, force=True).state == "blocked"
    assert route.call_count == 0
    assert pipeline(checkout, ARMED).publish(pipe.draft(draft.id), live=True).state == "blocked"
    assert pipeline(checkout, ARMED).publish(pipe.draft(draft.id), live=True, force=True).state == "published"


def test_an_unreadable_ledger_blocks_publishing(checkout):
    draft = approved_draft(pipeline(checkout))
    (checkout / ".github").mkdir(exist_ok=True)
    (checkout / ".github" / "linkedin-log.json").write_text("{ broken")
    assert "ledger_unreadable" in [b.kind for b in pipeline(checkout, ARMED).preview(draft).blockers]


# ── statistics ──────────────────────────────────────────────────────────────


def test_statistics_join_onto_content_paths_and_merge_into_performance_json(checkout, web):
    from distribution.ledger import entry_for

    ledger = Ledger(checkout / ".github/linkedin-log.json")
    ledger.record(
        MCP_URL, entry_for(urn="urn:li:share:1", kind="article", target="linkedin", source_file=MCP_POST, author=AUTHOR)
    )
    ledger.record(
        "https://example.test/other/",
        entry_for(
            urn="urn:li:share:2", kind="article", target="linkedin", source_file="x.md", author="urn:li:organization:9"
        ),
    )
    (checkout / ".cms" / "distribution").mkdir(parents=True)
    (checkout / ".cms/distribution/performance.json").write_text(
        json.dumps({"content": {"old.md": {"impressions": 1}}})
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
    result = pipeline(checkout).statistics(write=True)
    assert result["performance"] == {
        MCP_POST: {"impressions": 90, "clicks": 4, "reactions": 5, "comments": 1, "shares": 0, "engagements": 6}
    }
    assert result["skipped"] == ["https://example.test/other/"], "another author's post is not read as this author's"
    data = json.loads((checkout / ".cms/distribution/performance.json").read_text())
    assert list(data) == ["generated_at", "note", "content"]
    assert sorted(data["content"]) == sorted(["old.md", MCP_POST])
    assert data["note"] == "Aggregate statistics for the author's own content. No per-reader data."


# ── the command line ────────────────────────────────────────────────────────


def run(args, env=None):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(args, out=out, err=err, env=env or {}, sleeper=nosleep)
    return code, out.getvalue(), err.getvalue()


def test_the_command_line_walks_the_governed_path(checkout, web):
    code, out, _ = run(["draft", "tech/2026-07-06-mcp-for-the-back-office", "--site", str(checkout)])
    assert code == 0 and "status: pending" in out
    draft = drafts.all_drafts(Config(checkout, env={}))[0].id
    assert run(["preview", draft, "--site", str(checkout)])[0] == 0, "a pending draft is waiting, not broken"
    assert run(["publish", "--site", str(checkout), "--force"])[0] == 1, "--force needs a draft"
    assert run(["approve", draft, "--site", str(checkout)])[0] == 0
    assert run(["preview", "--site", str(checkout)])[0] == 0
    code, out, _ = run(["publish", "--site", str(checkout)])
    assert code == 0 and "REHEARSED" in out
    code, out, _ = run(["publish", "--site", str(checkout), "--live"])
    assert code == 1 and "not armed" in out
    code, out, _ = run(["publish", "--site", str(checkout), draft, "--live"], env=ARMED)
    assert code == 1 and "no LinkedIn credential" in out, "the workflow names the draft after the options"
    code, out, _ = run(["status", "--site", str(checkout), "--json"], env={"LINKEDIN_ACCESS_TOKEN": TOKEN})
    report = json.loads(out)
    assert (code, report["drafts"]["approved"], report["armed"]) == (0, 1, False)
    assert TOKEN not in out and not web.calls


def test_the_command_line_plan_usage_errors_and_the_management_command(checkout):
    code, out, _ = run(["plan"])
    assert code == 0 and "returns   aggregate counts for the member's own post" in out
    assert run(["frobnicate"])[0] == 2
    assert run(["help"])[0] == 0
    assert run(["approve", "missing", "--site", str(checkout)])[0] == 1
    out = io.StringIO()
    call_command("linkedin", "sources", "--site", str(checkout), "--json", stdout=out)
    assert [s["url"] for s in json.loads(out.getvalue())] == [s["url"] for s in GOLDEN["sources"]]
    with pytest.raises(SystemExit) as stopped:
        call_command(
            "linkedin", "approve", "missing", "--site", str(checkout), stdout=io.StringIO(), stderr=io.StringIO()
        )
    assert stopped.value.code == 1


def test_the_doctors_distribution_check(tmp_path):
    """The Ruby doctor's `check_distribution` (test_doctor.rb), ported with the lane it reads."""
    from distribution.lane.doctor import findings

    def site(block=None, **files):
        root = tmp_path / f"s{len(list(tmp_path.iterdir()))}"
        root.mkdir()
        zer0 = '{\n  // console dialect\n  "$schema": "https://example.com/zer0.schema.json",\n}\n'
        if block is not None:
            zer0 = zer0.replace('"$schema"', f'"distribution": {{ "linkedin": {block} }},\n  "$schema"')
        (root / "zer0.json").write_text(zer0)
        for rel, text in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text)
        return root

    def rules(found, severity=None):
        return sorted(f["rule"] for f in found if severity in (None, f["severity"]))

    valid = '{ "author": "urn:li:organization:1", "siteUrl": "https://example.test", "ledger": "log.json" }'
    assert findings(site(valid)) == [] and findings(site()) == []
    bad = findings(site('{ "author": "urn:li:company:1", "publishAllow": true }'))
    assert rules(bad, "error") == ["distribution-config-invalid"] and "distribution-config" in rules(bad, "warning")
    assert "distribution-ledger-unreadable" in rules(findings(site(valid, **{"log.json": "{ not json"})), "error")
    assert "distribution-config-invalid" in rules(
        findings(site('{ "author": "urn:li:person:x", "queue": "../outside" }')), "error"
    )
    vendored = findings(site(**{"scripts/features/linkedin/posts.py": "# publisher\n"}))
    assert [(f["severity"], f["file"], f["check_id"], len(f["fingerprint"])) for f in vendored] == [
        ("warning", "scripts/features/linkedin/posts.py", "distribution", 12)
    ]


def test_the_oauth_callback_request_line():
    assert cli.parse_request_line("GET /callback?code=abc&state=s1 HTTP/1.1\r\n") == {"code": "abc", "state": "s1"}
    assert cli.parse_request_line("GET /favicon.ico HTTP/1.1\r\n") is None
    assert cli.parse_request_line("POST /callback?code=abc HTTP/1.1\r\n") is None
