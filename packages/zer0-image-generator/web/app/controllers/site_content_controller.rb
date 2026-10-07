# frozen_string_literal: true

class SiteContentController < ApplicationController
  def index
    load_scan!
    return if @scan_error

    @filter = params[:filter].to_s
    @collection = params[:collection].to_s
    @q = params[:q].to_s.strip
    @entries = case @filter
               when "missing" then @scan.entries.select(&:missing?)
               when "present" then @scan.entries.select(&:exists)
               else @scan.entries
               end
    @entries = @entries.select { |entry| entry.collection == @collection } if @collection.present?
    if @q.present?
      needle = @q.downcase
      @entries = @entries.select { |entry| "#{entry.title} #{entry.relative}".downcase.include?(needle) }
    end
  end

  def show
    load_scan!
    return if @scan_error

    relative = params[:file].to_s
    @entry = @scan.entries.find { |entry| entry.relative == relative }
    return redirect_to site_content_index_path(@site), alert: "No content file matched that path." if @entry.nil?
  end

  private

  def load_scan!
    @site = Site.find(params[:site_id])
    @scan = SiteScanner.new(@site).call
  rescue SiteScanner::Error => e
    @scan_error = e.message
  end
end
