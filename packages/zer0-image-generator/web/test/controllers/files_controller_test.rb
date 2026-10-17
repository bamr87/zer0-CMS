# frozen_string_literal: true

require "test_helper"

class FilesControllerTest < ActionDispatch::IntegrationTest
  # The allow-list check is the entire security boundary for serving files that
  # live outside public/. These tests assert it cannot be walked out of.

  setup do
    @dir = Dir.mktmpdir
    File.write(File.join(@dir, "_config.yml"), "title: t\n")
    FileUtils.mkdir_p(File.join(@dir, "assets"))
    # A 1x1 PNG so the content-type path is exercised.
    File.binwrite(File.join(@dir, "assets", "ok.png"),
                  ["89504e470d0a1a0a"].pack("H*") + "rest-of-png")
    @site = Site.create!(name: "S", path: @dir)
  end

  teardown { FileUtils.remove_entry(@dir) }

  test "serves a file inside a registered site" do
    get "/files#{@dir}/assets/ok.png", headers: modern
    assert_response :success
    assert_equal "image/png", response.media_type
  end

  test "refuses a path outside every allowed root" do
    secret = Tempfile.new(["secret", ".png"])
    secret.write("nope"); secret.flush
    get "/files#{secret.path}", headers: modern
    assert_includes [403, 404], response.status, "must not serve files outside a registered root"
    secret.close!
  end

  test "a traversal attempt cannot escape a registered root" do
    # /files/<site>/assets/../../../etc/hosts must not resolve to /etc/hosts.
    get "/files#{@dir}/assets/../../../../../../etc/hosts", headers: modern
    assert_includes [403, 404], response.status
  end

  test "refuses a non-image extension even inside a root" do
    File.write(File.join(@dir, "secret.txt"), "data")
    get "/files#{@dir}/secret.txt", headers: modern
    refute_equal 200, response.status
  end

  test "serves the repo's first-party sample artwork (the Library depends on it)" do
    sample = Rails.application.config.repo_root.join("docs/samples/constellation.svg")
    skip "sample not present" unless sample.file?

    get "/files#{sample.realpath}", headers: modern
    assert_response :success
    assert_equal "image/svg+xml", response.media_type
  end

  private

  def modern
    { "User-Agent" => "Mozilla/5.0 Chrome/125.0 Safari/537.36", "Host" => "localhost" }
  end
end
