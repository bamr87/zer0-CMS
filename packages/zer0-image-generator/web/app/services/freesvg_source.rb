# frozen_string_literal: true

# Bridges the FreeSVG.org sourcing UI to the engine's ported FreeSVG client.
#
# The client is an auxiliary engine module (network client + tiered cache), so
# it is loaded on demand. Until it is present this whole feature reports
# unavailable rather than erroring — the app's core (generation, studio) does
# not depend on it.
module FreesvgSource
  class Error < StandardError; end

  # LoadError is a ScriptError, not a StandardError, so it must be named
  # explicitly — otherwise a not-yet-present sourcing module leaks a 500 instead
  # of degrading the feature.
  def self.available?
    client
    true
  rescue ScriptError, StandardError
    false
  end

  # Search results as an array of plain hashes ({id, title, url, ...}) so the
  # view does not couple to the engine's object shapes.
  def self.search(query)
    client.search(query).map { |item| normalize(item) }
  rescue ScriptError, StandardError => e
    raise Error, e.message
  end

  # Promote a result into tools/svg/library with provenance. Returns the
  # manifest entry that was written.
  def self.promote(svg_id, tags: [])
    entry = client.promote(svg_id, tags: tags)
    entry.is_a?(Hash) ? entry : { "title" => svg_id.to_s }
  rescue ScriptError, StandardError => e
    raise Error, e.message
  end

  def self.client
    EngineBridge.load!
    Zer0ImageGenerator.load_sourcing
    # The ported client's exact shape is owned by the freesvg slice; resolve it
    # lazily so this bridge is the only place that needs updating if the name
    # settles differently.
    @client ||= Zer0ImageGenerator::Freesvg::Client.new
  end

  def self.normalize(item)
    return item if item.is_a?(Hash)

    { "id" => item.respond_to?(:id) ? item.id : nil,
      "title" => item.respond_to?(:title) ? item.title : item.to_s }
  end
end
