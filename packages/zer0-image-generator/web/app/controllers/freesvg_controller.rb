# frozen_string_literal: true

# FreeSVG.org sourcing: search the public catalog, preview results, and promote
# keepers into the library with provenance. Backed by the engine's ported
# FreeSVG client and its tiered cache, so repeat searches cost no API calls.
class FreesvgController < ApplicationController
  before_action :ensure_client

  def search
    @query = params[:q].to_s.strip
    @results = @query.present? ? FreesvgSource.search(@query) : []
  rescue FreesvgSource::Error => e
    @error = e.message
    @results = []
  end

  def promote
    entry = FreesvgSource.promote(params[:id], tags: params[:tags].to_s.split(",").map(&:strip))
    LibrarySync.call
    redirect_to library_entries_path, notice: "Promoted “#{entry["title"]}” into the library."
  rescue FreesvgSource::Error => e
    redirect_to freesvg_search_path(q: params[:q]), alert: e.message
  end

  private

  # The FreeSVG client is an auxiliary engine module loaded on demand. If it is
  # unavailable (not yet present, or a load error), the feature degrades to a
  # clear message rather than a 500.
  def ensure_client
    @client_available = FreesvgSource.available?
  end
end
