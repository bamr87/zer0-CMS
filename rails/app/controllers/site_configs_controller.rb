# frozen_string_literal: true

class SiteConfigsController < ApplicationController
  def show
    @site = Site.find(params[:site_id])
    @yaml = @site.config_file.file? ? @site.config_file.read : ""
    @config = Zer0Cms::Cms::Catalog.read_config(@site.root)
  end
end
