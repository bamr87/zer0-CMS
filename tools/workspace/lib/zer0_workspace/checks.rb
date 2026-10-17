# frozen_string_literal: true

# `bin/zer0 check`: the workspace's structural contract. Each rule returns a
# list of findings; an empty list from every rule is a green workspace.
#
# The rules exist because the cost of a monorepo is drift nobody notices: a
# directory imported but never registered, a vendored copy that stopped being
# a copy, a workflow that no longer filters on the path it gates. Each finding
# says what is wrong and what fixes it.

require "yaml"

module Zer0Workspace
  Finding = Struct.new(:rule, :message, keyword_init: true) do
    def to_s
      "#{rule}: #{message}"
    end
  end

  class Checks
    CONTAINERS = %w[packages sites apps].freeze
    RULES = %i[paths_exist containers_registered workflows vendored].freeze

    def initialize(manifest, files: nil)
      @manifest = manifest
      @root = manifest.root
      @files = files
    end

    def run(only: RULES)
      only.flat_map { |rule| send(rule) }
    end

    # Every project's directory exists, and every glob it claims matches at
    # least one tracked file (a glob that matches nothing is a typo or a file
    # that was deleted without updating the manifest).
    def paths_exist
      @manifest.projects.flat_map do |p|
        next [finding(:paths_exist, "#{p.name}: #{p.path}/ does not exist")] unless File.directory?(File.join(@root, p.path))

        p.paths.reject { |glob| files.any? { |f| Ownership.match?(glob, f) } }
               .map { |glob| finding(:paths_exist, "#{p.name}: #{glob.inspect} matches no tracked file") }
      end
    end

    # Every directory directly under packages/, sites/ and apps/ is a project.
    def containers_registered
      registered = @manifest.projects.map(&:path)
      CONTAINERS.flat_map do |container|
        dir = File.join(@root, container)
        next [] unless File.directory?(dir)

        Dir.children(dir).sort.filter_map do |child|
          path = "#{container}/#{child}"
          next unless File.directory?(File.join(@root, path))
          next if registered.include?(path)

          finding(:containers_registered, "#{path}/ is not registered in workspace.yml — add it under projects:")
        end
      end
    end

    # A project's `ci:` names a root workflow that exists and, when that
    # workflow filters on paths, includes the project's own path. `none` must
    # carry a reason.
    def workflows
      @manifest.projects.flat_map do |p|
        if p.workflow.nil?
          reason = p.ci.sub(/\Anone\s*[—-]?\s*/, "")
          next reason.empty? ? [finding(:workflows, "#{p.name}: ci is `none` without a reason — say why nothing gates it")] : []
        end

        file = File.join(@root, ".github/workflows", p.workflow)
        next [finding(:workflows, "#{p.name}: ci names .github/workflows/#{p.workflow}, which does not exist")] unless File.file?(file)

        filters = workflow_path_filters(file)
        next [] if filters.nil? || p.path == "."

        filters.any? { |f| f == "#{p.path}/**" || f.start_with?("#{p.path}/") } ? [] :
          [finding(:workflows, "#{p.name}: #{p.workflow} filters on paths but none is under #{p.path}/")]
      end
    end

    # Every vendored copy is byte-identical to its source.
    def vendored
      @manifest.vendored.flat_map do |v|
        source = File.join(@root, v.source)
        copy = File.join(@root, v.copy)
        next [finding(:vendored, "#{v.source} (source of #{v.copy}) does not exist")] unless File.file?(source)
        next [finding(:vendored, "#{v.copy} (copy of #{v.source}) does not exist — bin/zer0 vendor --write")] unless File.file?(copy)
        next [] if File.binread(source) == File.binread(copy)

        [finding(:vendored, "#{v.copy} has drifted from #{v.source} — bin/zer0 vendor --write, then read the diff")]
      end
    end

    private

    def files
      @files ||= begin
        out = IO.popen(["git", "-C", @root, "ls-files", "-z"], &:read)
        out.split("\0")
      end
    end

    # The union of `paths:` under the pull_request/push triggers, or nil when
    # the workflow does not filter on paths at all.
    def workflow_path_filters(file)
      data = YAML.safe_load(File.read(file), aliases: true) || {}
      on = data["on"] || data[true]
      return nil unless on.is_a?(Hash)

      lists = %w[pull_request push].filter_map { |event| on[event].is_a?(Hash) ? on[event]["paths"] : nil }
      lists.empty? ? nil : lists.flatten.map(&:to_s)
    end

    def finding(rule, message)
      Finding.new(rule: rule, message: message)
    end
  end
end
