# frozen_string_literal: true

# Tests for Zer0Workspace (bin/zer0): the manifest's validation, file
# ownership and the affected set, the structural checks, the vendored-copy
# contract, the task runner and the CLI's exit codes. Each test builds a small
# throwaway workspace with its own git repository, so nothing here depends on
# the real workspace.yml — test_real_manifest.rb covers that one.
#
# Run: ruby tools/workspace/test/test_workspace.rb

require "minitest/autorun"
require "tmpdir"
require "fileutils"
require "stringio"
require_relative "../lib/zer0_workspace"

class WorkspaceTestCase < Minitest::Test
  MANIFEST = <<~YAML
    version: 1
    projects:
      root-app:
        path: "."
        paths: ["src/**", "package.json"]
        kind: extension
        summary: The root project.
        ci: root.yml
        tasks:
          check: "true"
      theme:
        path: packages/theme
        kind: gem
        summary: A theme.
        ci: theme.yml
        tasks:
          check: "true"
          test:
            run: "exit 3"
            cwd: lib
      site:
        path: sites/site
        kind: site
        site: "."
        summary: A site built on the theme.
        depends_on: [theme]
        ci: none — nothing to test
        tasks:
          build: "true"
    vendored:
      - copy: src/tokens.css
        source: packages/theme/tokens.css
  YAML

  def setup
    @root = Dir.mktmpdir("zer0-ws")
    write("workspace.yml", MANIFEST)
    write("src/a.ts", "a")
    write("package.json", "{}")
    write("packages/theme/tokens.css", "--x: 1;")
    write("packages/theme/lib/.keep", "")
    write("src/tokens.css", "--x: 1;")
    write("sites/site/index.md", "hi")
    write(".github/workflows/root.yml", "on: [push]\n")
    write(".github/workflows/theme.yml", "on:\n  pull_request:\n    paths: [\"packages/theme/**\"]\n")
    git("init", "-q")
    git("add", "-A")
  end

  def teardown
    FileUtils.remove_entry(@root)
  end

  def write(rel, body)
    path = File.join(@root, rel)
    FileUtils.mkdir_p(File.dirname(path))
    File.write(path, body)
  end

  def git(*args)
    system("git", "-C", @root, *args, out: File::NULL, err: File::NULL) or raise "git #{args.join(" ")} failed"
  end

  def manifest
    Zer0Workspace::Manifest.load(@root)
  end

  def cli(*argv)
    out = StringIO.new
    err = StringIO.new
    status = Zer0Workspace::CLI.new(argv, root: @root, out: out, err: err).run
    [status, out.string, err.string]
  end
end

class TestManifest < WorkspaceTestCase
  def test_loads_projects_in_order_with_tasks
    m = manifest
    assert_equal %w[root-app theme site], m.names
    assert_equal "lib", m.project("theme").task("test").cwd
    assert_equal ".", m.project("theme").task("check").cwd
    assert_nil m.project("site").workflow
    assert_equal ["packages/theme/**"], m.project("theme").globs
  end

  def test_dependents_are_transitive
    write("workspace.yml", MANIFEST.sub("vendored:\n", <<~YAML.gsub(/^/, "  ") + "vendored:\n"))
      blog:
        path: sites/blog
        kind: site
        summary: Built on the site.
        depends_on: [site]
        ci: none — demo
    YAML
    assert_equal %w[site blog], manifest.dependents_of("theme")
  end

  def test_rejects_unknown_keys_kinds_tasks_and_dependencies
    bad = MANIFEST.sub("kind: gem", "kind: library")
    write("workspace.yml", bad)
    assert_raises(Zer0Workspace::ManifestError) { manifest }

    write("workspace.yml", MANIFEST.sub("check: \"true\"\n      test:", "lint: \"true\"\n      test:"))
    err = assert_raises(Zer0Workspace::ManifestError) { manifest }
    assert_match(/unknown task lint/, err.message)

    write("workspace.yml", MANIFEST.sub("depends_on: [theme]", "depends_on: [nope]"))
    err = assert_raises(Zer0Workspace::ManifestError) { manifest }
    assert_match(/not a project/, err.message)

    write("workspace.yml", MANIFEST.sub("    summary: A theme.\n", "    summary: A theme.\n    colour: blue\n"))
    err = assert_raises(Zer0Workspace::ManifestError) { manifest }
    assert_match(/unknown key\(s\) colour/, err.message)
  end

  def test_root_project_must_list_its_paths
    write("workspace.yml", MANIFEST.sub("    paths: [\"src/**\", \"package.json\"]\n", ""))
    err = assert_raises(Zer0Workspace::ManifestError) { manifest }
    assert_match(/must list the paths/, err.message)
  end

  def test_rejects_cycles
    write("workspace.yml", MANIFEST.sub("    summary: A theme.\n", "    summary: A theme.\n    depends_on: [site]\n"))
    err = assert_raises(Zer0Workspace::ManifestError) { manifest }
    assert_match(/cycle/, err.message)
  end
end

class TestOwnership < WorkspaceTestCase
  def test_most_specific_glob_wins_and_workflows_map_to_their_project
    o = Zer0Workspace::Ownership.new(manifest)
    assert_equal "root-app", o.owner("src/a.ts")
    assert_equal "root-app", o.owner("package.json")
    assert_equal "theme", o.owner("packages/theme/x/y.rb")
    assert_equal "theme", o.owner(".github/workflows/theme.yml")
    assert_nil o.owner(".github/workflows/unrelated.yml")
    assert_nil o.owner("docs/README.md")
    assert_nil o.owner("packages/themes/x"), "a sibling with a longer name is not inside the project"
  end

  def test_affected_adds_dependents_and_reports_unowned_files
    r = Zer0Workspace::Ownership.new(manifest).affected(["packages/theme/a.rb", "docs/x.md"])
    assert_equal %w[theme site], r[:affected]
    assert_equal %w[theme], r[:direct]
    assert_equal %w[docs/x.md], r[:unowned]
  end

  def test_a_shared_workflow_affects_every_project_it_gates
    write("workspace.yml", MANIFEST.sub("ci: none — nothing to test", "ci: theme.yml"))
    o = Zer0Workspace::Ownership.new(manifest)
    assert_equal %w[theme site], o.owners(".github/workflows/theme.yml")
    assert_equal %w[theme site], o.affected([".github/workflows/theme.yml"])[:direct]
  end

  def test_plain_globs_do_not_cross_directories
    refute Zer0Workspace::Ownership.match?("*.json", "a/b.json")
    assert Zer0Workspace::Ownership.match?("src/**", "src/deep/file")
  end
end

class TestChecks < WorkspaceTestCase
  def findings
    Zer0Workspace::Checks.new(manifest).run.map(&:to_s)
  end

  def test_a_consistent_workspace_has_no_findings
    assert_empty findings
  end

  def test_unregistered_container_directory_is_a_finding
    write("apps/stray/README.md", "x")
    assert(findings.any? { |f| f.include?("apps/stray/ is not registered") })
  end

  def test_missing_workflow_and_wrong_path_filter_are_findings
    FileUtils.rm(File.join(@root, ".github/workflows/root.yml"))
    write(".github/workflows/theme.yml", "on:\n  pull_request:\n    paths: [\"elsewhere/**\"]\n")
    f = findings
    assert(f.any? { |x| x.include?("root.yml, which does not exist") })
    assert(f.any? { |x| x.include?("none is under packages/theme/") })
  end

  def test_none_without_a_reason_is_a_finding
    write("workspace.yml", MANIFEST.sub("ci: none — nothing to test", "ci: none"))
    assert(findings.any? { |x| x.include?("without a reason") })
  end

  def test_glob_matching_no_tracked_file_is_a_finding
    write("workspace.yml", MANIFEST.sub("\"package.json\"]", "\"package.json\", \"gone.txt\"]"))
    assert(findings.any? { |x| x.include?("\"gone.txt\" matches no tracked file") })
  end

  def test_vendored_drift_is_a_finding_and_vendor_write_repairs_it
    write("packages/theme/tokens.css", "--x: 2;")
    assert(findings.any? { |x| x.include?("src/tokens.css has drifted") })

    written = Zer0Workspace::Vendor.new(manifest).write!
    assert_equal ["src/tokens.css"], written.map(&:copy)
    assert_equal "--x: 2;", File.read(File.join(@root, "src/tokens.css"))
    assert_empty findings
  end
end

class TestRunner < WorkspaceTestCase
  def test_runs_in_the_task_directory_with_its_env_and_skips_projects_without_it
    calls = []
    spawn = ->(env, cmd, dir) { calls << [env, cmd, dir]; cmd != "exit 3" }
    results = Zer0Workspace::Runner.new(manifest, out: StringIO.new, spawn: spawn, keep_going: true)
                                   .run("test", %w[root-app theme site])
    assert_equal %i[skipped failed skipped], results.map(&:status)
    assert_equal [[{}, "exit 3", File.join(File.realpath(@root), "packages/theme/lib")]],
                 calls.map { |e, c, d| [e, c, File.realpath(d)] }
  end

  def test_stops_at_the_first_failure_unless_told_to_keep_going
    spawn = ->(_env, _cmd, _dir) { false }
    results = Zer0Workspace::Runner.new(manifest, out: StringIO.new, spawn: spawn).run("check", %w[root-app theme])
    assert_equal %i[failed], results.map(&:status)
  end

  def test_dry_run_spawns_nothing
    spawn = ->(*) { flunk "dry run must not spawn" }
    results = Zer0Workspace::Runner.new(manifest, out: StringIO.new, spawn: spawn, dry_run: true).run("check", %w[theme])
    assert_equal %i[skipped], results.map(&:status)
  end
end

class TestCLI < WorkspaceTestCase
  def test_exit_codes
    assert_equal 0, cli("list").first
    assert_equal 0, cli("check").first
    assert_equal 0, cli("vendor").first
    assert_equal 2, cli("bogus").first
    assert_equal 2, cli("info", "nope").first
    assert_equal 2, cli("run", "lint").first
  end

  def test_run_reports_failure_with_status_one
    status, out, = cli("run", "test", "theme")
    assert_equal 1, status
    assert_match(/failed\s+theme/, out)
  end

  def test_check_fails_on_drift
    write("packages/theme/tokens.css", "--x: 9;")
    status, out, = cli("check")
    assert_equal 1, status
    assert_match(/drifted/, out)
  end

  def test_affected_with_files_and_json
    _, out, = cli("affected", "--files", "packages/theme/a,README.md", "--json")
    data = JSON.parse(out)
    assert_equal %w[theme site], data["affected"]
    assert_equal %w[README.md], data["unowned"]
  end

  def test_matrix_lists_projects_with_the_task
    _, out, = cli("matrix", "check")
    assert_equal %w[root-app theme], JSON.parse(out)
  end
end

class TestDoctor < WorkspaceTestCase
  def test_checks_every_declared_site_and_parses_the_result_line
    seen = []
    capture = ->(root) { seen << root; "...\nresult: 2 error(s), 5 warning(s)\n" }
    reports = Zer0Workspace::Doctor.new(manifest, capture: capture).run
    assert_equal %w[sites/site], seen
    assert_equal [[2, 5]], reports.map { |r| [r.errors, r.warnings] }
    refute reports.first.ok?
  end

  def test_a_doctor_that_prints_no_result_counts_as_an_error
    reports = Zer0Workspace::Doctor.new(manifest, capture: ->(_) { "boom" }).run
    assert_equal 1, reports.first.errors
  end

  def test_a_project_without_a_site_root_is_refused
    assert_raises(Zer0Workspace::ManifestError) { Zer0Workspace::Doctor.new(manifest, capture: ->(_) { "" }).run(%w[theme]) }
  end

  def test_site_root_joins_the_project_path
    assert_equal "sites/site", manifest.project("site").site_root
    assert_nil manifest.project("theme").site_root
  end
end
