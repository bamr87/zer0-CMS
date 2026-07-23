# frozen_string_literal: true

# "Process further with OpenAI": takes one image a composition already produced
# and runs it through OpenAI's images/edits endpoint, appending the enhanced
# result as a new version.
class EnhanceJob < ApplicationJob
  queue_as :default

  def perform(image_id, prompt: nil)
    image = CompositionImage.find(image_id)
    composition = image.composition
    composition.start!
    broadcast_header(composition)

    env = ENV.to_h.merge(Credential.environment)
    forge = Forge.new(env: env, logger: log_sink(composition))
    forge.enhance(image, prompt: prompt)

    composition.ready!
    broadcast_done(composition)
  rescue Forge::Error, StandardError => e
    composition&.append_log("\n[ERROR] #{e.message}\n")
    composition&.fail!(e.message)
    broadcast_done(composition) if composition
    raise unless e.is_a?(Forge::Error)
  end

  private

  def log_sink(composition)
    lambda do |message|
      line = "#{message}\n"
      composition.append_log(line)
      Turbo::StreamsChannel.broadcast_append_to(
        composition, target: "composition-log",
        partial: "compositions/log_chunk", locals: { text: line }
      )
    rescue StandardError
      nil
    end
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
