# frozen_string_literal: true

class SiteMediaController < ApplicationController
  def index
    @site = Site.find(params[:site_id])
    files = Zer0Cms::Cms::Catalog.media(@site.root)
    @pagy, @files = pagy_array(files, limit: 48)
  end
end
