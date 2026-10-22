# frozen_string_literal: true

# Which project owns a file, and which projects a set of changed files affects.
#
# A file belongs to the project whose glob matches it most specifically (the
# longest literal prefix wins), so `packages/zer0-image-generator/x` belongs to
# the image generator even though nothing else claims `packages/`. A root workflow belongs to
# the project whose `ci:` names it. Anything left over — docs/, workspace.yml,
# tools/ — is workspace infrastructure and affects no project by itself.
# A change to a project also affects every project that depends on it.

module Zer0Workspace
  class Ownership
    WORKFLOWS = ".github/workflows/"

    def initialize(manifest)
      @manifest = manifest
    end

    # The project name that owns `file`, or nil for workspace infrastructure.
    def owner(file)
      owners(file).first
    end

    # Every project `file` belongs to: one for a project file, every project a
    # shared workflow gates (sites.yml gates three), none for infrastructure.
    def owners(file)
      if file.start_with?(WORKFLOWS) && file.index("/", WORKFLOWS.length).nil?
        return @manifest.projects.select { |p| p.workflow == file.delete_prefix(WORKFLOWS) }.map(&:name)
      end

      [best_glob_owner(file)].compact
    end

    # { affected: [names in manifest order], direct: [...], unowned: [files] }
    def affected(files)
      direct = []
      unowned = []
      files.each do |file|
        names = owners(file)
        unowned << file if names.empty?
        names.each { |name| direct << name unless direct.include?(name) }
      end
      all = direct.dup
      direct.each { |name| @manifest.dependents_of(name).each { |d| all << d unless all.include?(d) } }
      ordered = @manifest.names.select { |n| all.include?(n) }
      { affected: ordered, direct: @manifest.names.select { |n| direct.include?(n) }, unowned: unowned }
    end

    # "dir/**" owns everything under dir; any other glob is matched by
    # File.fnmatch with path semantics, so "*.json" does not cross a slash.
    def self.match?(glob, file)
      if glob.end_with?("/**")
        prefix = glob.delete_suffix("**")
        file.start_with?(prefix)
      else
        File.fnmatch?(glob, file, File::FNM_PATHNAME | File::FNM_DOTMATCH | File::FNM_EXTGLOB)
      end
    end

    def self.literal_prefix(glob)
      glob[/\A[^*?\[{]*/]
    end

    private

    def best_glob_owner(file)
      best = nil
      best_len = -1
      @manifest.projects.each do |project|
        project.globs.each do |glob|
          next unless self.class.match?(glob, file)

          len = self.class.literal_prefix(glob).length
          if len > best_len
            best = project.name
            best_len = len
          end
        end
      end
      best
    end
  end
end
