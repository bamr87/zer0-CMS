# frozen_string_literal: true

# `bin/zer0 doctor`: the CMS's own `zer0 doctor` (rails/bin/zer0-cms, stdlib
# only) run against every project the manifest marks as a zer0 site, so the
# stack contract the CMS enforces on the wider fleet is enforced on this
# repository's sites in one command. Each run's last line is
# "result: N error(s), M warning(s)"; that is what gets collected.

require "open3"

module Zer0Workspace
  class Doctor
    Report = Struct.new(:project, :root, :errors, :warnings, :output, keyword_init: true) do
      def ok?
        errors.zero?
      end
    end

    RESULT = /^result: (\d+) error\(s\), (\d+) warning\(s\)/
    CLI = "rails/bin/zer0-cms"

    def initialize(manifest, capture: nil)
      @manifest = manifest
      @capture = capture || method(:capture_doctor)
    end

    # The projects that declare a `site:` root.
    def sites
      @manifest.projects.select(&:site_root)
    end

    def run(names = nil)
      chosen = names.nil? || names.empty? ? sites : names.map { |n| @manifest.project(n) }
      chosen.map do |project|
        root = project.site_root or raise ManifestError, "#{project.name} declares no site: root to check"
        output = @capture.call(root)
        m = output.match(RESULT)
        errors, warnings = m ? [m[1].to_i, m[2].to_i] : [1, 0] # no result line means the doctor itself failed
        Report.new(project: project.name, root: root, errors: errors, warnings: warnings, output: output)
      end
    end

    private

    def capture_doctor(root)
      out, = Open3.capture2e("ruby", File.join(@manifest.root, CLI), "doctor", File.join(@manifest.root, root))
      out
    end
  end
end
