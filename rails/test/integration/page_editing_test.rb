# frozen_string_literal: true

require "test_helper"

class PageEditingTest < ActionDispatch::IntegrationTest
  HELLO = "pages/_posts/2026-01-01-hello.md"

  setup do
    @site = build_site
    @page = @site.pages.find_by!(relative: HELLO)
  end

  def disk(relative = HELLO)
    File.join(@site.path, relative)
  end

  def form_for(page)
    get edit_admin_page_path(page)
    assert_response :success
    submitted_form_values
  end

  test "an edit rewrites only the edited line" do
    before = File.binread(disk)
    values = form_for(@page)
    patch admin_page_path(@page), params: { page: values.merge("title" => "Hello, edited: yes") }
    assert_redirected_to admin_page_path(@page)

    after = File.binread(disk)
    changed = before.lines.zip(after.lines).reject { |old, new| old == new }
    assert_equal before.lines.size, after.lines.size
    assert_equal [["title: Hello\n", "title: \"Hello, edited: yes\"\n"]], changed
    assert_equal "Hello, edited: yes", @page.reload.title
    assert_equal Digest::SHA256.hexdigest(after), @page.digest
  end

  test "an unchanged save of any indexed file is a byte-for-byte no-op" do
    Dir[Rails.root.join("test/fixtures/front_matter/*.md")].each do |source|
      write_file(@site, "pages/_docs/#{File.basename(source)}", File.binread(source))
    end
    write_file(@site, "pages/_docs/windows.md", "﻿---\r\ntitle: 'Windows'\r\ndate: 2025-09-03\r\n---\r\nBody\r\n")
    @site.sync!

    @site.pages.find_each do |page|
      before = File.binread(disk(page.relative))
      mtime = File.mtime(disk(page.relative))
      patch admin_page_path(page), params: { page: form_for(page) }
      assert_response :see_other, page.relative
      assert_equal "No changes — #{page.relative} was not written.", flash[:notice], page.relative
      assert_equal before, File.binread(disk(page.relative)), page.relative
      assert_equal mtime, File.mtime(disk(page.relative)), page.relative
    end
  end

  test "a file changed on disk since the last sync is refused and left alone" do
    values = form_for(@page).merge("title" => "Mine")
    external = "#{File.read(disk)}Edited in another editor.\n"
    File.write(disk, external)

    get edit_admin_page_path(@page)
    assert_response :conflict
    patch admin_page_path(@page), params: { page: values }
    assert_response :conflict
    assert_match "changed on disk since the last sync", response.body
    assert_select "form.button_to[action=?]", sync_admin_site_path(@site)
    assert_equal external, File.read(disk)
  end

  test "a form opened before the index changed is refused" do
    values = form_for(@page)
    patch admin_page_path(@page), params: { page: values.merge("title" => "Late", "base_digest" => "0" * 64) }
    assert_response :conflict
    assert_equal "---\ntitle: Hello\ntags: [fixture]\n---\nA dated post.\n", File.read(disk)
  end

  test "emptying a present key deletes it; an empty absent key stays absent" do
    values = form_for(@page)
    patch admin_page_path(@page), params: { page: values.merge("tags" => "", "description" => "") }
    assert_equal "---\ntitle: Hello\n---\nA dated post.\n", File.read(disk)
  end

  test "lists keep their style and new keys go before the closing fence" do
    values = form_for(@page)
    patch admin_page_path(@page), params: { page: values.merge("tags" => "fixture, yes, 2026", "author" => "amr") }
    assert_equal "---\ntitle: Hello\ntags: [fixture, \"yes\", \"2026\"]\nauthor: amr\n---\nA dated post.\n", File.read(disk)
    assert_equal %w[fixture yes 2026], @page.reload.tags
  end

  test "the body is replaced without touching the front matter, in the file's line endings" do
    path = write_file(@site, "pages/_docs/crlf.md", "---\r\ntitle: Win\r\n---\r\nOld body\r\n")
    @site.sync!
    page = @site.pages.find_by!(relative: "pages/_docs/crlf.md")
    values = form_for(page)
    patch admin_page_path(page), params: { page: values.merge("body" => "New body\r\nline two\r\n", "title" => "Mac") }
    assert_equal "---\r\ntitle: Mac\r\n---\r\nNew body\r\nline two\r\n", File.binread(path)
  end

  test "an update through a symlink is refused and the target is untouched" do
    target = File.join(scratch_dir, "target.md")
    File.write(target, "---\ntitle: Outside\n---\n")
    values = form_for(@page)
    File.delete(disk)
    File.symlink(target, disk)

    patch admin_page_path(@page), params: { page: values.merge("title" => "Pwned") }
    assert_response :unprocessable_entity
    assert_match "symlink", response.body
    assert_equal "---\ntitle: Outside\n---\n", File.read(target)
  end

  test "an update cannot be steered outside the site by the index" do
    @page.update_columns(relative: "../outside.md")
    patch admin_page_path(@page), params: { page: { "title" => "x" } }
    assert_response :unprocessable_entity
    refute File.exist?(File.join(File.dirname(@site.path), "outside.md"))
  end

  test "a new page is created by the writer in a declared collection and section" do
    FileUtils.mkdir_p(File.join(@site.path, "pages/_posts/hacks"))
    post admin_pages_path, params: { page: { site_id: @site.id, collection: "posts", section: "hacks",
                                             title: "Brand new: hack", tags: "a, b", draft: "1", body: "Hi\r\n" } }
    relative = "pages/_posts/hacks/#{Date.today.iso8601}-brand-new-hack.md"
    created = @site.pages.find_by!(relative: relative)
    assert_redirected_to edit_admin_page_path(created)
    doc = Zer0Cms::Cms::FrontMatter.parse(File.read(disk(relative)), strict: true)
    assert_equal({ "title" => "Brand new: hack", "tags" => %w[a b], "draft" => true }, doc.data.except("date"))
    assert_equal "Hi\n", doc.body
  end

  test "a new page in an undeclared collection is refused" do
    post admin_pages_path, params: { page: { site_id: @site.id, collection: "../../etc", title: "x" } }
    assert_response :unprocessable_entity
    assert_match "unknown collection", response.body
  end

  test "duplicate writes a draft copy next to the original" do
    post duplicate_admin_page_path(@page)
    copy = @site.pages.find_by!(relative: "pages/_posts/2026-01-01-hello-copy.md")
    assert_redirected_to edit_admin_page_path(copy)
    assert copy.draft
    assert_equal "Hello (copy)", copy.title
  end

  test "destroy deletes the file and its row" do
    delete admin_page_path(@page)
    assert_redirected_to admin_pages_path
    refute File.exist?(disk)
    refute Page.exists?(@page.id)
  end

  test "destroy refuses a file that changed since the last sync" do
    File.write(disk, "changed\n")
    delete admin_page_path(@page)
    assert_redirected_to admin_page_path(@page)
    assert File.exist?(disk)
  end

  test "the markdown preview returns sanitized HTML" do
    post admin_markdown_preview_path, params: { markdown: "# Hi\n\n<script>alert(1)</script>\n\n[x](javascript:alert(1))" }
    assert_response :success
    assert_includes response.body, "<h1"
    refute_includes response.body, "<script"
    refute_includes response.body, "javascript:"
  end
end
