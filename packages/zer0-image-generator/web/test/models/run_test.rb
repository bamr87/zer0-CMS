# frozen_string_literal: true

require "test_helper"

class RunTest < ActiveSupport::TestCase
  def with_site
    Dir.mktmpdir do |dir|
      File.write(File.join(dir, "_config.yml"), "title: t\n")
      yield Site.create!(name: "S", path: dir)
    end
  end

  test "site-scoped kinds require a site; studio kinds forbid one" do
    with_site do |site|
      assert site.runs.new(kind: "generate").valid?
      refute Run.new(kind: "generate").valid?, "generate needs a site"
      assert Run.new(kind: "studio").valid?, "studio has no site"
      refute site.runs.new(kind: "studio").valid?, "studio must not carry a site"
    end
  end

  test "append_log concatenates without read-modify-write loss" do
    run = Run.new(kind: "studio", status: "running")
    run.save!
    run.append_log("line 1\n")
    run.append_log("line 2\n")
    assert_equal "line 1\nline 2\n", run.reload.log
  end

  test "lifecycle transitions set timestamps and status" do
    run = Run.create!(kind: "studio")
    run.start!
    assert run.running?
    assert run.started_at
    run.finish!(stats: { "generated" => 3 })
    assert_equal "succeeded", run.status
    assert run.finished?
    assert_equal 3, run.stats["generated"]
  end
end
