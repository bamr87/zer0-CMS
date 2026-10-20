# frozen_string_literal: true

class DashboardController < ApplicationController
  def show
    @sites = Site.named
    @recent_runs = Run.recent.includes(:site).limit(8)
    @recent_compositions = Composition.recent.limit(6)
    @active_runs = Run.active.count
    @credentials = Credential.usable.pluck(:provider)
    @studio_count = StudioRender.count
    @library_count = LibraryEntry.count
    @composition_count = Composition.count
    @favorites = StudioRender.favorites.recent.limit(8)
    @env = AiEnv.snapshot
    @claude_ok = Credential.claude_available?(@env)
  end
end
