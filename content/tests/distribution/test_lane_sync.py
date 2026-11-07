"""Keeping a site and its LinkedIn page in step (the lane, `manage.py
linkedin sync | weekly | revise | revisit`): every shareable page has a post or
a draft waiting for one, the site knows each page's posts (`siteMap`), one
featured article a week from a ring of sections, revisions of a published
post's text, and the order a review loop takes the posts in. Recorded HTTP
only; the clock is the fixtures' `NOW`, a Monday (2026-09-14 12:00 UTC).
"""

import io
import json
from datetime import timedelta

import pytest

from distribution.lane import cli, drafts
from distribution.lane.pipeline import Pipeline
from distribution.lane.site import Config, ConfigError
from distribution.ledger import Ledger, entry_for

from .conftest import AUTHOR, MCP_POST, MCP_URL, NOW
from .test_lane import ARMED, REST, credentials, nosleep, script_publish

WEEKLY = {"ring": ["muses", "corp", "tech"], "anchor": "2026-09-07", "at": "tue 09:00", "timezone": "UTC"}
LEDGER = ".github/linkedin-log.json"


def lane(root, *, env=None, when=NOW):
    return Pipeline(Config(root, env=env or {}), sleeper=nosleep, clock=lambda: when, credentials=credentials())


def post(root, section, name, *, featured=False, date="2026-08-20T10:00:00.000Z"):
    path = root / "pages" / "_posts" / section / f"{date[:10]}-{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    flag = "featured: true\n" if featured else ""
    path.write_text(
        f"---\ntitle: {name.replace('-', ' ').capitalize()}\ndescription: About {name}\ndate: {date}\n"
        f"categories: [{section}]\n{flag}---\nBody.\n"
    )
    return path.relative_to(root).as_posix()


def shared(root, key, urn, *, source=None, when=NOW - timedelta(days=30)):
    Ledger(root / LEDGER).record(
        key, entry_for(urn=urn, kind="article", target="linkedin", author=AUTHOR, source_file=source, now=when)
    )


# ── every page on LinkedIn, and LinkedIn on every page ──────────────────────


def test_sync_reports_each_page_and_drafts_the_missing_ones(make_checkout):
    root = make_checkout({"siteMap": "_data/linkedin/posts.json"})
    muse = post(root, "muses", "a-quiet-thought")
    shared(root, MCP_URL, "urn:li:share:1", source=MCP_POST)
    shared(root, "https://elsewhere.test/posts/2026/07/06/mcp-for-the-back-office/", "urn:li:share:5")
    pipe = lane(root)
    states = {row["path"]: row["state"] for row in pipe.sync()}
    assert states[MCP_POST] == "shared" and states[muse] == "missing"
    assert "pages/_posts/tech/2026-08-01-not-yet.md" not in states, "a draft page is not shareable"
    out = io.StringIO()
    assert cli.main(["sync", "--site", str(root)], out=out, env={}) == 1, "a missing page is a gap the check shows"
    made = lane(root).draft_missing(limit=1)
    assert len(made) == 1 and made[0].status == "pending"
    queued = {row["path"]: row["state"] for row in lane(root).sync()}
    assert sorted(queued.values()).count("missing") == len(states) - 2 and "queued" in queued.values()
    assert lane(root).write_site_map() is True and lane(root).write_site_map() is False, "written only on a change"
    site_map = json.loads((root / "_data/linkedin/posts.json").read_text())
    assert site_map == {
        "/posts/2026/07/06/mcp-for-the-back-office/": {
            "posts": [
                {"posted_at": "2026-08-15T12:00:00Z", "url": "https://www.linkedin.com/feed/update/urn:li:share:1/"}
            ],
            "url": MCP_URL,
        }
    }


def test_a_publish_refreshes_the_site_map(make_checkout, web):
    root = make_checkout({"siteMap": "_data/linkedin/posts.json"})
    script_publish(web, urn="urn:li:share:77")
    draft = lane(root).compose(MCP_POST)
    assert lane(root).approve(draft).state == "approved"
    assert lane(root, env=ARMED).publish(lane(root).draft(draft.id), live=True).state == "published"
    posts = json.loads((root / "_data/linkedin/posts.json").read_text())["/posts/2026/07/06/mcp-for-the-back-office/"][
        "posts"
    ]
    assert [p["url"] for p in posts] == ["https://www.linkedin.com/feed/update/urn:li:share:77/"]


# ── the week's featured article ─────────────────────────────────────────────


def test_the_week_takes_the_rings_section_and_its_featured_post_once(make_checkout):
    root = make_checkout({"weekly": WEEKLY})
    newest = post(root, "corp", "newest-memo", date="2026-09-01T10:00:00.000Z")
    starred = post(root, "corp", "the-flagship", featured=True, date="2026-06-01T10:00:00.000Z")
    post(root, "muses", "a-quiet-thought")
    pipe = lane(root)
    # Monday 12:00: this week's Tuesday 09:00 is ahead, so this week (2026-W38, the ring's second week: corp).
    assert pipe.feature_week() == ("2026-W38", NOW.replace(day=15, hour=9))
    draft, message = pipe.weekly_feature()
    assert draft.meta["feature"] == "2026-W38" and draft.meta["section"] == "corp"
    assert draft.meta["source"] == starred, "a post marked featured goes before a newer one"
    assert draft.meta["publish_at"] == "2026-09-15 09:00" and draft.status == "pending"
    assert message.startswith("2026-W38: corp — ")
    again, said = lane(root).weekly_feature()
    assert again.relative == draft.relative and "already has its feature" in said
    # From the anchor's week, W37: muses, corp, tech, then round again — W40 muses, W41 corp.
    muses, _ = lane(root).weekly_feature("2026-W40")
    assert muses.meta["section"] == "muses"
    tech, _ = lane(root).weekly_feature("2026-W39")
    assert tech.meta["source"] == "pages/_posts/tech/2026-07-10-moved.md", "no post is marked: the newest goes"
    later, _ = lane(root).weekly_feature("2026-W41")  # corp again: the flagship is taken, the newest is next
    assert later.meta["source"] == newest
    after_tuesday = lane(root, when=NOW + timedelta(days=1, hours=1))
    assert after_tuesday.feature_week()[0] == "2026-W39", "past this week's slot, the next week's"


def test_a_feature_is_ledgered_by_its_week_so_the_page_keeps_its_own_share(make_checkout, web):
    root = make_checkout({"weekly": {**WEEKLY, "ring": ["tech"]}})
    route = script_publish(web, urn="urn:li:share:90")
    shared(root, MCP_URL, "urn:li:share:1", source=MCP_POST)
    draft, _ = lane(root).weekly_feature()
    assert lane(root).approve(draft).state == "approved"
    pipe = lane(root, env=ARMED, when=NOW + timedelta(days=1))
    outcome = pipe.publish(pipe.draft(draft.id), live=True)
    assert outcome.state == "published" and route.call_count == 1, outcome.messages
    ledger = Ledger(root / LEDGER)
    assert ledger.urn_for("feature:2026-W38") == "urn:li:share:90" and ledger.urn_for(MCP_URL) == "urn:li:share:1"
    assert lane(root).weekly_feature("2026-W38")[1] == "2026-W38 already has its feature: " + draft.relative


def test_weekly_settings_are_checked(make_checkout):
    errors = Config(
        make_checkout({"weekly": {"ring": [], "anchor": "soon", "at": "mon-fri 9", "when": 1}}), env={}
    ).errors
    assert [e.split(":")[0] for e in errors] == [
        "distribution.linkedin.weekly.when is not a setting (known",
        "distribution.linkedin.weekly.ring",
        "distribution.linkedin.weekly.anchor",
        "distribution.linkedin.weekly.at",
    ]
    with pytest.raises(ConfigError, match="no weekly feature configured"):
        lane(make_checkout()).weekly_feature()
    assert "siteMap must be a path inside the repository" in " ".join(
        Config(make_checkout({"siteMap": "../x.json"}), env={}).errors
    )


# ── a revision: new text for a post already out ─────────────────────────────


def test_a_revision_sets_a_published_posts_text_and_only_the_lanes_own(make_checkout, web):
    root = make_checkout({"cadence": {"timezone": "UTC", "slots": ["daily 11:00"]}})
    shared(root, MCP_URL, "urn:li:share:1", source=MCP_POST, when=NOW - timedelta(hours=2))
    update = web.post(f"{REST}/posts/urn%3Ali%3Ashare%3A1").respond(204)
    out = io.StringIO()
    assert (
        cli.main(
            [
                "revise",
                "urn:li:share:1",
                "--site",
                str(root),
                "--commentary",
                "Corrected: the standard is MCP 2025-06.",
            ],
            out=out,
            env={},
        )
        == 0
    )
    draft = next(d for d in lane(root).drafts() if d.type == "revision")
    assert lane(root).approve(draft).state == "approved"
    outcome = lane(root, env=ARMED).publish(lane(root).draft(draft.id), live=True)
    assert (outcome.state, outcome.urn) == ("published", "urn:li:share:1"), outcome.messages
    request = update.calls.last.request
    assert request.headers["X-RestLi-Method"] == "PARTIAL_UPDATE"
    assert json.loads(request.content) == {"patch": {"$set": {"commentary": "Corrected: the standard is MCP 2025-06."}}}
    entry = Ledger(root / LEDGER).entry(f"draft:{draft.relative}")
    assert entry["revises"] == "urn:li:share:1" and lane(root).draft(draft.id).status == "published"
    assert lane(root).history() == [NOW - timedelta(hours=2)], "a revision is not a new post to the cadence"
    # A revision takes no slot: a queue run under the cadence sends it at once, beside the draft that waits.
    again = drafts.create(
        lane(root).config, type="revision", slug="again", body="Corrected again.", meta={"revises": "urn:li:share:1"}
    )
    assert lane(root).approve(again).state == "approved"
    waiting = lane(root).compose_update("A note for the next slot.", slug="note")
    assert lane(root).approve(waiting).state == "approved"
    later = lane(root, env=ARMED, when=NOW + timedelta(hours=1))  # 13:00: today's 11:00 slot went to the post at 10:00
    assert {o.draft.id: o.state for o in later.publish_queue(live=True)} == {
        again.id: "published",
        waiting.id: "waiting",
    }
    assert [row.draft.id for row in later.calendar()] == [waiting.id], "the calendar is of posts, not revisions"
    stranger = drafts.create(
        lane(root).config, type="revision", slug="stranger", body="New text.", meta={"revises": "urn:li:share:999"}
    )
    blockers = lane(root).preview(stranger).blockers
    assert any(b.kind == "source_missing" and "not a post this lane published" in b.message for b in blockers)


# ── the review loop's order ─────────────────────────────────────────────────


def test_revisit_takes_the_least_recently_reviewed_post_first_and_records_a_review(make_checkout):
    root = make_checkout()
    shared(root, MCP_URL, "urn:li:share:1", source=MCP_POST, when=NOW - timedelta(days=60))
    shared(root, "https://example.test/posts/2026/07/10/moved/", "urn:li:share:2", when=NOW - timedelta(days=30))
    order = [row["urn"] for row in lane(root).revisit()]
    assert order == ["urn:li:share:1", "urn:li:share:2"], "never reviewed: the oldest first"
    lane(root).mark_reviewed(MCP_URL)
    assert [row["urn"] for row in lane(root).revisit()] == ["urn:li:share:2", "urn:li:share:1"]
    assert json.loads((root / LEDGER).read_text())["_meta"]["reviewed"] == {MCP_URL: "2026-09-14T12:00:00Z"}
    with pytest.raises(ValueError, match="is not a post"):
        lane(root).mark_reviewed("https://example.test/nowhere/")
