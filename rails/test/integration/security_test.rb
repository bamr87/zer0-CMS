# frozen_string_literal: true

require "test_helper"

class SecurityTest < ActionDispatch::IntegrationTest
  def credentials(user, password)
    { "HTTP_AUTHORIZATION" => ActionController::HttpAuthentication::Basic.encode_credentials(user, password) }
  end

  test "basic auth is enforced on every surface when ZER0_CMS_PASSWORD is set" do
    with_env("ZER0_CMS_PASSWORD" => "s3cret") do
      [admin_sites_path, new_abc_book_path, "/files/nothing.png"].each do |path|
        get path
        assert_response :unauthorized, path
      end
      get admin_sites_path, env: credentials("zer0", "wrong")
      assert_response :unauthorized
      get admin_sites_path, env: credentials("zer0", "s3cret")
      assert_response :success
      get admin_sites_path, env: credentials("zer0", "s3cret").merge("REMOTE_ADDR" => "192.168.1.20")
      assert_response :success
    end
  end

  test "an empty ZER0_CMS_USER (how compose passes an unset one) means the default user" do
    with_env("ZER0_CMS_PASSWORD" => "s3cret", "ZER0_CMS_USER" => "") do
      get admin_sites_path, env: credentials("", "s3cret")
      assert_response :unauthorized
      get admin_sites_path, env: credentials("zer0", "s3cret")
      assert_response :success
    end
  end

  test "without a password, requests from other machines are refused" do
    [admin_sites_path, admin_pages_path, new_abc_book_path, "/files/tmp/x.png"].each do |path|
      get path, env: { "REMOTE_ADDR" => "192.168.1.20" }
      assert_response :forbidden, path
    end
    get admin_sites_path, env: { "REMOTE_ADDR" => "::1" }
    assert_response :success
  end

  test "X-Forwarded-For cannot claim loopback, and a forwarded remote client is refused" do
    get admin_sites_path, env: { "REMOTE_ADDR" => "10.0.0.2", "HTTP_X_FORWARDED_FOR" => "127.0.0.1" }
    assert_response :forbidden
    get admin_sites_path, env: { "REMOTE_ADDR" => "127.0.0.1", "HTTP_X_FORWARDED_FOR" => "203.0.113.9" }
    assert_response :forbidden
  end

  test "an unknown Host header is refused" do
    host! "attacker.example"
    get admin_sites_path
    assert_response :forbidden
  end

  test "the CSP carries a fresh nonce that the importmap scripts use" do
    get admin_pages_path
    policy = response.headers["Content-Security-Policy"]
    nonce = policy[/script-src [^;]*'nonce-([^']+)'/, 1]
    assert nonce, policy
    assert_no_match(/unsafe-inline|unsafe-eval/, policy[/script-src[^;]*/])
    assert_select "script[type=importmap][nonce=?]", nonce
    assert_select "script[type=module][nonce=?]", nonce
    assert_select "meta[name=csp-nonce][content=?]", nonce

    get admin_sites_path
    refute_equal nonce, response.headers["Content-Security-Policy"][/'nonce-([^']+)'/, 1]
  end

  test "a write without the CSRF token is rejected" do
    site = build_site
    page = site.pages.find_by!(relative: "pages/_posts/2026-01-01-hello.md")
    before = File.read(File.join(site.path, page.relative))
    ActionController::Base.allow_forgery_protection = true
    patch admin_page_path(page), params: { page: { title: "forged" } }
    assert_response :unprocessable_content
    assert_equal before, File.read(File.join(site.path, page.relative))
  ensure
    ActionController::Base.allow_forgery_protection = false
  end
end
