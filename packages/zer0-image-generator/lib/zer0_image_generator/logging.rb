# frozen_string_literal: true

module Zer0ImageGenerator
  # Stands in for the Python engine's `sys.exit(1)`. The engine is now driven
  # by a Rails app as well as a CLI, and a web request must not be able to
  # take the process down — CLI.main is the only place that turns this back
  # into a process exit status, so the code path (and the status) is unchanged
  # for CLI users.
  class ExitError < StandardError
    attr_reader :status

    def initialize(message, status = 1)
      super(message)
      @status = status
    end
  end

  module Colors
    RED = "\e[0;31m"
    GREEN = "\e[0;32m"
    YELLOW = "\e[1;33m"
    BLUE = "\e[0;34m"
    CYAN = "\e[0;36m"
    PURPLE = "\e[0;35m"
    BOLD = "\e[1m"
    NC = "\e[0m"
  end

  # Default log destination: reproduces the Python engine's terminal output
  # byte for byte (same colors, same stream split, same blank lines). Nothing
  # in the Runner or the CLI touches $stdout directly, so a web UI can hand in
  # a sink that streams the very same run to a browser instead.
  #
  # Sink contract — three messages:
  #   log(message, level)  level is one of :info :step :success :warning
  #                        :error :debug
  #   say(text)            a bare line (the engine's plain `print` calls)
  #   header(title)        the boxed section banner
  class StreamSink
    LEVEL_COLORS = {
      info: Colors::BLUE,
      step: Colors::CYAN,
      success: Colors::GREEN,
      warning: Colors::YELLOW,
      error: Colors::RED,
      debug: Colors::PURPLE
    }.freeze

    # The levels the Python engine routes to sys.stderr.
    STDERR_LEVELS = %i[warning error debug].freeze

    RULE = ("=" * 64).freeze

    def initialize(out: $stdout, err: $stderr)
      @out = out
      @err = err
      @lock = Mutex.new
    end

    def log(message, level)
      color = LEVEL_COLORS.fetch(level, Colors::NC)
      stream = STDERR_LEVELS.include?(level) ? @err : @out
      emit(stream, "#{color}[#{level.to_s.upcase}]#{Colors::NC} #{message}\n")
    end

    def say(text)
      emit(@out, "#{text}\n")
    end

    def header(title)
      emit(@out, "\n#{Colors::CYAN}#{RULE}#{Colors::NC}\n" \
                 "  #{Colors::GREEN}#{title}#{Colors::NC}\n" \
                 "#{Colors::CYAN}#{RULE}#{Colors::NC}\n\n")
    end

    private

    # One write per line. Python's GIL gave `print` de-facto line atomicity
    # that worker threads relied on; Ruby has to ask for it explicitly or
    # parallel runs shred each other's output.
    def emit(stream, text)
      @lock.synchronize { stream.write(text) }
    end
  end

  # Holds what the Python engine kept in module globals: the active sink, the
  # VERBOSE switch that gates debug(), and the optional --log-file mirror.
  class Logger
    # Matches the Python's time.strftime("%Y-%m-%d %H:%M:%S").
    STAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

    attr_accessor :sink, :verbose

    def initialize(sink: nil, verbose: false)
      @sink = sink || StreamSink.new
      @verbose = verbose
      @log_file = nil
      @file_lock = Mutex.new
    end

    def log(message, level = :info)
      text = message.to_s
      key = level.to_sym
      @sink.log(text, key)
      mirror(text, key)
      nil
    end

    def info(message)
      log(message, :info)
    end

    def step(message)
      log(message, :step)
    end

    def success(message)
      log(message, :success)
    end

    def warn(message)
      log(message, :warning)
    end

    def debug(message)
      log(message, :debug) if @verbose
    end

    def error_exit(message, status = 1)
      log(message, :error)
      raise ExitError.new(message.to_s, status)
    end

    # The engine's bare `print(...)` / `print()` calls: plain stdout lines that
    # deliberately bypass the --log-file mirror.
    def say(text = "")
      @sink.say(text.to_s)
      nil
    end

    def print_header(title)
      @sink.header(title.to_s)
      nil
    end

    # Returns false after warning (never raises) — the Python catches OSError
    # here so an unwritable --log-file downgrades to a warning instead of
    # aborting a run that may already have cost money.
    def open_log_file(path)
      @file_lock.synchronize { @log_file = File.open(path, "w:UTF-8") }
      true
    rescue SystemCallError => e
      warn("Cannot open log file: #{e}")
      false
    end

    def close_log_file
      @file_lock.synchronize do
        return nil if @log_file.nil?

        @log_file.close
        @log_file = nil
      end
    end

    private

    def mirror(message, level)
      @file_lock.synchronize do
        return nil if @log_file.nil?

        @log_file.write("#{Time.now.strftime(STAMP_FORMAT)} [#{level.to_s.upcase}] #{message}\n")
        @log_file.flush
      end
    end
  end

  # Process-wide logger, the direct analogue of the engine's module-level
  # log()/info()/warn()/VERBOSE. Runner and CLI take an injected logger and
  # only fall back to this one, so a Rails process can run several jobs with
  # separate sinks without touching global state.
  module Logging
    class << self
      attr_writer :logger

      def logger
        @logger ||= Logger.new
      end

      # The engine's VERBOSE global.
      def verbose
        logger.verbose
      end

      def verbose=(value)
        logger.verbose = value
      end

      def log(message, level = :info)
        logger.log(message, level)
      end

      def info(message)
        logger.info(message)
      end

      def step(message)
        logger.step(message)
      end

      def success(message)
        logger.success(message)
      end

      def warn(message)
        logger.warn(message)
      end

      def debug(message)
        logger.debug(message)
      end

      def error_exit(message, status = 1)
        logger.error_exit(message, status)
      end

      def say(text = "")
        logger.say(text)
      end

      def print_header(title)
        logger.print_header(title)
      end
    end
  end
end
