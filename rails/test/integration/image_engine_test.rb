# frozen_string_literal: true

require "test_helper"

# The image-engine bridge end to end, over a copy of the Jekyll parity fixture:
# the `missing_preview:` filter, "Generate preview (local)" writing the key
# back through PageEditor, and every refusal.
#
# The real-engine tests run the zer0-image-generator the bundle locks — the
# 0.6.0 gem's Python engine — and skip cleanly when python3 with PyYAML is
# absent. A rasterizer is optional: without one the local provider keeps an
# SVG, so both extensions are accepted. With ZER0_IMAGE_GENERATOR_LIB pointing
# at an image generator checkout that ships Zer0ImageGenerator::Facade, the
# same generation also runs through the facade.
class ImageEngineTest < ActionDispatch::IntegrationTest
  HELLO = "pages/_posts/2026-01-01-hello.md"
  # The fixture's posts collection as the engine walks it: every .md under
  # pages/_posts with front matter (2026-02-02-no-front-matter.md has none).
  MISSING = %w[
    pages/_posts/2026-01-01-hello.md pages/_posts/2099-01-01-future.md
    pages/_posts/sub/2026-03-03-nested.md pages/_posts/undated.md
  ].freeze

  # A backend double for the refusal paths: no process, scripted effects.
  class FakeBackend
    attr_reader :calls

    def initialize(unavailable: nil, missing: [], &effect)
      @unavailable = unavailable
      @missing = missing
      @effect = effect
      @calls = []
    end

    def unavailable_reason = @unavailable
    def description = "fake engine"

    def missing_previews(_root)
      @calls << :missing
      @missing.map { |relative| ImageEngine::Missing.new(relative: relative) }
    end

    def generate(root, file, output_dir:, key:)
      @calls << [:generate, file, output_dir, key]
      @effect ? @effect.call(root, file) : { status: :skipped, log: [] }
    end
  end

  setup do
    @saved_backend = ImageEngine.instance_variable_get(:@backend)
    @site = build_site
    @page = @site.pages.find_by!(relative: HELLO)
  end

  teardown { ImageEngine.backend = @saved_backend }

  def disk(relative = HELLO)
    File.join(@site.path, relative)
  end

  def python_engine!
    backend = ImageEngine::PythonBackend.new
    skip "the locked image engine cannot run here: #{backend.unavailable_reason}" if backend.unavailable_reason
    ImageEngine.backend = backend
  end

  def facade_engine!
    lib = ENV["ZER0_IMAGE_GENERATOR_LIB"].to_s
    skip "set ZER0_IMAGE_GENERATOR_LIB to an image generator lib/ that ships the facade" unless File.file?(File.join(lib, "zer0_image_generator/facade.rb"))
    $LOAD_PATH.unshift(lib) unless $LOAD_PATH.include?(lib)
    ImageEngine.backend = ImageEngine::FacadeBackend.new
  end

  def assert_generates_through_page_editor
    before = File.binread(disk)
    assert_includes ImageEngine.missing_previews(@site).map(&:relative), HELLO

    post generate_preview_admin_page_path(@page)
    assert_redirected_to admin_page_path(@page)
    assert_match(/\AGenerated a local preview: preview: /, flash[:notice])

    after = File.binread(disk)
    value = after[%r{^preview: (/images/previews/hello\.(?:svg|png))$}, 1]
    assert value, "the preview key was written: #{after.inspect}"
    # PageEditor's line surgery appends a new key before the closing fence;
    # the engine's own writer would have put it under `title:`.
    assert_equal before.sub("tags: [fixture]\n", "tags: [fixture]\npreview: #{value}\n"), after
    image = File.join(@site.path, "assets", value)
    assert File.file?(image), "#{image} exists"

    @page.reload
    assert_equal value, @page.preview
    assert_equal Digest::SHA256.hexdigest(after), @page.digest
    assert @site.assets.exists?(relative: "assets#{value}"), "the new image is indexed"
    assert_empty Dir[File.join(@site.path, "pages/_posts/*.{bak,tmp~}")], "no engine scratch files are left"
    refute_includes ImageEngine.missing_previews(@site).map(&:relative), HELLO

    follow_redirect!
    assert_select "img[src=?]", "/files#{File.realpath(image)}"

    post generate_preview_admin_page_path(@page)
    assert_redirected_to admin_page_path(@page)
    assert_match "already has a preview", flash[:notice]
    assert_equal after, File.binread(disk)
  end

  test "the locked engine's missing list is the missing_preview: filter" do
    python_engine!
    assert_equal MISSING, ImageEngine.missing_previews(@site).map(&:relative)

    # The filter narrows the index, so a file the engine walks but Jekyll does
    # not read as content (undated.md in _posts) has no row to show.
    indexed = MISSING.select { |relative| @site.pages.exists?(relative: relative) }
    assert_equal MISSING - ["pages/_posts/undated.md"], indexed

    other = build_site(name: "other")
    get admin_pages_path(search: "site:#{@site.id} missing_preview:", per_page: 200)
    assert_response :success
    rows = css_select("tr.js-table-row").map { |row| Page.find(row["data-url"][%r{/admin/pages/(\d+)}, 1]).relative }
    assert_equal indexed.sort, rows.sort

    get admin_pages_path(search: "missing_preview:", per_page: 200)
    assert_select "tr.js-table-row", indexed.size * 2
    get admin_pages_path(search: "missing_preview:#{other.id}", per_page: 200)
    assert_select "tr.js-table-row", indexed.size
  end

  test "Generate preview (local) draws with the locked engine and writes the key through PageEditor" do
    python_engine!
    assert_generates_through_page_editor
  end

  test "Generate preview (local) draws through the image generator facade" do
    facade_engine!
    assert_generates_through_page_editor
  end

  test "a file changed since the last sync is refused before the engine runs" do
    fake = FakeBackend.new
    ImageEngine.backend = fake
    external = "#{File.read(disk)}Edited elsewhere.\n"
    File.write(disk, external)

    post generate_preview_admin_page_path(@page)
    assert_redirected_to admin_page_path(@page)
    assert_match "changed on disk since the last sync", flash[:alert]
    assert_empty fake.calls
    assert_equal external, File.read(disk)
  end

  test "an engine edit to anything but the preview key is undone" do
    ImageEngine.backend = FakeBackend.new do |_root, file|
      File.write(file, File.read(file).sub("title: Hello", "title: Rewritten\npreview: /images/previews/x.png"))
      { status: :generated, log: [] }
    end
    before = File.binread(disk)

    post generate_preview_admin_page_path(@page)
    assert_match "changed more than preview:", flash[:alert]
    assert_equal before, File.binread(disk)
    assert_equal Digest::SHA256.hexdigest(before), @page.reload.digest
  end

  test "an output_dir outside the site is refused before the engine runs" do
    fake = FakeBackend.new
    ImageEngine.backend = fake
    write_file(@site, "_config.yml", "#{File.read(disk("_config.yml"))}preview_images:\n  output_dir: ../../outside\n")

    post generate_preview_admin_page_path(@page)
    assert_match "resolves outside the site root", flash[:alert]
    assert_empty fake.calls
  end

  test "without a runnable engine the button is disabled and the filter says why" do
    ImageEngine.backend = FakeBackend.new(unavailable: "python3 with PyYAML is required")

    get admin_page_path(@page)
    assert_response :success
    assert_select "button[disabled][title=?]", "python3 with PyYAML is required", text: "Generate preview (local)"
    assert_select "a[href=?][target=_blank]", "http://localhost:3000", text: "Image generator ↗"

    get admin_pages_path(search: "site:#{@site.id} missing_preview:", per_page: 200)
    assert_response :success
    assert_match "missing_preview: is unavailable", response.body
    assert_select "tr.js-table-row", @site.pages.count

    post generate_preview_admin_page_path(@page)
    assert_match "No preview generated: python3 with PyYAML is required", flash[:alert]
  end

  test "the site page links to its missing previews and to the image generator" do
    ImageEngine.backend = FakeBackend.new(missing: [HELLO])
    get admin_site_path(@site)
    assert_select "a[href=?]", admin_pages_path(search: "site:#{@site.id} missing_preview:"), text: "Missing previews"
    get admin_pages_path(search: "site:#{@site.id} missing_preview:")
    assert_select "tr.js-table-row", 1
  end
end
