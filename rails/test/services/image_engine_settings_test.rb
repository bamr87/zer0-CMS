# frozen_string_literal: true

require "test_helper"

# ImageEngine's pure parts: reading `preview_images:` and parsing the Python
# engine's `--list-missing` output. No engine process runs here.
class ImageEngineSettingsTest < ActiveSupport::TestCase
  setup { @site = build_site }

  def config(text)
    write_file(@site, "_config.yml", "#{File.read(File.join(@site.path, "_config.yml"))}#{text}")
  end

  test "defaults match the engine's own" do
    settings = ImageEngine.settings_for(@site)
    assert_equal "preview", settings.key
    assert_equal "assets/images/previews", settings.output_dir
  end

  test "the site's preview_images block is honoured" do
    config("preview_images:\n  front_matter_key: image\n  output_dir: img/og/\n")
    settings = ImageEngine.settings_for(@site)
    assert_equal "image", settings.key
    assert_equal "img/og", settings.output_dir
  end

  # The engine joins output_dir onto the source with no normalisation, so an
  # absolute value is a path outside the site there too.
  test "an output_dir or key that could escape is refused" do
    { "  output_dir: ../outside\n" => /resolves outside the site root/,
      "  output_dir: /img/og\n" => /resolves outside the site root/,
      "  output_dir: .\n" => /below the site source/,
      "  front_matter_key: \"a: b\"\n" => /not a plain key/ }.each do |line, message|
      original = File.read(File.join(@site.path, "_config.yml"))
      config("preview_images:\n#{line}")
      error = assert_raises(ImageEngine::Error) { ImageEngine.settings_for(@site) }
      assert_match message, error.message
      File.write(File.join(@site.path, "_config.yml"), original)
    end
  end

  test "an output_dir through a symlink out of the site is refused" do
    outside = scratch_dir
    File.symlink(outside, File.join(@site.path, "assets-link"))
    config("preview_images:\n  output_dir: assets-link/previews\n")
    assert_raises(ImageEngine::Error) { ImageEngine.settings_for(@site) }
  end

  test "list-missing output parses to root-relative paths, ANSI and all" do
    root = @site.path
    output = +"\e[0;36m====\e[0m\n"
    output << "\e[1;33mMissing preview:\e[0m #{root}/pages/_posts/2026-01-01-hello.md\n  Title: Hello\n\n"
    output << "\e[1;33mMissing preview:\e[0m #{root}/pages/_posts/with space.md\n  Title: A: b\n"
    output << "  Current preview (not found): /images/previews/gone.png\n\n"
    output << "\e[1;33mMissing preview:\e[0m /elsewhere/_posts/x.md\n  Title: Outside\n\n"
    missing = ImageEngine::PythonBackend.parse_missing(output, root)
    assert_equal ["pages/_posts/2026-01-01-hello.md", "pages/_posts/with space.md"], missing.map(&:relative)
    assert_equal ["Hello", "A: b"], missing.map(&:title)
    assert_equal [nil, "/images/previews/gone.png"], missing.map(&:preview)
  end
end
