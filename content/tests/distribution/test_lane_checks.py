"""What a lane checks before a share goes, beyond the gates: that the page it
links to is up (`checkLink` — a share never sends readers to a page that is
not published yet), and which card image it carries (a draft's own `image:`,
the page's preview, the fallback; `requirePreview` refuses a share with no
image of its own). Recorded HTTP only.
"""

import shutil

import httpx
import respx

from distribution.lane import drafts
from distribution.lane.pipeline import Pipeline, page_status
from distribution.lane.site import Config

from .conftest import MCP_URL, NOW
from .test_lane import ARMED, approved_draft, credentials, nosleep, script_publish

CARD = "assets/images/previews/mcp-for-the-back-office.png"
OFFICE = "assets/images/office.png"


def with_fallback(make_checkout, **block):
    """A checkout whose fallback card image is a file of its own (a copy of the page's preview)."""
    root = make_checkout({"fallbackImage": OFFICE, **block})
    shutil.copy(root / CARD, root / OFFICE)
    return root


def lane(root, *, env=None, answers=200):
    return Pipeline(
        Config(root, env=env or {}),
        sleeper=nosleep,
        clock=lambda: NOW,
        credentials=credentials(),
        page_check=lambda url: answers,
    )


def linked(root, *, image=None, slug="elsewhere"):
    """An approved share of a page on another site (`link:`), with its own card image when `image` is given."""
    pipe = lane(root)
    meta = {"link": "https://elsewhere.test/a-page/", "title": "A page elsewhere", "description": "Worth a read."}
    if image:
        meta["image"] = image
    draft = drafts.create(pipe.config, type="article", slug=slug, body="A page on another site.", meta=meta)
    assert pipe.approve(draft).state == "approved"
    return pipe.draft(draft.id)


# ── the page is up before the share goes ────────────────────────────────────


def test_a_share_of_a_page_that_is_not_live_waits_in_a_queue_run_and_is_refused_by_name(checkout, web):
    post = script_publish(web)
    draft = approved_draft(lane(checkout))
    queued = lane(checkout, env=ARMED, answers=404).publish_queue(live=True)
    assert [o.state for o in queued] == ["waiting"] and post.call_count == 0
    assert queued[0].messages == [f"{MCP_URL} answers 404: the page is not live yet, so the share waits until it is"]
    named = lane(checkout, env=ARMED, answers=410).publish(lane(checkout).draft(draft.id), live=True)
    assert named.state == "blocked" and post.call_count == 0
    assert lane(checkout).draft(draft.id).status == "approved", "nothing was recorded"
    went = lane(checkout, env=ARMED, answers=200).publish_queue(live=True)
    assert [o.state for o in went] == ["published"] and post.call_count == 1


def test_an_answer_that_does_not_confirm_the_page_holds_it_and_check_link_false_skips_the_check(make_checkout, web):
    post = script_publish(web)
    root = make_checkout()
    approved_draft(lane(root))
    for answer in (403, 503, None):
        (outcome,) = lane(root, env=ARMED, answers=answer).publish_queue(live=True)
        assert (
            outcome.state == "waiting"
            and "not confirmed" in outcome.messages[0]
            and "checkLink: false" in outcome.messages[0]
        )
    assert post.call_count == 0
    unchecked = make_checkout({"checkLink": False})
    approved_draft(lane(unchecked))
    asked = []
    pipe = Pipeline(
        Config(unchecked, env=ARMED),
        sleeper=nosleep,
        clock=lambda: NOW,
        credentials=credentials(),
        page_check=asked.append,
    )
    assert [o.state for o in pipe.publish_queue(live=True)] == ["published"] and asked == []


def test_a_rehearsal_and_a_text_update_never_ask_the_page(checkout, web):
    asked = []
    draft = approved_draft(lane(checkout))
    pipe = Pipeline(
        Config(checkout, env={}), sleeper=nosleep, clock=lambda: NOW, credentials=credentials(), page_check=asked.append
    )
    assert pipe.publish(draft).state == "rehearsed" and asked == []
    assert pipe.page_down(drafts.create(pipe.config, type="update", slug="note", body="A note."), MCP_URL) is None


def test_the_page_check_follows_redirects_and_reads_a_missing_page_and_an_unreachable_one():
    with respx.mock() as router:
        router.get("https://up.test/old/").respond(301, headers={"Location": "https://up.test/new/"})
        router.get("https://up.test/new/").respond(200)
        router.get("https://up.test/gone/").respond(404)
        router.get("https://down.test/").mock(side_effect=httpx.ConnectError("refused"))
        assert page_status("https://up.test/old/") == 200
        assert page_status("https://up.test/gone/") == 404
        assert page_status("https://down.test/") is None
        assert router.calls[0].request.headers["User-Agent"].startswith("zer0-CMS distribution lane")


# ── the card image ──────────────────────────────────────────────────────────


def test_a_drafts_own_image_is_its_card_and_a_link_elsewhere_carries_it(make_checkout, web):
    root = with_fallback(make_checkout)
    shutil.copy(root / CARD, root / "assets" / "images" / "own-card.png")
    own = linked(root, image="assets/images/own-card.png")
    preview = lane(root).preview(own)
    assert preview.thumbnail == root / "assets" / "images" / "own-card.png"
    plain = linked(root, slug="no-image")
    fallback = lane(root).preview(plain)
    assert fallback.thumbnail == root / OFFICE and "using the fallback card image" in " ".join(fallback.notes)
    missing = linked(root, image="assets/images/nowhere.png", slug="missing")
    notes = lane(root).preview(missing).notes
    assert "image assets/images/nowhere.png is not on disk" in notes


def test_require_preview_refuses_a_share_that_would_carry_the_fallback(make_checkout, web):
    root = with_fallback(make_checkout, requirePreview=True)
    plain = linked(root, slug="no-image")
    blockers = lane(root).preview(plain).blockers
    assert [b.kind for b in blockers if b.kind == "source_missing"] == ["source_missing"]
    assert "requirePreview" in next(b.message for b in blockers if b.kind == "source_missing")
    shutil.copy(root / CARD, root / "assets" / "images" / "own-card.png")
    own = linked(root, image="assets/images/own-card.png", slug="own")
    assert "source_missing" not in [b.kind for b in lane(root).preview(own).blockers]
    page = approved_draft(lane(root))
    assert "source_missing" not in [b.kind for b in lane(root).preview(page).blockers], "the page's own preview"
    bad = make_checkout({"requirePreview": "yes"})
    assert "distribution.linkedin.requirePreview must be true or false" in Config(bad, env={}).errors
