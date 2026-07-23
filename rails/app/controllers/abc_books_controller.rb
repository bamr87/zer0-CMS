# frozen_string_literal: true

# The web face of the ABC wizard. Every action delegates to the same
# Zer0Cms::Abc classes the CLI uses — the controller only turns request params
# into a Wizard and renders the result, so web and CLI can't diverge.
class AbcBooksController < ApplicationController
  # GET / — the wizard form (theme, art style, options).
  def new
    @styles = Zer0Cms::Abc::ArtStyles.default.to_menu
    @themes = Zer0Cms::Abc::Lexicon.available
  end

  # POST /abc/preview — build the spec and show the book markdown, write nothing.
  def preview
    spec = wizard.run
    @markdown = Zer0Cms::Abc::JekyllExporter.new(spec, site_root: Dir.tmpdir).render_markdown
    @spec = spec
    render :preview
  rescue Zer0Cms::Abc::Spec::InvalidSpec, ArgumentError,
         Zer0Cms::Abc::Providers::Anthropic::ProviderError => e
    redirect_to new_abc_book_path, alert: e.message
  end

  # POST /abc/export — write the bundle into the configured drsai checkout.
  def export
    spec = wizard.run
    root = Rails.application.config.x.drsai_site_root
    @result = Zer0Cms::Abc::JekyllExporter.new(spec, site_root: root).export
    @spec = spec
    render :export
  rescue Zer0Cms::Abc::Spec::InvalidSpec, ArgumentError,
         Zer0Cms::Abc::Providers::Anthropic::ProviderError => e
    redirect_to new_abc_book_path, alert: e.message
  end

  # GET /abc/catalog.json — art styles + options + themes (for a JS front end).
  def catalog
    render json: Zer0Cms::Abc::ArtStyles.default.to_menu.merge(
      "themes" => Zer0Cms::Abc::Lexicon.available
    )
  end

  private

  def wizard
    Zer0Cms::Abc::Wizard.new(**wizard_params)
  end

  def wizard_params
    p = params.permit(:theme, :slug, :title, :subtitle, :art_style, :palette,
                      :background, :mood, :audience, :provider).to_h.symbolize_keys
    p[:theme] = p[:theme].to_s.strip
    p[:provider] = (p[:provider].presence || "auto")
    p[:background] = (p[:background].presence || "plain")
    p[:mood] = (p[:mood].presence || "playful")
    p.reject { |_, v| v.respond_to?(:empty?) && v.empty? }
  end
end
