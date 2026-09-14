# frozen_string_literal: true

require "test_helper"

class AdminRoutesTest < ActionDispatch::IntegrationTest
  setup do
    @site = build_site
    write_file(@site, "assets/images/pixel.png", PNG)
    @site.sync!
  end

  test "the root redirects to the admin" do
    get "/"
    assert_redirected_to "/admin"
  end

  test "every index and new route renders" do
    ["/admin", admin_sites_path, admin_pages_path, admin_assets_path, admin_terms_path, new_admin_site_path,
     new_admin_page_path, new_admin_page_path(site_id: @site.id), new_abc_book_path].each do |path|
      get path
      assert_response :success, path
    end
  end

  test "every show and edit route renders for every indexed row" do
    get admin_site_path(@site)
    assert_response :success
    assert_select "pre.config", /collections_dir: pages/
    get edit_admin_site_path(@site)
    assert_response :success

    assert_operator @site.pages.count, :>, 10
    @site.pages.find_each do |page|
      get admin_page_path(page)
      assert_response :success, "show #{page.relative}"
      get edit_admin_page_path(page)
      assert_response :success, "edit #{page.relative}"
    end
    assert_operator @site.assets.count, :>=, 1
    @site.assets.find_each do |asset|
      get admin_asset_path(asset)
      assert_response :success, asset.relative
    end
    assert_operator @site.terms.count, :>=, 1
    @site.terms.find_each do |term|
      get admin_term_path(term)
      assert_response :success, term.to_s
    end
  end

  test "the site page counts pages per collection" do
    get admin_site_path(@site)
    @site.collection_counts.each do |collection, count|
      assert_select "td a", collection
      assert_select "td.right", count.to_s
    end
  end

  test "page filters narrow the index to exactly the matching rows" do
    expectations = {
      "draft:" => @site.pages.drafts,
      "live:" => @site.pages.live,
      "future:" => @site.pages.where(future: true),
      "error:" => @site.pages.where.not(error: [nil, ""]),
      "collection:docs" => @site.pages.where(collection: "docs"),
      "tag:fixture" => @site.pages.where(source_relative: "pages/_posts/2026-01-01-hello.md")
    }
    assert_operator expectations["draft:"].count, :>, 0
    assert_operator expectations["future:"].count, :>, 0
    expectations.each do |query, scope|
      get admin_pages_path(search: query)
      assert_response :success, query
      assert_select "tr.js-table-row", scope.count, query
    end
  end

  test "search matches title, description, author and source path" do
    get admin_pages_path(search: "outside-collections")
    assert_response :success
    assert_select "tr.js-table-row", @site.pages.where("source_relative LIKE ?", "%outside-collections%").count
    get admin_pages_path(search: "Hello")
    assert_select "tr.js-table-row a", /Hello/
  end

  test "pages sort by date, newest first, with undated pages last" do
    get admin_pages_path(per_page: 200)
    rows = css_select("tr.js-table-row").map { |row| row["data-url"] }
    ids = rows.map { |url| url[%r{/admin/pages/(\d+)}, 1].to_i }
    dates = ids.map { |id| Page.find(id).date }
    dated = dates.take_while(&:present?)
    assert_equal dated, dated.sort.reverse
    assert dates.drop(dated.size).all?(&:nil?), "undated pages come after every dated page"
    assert_equal "guides/template.md", Page.find(ids.last(dates.count(&:nil?)).find { |id| Page.find(id).source_relative == "guides/template.md" }).source_relative
  end
end
