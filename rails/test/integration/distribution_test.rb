# frozen_string_literal: true

require "test_helper"

# The browser surface of the distribution lane, over a copy of the Jekyll
# fixture site with a ScriptedTransport in place of LinkedIn: nothing here
# opens a socket, and an unscripted call fails the test.
class DistributionTest < ActionDispatch::IntegrationTest
  L = Zer0Cms::LinkedIn
  AUTHOR = "urn:li:organization:5"
  POST = "pages/_posts/2026-09-01-share-me.md"
  CLEAN = { "LINKEDIN_ACCESS_TOKEN" => nil, "LINKEDIN_REFRESH_TOKEN" => nil, "LINKEDIN_CLIENT_ID" => nil,
            "LINKEDIN_CLIENT_SECRET" => nil, "ZER0_LINKEDIN_PUBLISH" => nil, "LINKEDIN_ORG_URN" => nil,
            "LINKEDIN_AUTHOR_URN" => nil, "ZER0_CMS_LINKEDIN_REDIRECT_URI" => nil }.freeze

  setup do
    @site = build_site
    write_file(@site, POST, "---\ntitle: Share me\ndescription: A page worth sharing\ntags: [erp, ai]\n---\nBody\n")
    write_file(@site, "zer0.json", JSON.generate("distribution" => { "linkedin" => {
      "author" => AUTHOR, "siteUrl" => "https://example.test", "queue" => "drafts/linkedin", "ledger" => ".zer0/ledger.json"
    } }))
    @site.sync!
    @transport = L::ScriptedTransport.new
    LinkedinGateway.transport = @transport
  end

  teardown { LinkedinGateway.transport = nil }

  def draft_file
    Dir[File.join(@site.path, "drafts/linkedin/*.md")].first
  end

  test "the distribution pages and channel routes render" do
    with_env(CLEAN) do
      get admin_distribution_path
      assert_response :success
      assert_select "td", text: AUTHOR
      get admin_distribution_site_path(@site)
      assert_response :success
      assert_select "td", text: "Share me"
      get admin_channels_path
      assert_response :success
      get new_admin_channel_path
      assert_response :success
    end
  end

  test "a person drafts, approves and publishes, and every gate is checked by the server" do
    with_env(CLEAN) do
      page = @site.pages.find_by!(relative: POST)
      post admin_distribution_drafts_path(@site), params: { page_id: page.id }
      id = File.basename(draft_file, ".md")
      assert_redirected_to admin_distribution_draft_path(@site, id)
      follow_redirect!
      assert_response :success
      assert_select "pre.config", /"author": "#{AUTHOR}"/
      assert_includes File.read(draft_file), "status: pending"

      post admin_distribution_publish_path(@site, id), params: { confirm: "1" }
      assert_match(/draft status is pending/, flash[:alert])
      post admin_distribution_publish_path(@site, id)
      assert_match(/Tick the confirmation/, flash[:alert])

      post admin_distribution_approve_path(@site, id)
      assert_includes File.read(draft_file), "status: approved"

      post admin_distribution_publish_path(@site, id), params: { confirm: "1" }
      assert_match(/not armed/, flash[:alert])
      assert_empty @transport.requests

      @transport.on("POST", "https://api.linkedin.com/rest/posts", nil, status: 201, headers: { "x-restli-id" => "urn:li:share:77" })
      with_env("ZER0_LINKEDIN_PUBLISH" => "1", "LINKEDIN_ACCESS_TOKEN" => "tok-SECRET-123456") do
        post admin_distribution_publish_path(@site, id), params: { confirm: "1" }
      end
      assert_match(/Published/, flash[:notice])
      assert_equal 1, @transport.requests.size
      assert_includes File.read(draft_file), "linkedin_urn: urn:li:share:77"
      assert_includes File.read(File.join(@site.path, ".zer0/ledger.json")), "urn:li:share:77"

      get admin_distribution_site_path(@site)
      assert_response :success
      assert_select "a[href='https://www.linkedin.com/feed/update/urn:li:share:77/']"
      refute_includes response.body, "tok-SECRET-123456"
    end
  end

  test "a channel connects only through this session's state, and its token is encrypted and never shown" do
    channel = Channel.create!(site: @site, author_urn: AUTHOR, name: "The page")
    with_env(CLEAN) do
      post connect_admin_channel_path(channel)
      assert_match(/LINKEDIN_CLIENT_ID/, flash[:alert])
    end

    with_env(CLEAN.merge("LINKEDIN_CLIENT_ID" => "cid", "LINKEDIN_CLIENT_SECRET" => "csecret-abcdef")) do
      get linkedin_callback_path(state: "forged", code: "C")
      assert_response :forbidden

      post connect_admin_channel_path(channel)
      location = response.location
      assert location.start_with?("https://www.linkedin.com/oauth/v2/authorization?")
      query = URI.decode_www_form(URI.parse(location).query).to_h
      assert_equal ["cid", "http://localhost/oauth/linkedin/callback"], query.values_at("client_id", "redirect_uri")
      assert_equal "w_organization_social r_organization_social rw_organization_admin", query["scope"]
      refute_includes location, "csecret"

      @transport.on("POST", "https://www.linkedin.com/oauth/v2/accessToken",
                    { "access_token" => "AT-secret-token-value", "expires_in" => 5_184_000, "scope" => "w_organization_social,r_organization_social" })
      get linkedin_callback_path(state: query["state"], code: "C")
      assert_redirected_to admin_channel_path(channel)
      channel.reload
      assert channel.connected?
      assert_equal 60, channel.days_left
      stored = Channel.connection.select_value("SELECT access_token FROM channels WHERE id = #{channel.id}")
      refute_includes stored, "AT-secret-token-value"

      get admin_channel_path(channel)
      assert_response :success
      refute_includes response.body, "AT-secret-token-value"

      get linkedin_callback_path(state: query["state"], code: "C")
      assert_response :forbidden, "a state is single-use"

      patch admin_channel_path(channel), params: { channel: { name: "The page", author_urn: "urn:li:organization:6" } }
      refute channel.reload.connected?, "a channel that changes author forgets its token"

      post disconnect_admin_channel_path(channel)
      refute channel.reload.connected?
    end

    filter = ActiveSupport::ParameterFilter.new(Rails.application.config.filter_parameters)
    assert_equal({ "code" => "[FILTERED]", "state" => "[FILTERED]" }, filter.filter("code" => "C", "state" => "S"))
  end
end
