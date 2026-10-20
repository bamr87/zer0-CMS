class ApplicationController < ActionController::Base
  # Only allow modern browsers supporting webp images, web push, badges, import maps, CSS nesting, and CSS :has.
  allow_browser versions: :modern

  # Changes to the importmap will invalidate the etag for HTML responses
  stale_when_importmap_changes

  before_action :load_nav

  private

  def load_nav
    @nav_sites = Site.named
    @nav_active_runs = Run.active.count
  end
end
