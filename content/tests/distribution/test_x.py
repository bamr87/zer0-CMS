"""X: the client (`distribution/x/` — the call plan, OAuth 1.0a signing, OAuth
2.0 bearer tokens and their renewal, retries, the length X counts) and the lane over a site's own files (`manage.py x`,
`distribution/lane/x_*.py`) end to end, over the fixture site. Recorded HTTP
only (respx): an unscripted request fails the test, and nothing reaches X.
"""

import io
import json

import httpx
import pytest

from distribution.lane import drafts
from distribution.lane.x_cli import main
from distribution.lane.x_pipeline import XPipeline
from distribution.lane.x_site import XConfig
from distribution.ledger import Ledger
from distribution.x import Client, Credentials, Error, HTTPError, Refused, oauth, oauth2, plan, posts
from distribution.x.session import Session, UserToken

from .conftest import MCP_POST, MCP_URL, NOW, tree

API = "https://api.x.com"
ME = {"data": {"id": "1001", "username": "bamr87", "name": "Amr"}}
ENV = {
    "X_API_KEY": "app-key-123456",
    "X_API_SECRET": "app-secret-SECRET-123456",
    "X_ACCESS_TOKEN": "1001-token-123456",
    "X_ACCESS_TOKEN_SECRET": "token-secret-SECRET-123456",
}
ARMED = {**ENV, "ZER0_X_PUBLISH": "1"}
BLOCK = {"account": "@bamr87", "queue": "drafts/x", "ledger": ".github/x-log.json", "sources": ["posts"]}
SOURCE = "tech/2026-07-06-mcp-for-the-back-office"


def nosleep(_seconds):
    return None


@pytest.fixture
def x_checkout(make_checkout):
    def make(block=None, linkedin=None):
        zer0 = {"distribution": {"x": {**BLOCK, **(block or {})}}}
        if linkedin is not None:
            zer0["distribution"]["linkedin"] = linkedin
        return make_checkout(zer0=zer0)

    return make


def pipeline(root, env=None):
    return XPipeline(XConfig(root, env=ENV if env is None else env), sleeper=nosleep, clock=lambda: NOW)


def run(root, *argv, env=None, stdin=None):
    out, err = io.StringIO(), io.StringIO()
    code = main([*argv, "--site", str(root)], out=out, err=err, env=env or {}, sleeper=nosleep, stdin=stdin)
    return code, out.getvalue(), err.getvalue()


def approved(pipe, ref=SOURCE, **options):
    draft = pipe.compose(ref, **options)
    assert pipe.approve(draft).state == "approved"
    return pipe.draft(draft.id)


# ── the client ──────────────────────────────────────────────────────────────


def test_every_call_is_declared_reads_only_the_accounts_own_content_and_nothing_else_can_be_asked():
    assert plan.own_content_only()
    assert not [c.path for c in plan.CALLS if plan.forbidden_path(c.path)]
    assert not plan.own_content_only([plan.Call("x", "GET", "/2/users/{id}/followers", "p", "the followers")])
    assert plan.forbidden_path("/2/users/1/following") and plan.forbidden_path("/2/tweets/search/recent")
    with pytest.raises(Refused, match="not a declared X call"):
        Client(Credentials(*ENV.values())).request("likes")
    assert [c.id for c in plan.CALLS if c.write] == ["posts_create"]


def test_a_request_is_signed_with_oauth_1a_and_refused_without_a_credential(web):
    route = web.post(f"{API}/2/tweets").respond(201, json={"data": {"id": "77", "text": "hi"}})
    assert posts.create(Client(Credentials(*ENV.values())), posts.payload(commentary="hi")) == "77"
    auth = route.calls.last.request.headers["authorization"]
    for part in ('oauth_consumer_key="app-key-123456"', 'oauth_token="1001-token-123456"', "HMAC-SHA1"):
        assert part in auth
    assert "SECRET" not in auth, "secrets sign the request; they are never sent"
    assert json.loads(route.calls.last.request.content) == {"text": "hi"}
    with pytest.raises(Refused, match="X_ACCESS_TOKEN"):
        Client(Credentials("k", "s")).request("me")
    with pytest.raises(Refused, match="X_API_KEY"):
        Client(Credentials()).request("me")


def test_an_oauth2_token_is_a_bearer_the_app_alone_takes_it_and_a_renewal_is_never_repeated(web):
    me = web.get(f"{API}/2/users/me").respond(200, json=ME)
    assert posts.me(Client(bearer="x-access-SECRET-123456"))["username"] == "bamr87"
    assert me.calls.last.request.headers["authorization"] == "Bearer x-access-SECRET-123456"
    with pytest.raises(Refused, match="OAuth 1.0a"):
        Client(bearer="x-access-SECRET-123456").request("request_token")
    with pytest.raises(Refused, match="X_CLIENT_ID"):
        Client(bearer="x-access-SECRET-123456").request("oauth2_token", form={"grant_type": "refresh_token"})
    token = web.post(f"{API}/2/oauth2/token").respond(503)
    session = Session(UserToken("", "x-refresh-SECRET-123456", "cid", "x-client-SECRET-123456"), sleeper=nosleep)
    with pytest.raises(HTTPError) as caught:
        session.run(posts.me)
    assert token.call_count == 1, "a renewal that reached X spent its refresh token"
    assert me.call_count == 1 and "SECRET" not in str(caught.value)
    assert not [c.id for c in plan.CALLS if c.grant and c.write] and plan.fetch("oauth2_token").grant
    with pytest.raises(ValueError, match="X_CLIENT_ID and X_CLIENT_SECRET"):
        oauth2.OAuth("cid", "")


def test_a_write_is_never_retried_after_a_5xx_and_a_read_is(web):
    create = web.post(f"{API}/2/tweets").respond(503, json={"title": "Service Unavailable", "detail": "busy"})
    client = Client(Credentials(*ENV.values()), sleeper=nosleep)
    with pytest.raises(HTTPError, match="503"):
        posts.create(client, {"text": "hi"})
    assert create.call_count == 1, "a 5xx after POST /2/tweets may mean the post exists"
    me = web.get(f"{API}/2/users/me").mock(side_effect=[httpx.Response(503), httpx.Response(200, json=ME)])
    assert posts.me(client)["username"] == "bamr87" and me.call_count == 2


def test_an_error_is_xs_sentence_with_every_credential_scrubbed_out(web):
    detail = "You are not allowed to create a Tweet with duplicate content. token-secret-SECRET-123456"
    web.post(f"{API}/2/tweets").respond(403, json={"title": "Forbidden", "detail": detail, "type": "about:blank"})
    with pytest.raises(HTTPError) as caught:
        posts.create(Client(Credentials(*ENV.values())), {"text": "hi"})
    assert "duplicate content" in str(caught.value) and "SECRET" not in str(caught.value)
    assert caught.value.forbidden


def test_the_length_is_counted_as_x_counts_it():
    assert plan.weighted_length("hello") == 5
    assert plan.weighted_length("read https://www.bash-365.com/a/very/long/path/that/x/shortens/") == 5 + 23
    assert plan.weighted_length("bash-365.com") == 23, "X links a bare domain"
    assert plan.weighted_length("mail info@bash-365.com") == len("mail info@bash-365.com"), "an address is no link"
    assert plan.weighted_length("日本") == 4 and plan.weighted_length("é") == 1
    assert plan.post_text("Hook.", "https://e.test/a/") == "Hook.\n\nhttps://e.test/a/"
    assert plan.post_text("Read https://e.test/a/ now", "https://e.test/a/") == "Read https://e.test/a/ now"
    assert plan.handle("@bamr87") == "bamr87" and plan.handle("no spaces") is None and plan.handle("a" * 16) is None


def test_a_lookup_keeps_only_the_accounts_own_posts_and_their_counts(web):
    web.get(url__startswith=f"{API}/2/tweets?ids=").respond(
        200,
        json={
            "data": [
                {
                    "id": "1",
                    "author_id": "1001",
                    "text": "a",
                    "public_metrics": {
                        "impression_count": 90,
                        "like_count": 5,
                        "reply_count": 1,
                        "retweet_count": 2,
                        "quote_count": 1,
                        "bookmark_count": 9,
                    },
                },
                {"id": "2", "author_id": "999", "text": "someone else's"},
            ]
        },
    )
    found = posts.lookup(Client(Credentials(*ENV.values())), ["1", "2", "not-an-id"], account_id="1001")
    assert list(found) == ["1"]
    counts = posts.counts(found["1"])
    assert counts == {"impressions": 90, "clicks": 0, "reactions": 5, "comments": 1, "shares": 3, "engagements": 9}


def test_connecting_trades_a_pin_for_the_accounts_token(web):
    web.post(f"{API}/oauth/request_token").respond(
        200, text="oauth_token=req&oauth_token_secret=reqsec&oauth_callback_confirmed=true"
    )
    done = web.post(f"{API}/oauth/access_token").respond(
        200, text="oauth_token=1001-new&oauth_token_secret=newsec&user_id=1001&screen_name=bamr87"
    )
    client = Client(Credentials("app-key-123456", "app-secret-SECRET-123456"))
    token, secret = oauth.request_token(client)
    assert oauth.authorize_url(token) == "https://api.x.com/oauth/authorize?oauth_token=req"
    found = oauth.access_token(client, token=token, secret=secret, pin="1234567")
    assert found == {"access_token": "1001-new", "access_token_secret": "newsec", "account": "bamr87"}
    sent = done.calls.last.request.headers["authorization"]
    assert 'oauth_verifier="1234567"' in sent and 'oauth_token="req"' in sent


# ── the lane ────────────────────────────────────────────────────────────────


def test_the_settings_are_xs_own_block_and_never_arm(x_checkout):
    config = XConfig(x_checkout(), env={})
    assert (config.account, config.queue, config.ledger, config.hashtag_limit) == (
        "bamr87",
        "drafts/x",
        ".github/x-log.json",
        2,
    )
    assert not config.publish_armed and config.errors == []
    assert XConfig(x_checkout(), env={"ZER0_LINKEDIN_PUBLISH": "1"}).publish_armed is False, "one network's switch"
    bad = XConfig(x_checkout({"account": "not a handle", "publishAllow": True}), env={})
    assert bad.errors == ['account must be an X handle (letters, digits, _, at most 15), got "not a handle"']
    assert any("distribution.x.publishAllow is not a setting" in w for w in bad.warnings)


def test_a_preview_is_the_exact_post_with_its_length_and_every_blocker_and_writes_nothing(x_checkout):
    root = x_checkout()
    pipe = pipeline(root, env={})
    draft = pipe.compose(SOURCE)
    before = tree(root)
    preview = pipe.preview(draft)
    text = preview.payload["text"]
    assert text.endswith(f"\n\n{MCP_URL}") and preview.key == MCP_URL
    assert [b.kind for b in preview.blockers] == ["status_not_accepted", "publish_disabled", "no_credential"]
    assert preview.problems == [], "waiting, not wrong: a rehearsal passes"
    shown = preview.as_dict(root)
    assert shown["length"] == plan.weighted_length(text) and shown["limit"] == 280 and "fold" not in shown
    assert tree(root) == before


def test_a_post_over_280_as_x_counts_it_is_a_guard_error(x_checkout):
    pipe = pipeline(x_checkout(), env=ARMED)
    draft = approved(pipe, commentary="word " * 60)
    preview = pipe.preview(draft)
    assert [b.kind for b in preview.blockers] == ["guard_error"]
    assert "as X counts them (max 280" in preview.blockers[0].message
    assert not [f for f in preview.guard if f["message"].startswith("fold at")], "LinkedIn's fold is not X's"


def test_publishing_posts_as_the_configured_account_and_ledgers_it_in_xs_own_file(x_checkout, web):
    linkedin_shared = {MCP_URL: {"urn": "urn:li:share:1", "linkedin_urn": "urn:li:share:1", "target": "linkedin"}}
    root = x_checkout()
    (root / ".github").mkdir(exist_ok=True)
    (root / ".github" / "linkedin-log.json").write_text(json.dumps(linkedin_shared))
    web.get(f"{API}/2/users/me").respond(200, json=ME)
    create = web.post(f"{API}/2/tweets").respond(201, json={"data": {"id": "1850000000000000001", "text": "…"}})
    pipe = pipeline(root, env=ARMED)
    draft = approved(pipe)
    rehearsal = pipe.publish(draft)
    assert rehearsal.state == "rehearsed" and create.call_count == 0
    outcome = pipe.publish(draft, live=True)
    assert outcome.state == "published", outcome.messages
    assert "https://x.com/bamr87/status/1850000000000000001" in outcome.messages
    assert outcome.as_dict()["post_id"] == "1850000000000000001" and "linkedin_urn" not in outcome.as_dict()
    assert json.loads(create.calls.last.request.content)["text"].endswith(MCP_URL)
    entry = Ledger(root / ".github" / "x-log.json").entry(MCP_URL)
    assert entry == {
        "author": "bamr87",
        "posted_at": "2026-09-14T12:00:00Z",
        "source_file": MCP_POST,
        "target": "x",
        "type": "article",
        "urn": "1850000000000000001",
    }
    assert pipe.draft(draft.id).meta["post_id"] == "1850000000000000001"
    assert pipe.draft(draft.id).status == "published"
    assert [b.kind for b in pipe.preview(pipe.draft(draft.id)).blockers][:1] == ["already_published"]


def test_a_token_for_another_account_is_refused_before_anything_is_sent(x_checkout, web):
    web.get(f"{API}/2/users/me").respond(200, json={"data": {"id": "5", "username": "someone"}})
    create = web.post(f"{API}/2/tweets").respond(201, json={"data": {"id": "1"}})
    pipe = pipeline(x_checkout(), env=ARMED)
    outcome = pipe.publish(approved(pipe), live=True)
    assert outcome.state == "failed" and "posts as @someone, not @bamr87" in outcome.messages[0]
    assert create.call_count == 0 and not Ledger(pipe.config.path(pipe.config.ledger)).exists()


def test_a_post_x_did_not_confirm_blocks_every_run_until_a_person_records_it(x_checkout, web):
    web.get(f"{API}/2/users/me").respond(200, json=ME)
    web.post(f"{API}/2/tweets").respond(502)
    pipe = pipeline(x_checkout(), env=ARMED)
    draft = approved(pipe)
    outcome = pipe.publish(draft, live=True)
    assert outcome.state == "failed" and "X did not confirm the post" in outcome.messages[-1]
    assert "`manage.py x record" in outcome.messages[-1]
    blocked = pipe.preview(pipe.draft(draft.id))
    assert [b.kind for b in blocked.blockers] == ["publish_unconfirmed"]
    assert "account's posts on X" in blocked.blockers[0].message
    with pytest.raises(ValueError, match="not an X post id"):
        pipe.record_post(draft, "urn:li:share:1")
    recorded = pipe.record_post(draft, "1850000000000000002")
    assert recorded.state == "recorded" and recorded.as_dict()["post_id"] == "1850000000000000002"
    assert pipe.ledger.urn_for(MCP_URL) == "1850000000000000002"


def test_the_command_line_walks_the_governed_path(x_checkout, web):
    root = x_checkout({"acceptStatuses": ["pending", "approved"]})
    code, out, _ = run(root, "draft", SOURCE)
    assert code == 0 and "status: pending" in out
    draft_id = drafts.all_drafts(XConfig(root, env={}))[0].id
    code, out, _ = run(root, "preview", draft_id)
    assert code == 0 and "characters as X counts them" in out and "POST https://api.x.com/2/tweets" in out
    code, out, _ = run(root, "publish", "--json")
    rehearsed = json.loads(out)
    assert code == 0 and [(o["state"], o["post_id"]) for o in rehearsed] == [("rehearsed", None)], "what CI will send"
    code, out, err = run(root, "publish", draft_id, "--live", env=ENV)
    assert code == 1 and "ZER0_X_PUBLISH=1" in out
    web.get(f"{API}/2/users/me").respond(200, json=ME)
    web.post(f"{API}/2/tweets").respond(201, json={"data": {"id": "42"}})
    code, out, err = run(root, "publish", draft_id, "--live", env={**ARMED, "ZER0_X_MERGED": "1"})
    assert code == 0 and "PUBLISHED" in out and "https://x.com/bamr87/status/42" in out, err
    code, out, _ = run(root, "status", "--json", env=ENV)
    report = json.loads(out)
    assert report["published"] == 1 and report["account"] == "bamr87"
    assert report["credentials"] == dict.fromkeys(ENV, True), "names only"
    assert not any(value in out for value in ENV.values())


def test_status_check_says_which_account_the_token_posts_as(x_checkout, web):
    web.get(f"{API}/2/users/me").respond(200, json=ME)
    code, out, _ = run(x_checkout(), "status", "--check", env=ENV)
    assert code == 0 and "posts as @bamr87" in out
    code, out, _ = run(x_checkout(), "status", "--check", env={})
    assert code == 1 and "no X credential" in out


def test_connect_prints_the_token_for_a_secret_only_when_asked(x_checkout, web):
    web.post(f"{API}/oauth/request_token").respond(200, text="oauth_token=req&oauth_token_secret=reqsec")
    web.post(f"{API}/oauth/access_token").respond(
        200, text="oauth_token=1001-new&oauth_token_secret=newsec&screen_name=bamr87"
    )
    app = {"X_API_KEY": "app-key-123456", "X_API_SECRET": "app-secret-SECRET-123456"}
    code, out, _ = run(x_checkout(), "connect", env=app, stdin=io.StringIO("1234567\n"))
    assert code == 0 and "oauth_token=req" in out and "newsec" not in out and "not stored" in out
    code, out, _ = run(x_checkout(), "connect", "--print-token", env=app, stdin=io.StringIO("1234567\n"))
    assert "X_ACCESS_TOKEN=1001-new" in out and "X_ACCESS_TOKEN_SECRET=newsec" in out
    code, _, err = run(x_checkout(), "connect", env={})
    assert code == 1 and "X_API_KEY" in err


def test_the_mcp_server_lists_x_tools_previews_and_keeps_publish_off(x_checkout):
    root = x_checkout()
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "x_draft", "arguments": {"source": SOURCE}},
        },
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "x_publish", "arguments": {"draft": "x", "confirm": True}},
        },
    ]
    stdin = io.StringIO("".join(json.dumps(line) + "\n" for line in lines))
    code, out, _ = run(root, "mcp", env=ARMED, stdin=stdin)
    replies = [json.loads(line) for line in out.splitlines()]
    assert code == 0 and replies[0]["result"]["serverInfo"]["name"] == "zer0-x"
    names = [t["name"] for t in replies[1]["result"]["tools"]]
    assert names == ["x_status", "x_plan", "x_sources", "x_queue", "x_preview", "x_draft", "x_posts", "x_publish"]
    drafted = json.loads(replies[2]["result"]["content"][0]["text"])
    assert drafted["status"] == "pending" and drafted["preview"]["limit"] == 280
    assert replies[3]["result"]["isError"] and "ZER0_X_MCP_PUBLISH=1" in replies[3]["result"]["content"][0]["text"]


def test_an_unknown_account_answers_with_an_error_a_person_can_act_on(x_checkout, web):
    web.get(f"{API}/2/users/me").respond(
        401, json={"title": "Unauthorized", "detail": "Unauthorized", "type": "about:blank"}
    )
    with pytest.raises(Error, match="401"):
        pipeline(x_checkout()).account()
