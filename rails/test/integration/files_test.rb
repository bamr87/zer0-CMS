# frozen_string_literal: true

require "test_helper"

class FilesTest < ActionDispatch::IntegrationTest
  setup do
    @site = build_site
    @image = write_file(@site, "assets/images/pixel.png", PNG)
    @outside = scratch_dir
    File.binwrite(File.join(@outside, "secret.png"), PNG)
  end

  def fetch(absolute)
    get "/files#{absolute}"
  end

  test "serves an image inside a registered site, sandboxed" do
    fetch(@image)
    assert_response :success
    assert_equal "image/png", response.media_type
    assert_equal PNG, response.body
    assert_includes response.headers["Content-Security-Policy"], "sandbox"
    assert_equal "nosniff", response.headers["X-Content-Type-Options"]
  end

  test "refuses a file outside every site" do
    fetch(File.join(@outside, "secret.png"))
    assert_response :not_found
  end

  test "refuses traversal out of a site" do
    relative_out = Pathname.new(@outside).relative_path_from(Pathname.new(@site.path)).to_s
    fetch("#{@site.path}/#{relative_out}/secret.png")
    assert_response :forbidden
    get "/files#{@site.path}/assets/%2e%2e/%2e%2e/#{relative_out}/secret.png"
    assert_includes [403, 404], response.status
    refute_equal PNG, response.body
  end

  test "refuses a symlinked file inside a site" do
    link = File.join(@site.path, "assets/images/link.png")
    File.symlink(File.join(@outside, "secret.png"), link)
    fetch(link)
    assert_response :forbidden
  end

  test "refuses a symlinked directory inside a site" do
    File.symlink(@outside, File.join(@site.path, "assets/linked"))
    fetch(File.join(@site.path, "assets/linked/secret.png"))
    assert_response :forbidden
  end

  test "refuses anything that is not an image, with an empty body" do
    fetch(File.join(@site.path, "_config.yml"))
    assert_response :not_found
    assert_empty response.body
    fetch(File.join(@site.path, "assets/images/missing.png"))
    assert_response :not_found
    assert_empty response.body
  end

  test "the preview thumbnail resolves through /files" do
    File.write(File.join(@site.path, "pages/_posts/2026-01-01-hello.md"),
               "---\ntitle: Hello\npreview: /assets/images/pixel.png\n---\nBody\n")
    @site.sync!
    page = @site.pages.find_by!(relative: "pages/_posts/2026-01-01-hello.md")
    get admin_page_path(page)
    assert_select "img[src=?]", "/files#{@image}"
  end
end
