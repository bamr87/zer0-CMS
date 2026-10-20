# frozen_string_literal: true

require "test_helper"

class GenerationJobTest < ActiveJob::TestCase
  # Drives the real engine against a throwaway copy of the CI fixture site with
  # the free `local` provider — the same end-to-end path the CLI's integration
  # job exercises, but through the web job.

  FIXTURE = Rails.root.join("..", "test", "fixture-site").expand_path

  setup do
    @dir = Dir.mktmpdir
    FileUtils.cp_r(FIXTURE.to_s + "/.", @dir)
    @site = Site.create!(name: "Fixture", path: @dir)
  end

  teardown { FileUtils.remove_entry(@dir) }

  test "a dry run writes nothing and records no artifacts" do
    run = @site.runs.create!(kind: "dry_run", params: { "collection" => "all" })
    GenerationJob.perform_now(run.id)
    run.reload
    assert_equal "succeeded", run.status
    assert_equal 0, run.artifacts.count
    refute Dir.exist?(File.join(@dir, "assets", "images", "previews")),
           "dry run must not create the output directory"
  end

  test "a local generate produces PNGs and wires front matter, no .bak left" do
    run = @site.runs.create!(kind: "generate",
                             params: { "collection" => "all", "rasterizer" => "inkscape" })
    GenerationJob.perform_now(run.id)
    run.reload

    skip "no rasterizer available on this host" if run.stats["errors"].to_i.positive? &&
                                                    run.log.include?("No SVG rasterizer")

    assert_equal "succeeded", run.status, run.error
    assert_operator run.artifacts.count, :>=, 1
    run.artifacts.each { |a| assert a.exists?, "artifact #{a.path} should be on disk" }
    assert_empty Dir.glob(File.join(@dir, "**", "*.bak")), "no .bak files may survive"
    body = File.read(Dir.glob(File.join(@dir, "_posts", "*.md")).first)
    assert_match(/^preview:/, body, "front matter should be wired")
  end

  test "a second generate run is idempotent" do
    2.times do
      run = @site.runs.create!(kind: "generate",
                               params: { "collection" => "all", "rasterizer" => "inkscape" })
      GenerationJob.perform_now(run.id)
      @last = run.reload
    end
    skip "no rasterizer" if @last.log.include?("No SVG rasterizer")
    assert_operator @last.stats["skipped"].to_i, :>=, 1, "existing previews should be skipped"
    assert_equal 0, @last.stats["generated"].to_i
  end
end
