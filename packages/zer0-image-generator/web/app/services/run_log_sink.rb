# frozen_string_literal: true

# A logging sink (the engine's sink contract: log/say/header) that appends
# every line to a Run's log and broadcasts it over Turbo Streams so the run
# page tails live.
#
# The engine's own StreamSink colorizes with ANSI for a terminal; here the
# lines are stripped of ANSI and stored as plain text, with the level preserved
# so the UI can re-color them in CSS.
class RunLogSink
  ANSI = /\e\[[0-9;]*m/

  def initialize(run, broadcast: true)
    @run = run
    @broadcast = broadcast
    @buffer = +""
    @mutex = Mutex.new
    # Flush on a short interval rather than per line: a parallel generate can
    # emit hundreds of lines, and one DB write + one broadcast each would swamp
    # both. Time-based batching keeps the tail live without the storm.
    @last_flush = monotonic
  end

  def log(message, level)
    append("[#{level.to_s.upcase}] #{strip(message)}\n")
  end

  def say(text)
    append("#{strip(text)}\n")
  end

  def header(title)
    append("\n=== #{strip(title)} ===\n")
  end

  # Force any buffered output to the database. Called at run end so the final
  # lines are never lost to the flush interval.
  def flush!
    pending = nil
    @mutex.synchronize do
      pending = @buffer
      @buffer = +""
      @last_flush = monotonic
    end
    return if pending.empty?

    @run.append_log(pending)
    broadcast(pending) if @broadcast
  end

  private

  def append(line)
    ready = false
    @mutex.synchronize do
      @buffer << line
      ready = (monotonic - @last_flush) >= 0.4 || @buffer.bytesize > 4_000
    end
    flush! if ready
  end

  def broadcast(text)
    Turbo::StreamsChannel.broadcast_append_to(
      @run, target: "run-log",
      partial: "runs/log_chunk", locals: { text: text }
    )
  rescue StandardError
    # A broadcast failure (no subscriber, cable hiccup) must never fail the
    # run — the log is already durably in the database.
    nil
  end

  def strip(text)
    text.to_s.gsub(ANSI, "")
  end

  def monotonic
    Process.clock_gettime(Process::CLOCK_MONOTONIC)
  end
end
