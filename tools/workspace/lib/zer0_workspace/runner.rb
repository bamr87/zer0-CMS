# frozen_string_literal: true

# Runs a manifest task (setup/check/test/build) for one or more projects, each
# in its own directory with its own environment, through `bash -c` so a task
# can be the same one-liner a contributor would type. A project without that
# task is skipped and reported as such — never counted as a pass.

require "open3"

module Zer0Workspace
  Result = Struct.new(:project, :task, :status, :seconds, keyword_init: true) do
    # :passed, :failed or :skipped
    def ok?
      status != :failed
    end
  end

  class Runner
    def initialize(manifest, out: $stdout, dry_run: false, keep_going: false, spawn: nil)
      @manifest = manifest
      @out = out
      @dry_run = dry_run
      @keep_going = keep_going
      @spawn = spawn || method(:spawn_bash)
    end

    def run(task, names)
      results = []
      names.each do |name|
        project = @manifest.project(name)
        spec = project.task(task)
        if spec.nil?
          results << Result.new(project: name, task: task, status: :skipped, seconds: 0)
          next
        end

        dir = File.expand_path(File.join(project.path, spec.cwd), @manifest.root)
        @out.puts "==> #{name}: #{task}  (#{relative(dir)})"
        @out.puts "    $ #{spec.run}"
        if @dry_run
          results << Result.new(project: name, task: task, status: :skipped, seconds: 0)
          next
        end

        started = Process.clock_gettime(Process::CLOCK_MONOTONIC)
        ok = @spawn.call(spec.env, spec.run, dir)
        seconds = Process.clock_gettime(Process::CLOCK_MONOTONIC) - started
        results << Result.new(project: name, task: task, status: ok ? :passed : :failed, seconds: seconds.round(1))
        break if !ok && !@keep_going
      end
      results
    end

    private

    def spawn_bash(env, command, dir)
      system(env, "bash", "-c", command, chdir: dir)
    end

    def relative(dir)
      rel = dir.delete_prefix(File.expand_path(@manifest.root))
      rel.empty? ? "." : rel.delete_prefix("/")
    end
  end
end
