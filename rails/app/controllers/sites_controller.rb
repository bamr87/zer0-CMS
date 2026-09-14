# frozen_string_literal: true

class SitesController < ApplicationController
  before_action :set_site, only: %i[show edit update destroy rescan]

  def index
    @q = params[:q].to_s.strip
    @sites = Site.named
    if @q.present?
      like = "%#{ActiveRecord::Base.sanitize_sql_like(@q)}%"
      @sites = @sites.where("name LIKE ? OR path LIKE ?", like, like)
    end
    @unregistered = Site.discover_roots
  end

  def show
    @catalog = @site.catalog
    @site.update_column(:last_scanned_at, Time.current)
  rescue StandardError => e
    @scan_error = e.message
  end

  def new
    @site = Site.new
  end

  def edit; end

  def create
    @site = Site.new(site_params)
    if @site.save
      @site.absorb_source_subdir
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
    redirect_to sites_path, notice: "Site removed. Files on disk were left untouched."
  end

  def rescan
    @site.absorb_source_subdir
    @site.update(last_scanned_at: Time.current)
    redirect_to @site, notice: "Rescanned."
  end

  def import_discovered
    count = 0
    Site.discover_roots.each do |root|
      site = Site.new(name: File.basename(root), path: root)
      next unless site.save

      site.absorb_source_subdir
      count += 1
    end
    redirect_to sites_path, notice: (count.positive? ? "Registered #{count} site#{'s' if count != 1}." : "No new sites to register.")
  end

  private

  def set_site
    @site = Site.find(params[:id])
  end

  def site_params
    params.require(:site).permit(:name, :path, :notes)
  end
end
