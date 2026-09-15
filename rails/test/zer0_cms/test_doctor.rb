# frozen_string_literal: true

require "minitest/autorun"
require "digest"
require "fileutils"
require "json"
require "open3"
require "rbconfig"
require "tmpdir"
require_relative "../../lib/zer0_cms/doctor"

class TestDoctor < Minitest::Test
  Doctor = Zer0Cms::Doctor
  CLI = File.expand_path("../../bin/zer0-cms", __dir__)

  ALIGNED = {
    "_config.yml" => "remote_theme: bamr87/zer0-mistakes@v1\ncollections_dir: pages\npreview_images:\n  provider: local\n",
    ".theme-overrides.yml" => "overrides: []\n",
    "Gemfile" => "source \"https://rubygems.org\"\ngem \"zer0-image-generator\", \"~> 0.6\", group: :jekyll_plugins\n",
    "zer0.json" => "{\n  // console dialect\n  \"$schema\": \"https://example.com/zer0.schema.json\",\n  \"contentFolders\": [\n    { \"path\": \"[[workspace]]/pages/_posts\", },\n    { \"path\": \"[[workspace]]/pages/{{year}}/x\" },\n  ],\n}\n",
    "fleet.manifest.yml" => "name: fixture\nlanes: []\n",
    "pages/_posts/2026-01-01-hello.md" => "---\ntitle: Hello\ndate: 2026-01-01\nlastmod: 2026-01-02\ndescription: d\nlayout: article\ncategories: [a]\ntags: [b]\nauthor: rhea\n---\nBody\n"
  }.freeze

  def site(files = ALIGNED)
    Dir.mktmpdir do |dir|
      files.each do |rel, text|
        next if text.nil?

        path = File.join(dir, rel)
        FileUtils.mkdir_p(File.dirname(path))
        File.write(path, text)
      end
      yield dir
    end
  end

  def rules(report, severity = nil)
    report.findings.select { |f| severity.nil? || f["severity"] == severity }.map { |f| f["rule"] }.sort
  end

  def test_an_aligned_site_is_clean
    site do |dir|
      report = Doctor.run(dir)
      assert_empty report.findings, report.findings.inspect
      assert report.ok?
    end
  end

  def test_distribution_check
    with_block = lambda do |block|
      ALIGNED.merge("zer0.json" => ALIGNED["zer0.json"].sub("\"$schema\"", "\"distribution\": { \"linkedin\": #{block} },\n  \"$schema\""))
    end
    valid = '{ "author": "urn:li:organization:1", "siteUrl": "https://example.test", "ledger": "log.json" }'
    site(with_block.call(valid)) { |dir| assert_empty Doctor.run(dir).findings.select { |f| f["check_id"] == "distribution" } }

    site(with_block.call('{ "author": "urn:li:company:1", "publishAllow": true }')) do |dir|
      report = Doctor.run(dir)
      assert_equal %w[distribution-config-invalid], rules(report, "error").grep(/distribution/)
      assert_includes rules(report, "warning"), "distribution-config"
      refute report.ok?
    end
    site(with_block.call(valid).merge("log.json" => "{ not json")) do |dir|
      assert_includes rules(Doctor.run(dir), "error"), "distribution-ledger-unreadable"
    end
    site(with_block.call('{ "author": "urn:li:person:x", "queue": "../outside" }')) do |dir|
      assert_includes rules(Doctor.run(dir), "error"), "distribution-config-invalid"
    end
    site(ALIGNED.merge("scripts/features/linkedin/posts.py" => "# publisher\n")) do |dir|
      finding = Doctor.run(dir).findings.find { |f| f["rule"] == "vendored-linkedin-publisher" }
      assert_equal ["warning", "scripts/features/linkedin/posts.py"], finding.values_at("severity", "file")
    end
  end

  def test_theme_check
    site(ALIGNED.merge("_config.yml" => "remote_theme: someone/else\npreview_images: {}\n", ".theme-overrides.yml" => nil)) do |dir|
      assert_equal %w[no-theme-overrides theme-not-zer0], rules(Doctor.run(dir)).grep(/theme/)
    end
    site(ALIGNED.merge("_config.yml" => "theme: jekyll-theme-zer0\npreview_images: {}\n")) do |dir|
      assert_empty rules(Doctor.run(dir))
    end
    site(ALIGNED.merge("_config.yml" => "title: [broken\n")) do |dir|
      finding = Doctor.run(dir).findings.find { |f| f["rule"] == "config-unreadable" }
      assert_equal ["error", "_config.yml", 1], finding.values_at("severity", "file", "line")
    end
    site(ALIGNED.merge("_config.yml" => nil)) do |dir|
      assert_includes rules(Doctor.run(dir), "error"), "config-unreadable"
    end
  end

  def test_image_engine_check
    files = ALIGNED.merge(
      "_config.yml" => "remote_theme: bamr87/zer0-mistakes\n",
      "Gemfile" => "gem \"github-pages\"\n",
      "_plugins/preview_image_generator.rb" => "config = site.config['preview_images']\n",
      "_plugins/preview_generator.rb" => "config = site.config['preview_images']\n",
      "scripts/lib/preview_generator.py" => "cfg = config.get('preview_images', {})\n"
    )
    site(files) do |dir|
      report = Doctor.run(dir)
      assert_equal %w[vendored-preview-fork] * 3, rules(report, "error")
      assert_equal %w[gemfile-missing-image-generator no-preview-images-config], rules(report, "warning")
      assert_equal %w[_plugins/preview_generator.rb _plugins/preview_image_generator.rb scripts/lib/preview_generator.py],
                   report.findings.select { |f| f["severity"] == "error" }.map { |f| f["file"] }.sort
    end
  end

  # it-journey's _plugins/preview_generator.rb mirrors pages under /preview/
  # for Front Matter CMS; it shares the fork's filename but not its job.
  def test_a_namesake_that_does_not_read_preview_images_is_not_a_fork
    files = ALIGNED.merge(
      "_plugins/preview_generator.rb" => "config = site.config['preview_generator'] || {}\n"
    )
    site(files) do |dir|
      refute_includes rules(Doctor.run(dir), "error"), "vendored-preview-fork"
    end
  end

  def test_cms_check
    site(ALIGNED.merge("zer0.json" => nil)) do |dir|
      assert_equal %w[no-zer0-json], rules(Doctor.run(dir))
    end
    site(ALIGNED.merge("zer0.json" => "{ \"contentFolders\": [ { \"path\": \"[[workspace]]/pages/_nope\" } ] }")) do |dir|
      report = Doctor.run(dir)
      assert_equal %w[content-folder-missing], rules(report, "error")
      assert_equal %w[zer0-json-no-schema], rules(report, "warning")
    end
    site(ALIGNED.merge("zer0.json" => "{ \"$schema\": \"x\", // ok\n \"a\": \"//not a comment\" /* block */, }")) do |dir|
      assert_empty rules(Doctor.run(dir))
    end
    site(ALIGNED.merge("zer0.json" => "{ \"$schema\": \"x\" \"missing comma\": 1 }")) do |dir|
      assert_equal %w[zer0-json-invalid], rules(Doctor.run(dir), "error")
    end
  end

  def test_fleet_check_is_strict
    { "name: a\n  wrapped: at column 80 went wrong\nx: [\n" => "fleet-manifest-invalid",
      "name: a\nname: b\n" => "fleet-manifest-invalid",
      "- a list\n" => "fleet-manifest-invalid",
      "base: &b {x: 1}\nother: *b\n" => "fleet-manifest-invalid" }.each do |text, rule|
      site(ALIGNED.merge("fleet.manifest.yml" => text)) do |dir|
        assert_equal [rule], rules(Doctor.run(dir), "error"), text
      end
    end
    site(ALIGNED.merge("fleet.manifest.yml" => nil)) do |dir|
      assert_empty rules(Doctor.run(dir))
    end
  end

  def test_content_check_uses_the_theme_schema
    files = ALIGNED.merge(
      "pages/_posts/2026-01-02-thin.md" => "---\ntitle: Thin\nlastmod: ''\n---\nBody\n",
      "pages/_posts/2026-01-03-broken.md" => "---\ntitle: [x\n---\nBody\n"
    )
    site(files) do |dir|
      report = Doctor.run(dir)
      broken = report.findings.find { |f| f["rule"] == "front-matter-invalid" }
      assert_equal ["error", "pages/_posts/2026-01-03-broken.md", 2], broken.values_at("severity", "file", "line")
      thin = report.findings.select { |f| f["file"] == "pages/_posts/2026-01-02-thin.md" }.map { |f| f["rule"] }.sort
      assert_equal %w[author categories date description lastmod layout tags].map { |k| "missing-key:#{k}" }, thin
      assert(report.findings.select { |f| f["rule"].start_with?("missing-key:") }.all? { |f| f["severity"] == "warning" })
    end
  end

  def test_a_sites_own_schema_wins_and_schema_option_wins_over_it
    own = "global:\n  required_fields: [owned]\n"
    site(ALIGNED.merge(".github/config/frontmatter_schema.yml" => own)) do |dir|
      report = Doctor.run(dir)
      assert_equal ["missing-key:owned"], rules(report)
      assert_equal File.join(dir, ".github/config/frontmatter_schema.yml"), report.schema
      option = File.join(dir, "strict.yml")
      File.write(option, "global:\n  required_fields: [flag]\n")
      assert_equal ["missing-key:flag"], rules(Doctor.run(dir, schema: option))
    end
  end

  def test_vendored_schema_is_the_theme_contract
    schema = YAML.safe_load(File.read(Doctor::VENDORED_SCHEMA))
    assert_equal %w[title lastmod], schema.dig("global", "required_fields")
    assert_includes schema["collections"].keys, "posts"
  end

  def test_findings_shape_and_fingerprint
    finding = Doctor.finding("cms", "warning", "no-zer0-json", "no zer0.json", file: "zer0.json")
    assert_equal %w[check_id severity file line rule evidence fingerprint], finding.keys
    assert_equal Digest::SHA1.hexdigest("cms|no-zer0-json|zer0.json|no zer0.json")[0, 12], finding["fingerprint"]
  end

  def test_cli_formats_and_exit_codes
    site(ALIGNED.merge("zer0.json" => "not json")) do |dir|
      out, status = Open3.capture2(RbConfig.ruby, CLI, "doctor", dir, "--format", "findings")
      assert_equal 1, status.exitstatus
      lines = out.lines.map { |line| JSON.parse(line) }
      assert_equal ["zer0-json-invalid"], lines.map { |f| f["rule"] }
      text, status = Open3.capture2(RbConfig.ruby, CLI, "doctor", dir)
      assert_equal 1, status.exitstatus
      assert_match(/cms +1 error\(s\), 0 warning\(s\)/, text)
      assert_match(/result: 1 error\(s\), 0 warning\(s\)/, text)
    end
    site do |dir|
      _out, status = Open3.capture2(RbConfig.ruby, CLI, "doctor", dir)
      assert_equal 0, status.exitstatus
    end
    _out, err, status = Open3.capture3(RbConfig.ruby, CLI, "doctor", "--format", "xml", Dir.pwd)
    assert_equal 2, status.exitstatus
    assert_match(/invalid argument/, err)
  end
end
