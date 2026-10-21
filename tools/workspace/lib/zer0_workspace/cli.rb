# frozen_string_literal: true

# The `bin/zer0` command line: one entry point for every project in the
# workspace. Commands print for people by default and emit JSON with --json
# where CI consumes them. Only this file prints or exits; the classes it drives
# return values.

require "json"
require "optparse"

module Zer0Workspace
  class CLI
    USAGE = <<~TEXT
      usage: bin/zer0 <command> [options]

        list                         every project: path, kind, what it publishes, what gates it
        info <project>               one project in full
        run <task> [project...]      run setup|check|test|build|pages for the named projects
            --all                    every project that has the task (the default with no names)
            --affected [--base REF]  only projects changed since REF (default origin/main), plus dependents
            --dry-run                print the commands without running them
            --keep-going             do not stop at the first failure
        affected [--base REF]        projects changed since REF, plus the projects that depend on them
            --files f1,f2            use these paths instead of asking git
            --json                   {"affected": [...], "direct": [...], "unowned": [...]}
        matrix <task> [--affected]   JSON list of projects that have <task>, for a CI matrix
        routes [--json]              where the one Pages deploy serves each site (route, path, pages task)
        check                        the workspace contract: registration, paths, workflows, routes, vendored copies
        vendor [--write]             vendored copies and whether each still matches its source
        doctor [project...]          the CMS's zer0 doctor on every zer0 site in the workspace
            --strict                 exit 1 when any site has an error (default: report only)
            --verbose                print each site's full doctor report
        tags [--remote NAME]         tags on the remote: this repository's releases vs. those inherited from the fork
            --delete                 delete the inherited ones on the remote and locally
            --json                   {"own": [...], "inherited": [...], "other": [...]}
    TEXT

    def initialize(argv, root:, out: $stdout, err: $stderr)
      @argv = argv.dup
      @root = root
      @out = out
      @err = err
    end

    # Returns the process exit status.
    def run
      command = @argv.shift
      case command
      when nil, "-h", "--help", "help" then @out.puts(USAGE) || 0
      when "list" then list
      when "info" then info
      when "run" then run_task
      when "affected" then affected
      when "matrix" then matrix
      when "routes" then routes
      when "check" then check
      when "vendor" then vendor
      when "doctor" then doctor
      when "tags" then tags
      else
        @err.puts "bin/zer0: unknown command #{command.inspect}\n\n#{USAGE}"
        2
      end
    rescue ManifestError, OptionParser::ParseError => e
      @err.puts "bin/zer0: #{e.message}"
      2
    end

    private

    def manifest
      @manifest ||= Manifest.load(@root)
    end

    def list
      json = parse { |o, opts| o.on("--json") { opts[:json] = true } }[:json]
      if json
        @out.puts JSON.pretty_generate(manifest.projects.map { |p| summary_hash(p) })
        return 0
      end

      rows = manifest.projects.map { |p| [p.name, p.path, p.kind, p.publishes.join(" ").then { |s| s.empty? ? "-" : s }, p.workflow || "none"] }
      table([%w[PROJECT PATH KIND PUBLISHES CI], *rows])
      0
    end

    def info
      name = @argv.shift or raise OptionParser::MissingArgument, "info needs a project name"
      p = manifest.project(name)
      @out.puts "#{p.name} — #{p.summary}"
      @out.puts "  path:       #{p.path}#{p.paths.empty? ? "" : "  (owns #{p.paths.join(", ")})"}"
      @out.puts "  kind:       #{p.kind}   stack: #{p.stack.join(", ")}"
      @out.puts "  upstream:   #{p.upstream}" unless p.upstream.empty?
      @out.puts "  depends on: #{p.depends_on.empty? ? "-" : p.depends_on.join(", ")}"
      @out.puts "  used by:    #{manifest.dependents_of(p.name).then { |d| d.empty? ? "-" : d.join(", ") }}"
      @out.puts "  publishes:  #{p.publishes.empty? ? "-" : p.publishes.join(", ")}"
      @out.puts "  ci:         #{p.ci}"
      @out.puts "  site:       #{p.site_root} (checked by bin/zer0 doctor)" if p.site_root
      TASKS.each do |t|
        spec = p.task(t) or next
        where = spec.cwd == "." ? "" : " (in #{spec.cwd})"
        env = spec.env.empty? ? "" : " [#{spec.env.map { |k, v| "#{k}=#{v}" }.join(" ")}]"
        @out.puts "  #{t.ljust(6)}      #{spec.run}#{where}#{env}"
      end
      0
    end

    def run_task
      task = @argv.shift or raise OptionParser::MissingArgument, "run needs a task (#{TASKS.join("|")})"
      raise OptionParser::InvalidArgument, "unknown task #{task} (#{TASKS.join("|")})" unless TASKS.include?(task)

      opts = parse do |o, h|
        o.on("--all") { h[:all] = true }
        o.on("--affected") { h[:affected] = true }
        o.on("--base REF") { |v| h[:base] = v }
        o.on("--dry-run") { h[:dry_run] = true }
        o.on("--keep-going") { h[:keep_going] = true }
      end
      names = @argv.empty? ? with_task(task, opts) : @argv.each { |n| manifest.project(n) }
      if names.empty?
        @out.puts "Nothing to run: no #{opts[:affected] ? "affected " : ""}project has a #{task} task."
        return 0
      end

      results = Runner.new(manifest, out: @out, dry_run: opts[:dry_run], keep_going: opts[:keep_going]).run(task, names)
      @out.puts
      results.each { |r| @out.puts "  #{r.status.to_s.ljust(8)} #{r.project}#{r.status == :passed || r.status == :failed ? " (#{r.seconds}s)" : ""}" }
      results.all?(&:ok?) ? 0 : 1
    end

    def affected
      opts = parse do |o, h|
        o.on("--base REF") { |v| h[:base] = v }
        o.on("--files LIST", Array) { |v| h[:files] = v }
        o.on("--json") { h[:json] = true }
      end
      result = Ownership.new(manifest).affected(opts[:files] || changed_files(opts[:base]))
      if opts[:json]
        @out.puts JSON.generate(result)
      else
        @out.puts(result[:affected].empty? ? "No project is affected." : result[:affected].join("\n"))
        @err.puts "(workspace files only: #{result[:unowned].length})" if result[:affected].empty? && !result[:unowned].empty?
      end
      0
    end

    def matrix
      task = @argv.shift or raise OptionParser::MissingArgument, "matrix needs a task"
      opts = parse do |o, h|
        o.on("--affected") { h[:affected] = true }
        o.on("--base REF") { |v| h[:base] = v }
      end
      @out.puts JSON.generate(with_task(task, opts))
      0
    end

    # The one Pages deploy's plan: every routed project, root first. pages.yml builds a
    # matrix from --json and stitches each build into the artifact at its route.
    # Where a site's Gemfile lives: its site root (already relative to the repository
    # root), or the project directory when it declares none. pages.yml bundles there.
    def bundle_dir(project)
      project.site_root || project.path
    end

    def routes
      json = parse { |o, opts| o.on("--json") { opts[:json] = true } }[:json]
      routed = manifest.projects.select(&:route_path).sort_by { |p| [p.route_path == "/" ? 0 : 1, p.route_path] }
      if json
        @out.puts JSON.generate(routed.map { |p| { name: p.name, path: p.path, route: p.route_path, bundle_dir: bundle_dir(p) } })
        return 0
      end

      unrouted = manifest.projects.select { |p| p.publishes.include?("pages") && p.route_path.nil? }
      table([%w[ROUTE PROJECT PATH], *routed.map { |p| [p.route_path, p.name, p.path] }])
      unrouted.each { |p| @out.puts "  (no route) #{p.name}: #{p.route || "—"}" }
      0
    end

    def check
      findings = Checks.new(manifest).run
      if findings.empty?
        @out.puts "workspace OK — #{manifest.projects.length} projects, #{manifest.vendored.length} vendored copies, every rule green."
        return 0
      end

      findings.each { |f| @out.puts "  ✗ #{f}" }
      @out.puts "\n#{findings.length} finding(s)."
      1
    end

    def vendor
      write = parse { |o, h| o.on("--write") { h[:write] = true } }[:write]
      v = Vendor.new(manifest)
      if write
        written = v.write!
        @out.puts(written.empty? ? "Every vendored copy already matches its source." : written.map { |w| "re-vendored #{w.copy}" }.join("\n"))
        return 0
      end

      v.statuses.each { |s| @out.puts "  #{s.state.to_s.ljust(14)} #{s.vendored.copy}\n  #{"".ljust(14)} ← #{s.vendored.source}" }
      v.statuses.all? { |s| s.state == :same } ? 0 : 1
    end

    def doctor
      opts = parse do |o, h|
        o.on("--strict") { h[:strict] = true }
        o.on("--verbose") { h[:verbose] = true }
      end
      reports = Doctor.new(manifest).run(@argv)
      reports.each do |r|
        @out.puts r.output if opts[:verbose]
        @out.puts "  #{(r.ok? ? "ok" : "errors").ljust(7)} #{r.project.ljust(22)} #{r.errors} error(s), #{r.warnings} warning(s)  (#{r.root})"
      end
      return 0 unless opts[:strict]

      reports.all?(&:ok?) ? 0 : 1
    end

    def tags
      opts = parse do |o, h|
        o.on("--remote NAME") { |v| h[:remote] = v }
        o.on("--delete") { h[:delete] = true }
        o.on("--json") { h[:json] = true }
      end
      remote = opts[:remote] || "origin"
      t = Tags.new(@root)
      groups = t.classify(t.remote_tags(remote))
      if opts[:json]
        @out.puts JSON.generate(groups.to_h)
      else
        @out.puts "#{remote}: #{groups.own.length} release tag(s) of this repository, #{groups.inherited.length} inherited, #{groups.other.length} other"
        @out.puts "  own:       #{groups.own.join(" ")}" unless groups.own.empty?
        @out.puts "  inherited: #{groups.inherited.join(" ")}" unless groups.inherited.empty?
        @out.puts "  other:     #{groups.other.join(" ")}" unless groups.other.empty?
      end
      return 0 unless opts[:delete]
      return @out.puts("Nothing to delete.") || 0 if groups.inherited.empty?

      failed = t.delete!(remote, groups.inherited)
      @out.puts "deleted #{groups.inherited.length - failed.length} inherited tag(s) from #{remote} and this clone"
      return 0 if failed.empty?

      @err.puts "could not delete on #{remote}: #{failed.join(" ")}"
      1
    end

    def with_task(task, opts)
      names = manifest.projects.select { |p| p.task(task) }.map(&:name)
      return names unless opts[:affected]

      affected = Ownership.new(manifest).affected(changed_files(opts[:base]))[:affected]
      names & affected
    end

    # Files changed between the merge base with `base` and the working tree,
    # so local, uncommitted edits count too.
    def changed_files(base)
      base ||= "origin/main"
      mb = git("merge-base", base, "HEAD").strip
      raise ManifestError, "cannot find a merge base with #{base} (fetch it first)" if mb.empty?

      (git("diff", "--name-only", mb).split("\n") + git("ls-files", "--others", "--exclude-standard").split("\n")).uniq
    end

    def git(*args)
      IO.popen(["git", "-C", @root, *args], err: File::NULL, &:read)
    end

    def parse
      opts = {}
      OptionParser.new { |o| yield o, opts }.parse!(@argv)
      opts
    end

    def summary_hash(p)
      { name: p.name, path: p.path, kind: p.kind, stack: p.stack, summary: p.summary, upstream: p.upstream,
        depends_on: p.depends_on, publishes: p.publishes, ci: p.ci, site: p.site_root, route: p.route_path,
        tasks: p.tasks.keys }
    end

    def table(rows)
      widths = rows.transpose.map { |col| col.map(&:length).max }
      rows.each { |r| @out.puts r.each_with_index.map { |c, i| c.ljust(widths[i]) }.join("  ").rstrip }
    end
  end
end
