# frozen_string_literal: true

require "minitest/autorun"
require "tmpdir"
require_relative "../../lib/zer0_cms/linkedin"

# The LinkedIn client, exercised through ScriptedTransport: no test here opens
# a socket, and an unscripted request fails the test.
class TestLinkedIn < Minitest::Test
  L = Zer0Cms::LinkedIn
  NOSLEEP = ->(_seconds) {}
  TOKEN = "tok-SECRET-123456"
  ORG = "urn:li:organization:5"

  def transport
    L::ScriptedTransport.new
  end

  def client(scripted, **options)
    L::Client.new(token: TOKEN, transport: scripted, sleeper: NOSLEEP, **options)
  end

  def oauth(scripted)
    L::OAuth.new(client_id: "cid", client_secret: "csecret-abcdef", transport: scripted, sleeper: NOSLEEP)
  end

  # --- the declared surface --------------------------------------------------

  def test_every_declared_call_returns_own_content_and_none_reaches_a_forbidden_path
    assert L::Plan.own_content_only?
    L::Plan::CALLS.each { |call| refute L::Plan.forbidden_path?(call.path), call.id }
    refute L::Plan.own_content_only?([L::Plan::Call.new(id: :x, returns: "a member's connections")])
    %w[/v2/connections /rest/networkSizes/urn /rest/socialActions/urn/likes /rest/organizationFollowerStatistics
       /v2/people/(id:1) /rest/conversations].each { |path| assert L::Plan.forbidden_path?(path), path }
  end

  def test_the_plan_is_short_and_its_writes_are_named
    assert_equal %i[posts_create posts_delete images_initialize images_upload], L::Plan.writes.map(&:id)
    assert_includes L::Plan.describe, "aggregate counts for the page's own posts"
  end

  def test_an_undeclared_call_is_refused_before_a_socket
    scripted = transport
    assert_raises(L::Refused) { client(scripted).request(:connections) }
    assert_empty scripted.requests
  end

  def test_no_token_is_refused_before_a_socket
    scripted = transport
    assert_raises(L::Error) { L::Client.new(transport: scripted).request(:posts_get, path: { urn: "urn:li:share:1" }) }
    assert_empty scripted.requests
  end

  def test_a_scope_the_token_is_known_not_to_hold_is_refused_locally
    scripted = transport
    assert_raises(L::Refused) do
      client(scripted, granted_scopes: %w[w_member_social]).request(:organization_share_statistics, query: [%w[q x]])
    end
    assert_empty scripted.requests
  end

  def test_an_upload_url_must_be_https_on_linkedin_com
    scripted = transport
    c = client(scripted)
    ["https://evil.example.com/x", "http://www.linkedin.com/dms-uploads/x", "https://linkedin.com.evil.io/x", "not a url"].each do |url|
      assert_raises(L::Refused, url) { c.request(:images_upload, url: url, raw: "b") }
    end
    assert_raises(L::Refused) { c.request(:posts_create, url: "https://www.linkedin.com/x") }
    assert_empty scripted.requests
  end

  # --- requests ---------------------------------------------------------------

  def test_a_rest_read_carries_the_versioned_headers_and_an_encoded_urn
    scripted = transport.on("GET", "https://api.linkedin.com/rest/posts/urn%3Ali%3Ashare%3A42",
                            { "id" => "urn:li:share:42", "commentary" => "hi", "internal" => "dropped" })
    assert_equal({ "id" => "urn:li:share:42", "commentary" => "hi" }, L::Posts.get(client(scripted), "urn:li:share:42"))
    headers = scripted.requests.first.headers
    assert_equal "Bearer #{TOKEN}", headers["Authorization"]
    assert_equal L::DEFAULT_API_VERSION, headers["LinkedIn-Version"]
    assert_equal "2.0.0", headers["X-Restli-Protocol-Version"]
    refute headers.key?("X-RestLi-Method")
  end

  def test_a_finder_names_its_method_and_clamps_count
    scripted = transport.on("GET", "https://api.linkedin.com/rest/posts?", { "elements" => [{ "id" => "urn:li:share:1" }] })
    assert_equal [{ "id" => "urn:li:share:1" }], L::Posts.by_author(client(scripted), author: ORG, count: 500)
    request = scripted.requests.first
    assert_equal "FINDER", request.headers["X-RestLi-Method"]
    assert_equal({ "q" => "author", "author" => ORG, "count" => "100", "sortBy" => "LAST_MODIFIED" }, request.query)
    assert_includes request.url, "author=urn%3Ali%3Aorganization%3A5"
  end

  def test_a_read_is_retried_on_a_5xx_honouring_retry_after
    slept = []
    scripted = transport
    scripted.on("GET", "https://api.linkedin.com/rest/posts/", nil, status: 503, headers: { "Retry-After" => "7" }, times: 1)
    scripted.on("GET", "https://api.linkedin.com/rest/posts/", { "id" => "urn:li:share:1" })
    L::Posts.get(L::Client.new(token: TOKEN, transport: scripted, sleeper: ->(s) { slept << s }), "urn:li:share:1")
    assert_equal [7], slept
    assert_equal 2, scripted.requests.size
  end

  def test_a_write_is_never_retried_after_a_5xx
    scripted = transport.on("POST", "https://api.linkedin.com/rest/posts", { "message" => "boom" }, status: 500)
    error = assert_raises(L::HTTPError) do
      L::Posts.create(client(scripted), L::Posts.text_payload(author: ORG, commentary: "hello"))
    end
    assert_equal 500, error.status
    assert_equal 1, scripted.requests.size, "a POST that may have landed must not be sent twice"
  end

  def test_a_write_is_retried_on_429_and_the_urn_comes_from_x_restli_id
    scripted = transport
    scripted.on("POST", "https://api.linkedin.com/rest/posts", nil, status: 429, times: 1)
    scripted.on("POST", "https://api.linkedin.com/rest/posts", nil, status: 201, headers: { "x-restli-id" => "urn%3Ali%3Ashare%3A99" })
    assert_equal "urn:li:share:99", L::Posts.create(client(scripted), L::Posts.text_payload(author: ORG, commentary: "hello"))
    assert_equal 2, scripted.requests.size
    assert_equal "application/json", scripted.requests.last.headers["Content-Type"]
  end

  def test_a_created_post_without_x_restli_id_is_an_error
    scripted = transport.on("POST", "https://api.linkedin.com/rest/posts", nil, status: 201)
    assert_raises(L::Error) { L::Posts.create(client(scripted), L::Posts.text_payload(author: ORG, commentary: "x")) }
  end

  def test_an_error_never_carries_a_credential
    scripted = transport.on("GET", "https://api.linkedin.com/rest/posts/",
                            { "message" => "token #{TOKEN} is bad", "serviceErrorCode" => 65_600 },
                            status: 401, headers: { "x-li-uuid" => "req-1" })
    error = assert_raises(L::HTTPError) { L::Posts.get(client(scripted), "urn:li:share:1") }
    refute_includes error.message, TOKEN
    assert_includes error.message, "[redacted]"
    assert_includes error.message, "req-1"
    assert error.unauthorized?
    assert_equal 65_600, error.code
  end

  def test_version_status
    today = Date.new(2026, 9, 14)
    assert_equal :ok, L.version_status("202608", today: today)
    assert_equal :aging, L.version_status("202511", today: today)
    assert_equal :sunset, L.version_status("202509", today: today)
    assert_equal :future, L.version_status("202610", today: today)
    assert_equal :invalid, L.version_status("2026-08", today: today)
    assert_equal :invalid, L.version_status("202613", today: today)
    assert_raises(ArgumentError) { L::Client.new(api_version: "latest") }
  end

  # --- little text and payloads ---------------------------------------------

  def test_little_text_escapes_every_reserved_character
    assert_equal "a\\(b\\) \\[c\\] \\{d\\} \\<e\\> f\\|g h\\*i j\\_k l\\~m n\\\\o C\\# \\@home",
                 L::LittleText.escape("a(b) [c] {d} <e> f|g h*i j_k l~m n\\o C# @home")
  end

  def test_little_text_keeps_hashtags_and_mentions_as_elements
    assert_equal "#SmallBusiness and #AI2026", L::LittleText.escape("#SmallBusiness and #AI2026")
    assert_equal "Thanks @[Acme Co](urn:li:organization:123) \\(really\\)",
                 L::LittleText.escape("Thanks @[Acme Co](urn:li:organization:123) (really)")
    # A mention of anything but a person or organization URN is text, fully escaped.
    assert_equal "\\@\\[x\\]\\(https://evil.test\\)", L::LittleText.escape("@[x](https://evil.test)")
  end

  def test_an_article_payload_is_the_shape_linkedin_documents
    payload = L::Posts.article_payload(author: ORG, commentary: "Read (this)", source: "https://x.test/a/", title: "T",
                                       description: "D", thumbnail: "urn:li:image:1")
    assert_equal ORG, payload["author"]
    assert_equal "Read \\(this\\)", payload["commentary"]
    assert_equal "PUBLIC", payload["visibility"]
    assert_equal({ "feedDistribution" => "MAIN_FEED", "targetEntities" => [], "thirdPartyDistributionChannels" => [] },
                 payload["distribution"])
    assert_equal "PUBLISHED", payload["lifecycleState"]
    assert_equal false, payload["isReshareDisabledByAuthor"]
    assert_equal({ "source" => "https://x.test/a/", "title" => "T", "description" => "D", "thumbnail" => "urn:li:image:1" },
                 payload["content"]["article"])
    refute L::Posts.text_payload(author: "urn:li:person:abc", commentary: "x").key?("content")
  end

  def test_payload_arguments_are_checked
    assert_raises(ArgumentError) { L::Posts.text_payload(author: "urn:li:company:5", commentary: "x") }
    assert_raises(ArgumentError) do
      L::Posts.article_payload(author: ORG, commentary: "x", source: "javascript:alert(1)", title: "T", description: "D")
    end
    assert_raises(ArgumentError) { L::Posts.get(client(transport), "urn:li:share:1/../x") }
  end

  # --- OAuth --------------------------------------------------------------------

  def test_the_consent_url_encodes_its_parameters_and_never_the_secret
    url = oauth(transport).authorize_url(redirect_uri: "http://127.0.0.1:8765/callback", state: "s1",
                                         scopes: %w[w_organization_social r_organization_social])
    assert_equal "https://www.linkedin.com/oauth/v2/authorization?response_type=code&client_id=cid&" \
                 "redirect_uri=http%3A%2F%2F127.0.0.1%3A8765%2Fcallback&state=s1&scope=w_organization_social%20r_organization_social", url
    refute_includes url, "csecret"
    assert_raises(ArgumentError) { oauth(transport).authorize_url(redirect_uri: "/callback", state: "s", scopes: ["x"]) }
    assert_raises(ArgumentError) { oauth(transport).authorize_url(redirect_uri: "https://a.test/cb#f", state: "s", scopes: ["x"]) }
    assert_raises(ArgumentError) { L::OAuth.new(client_id: "", client_secret: "x") }
  end

  def test_exchange_refresh_and_introspect
    now = Time.utc(2026, 9, 14)
    scripted = transport
    scripted.on("POST", "https://www.linkedin.com/oauth/v2/accessToken",
                { "access_token" => "AT", "expires_in" => 5_184_000, "refresh_token" => "RT",
                  "refresh_token_expires_in" => 31_536_000, "scope" => "w_organization_social,r_organization_social" })
    scripted.on("POST", "https://www.linkedin.com/oauth/v2/introspectToken",
                { "active" => true, "status" => "active", "expires_at" => now.to_i + (3 * 86_400),
                  "scope" => "w_organization_social,r_organization_social", "auth_type" => "3L" })
    flow = oauth(scripted)

    token = flow.exchange(code: "C", redirect_uri: "http://127.0.0.1:8765/callback", now: now)
    assert_equal ["AT", "RT", 60], [token.access_token, token.refresh_token, token.days_left(now)]
    assert_equal %w[w_organization_social r_organization_social], token.scopes
    first = scripted.requests.first
    assert_equal({ "grant_type" => "authorization_code", "code" => "C", "redirect_uri" => "http://127.0.0.1:8765/callback",
                   "client_id" => "cid", "client_secret" => "csecret-abcdef" }, first.form)
    refute first.headers.key?("Authorization")
    refute first.headers.key?("LinkedIn-Version")
    refute_includes first.url, "csecret"

    flow.refresh(refresh_token: "RT", now: now)
    assert_equal "refresh_token", scripted.requests[1].form["grant_type"]

    info = flow.introspect("AT")
    assert info.active
    assert_equal 3, info.days_left(now)
    assert_equal "AT", scripted.requests[2].form["token"]
  end

  def test_a_code_exchange_is_never_retried
    scripted = transport.on("POST", "https://www.linkedin.com/oauth/v2/accessToken", { "error" => "server_error" }, status: 500)
    assert_raises(L::HTTPError) { oauth(scripted).exchange(code: "C", redirect_uri: "https://a.test/cb") }
    assert_equal 1, scripted.requests.size, "an authorization code is single-use"
  end

  def test_state_comparison
    assert L::OAuth.state_matches?("abc", "abc")
    refute L::OAuth.state_matches?("abc", "abd")
    refute L::OAuth.state_matches?("abc", "ab")
    refute L::OAuth.state_matches?("", "")
    assert_operator L::OAuth.new_state.length, :>=, 40
  end

  def test_the_member_behind_a_token
    scripted = transport.on("GET", "https://api.linkedin.com/v2/userinfo", { "sub" => "782bbtaQ", "name" => "John Doe" })
    assert_equal({ "urn" => "urn:li:person:782bbtaQ", "name" => "John Doe" }, L::OAuth.member(client(scripted)))
    refute scripted.requests.first.headers.key?("LinkedIn-Version"), "userinfo is not a versioned /rest call"
  end

  # --- images, pages, statistics -------------------------------------------

  def test_an_image_upload_reserves_a_slot_sends_the_bytes_and_waits
    Dir.mktmpdir do |dir|
      png = File.join(dir, "card.png")
      File.binwrite(png, ["89504e470d0a1a0a"].pack("H*"))
      scripted = transport
      scripted.on("POST", "https://api.linkedin.com/rest/images?action=initializeUpload",
                  { "value" => { "uploadUrl" => "https://www.linkedin.com/dms-uploads/abc/uploaded-image/0", "image" => "urn:li:image:C4E" } })
      scripted.on("PUT", "https://www.linkedin.com/dms-uploads/", nil, status: 201)
      scripted.on("GET", "https://api.linkedin.com/rest/images/urn%3Ali%3Aimage%3AC4E", { "status" => "AVAILABLE" })

      assert_equal "urn:li:image:C4E", L::Images.upload(client(scripted), owner: ORG, path: png, sleeper: NOSLEEP)
      assert_equal({ "initializeUploadRequest" => { "owner" => ORG } }, scripted.requests[0].json)
      assert_equal "image/png", scripted.requests[1].headers["Content-Type"]
      assert_equal File.binread(png), scripted.requests[1].body
      refute scripted.requests[1].headers.key?("LinkedIn-Version")

      svg = File.join(dir, "card.svg")
      File.write(svg, "<svg/>")
      ok, reason = L::Images.uploadable?(svg)
      refute ok
      assert_includes reason, ".svg"
    end
  end

  def test_pages_the_member_may_post_to_and_forbidden_is_nil_not_empty
    scripted = transport.on("GET", "https://api.linkedin.com/rest/organizationAcls?", { "elements" => [
      { "role" => "ANALYST", "organization" => "urn:li:organization:1", "state" => "APPROVED" },
      { "role" => "CONTENT_ADMINISTRATOR", "organizationTarget" => "urn:li:organization:2" },
      { "role" => "ADMINISTRATOR", "organizationTarget" => "urn:li:organization:2" }
    ] })
    pages = L::Organizations.administered(client(scripted))
    assert_equal [["urn:li:organization:2", "ADMINISTRATOR"]], pages.map { |page| [page.urn, page.role] }
    assert_equal({ "q" => "roleAssignee", "state" => "APPROVED", "count" => "100" }, scripted.requests.first.query)

    forbidden = transport.on("GET", "https://api.linkedin.com/rest/organizationAcls?", { "message" => "no" }, status: 403)
    assert_nil L::Organizations.administered(client(forbidden))
  end

  def test_page_statistics_are_batched_normalized_and_absent_means_zero
    scripted = transport.on("GET", "https://api.linkedin.com/rest/organizationalEntityShareStatistics?", { "elements" => [
      { "share" => "urn:li:share:1", "totalShareStatistics" => {
        "impressionCount" => 100, "clickCount" => 7, "likeCount" => -2, "commentCount" => 3, "shareCount" => 1,
        "uniqueImpressionsCount" => 80, "engagement" => 0.1
      } },
      { "share" => "urn:li:share:999", "totalShareStatistics" => { "impressionCount" => 5 } }
    ] })
    stats = L::Statistics.for_organization(client(scripted), organization: ORG, urns: %w[urn:li:share:1 urn:li:share:2 junk])
    assert_equal({ "impressions" => 100, "clicks" => 7, "reactions" => 0, "comments" => 3, "shares" => 1, "engagements" => 4 },
                 stats["urn:li:share:1"])
    assert_equal 0, stats["urn:li:share:2"]["impressions"]
    assert_equal %w[urn:li:share:1 urn:li:share:2], stats.keys.sort, "only posts this lane asked about"
    assert_includes scripted.requests.first.url, "shares=List(urn%3Ali%3Ashare%3A1,urn%3Ali%3Ashare%3A2)"
    assert_includes scripted.requests.first.url, "organizationalEntity=urn%3Ali%3Aorganization%3A5"
  end

  def test_member_post_statistics_read_one_metric_per_call
    counts = { "IMPRESSION" => 50, "REACTION" => 4, "COMMENT" => 2, "RESHARE" => 1, "LINK_CLICKS" => 9 }
    scripted = transport.on("GET", "https://api.linkedin.com/rest/memberCreatorPostAnalytics?", lambda do |request|
      { "elements" => [{ "count" => counts.fetch(request.query["queryType"]), "metricType" => request.query["queryType"] }] }
    end)
    stats = L::Statistics.for_member_post(client(scripted), urn: "urn:li:ugcPost:7")
    assert_equal({ "impressions" => 50, "clicks" => 9, "reactions" => 4, "comments" => 2, "shares" => 1, "engagements" => 7 }, stats)
    assert_equal 5, scripted.requests.size
    assert_includes scripted.requests.first.url, "entity=(ugc:urn%3Ali%3AugcPost%3A7)"
    assert_equal "TOTAL", scripted.requests.first.query["aggregation"]

    older = L::Client.new(token: TOKEN, api_version: "202601", transport: scripted, sleeper: NOSLEEP)
    assert_equal 0, L::Statistics.for_member_post(older, urn: "urn:li:share:7")["clicks"]
    assert_equal 9, scripted.requests.size, "LINK_CLICKS is not requested before 202604"
  end
end
