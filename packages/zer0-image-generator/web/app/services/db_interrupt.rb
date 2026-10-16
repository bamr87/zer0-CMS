# frozen_string_literal: true

# The engine's cancellation primitive, backed by a Run's status.
#
# The engine polls `tripped?` between files. Cancellation arrives as a status
# change written by the web process (the Cancel button), which may be a
# different process than the job worker — so the flag cannot just be an
# in-memory boolean; it has to consult the database. Reads are throttled so a
# fast serial run does not issue one query per file.
class DbInterrupt
  POLL_INTERVAL = 1.0 # seconds

  def initialize(run)
    @run = run
    @tripped = false
    @last_check = 0.0
  end

  def trip
    @tripped = true
  end

  def tripped?
    return true if @tripped

    now = Process.clock_gettime(Process::CLOCK_MONOTONIC)
    return @tripped if (now - @last_check) < POLL_INTERVAL

    @last_check = now
    # `pluck` avoids instantiating the record and its (possibly large) log
    # column on every poll.
    @tripped = Run.where(id: @run.id).pick(:status) == "cancelled"
  end
end
