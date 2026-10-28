"""The LinkedIn client (`distribution/linkedin/`), ported with the Ruby lane's
tests (`rails/test/zer0_cms/test_linkedin.rb`) and held to what the Ruby lane
computed (`golden/ruby-lane.json`, recorded on ruby:3.3 before it was deleted).

Every request is recorded HTTP (respx): a request no route answers fails the
test, and none reaches LinkedIn.
"""

import base64
import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest
import respx

from distribution.linkedin import Client, Error, HTTPError, Refused, oauth, plan, posts, restli, statistics

GOLDEN = json.loads((Path(__file__).parent / "golden" / "ruby-lane.json").read_text())
TOKEN = "tok-SECRET-123456"
ORG = "urn:li:organization:5"
REST = "https://api.linkedin.com/rest"


def nosleep(_seconds):
    return None


@pytest.fixture
def web():
    with respx.mock(assert_all_called=False) as router:
        yield router


def client(**options):
    return Client(TOKEN, sleeper=nosleep, **options)


def flow():
    return oauth.OAuth("cid", "csecret-abcdef", sleeper=nosleep)


def query_of(request) -> dict:
    return dict(parse_qsl(urlsplit(str(request.url)).query))


def form_of(request) -> dict:
    return dict(parse_qsl(request.content.decode()))


# ── the declared surface ────────────────────────────────────────────────────


def test_every_declared_call_returns_own_content_and_none_reaches_a_forbidden_path():
    assert plan.own_content_only()
    assert not any(plan.forbidden_path(call.path) for call in plan.CALLS)
    assert not plan.own_content_only([plan.Call("x", "GET", plan.API_HOST, "/x", "x", "a member's connections")])
    for path in (
        "/v2/connections",
        "/rest/networkSizes/urn",
        "/rest/socialActions/urn/likes",
        "/rest/organizationFollowerStatistics",
        "/v2/people/(id:1)",
        "/rest/conversations",
    ):
        assert plan.forbidden_path(path), path


def test_the_plan_is_the_ruby_lanes_and_its_writes_are_named():
    assert [c.id for c in plan.writes()] == ["posts_create", "posts_delete", "images_initialize", "images_upload"]
    assert [c.as_dict() for c in plan.CALLS] == GOLDEN["plan"]["calls"]
    assert plan.describe() == GOLDEN["plan"]["describe"]


def test_an_undeclared_call_no_token_and_an_unheld_scope_are_refused_before_a_socket(web):
    with pytest.raises(Refused):
        client().request("connections")
    with pytest.raises(Error):
        Client(sleeper=nosleep).request("posts_get", path={"urn": "urn:li:share:1"})
    with pytest.raises(Refused):
        client(granted_scopes=["w_member_social"]).request("organization_share_statistics", query=[("q", "x")])
    assert not web.calls


def test_an_upload_url_must_be_https_on_linkedin_com(web):
    c = client()
    for url in (
        "https://evil.example.com/x",
        "http://www.linkedin.com/dms-uploads/x",
        "https://linkedin.com.evil.io/x",
        "not a url",
    ):
        with pytest.raises(Refused):
            c.request("images_upload", url=url, raw=b"b")
    with pytest.raises(Refused):
        c.request("posts_create", url="https://www.linkedin.com/x")
    assert not web.calls


# ── requests ────────────────────────────────────────────────────────────────


def test_a_rest_read_carries_the_versioned_headers_and_an_encoded_urn(web):
    route = web.get(f"{REST}/posts/urn%3Ali%3Ashare%3A42").respond(
        200, json={"id": "urn:li:share:42", "commentary": "hi", "internal": "dropped"}
    )
    assert posts.get(client(), "urn:li:share:42") == {"id": "urn:li:share:42", "commentary": "hi"}
    headers = route.calls.last.request.headers
    assert headers["Authorization"] == f"Bearer {TOKEN}"
    assert headers["LinkedIn-Version"] == plan.DEFAULT_API_VERSION
    assert headers["X-Restli-Protocol-Version"] == "2.0.0"
    assert "X-RestLi-Method" not in headers


def test_a_finder_names_its_method_and_clamps_count(web):
    route = web.get(url__startswith=f"{REST}/posts?").respond(200, json={"elements": [{"id": "urn:li:share:1"}]})
    assert posts.by_author(client(), author=ORG, count=500) == [{"id": "urn:li:share:1"}]
    request = route.calls.last.request
    assert request.headers["X-RestLi-Method"] == "FINDER"
    assert query_of(request) == {"q": "author", "author": ORG, "count": "100", "sortBy": "LAST_MODIFIED"}
    assert "author=urn%3Ali%3Aorganization%3A5" in str(request.url)


def test_a_read_is_retried_on_a_5xx_honouring_retry_after(web):
    slept = []
    web.get(url__startswith=f"{REST}/posts/").mock(
        side_effect=[
            httpx.Response(503, headers={"Retry-After": "7"}),
            httpx.Response(200, json={"id": "urn:li:share:1"}),
        ]
    )
    posts.get(Client(TOKEN, sleeper=slept.append), "urn:li:share:1")
    assert slept == [7]
    assert len(web.calls) == 2


def test_a_write_is_never_retried_after_a_5xx_but_is_after_a_429(web):
    route = web.post(f"{REST}/posts").respond(500, json={"message": "boom"})
    with pytest.raises(HTTPError) as caught:
        posts.create(client(), posts.text_payload(author=ORG, commentary="hello"))
    assert caught.value.status == 500
    assert route.call_count == 1, "a POST that may have landed must not be sent twice"

    route.mock(side_effect=[httpx.Response(429), httpx.Response(201, headers={"x-restli-id": "urn%3Ali%3Ashare%3A99"})])
    assert posts.create(client(), posts.text_payload(author=ORG, commentary="hello")) == "urn:li:share:99"
    assert route.calls.last.request.headers["Content-Type"] == "application/json"


def test_a_created_post_without_x_restli_id_is_an_error(web):
    web.post(f"{REST}/posts").respond(201)
    with pytest.raises(Error):
        posts.create(client(), posts.text_payload(author=ORG, commentary="x"))


def test_an_error_never_carries_a_credential(web):
    web.get(url__startswith=f"{REST}/posts/").respond(
        401, json={"message": f"token {TOKEN} is bad", "serviceErrorCode": 65600}, headers={"x-li-uuid": "req-1"}
    )
    with pytest.raises(HTTPError) as caught:
        posts.get(client(), "urn:li:share:1")
    error = caught.value
    assert TOKEN not in str(error) and "[redacted]" in str(error) and "req-1" in str(error)
    assert error.unauthorized and error.code == 65600


def test_a_dropped_connection_is_retried_for_a_read_and_reported_as_status_zero_for_a_write(web):
    web.get(url__startswith=f"{REST}/posts/").mock(
        side_effect=[httpx.ConnectError("down"), httpx.Response(200, json={"id": "urn:li:share:1"})]
    )
    assert posts.get(client(), "urn:li:share:1")["id"] == "urn:li:share:1"
    web.post(f"{REST}/posts").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(HTTPError) as caught:
        posts.create(client(), posts.text_payload(author=ORG, commentary="x"))
    assert caught.value.status == 0


def test_version_status():
    today = date(2026, 9, 14)
    assert plan.version_status("202608", today) == "ok"
    assert plan.version_status("202511", today) == "aging"
    assert plan.version_status("202509", today) == "sunset"
    assert plan.version_status("202610", today) == "future"
    assert plan.version_status("2026-08", today) == "invalid"
    assert plan.version_status("202613", today) == "invalid"
    with pytest.raises(ValueError):
        Client(api_version="latest")


# ── little text and payloads ────────────────────────────────────────────────


def test_little_text_matches_the_ruby_lane_on_every_recorded_sample():
    assert restli.escape("a(b) [c] {d} <e> f|g h*i j_k l~m n\\o C# @home") == (
        "a\\(b\\) \\[c\\] \\{d\\} \\<e\\> f\\|g h\\*i j\\_k l\\~m n\\\\o C\\# \\@home"
    )
    assert restli.escape("#SmallBusiness and #AI2026") == "#SmallBusiness and #AI2026"
    assert restli.escape("@[x](https://evil.test)") == "\\@\\[x\\]\\(https://evil.test\\)"
    for text, escaped in GOLDEN["little_text"]:
        assert restli.escape(text) == escaped, text


def test_an_article_payload_is_the_shape_linkedin_documents():
    payload = posts.article_payload(
        author=ORG,
        commentary="Read (this)",
        source="https://x.test/a/",
        title="T",
        description="D",
        thumbnail="urn:li:image:1",
    )
    assert payload["author"] == ORG and payload["commentary"] == "Read \\(this\\)"
    assert payload["visibility"] == "PUBLIC" and payload["lifecycleState"] == "PUBLISHED"
    assert payload["distribution"] == {
        "feedDistribution": "MAIN_FEED",
        "targetEntities": [],
        "thirdPartyDistributionChannels": [],
    }
    assert payload["isReshareDisabledByAuthor"] is False
    assert payload["content"]["article"] == {
        "source": "https://x.test/a/",
        "title": "T",
        "description": "D",
        "thumbnail": "urn:li:image:1",
    }
    assert "content" not in posts.text_payload(author="urn:li:person:abc", commentary="x")


def test_payload_arguments_are_checked():
    with pytest.raises(ValueError):
        posts.text_payload(author="urn:li:company:5", commentary="x")
    with pytest.raises(ValueError):
        posts.article_payload(author=ORG, commentary="x", source="javascript:alert(1)", title="T", description="D")
    with pytest.raises(ValueError):
        posts.get(client(), "urn:li:share:1/../x")


# ── OAuth ───────────────────────────────────────────────────────────────────


def test_the_consent_url_carries_state_and_a_pkce_challenge_and_never_the_secret():
    url = flow().authorize_url(
        redirect_uri="http://127.0.0.1:8765/callback",
        state="s1",
        scopes=["w_organization_social", "r_organization_social"],
    )
    assert url == (
        "https://www.linkedin.com/oauth/v2/authorization?response_type=code&client_id=cid&"
        "redirect_uri=http%3A%2F%2F127.0.0.1%3A8765%2Fcallback&state=s1&scope=w_organization_social%20r_organization_social"
    )
    verifier = oauth.new_verifier()
    assert 43 <= len(verifier) <= 128
    with_pkce = flow().authorize_url(
        redirect_uri="https://cms.test/cb", state="s", scopes=["x"], code_challenge=oauth.challenge(verifier)
    )
    params = dict(parse_qsl(urlsplit(with_pkce).query))
    assert params["code_challenge_method"] == "S256" and params["code_challenge"] == oauth.challenge(verifier)
    assert "csecret" not in url + with_pkce
    for bad in ("/callback", "https://a.test/cb#f"):
        with pytest.raises(ValueError):
            flow().authorize_url(redirect_uri=bad, state="s", scopes=["x"])
    with pytest.raises(ValueError):
        oauth.OAuth("", "x")
    # S256 (RFC 7636 § 4.2): base64url of the SHA-256 of the verifier, without padding.
    digest = hashlib.sha256(verifier.encode()).digest()
    assert oauth.challenge(verifier) == base64.urlsafe_b64encode(digest).decode().rstrip("=")
    assert len(oauth.challenge(verifier)) == 43 and oauth.challenge(verifier) != oauth.challenge(oauth.new_verifier())


def test_exchange_with_the_verifier_refresh_and_introspect(web):
    now = datetime(2026, 9, 14, tzinfo=UTC)
    token_route = web.post("https://www.linkedin.com/oauth/v2/accessToken").respond(
        200,
        json={
            "access_token": "AT",
            "expires_in": 5184000,
            "refresh_token": "RT",
            "refresh_token_expires_in": 31536000,
            "scope": "w_organization_social,r_organization_social",
        },
    )
    web.post("https://www.linkedin.com/oauth/v2/introspectToken").respond(
        200,
        json={
            "active": True,
            "status": "active",
            "expires_at": int(now.timestamp()) + 3 * 86400,
            "scope": "w_organization_social,r_organization_social",
            "auth_type": "3L",
        },
    )
    token = flow().exchange(code="C", redirect_uri="http://127.0.0.1:8765/callback", code_verifier="V" * 50, now=now)
    assert (token.access_token, token.refresh_token, token.days_left(now)) == ("AT", "RT", 60)
    assert token.scopes == ["w_organization_social", "r_organization_social"]
    first = token_route.calls[0].request
    assert form_of(first) == {
        "grant_type": "authorization_code",
        "code": "C",
        "redirect_uri": "http://127.0.0.1:8765/callback",
        "code_verifier": "V" * 50,
        "client_id": "cid",
        "client_secret": "csecret-abcdef",
    }
    assert "Authorization" not in first.headers and "LinkedIn-Version" not in first.headers
    assert "csecret" not in str(first.url)

    flow().refresh(refresh_token="RT", now=now)
    assert form_of(token_route.calls[1].request)["grant_type"] == "refresh_token"

    info = flow().introspect("AT")
    assert info.active and info.days_left(now) == 3
    assert form_of(web.calls.last.request)["token"] == "AT"


def test_a_code_exchange_is_never_retried(web):
    route = web.post("https://www.linkedin.com/oauth/v2/accessToken").respond(500, json={"error": "server_error"})
    with pytest.raises(HTTPError):
        flow().exchange(code="C", redirect_uri="https://a.test/cb")
    assert route.call_count == 1, "an authorization code is single-use"


def test_state_comparison():
    assert oauth.state_matches("abc", "abc")
    assert not oauth.state_matches("abc", "abd")
    assert not oauth.state_matches("abc", "ab")
    assert not oauth.state_matches("", "")
    assert len(oauth.new_state()) >= 40


def test_the_member_behind_a_token(web):
    route = web.get("https://api.linkedin.com/v2/userinfo").respond(200, json={"sub": "782bbtaQ", "name": "John Doe"})
    assert oauth.member(client()) == {"urn": "urn:li:person:782bbtaQ", "name": "John Doe"}
    assert "LinkedIn-Version" not in route.calls.last.request.headers, "userinfo is not a versioned /rest call"


# ── images, pages, statistics ───────────────────────────────────────────────


def test_an_image_upload_reserves_a_slot_sends_the_bytes_and_waits(web):
    png = bytes.fromhex("89504e470d0a1a0a")
    init = web.post(f"{REST}/images?action=initializeUpload").respond(
        200,
        json={
            "value": {
                "uploadUrl": "https://www.linkedin.com/dms-uploads/abc/uploaded-image/0",
                "image": "urn:li:image:C4E",
            }
        },
    )
    put = web.put(url__startswith="https://www.linkedin.com/dms-uploads/").respond(201)
    web.get(f"{REST}/images/urn%3Ali%3Aimage%3AC4E").respond(200, json={"status": "AVAILABLE"})
    assert posts.upload_image(client(), owner=ORG, name="card.png", data=png, sleeper=nosleep) == "urn:li:image:C4E"
    assert json.loads(init.calls.last.request.content) == {"initializeUploadRequest": {"owner": ORG}}
    upload = put.calls.last.request
    assert upload.headers["Content-Type"] == "image/png" and upload.content == png
    assert "LinkedIn-Version" not in upload.headers
    ok, reason = posts.uploadable("card.svg", 6)
    assert not ok and ".svg" in reason


def test_pages_the_member_may_post_to_and_forbidden_is_none_not_empty(web):
    route = web.get(url__startswith=f"{REST}/organizationAcls?").respond(
        200,
        json={
            "elements": [
                {"role": "ANALYST", "organization": "urn:li:organization:1", "state": "APPROVED"},
                {"role": "CONTENT_ADMINISTRATOR", "organizationTarget": "urn:li:organization:2"},
                {"role": "ADMINISTRATOR", "organizationTarget": "urn:li:organization:2"},
            ]
        },
    )
    pages = statistics.administered(client())
    assert [(p.urn, p.role) for p in pages] == [("urn:li:organization:2", "ADMINISTRATOR")]
    assert query_of(route.calls.last.request) == {"q": "roleAssignee", "state": "APPROVED", "count": "100"}
    route.respond(403, json={"message": "no"})
    assert statistics.administered(client()) is None


def test_page_statistics_are_batched_normalized_and_absent_means_zero(web):
    route = web.get(url__startswith=f"{REST}/organizationalEntityShareStatistics?").respond(
        200,
        json={
            "elements": [
                {
                    "share": "urn:li:share:1",
                    "totalShareStatistics": {
                        "impressionCount": 100,
                        "clickCount": 7,
                        "likeCount": -2,
                        "commentCount": 3,
                        "shareCount": 1,
                        "uniqueImpressionsCount": 80,
                        "engagement": 0.1,
                    },
                },
                {"share": "urn:li:share:999", "totalShareStatistics": {"impressionCount": 5}},
            ]
        },
    )
    stats = statistics.for_organization(client(), organization=ORG, urns=["urn:li:share:1", "urn:li:share:2", "junk"])
    assert stats["urn:li:share:1"] == {
        "impressions": 100,
        "clicks": 7,
        "reactions": 0,
        "comments": 3,
        "shares": 1,
        "engagements": 4,
    }
    assert stats["urn:li:share:2"]["impressions"] == 0
    assert sorted(stats) == ["urn:li:share:1", "urn:li:share:2"], "only posts this lane asked about"
    url = str(route.calls.last.request.url)
    assert "shares=List(urn%3Ali%3Ashare%3A1,urn%3Ali%3Ashare%3A2)" in url
    assert "organizationalEntity=urn%3Ali%3Aorganization%3A5" in url


def test_member_post_statistics_read_one_metric_per_call(web):
    counts = {"IMPRESSION": 50, "REACTION": 4, "COMMENT": 2, "RESHARE": 1, "LINK_CLICKS": 9}

    def answer(request):
        kind = query_of(request)["queryType"]
        return httpx.Response(200, json={"elements": [{"count": counts[kind], "metricType": kind}]})

    route = web.get(url__startswith=f"{REST}/memberCreatorPostAnalytics?").mock(side_effect=answer)
    stats = statistics.for_member_post(client(), urn="urn:li:ugcPost:7")
    assert stats == {"impressions": 50, "clicks": 9, "reactions": 4, "comments": 2, "shares": 1, "engagements": 7}
    assert route.call_count == 5
    first = route.calls[0].request
    assert "entity=(ugc:urn%3Ali%3AugcPost%3A7)" in str(first.url) and query_of(first)["aggregation"] == "TOTAL"
    older = Client(TOKEN, api_version="202601", sleeper=nosleep)
    assert statistics.for_member_post(older, urn="urn:li:share:7")["clicks"] == 0
    assert route.call_count == 9, "LINK_CLICKS is not requested before 202604"
