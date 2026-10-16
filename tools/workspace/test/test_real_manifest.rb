# frozen_string_literal: true

# The repository's own workspace.yml: it loads, and every rule of
# `bin/zer0 check` passes against the real tree. This is the test that fails
# when a project is imported without being registered, a vendored copy
# drifts, or a workflow stops filtering on the path it gates.
#
# Run: ruby tools/workspace/test/test_real_manifest.rb

require "minitest/autorun"
require_relative "../lib/zer0_workspace"

class TestRealManifest < Minitest::Test
  ROOT = File.expand_path("../../..", __dir__)

  def manifest
    @manifest ||= Zer0Workspace::Manifest.load(ROOT)
  end

  def test_loads
    refute_empty manifest.projects
  end

  Zer0Workspace::Checks::RULES.each do |rule|
    define_method(:"test_rule_#{rule}") do
      findings = Zer0Workspace::Checks.new(manifest).run(only: [rule])
      assert_empty findings.map(&:to_s), "bin/zer0 check — #{rule}"
    end
  end

  # Every project the manifest says publishes Pages or a package is one
  # docs/MONOREPO.md accounts for, so a new project cannot ship unmentioned.
  def test_every_project_is_in_the_monorepo_guide
    guide = File.read(File.join(ROOT, "docs/MONOREPO.md"))
    manifest.projects.each do |p|
      next if p.path == "." || p.path == "rails"

      assert_includes guide, "`#{p.path}/`", "docs/MONOREPO.md does not mention #{p.path}/"
    end
  end
end
