# frozen_string_literal: true

require "test_helper"

class DashboardControllerTest < ActionDispatch::IntegrationTest
  test "dashboard links every feature" do
    get root_path, headers: modern
    assert_response :success
    assert_select "a[href=?]", sites_path
    assert_select "a[href=?]", runs_path
    assert_select "a[href=?]", compositions_path
    assert_select "a[href=?]", new_composition_path
    assert_select "a[href=?]", studio_root_path
    assert_select "a[href=?]", library_entries_path
    assert_select "a[href=?]", freesvg_search_path
    assert_select "a[href=?]", credentials_path
  end

  test "sidebar lists a registered site" do
    dir = Dir.mktmpdir
    File.write(File.join(dir, "_config.yml"), "title: t\n")
    site = Site.create!(name: "fixture-blog", path: dir)

    get root_path, headers: modern
    assert_response :success
    assert_select "a[href=?]", site_path(site), text: /fixture-blog/
  ensure
    FileUtils.remove_entry(dir) if dir
  end

  private

  def modern
    { "User-Agent" => "Mozilla/5.0 Chrome/125.0 Safari/537.36", "Host" => "localhost" }
  end
end
