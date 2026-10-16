# frozen_string_literal: true

# `bin/zer0 vendor`: the status of every vendored copy, and with `write: true`
# a fresh byte copy of each drifted one from its source. Re-vendoring is a
# change somebody reads in a diff, which is why this never runs on its own.

require "fileutils"

module Zer0Workspace
  class Vendor
    Status = Struct.new(:vendored, :state, keyword_init: true) # :same, :drifted, :missing_copy, :missing_source

    def initialize(manifest)
      @manifest = manifest
    end

    def statuses
      @manifest.vendored.map do |v|
        source = path(v.source)
        copy = path(v.copy)
        state =
          if !File.file?(source) then :missing_source
          elsif !File.file?(copy) then :missing_copy
          elsif File.binread(source) == File.binread(copy) then :same
          else :drifted
          end
        Status.new(vendored: v, state: state)
      end
    end

    # Copies every drifted or missing copy from its source; returns what it wrote.
    def write!
      statuses.select { |s| %i[drifted missing_copy].include?(s.state) }.map do |s|
        FileUtils.mkdir_p(File.dirname(path(s.vendored.copy)))
        File.binwrite(path(s.vendored.copy), File.binread(path(s.vendored.source)))
        s.vendored
      end
    end

    private

    def path(rel)
      File.join(@manifest.root, rel)
    end
  end
end
