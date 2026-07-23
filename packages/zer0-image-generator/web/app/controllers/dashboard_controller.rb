# frozen_string_literal: true

class DashboardController < ApplicationController
  def show
    @sites = Site.recently_scanned.limit(8)
    @recent_runs = Run.recent.includes(:site).limit(8)
    @active_runs = Run.active.count
    @credentials = Credential.usable.pluck(:provider)
    @studio_count = StudioRender.count
    @library_count = LibraryEntry.count
    @favorites = StudioRender.favorites.recent.limit(6)
  end
end
