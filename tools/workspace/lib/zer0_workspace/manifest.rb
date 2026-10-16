# frozen_string_literal: true

# The workspace manifest (workspace.yml) loaded into plain value objects and
# validated. Everything else in Zer0Workspace reads projects through here, so
# a malformed manifest fails in one place with a message naming the key,
# rather than as a nil error somewhere in a command.

require "yaml"

module Zer0Workspace
  class ManifestError < StandardError; end

  KINDS = %w[extension rails gem python site app].freeze
  TASKS = %w[setup check test build].freeze
  PROJECT_KEYS = %w[path paths kind stack summary upstream depends_on publishes ci site tasks].freeze
  TASK_KEYS = %w[run cwd env].freeze

  # One command a project runs: `run` from `cwd` (relative to the project's
  # path) with `env` added to the environment.
  Task = Struct.new(:name, :run, :cwd, :env, keyword_init: true)

  Project = Struct.new(:name, :path, :paths, :kind, :stack, :summary, :upstream,
                       :depends_on, :publishes, :ci, :site, :tasks, keyword_init: true) do
    # The globs this project owns. A project at "." must list them; any other
    # project owns its whole directory.
    def globs
      paths.empty? ? ["#{path}/**"] : paths
    end

    # The root workflow file that gates this project, or nil when `ci` says
    # `none — <reason>`.
    def workflow
      ci.start_with?("none") ? nil : ci
    end

    def task(name)
      tasks[name]
    end

    # The Jekyll root `zer0 doctor` checks, relative to the repository root,
    # or nil when the project is not a zer0 site.
    def site_root
      return nil if site.nil?

      site == "." ? path : File.join(path, site)
    end
  end

  Vendored = Struct.new(:copy, :source, :why, keyword_init: true)

  class Manifest
    attr_reader :root, :projects, :vendored

    def self.load(root, file: "workspace.yml")
      full = File.join(root, file)
      raise ManifestError, "#{file} not found under #{root}" unless File.file?(full)

      data = YAML.safe_load(File.read(full), permitted_classes: [], aliases: false)
      new(root, data)
    rescue Psych::SyntaxError => e
      raise ManifestError, "#{file} is not valid YAML: #{e.message}"
    end

    def initialize(root, data)
      @root = root
      raise ManifestError, "the manifest must be a mapping" unless data.is_a?(Hash)
      raise ManifestError, "version must be 1 (got #{data["version"].inspect})" unless data["version"] == 1

      projects = data["projects"]
      raise ManifestError, "projects must be a non-empty mapping" unless projects.is_a?(Hash) && !projects.empty?

      @projects = projects.map { |name, spec| build_project(name.to_s, spec) }
      @vendored = Array(data["vendored"]).each_with_index.map { |spec, i| build_vendored(spec, i) }
      validate_dependencies!
    end

    def project(name)
      @projects.find { |p| p.name == name } or raise ManifestError, "no project named #{name.inspect}"
    end

    def names
      @projects.map(&:name)
    end

    # The projects that depend on `name`, directly or through others.
    def dependents_of(name)
      found = []
      queue = [name]
      until queue.empty?
        current = queue.shift
        @projects.each do |p|
          next unless p.depends_on.include?(current) && !found.include?(p.name)

          found << p.name
          queue << p.name
        end
      end
      found
    end

    private

    def build_project(name, spec)
      raise ManifestError, "projects.#{name} must be a mapping" unless spec.is_a?(Hash)

      unknown = spec.keys - PROJECT_KEYS
      raise ManifestError, "projects.#{name}: unknown key(s) #{unknown.join(", ")}" unless unknown.empty?

      path = required_string(spec, "path", name)
      kind = required_string(spec, "kind", name)
      raise ManifestError, "projects.#{name}.kind must be one of #{KINDS.join(", ")} (got #{kind})" unless KINDS.include?(kind)

      paths = string_list(spec, "paths", name)
      raise ManifestError, "projects.#{name}: a project at \".\" must list the paths it owns" if path == "." && paths.empty?

      Project.new(
        name: name, path: path, paths: paths, kind: kind,
        stack: string_list(spec, "stack", name),
        summary: required_string(spec, "summary", name),
        upstream: spec["upstream"].to_s,
        depends_on: string_list(spec, "depends_on", name),
        publishes: string_list(spec, "publishes", name),
        ci: required_string(spec, "ci", name),
        site: optional_string(spec, "site", name),
        tasks: build_tasks(name, spec["tasks"] || {})
      )
    end

    def build_tasks(name, tasks)
      raise ManifestError, "projects.#{name}.tasks must be a mapping" unless tasks.is_a?(Hash)

      tasks.to_h do |task, value|
        raise ManifestError, "projects.#{name}.tasks: unknown task #{task} (known: #{TASKS.join(", ")})" unless TASKS.include?(task)

        [task, build_task(name, task, value)]
      end
    end

    def build_task(name, task, value)
      case value
      when String
        Task.new(name: task, run: value, cwd: ".", env: {})
      when Hash
        unknown = value.keys - TASK_KEYS
        raise ManifestError, "projects.#{name}.tasks.#{task}: unknown key(s) #{unknown.join(", ")}" unless unknown.empty?

        run = value["run"]
        raise ManifestError, "projects.#{name}.tasks.#{task}.run must be a string" unless run.is_a?(String) && !run.empty?

        env = value["env"] || {}
        raise ManifestError, "projects.#{name}.tasks.#{task}.env must be a mapping" unless env.is_a?(Hash)

        Task.new(name: task, run: run, cwd: (value["cwd"] || ".").to_s, env: env.to_h { |k, v| [k.to_s, v.to_s] })
      else
        raise ManifestError, "projects.#{name}.tasks.#{task} must be a command string or a {run:, cwd:, env:} mapping"
      end
    end

    def build_vendored(spec, index)
      raise ManifestError, "vendored[#{index}] must be a mapping" unless spec.is_a?(Hash)

      copy = spec["copy"].to_s
      source = spec["source"].to_s
      raise ManifestError, "vendored[#{index}] needs both copy and source" if copy.empty? || source.empty?

      Vendored.new(copy: copy, source: source, why: spec["why"].to_s)
    end

    def required_string(spec, key, name)
      value = spec[key]
      raise ManifestError, "projects.#{name}.#{key} is required" unless value.is_a?(String) && !value.strip.empty?

      value
    end

    def optional_string(spec, key, name)
      value = spec[key]
      return nil if value.nil?
      raise ManifestError, "projects.#{name}.#{key} must be a non-empty string" unless value.is_a?(String) && !value.strip.empty?

      value
    end

    def string_list(spec, key, name)
      value = spec[key]
      return [] if value.nil?
      raise ManifestError, "projects.#{name}.#{key} must be a list of strings" unless value.is_a?(Array) && value.all?(String)

      value
    end

    def validate_dependencies!
      @projects.each do |p|
        p.depends_on.each do |dep|
          raise ManifestError, "projects.#{p.name}.depends_on names #{dep.inspect}, which is not a project" unless names.include?(dep)
          raise ManifestError, "projects.#{p.name} depends on itself" if dep == p.name
        end
      end
      @projects.each do |p|
        raise ManifestError, "dependency cycle through #{p.name}" if dependents_of(p.name).include?(p.name)
      end
    end
  end
end
