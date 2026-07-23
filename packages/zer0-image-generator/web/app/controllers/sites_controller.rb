# frozen_string_literal: true

class SitesController < ApplicationController
  before_action :set_site, only: %i[show edit update destroy rescan]

  def index
    @sites = Site.recently_scanned
  end

  def show
    @scan = SiteScanner.new(@site).call
    @recent_runs = @site.runs.recent.limit(6)
  rescue SiteScanner::Error => e
    @scan_error = e.message
  end

  def new
    @site = Site.new
  end

  def edit; end

  def create
    @site = Site.new(site_params)
    # A newly registered site is worth reading immediately: source_subdir comes
    # from its _config.yml, and the user expects to land on a populated page.
    if @site.save
      absorb_source_subdir(@site)
      redirect_to @site, notice: "Site registered."
    else
      render :new, status: :unprocessable_entity
    end
  end

  def update
    if @site.update(site_params)
      redirect_to @site, notice: "Site updated."
    else
      render :edit, status: :unprocessable_entity
    end
  end

  def destroy
    @site.destroy
    redirect_to sites_path, notice: "Site removed. Its files on disk were left untouched."
  end

  def rescan
    absorb_source_subdir(@site)
    @site.update(last_scanned_at: Time.current)
    redirect_to @site, notice: "Rescanned."
  end

  private

  def set_site
    @site = Site.find(params[:id])
  end

  def site_params
    params.require(:site).permit(:name, :path, :source_subdir, :notes)
  end

  # Jekyll's own top-level `source:` shifts every disk path; read it once at
  # registration/rescan so the app resolves content the same way Jekyll does.
  def absorb_source_subdir(site)
    config = EngineBridge.read_config(site.root)
    source = config["source"].to_s.strip
    site.update_column(:source_subdir, source) if source.present? && source != site.source_subdir
  rescue EngineBridge::Error
    # A malformed _config.yml is the config editor's problem to surface, not a
    # reason to fail registration — leave source_subdir as-is.
  end
end
