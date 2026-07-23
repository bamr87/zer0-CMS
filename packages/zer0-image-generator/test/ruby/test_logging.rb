# frozen_string_literal: true

# Terminal-output + Stats tests: byte-exact log lines and header, stdout/stderr
# split, VERBOSE-gated debug, error_exit's exit status, --log-file mirroring,
# and the thread-safe counters / interrupt flag.
#
#     ruby -Ilib test/ruby/test_logging.rb

require "minitest/autorun"
require "stringio"
require "tempfile"

require "zer0_image_generator/logging"
require "zer0_image_generator/stats"

include Zer0ImageGenerator

class TestStreamSink < Minitest::Test
  def make
    out = StringIO.new
    err = StringIO.new
    [StreamSink.new(out: out, err: err), out, err]
  end

  def test_info_goes_to_stdout_with_blue_tag
    sink, out, err = make
    sink.log("hello", :info)
    assert_equal "#{Colors::BLUE}[INFO]#{Colors::NC} hello\n", out.string
    assert_equal "", err.string
  end

  def test_warning_error_debug_go_to_stderr
    sink, out, err = make
    sink.log("w", :warning)
    sink.log("e", :error)
    sink.log("d", :debug)
    assert_equal "", out.string
    assert_equal "#{Colors::YELLOW}[WARNING]#{Colors::NC} w\n" \
                 "#{Colors::RED}[ERROR]#{Colors::NC} e\n" \
                 "#{Colors::PURPLE}[DEBUG]#{Colors::NC} d\n", err.string
  end

  def test_step_and_success_stdout
    sink, out, = make
    sink.log("s1", :step)
    sink.log("s2", :success)
    assert_equal "#{Colors::CYAN}[STEP]#{Colors::NC} s1\n" \
                 "#{Colors::GREEN}[SUCCESS]#{Colors::NC} s2\n", out.string
  end

  def test_say_is_a_bare_line
    sink, out, = make
    sink.say("  Files skipped: 2")
    assert_equal "  Files skipped: 2\n", out.string
  end

  def test_header_is_byte_exact
    sink, out, = make
    sink.header("📊 Summary")
    line = "=" * 64
    expected = "\n#{Colors::CYAN}#{line}#{Colors::NC}\n" \
               "  #{Colors::GREEN}📊 Summary#{Colors::NC}\n" \
               "#{Colors::CYAN}#{line}#{Colors::NC}\n\n"
    assert_equal expected, out.string
  end
end

class TestLogger < Minitest::Test
  def logger_with_streams
    out = StringIO.new
    err = StringIO.new
    [Logger.new(sink: StreamSink.new(out: out, err: err)), out, err]
  end

  def test_debug_gated_by_verbose
    logger, _out, err = logger_with_streams
    logger.debug("hidden")
    assert_equal "", err.string
    logger.verbose = true
    logger.debug("shown")
    assert_includes err.string, "shown"
  end

  def test_error_exit_raises_exit_error_status_1
    logger, _out, err = logger_with_streams
    e = assert_raises(ExitError) { logger.error_exit("boom") }
    assert_equal 1, e.status
    assert_equal "boom", e.message
    assert_includes err.string, "[ERROR]"
  end

  def test_log_file_mirror_format
    file = Tempfile.new("log")
    file.close
    logger, = logger_with_streams
    assert logger.open_log_file(file.path)
    logger.info("wired up")
    logger.warn("careful")
    logger.close_log_file
    contents = File.read(file.path)
    # Timestamp prefix + level, no ANSI color in the file mirror.
    assert_match(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \[INFO\] wired up$/, contents)
    assert_match(/\[WARNING\] careful$/, contents)
    refute_includes contents, "\e[" # colors are terminal-only
  ensure
    file.unlink
  end

  def test_say_bypasses_the_log_file_mirror
    file = Tempfile.new("log2")
    file.close
    logger, = logger_with_streams
    logger.open_log_file(file.path)
    logger.say("  plain line")
    logger.close_log_file
    assert_equal "", File.read(file.path) # bare prints are not mirrored
  ensure
    file.unlink
  end

  def test_unwritable_log_file_warns_and_returns_false
    logger, _out, err = logger_with_streams
    refute logger.open_log_file("/no/such/dir/whatever.log")
    assert_includes err.string, "Cannot open log file"
  end
end

class TestStats < Minitest::Test
  def test_inc_counts
    s = Stats.new
    s.inc(:processed)
    s.inc(:processed)
    s.inc(:skipped)
    assert_equal 2, s.processed
    assert_equal 1, s.skipped
    assert_equal 0, s.errors
  end

  def test_unknown_stat_raises
    assert_raises(ArgumentError) { Stats.new.inc(:bogus) }
  end

  def test_inc_is_thread_safe
    s = Stats.new
    threads = Array.new(8) do
      Thread.new { 1000.times { s.inc(:generated) } }
    end
    threads.each(&:join)
    assert_equal 8000, s.generated
  end
end

class TestInterrupt < Minitest::Test
  def test_trip_and_check
    i = InterruptFlag.new
    refute i.tripped?
    i.trip
    assert i.tripped?
  end
end
