# frozen_string_literal: true

class SiteConfigsController < ApplicationController
  before_action :set_site

  def show
    @editor = SiteConfigEditor.new(@site)
    @values = @editor.current
  rescue SiteConfigEditor::Error => e
    @error = e.message
  end

  def update
    editor = SiteConfigEditor.new(@site)
    editor.update(config_params.to_h)
    redirect_to site_config_path(@site), notice: "preview_images: block updated in _config.yml."
  rescue SiteConfigEditor::Error => e
    redirect_to site_config_path(@site), alert: "Could not update config: #{e.message}"
  end

  private

  def set_site
    @site = Site.find(params[:site_id])
  end

  def config_params
    params.require(:config).permit(
      *SiteConfigEditor::STRING_KEYS, *SiteConfigEditor::BOOL_KEYS, *SiteConfigEditor::LIST_KEYS
    )
  end
end
