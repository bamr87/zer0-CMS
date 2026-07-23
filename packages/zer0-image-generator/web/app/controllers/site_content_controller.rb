# frozen_string_literal: true

class SiteContentController < ApplicationController
  def index
    @site = Site.find(params[:site_id])
    @scan = SiteScanner.new(@site).call
    @filter = params[:filter]
    @entries = case @filter
               when "missing" then @scan.entries.select(&:missing?)
               when "present" then @scan.entries.select(&:exists)
               else @scan.entries
               end
  rescue SiteScanner::Error => e
    @scan_error = e.message
  end
end
