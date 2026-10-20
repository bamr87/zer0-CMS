# frozen_string_literal: true

module Zer0ImageGenerator
  # Per-run counters. Mirrors the Python @dataclass Stats: worker threads share
  # one instance and call inc(name), so the mutation must be guarded (Python
  # relied on its own threading.Lock here, not just the GIL — inc reads then
  # writes, which is not atomic).
  class Stats
    ATTRS = %i[processed generated enhanced skipped errors].freeze

    attr_accessor(*ATTRS)

    def initialize(processed: 0, generated: 0, enhanced: 0, skipped: 0, errors: 0)
      @processed = processed
      @generated = generated
      @enhanced = enhanced
      @skipped = skipped
      @errors = errors
      @lock = Mutex.new
    end

    def inc(name)
      key = name.to_sym
      # Guard against a typo'd counter name silently doing nothing — the
      # Python setattr would have raised too (AttributeError on a slotless
      # write is not swallowed anywhere in the engine).
      raise ArgumentError, "unknown stat: #{name}" unless ATTRS.include?(key)

      @lock.synchronize { instance_variable_set("@#{key}", instance_variable_get("@#{key}") + 1) }
      nil
    end
  end

  # The engine's `_interrupted` global as an object, so the Runner can be
  # handed a fresh one per run (a Rails worker cancels one job without
  # poisoning the next). trip() is what _signal_handler does; tripped? is the
  # `if _interrupted:` guard sprinkled through the run loop.
  #
  # NOT named `Interrupt`: that is a Ruby core class (the SIGINT exception), and
  # this module is meant to be `include`d by a Rails host — the collision would
  # shadow the core class for that host.
  #
  # Deliberately lock-free: trip() is called from a signal-trap context, where
  # acquiring a Mutex raises ThreadError on modern Ruby. A single boolean
  # write/read is safe under MRI's GVL, which is exactly what the Python global
  # relied on too.
  class InterruptFlag
    def initialize
      @flag = false
    end

    def trip
      @flag = true
      nil
    end

    def tripped?
      @flag
    end
  end
end
