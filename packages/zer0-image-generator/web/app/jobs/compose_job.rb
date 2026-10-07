# frozen_string_literal: true

# Runs a composition's create/regenerate pipeline (analyze -> produce ->
# review) in the background, streaming progress into the composition's log and
# refreshing the workspace over Turbo when it finishes.
class ComposeJob < ApplicationJob
  queue_as :default

  def perform(composition_id)
    composition = Composition.find(composition_id)
    composition.start!
    broadcast_working(composition)

    env = AiEnv.snapshot
    forge = Forge.new(env: env, logger: log_sink(composition))
    forge.compose(composition)

    composition.ready!
    broadcast_done(composition)
  rescue Forge::Error, StandardError => e
    composition&.append_log("\n[ERROR] #{e.message}\n")
    composition&.fail!(e.message)
    broadcast_done(composition) if composition
    raise unless e.is_a?(Forge::Error)
  end

  private

  # A logger proc the Forge calls per stage: append to the durable log and
  # stream the line to any open workspace.
  def log_sink(composition)
    lambda do |message|
      line = "#{message}\n"
      composition.append_log(line)
      Turbo::StreamsChannel.broadcast_append_to(
        composition, target: "composition-log",
        partial: "compositions/log_chunk", locals: { text: line }
      )
    rescue StandardError
      nil # a broadcast hiccup must never fail the pipeline; the log is durable
    end
  end

  def broadcast_working(composition)
    broadcast_header(composition)
  end

  def broadcast_done(composition)
    composition.reload
    broadcast_header(composition)
    Turbo::StreamsChannel.broadcast_replace_to(
      composition, target: "composition-images",
      partial: "compositions/images", locals: { composition: composition }
    )
  rescue StandardError
    nil
  end

  def broadcast_header(composition)
    Turbo::StreamsChannel.broadcast_replace_to(
      composition, target: "composition-header",
      partial: "compositions/header", locals: { composition: composition.reload }
    )
  rescue StandardError
    nil
  end
end
