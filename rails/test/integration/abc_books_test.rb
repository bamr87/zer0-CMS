# frozen_string_literal: true

require "test_helper"

class AbcBooksTest < ActionDispatch::IntegrationTest
  def book_params(extra = {})
    style = Zer0Cms::Abc::ArtStyles.default.to_menu["styles"].first["id"]
    { theme: "IT systems", art_style: style, audience: "toddler", slug: "it-test-book" }.merge(extra)
  end

  test "the wizard renders inside the admin layout" do
    get new_abc_book_path
    assert_response :success
    assert_select "nav.sidebar"
    assert_select "input[name=target]"
  end

  test "the wizard preview renders the book and writes nothing" do
    post preview_abc_book_path, params: book_params
    assert_response :success
    assert_select "pre", /layout: book-abc/
  end

  test "export refuses a missing target" do
    post export_abc_book_path, params: book_params
    assert_redirected_to new_abc_book_path
    assert_match "Choose the target site directory", flash[:alert]
  end

  test "export refuses a directory without _config.yml" do
    target = scratch_dir
    post export_abc_book_path, params: book_params(target: target)
    assert_redirected_to new_abc_book_path
    assert_match "no _config.yml", flash[:alert]
    assert_empty Dir.children(target)
  end

  test "export refuses the SITES_DIR mount itself" do
    mount = scratch_dir
    File.write(File.join(mount, "_config.yml"), "title: mount\n")
    Rails.application.config.x.sites_dir = mount
    post export_abc_book_path, params: book_params(target: mount)
    assert_redirected_to new_abc_book_path
    refute File.exist?(File.join(mount, "pages"))
  end

  test "export writes the bundle into an explicit Jekyll root" do
    site = build_site
    post export_abc_book_path, params: book_params(target: site.path)
    assert_response :success
    assert File.file?(File.join(site.path, "pages/_books/it-test-book/index.md"))
    assert File.file?(File.join(site.path, "_data/abc_books/it-test-book.json"))
  end

  test "the catalog is JSON" do
    get abc_catalog_path
    assert_response :success
    assert_includes response.parsed_body.keys, "themes"
  end
end
