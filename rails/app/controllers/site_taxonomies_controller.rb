# frozen_string_literal: true

class SiteTaxonomiesController < ApplicationController
  def show
    @site = Site.find(params[:site_id])
    @catalog = @site.catalog
    @tags = @catalog.entries.flat_map(&:tags).tally.sort_by { |_, n| -n }
    @categories = @catalog.entries.flat_map(&:categories).tally.sort_by { |_, n| -n }
    @authors = @catalog.entries.map(&:author).reject(&:empty?).tally.sort_by { |_, n| -n }
  end
end
