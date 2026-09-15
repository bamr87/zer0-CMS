# frozen_string_literal: true

module Admin
  # POST /admin/markdown_preview — sanitized HTML for the editor's live preview.
  class MarkdownPreviewsController < ::ApplicationController
    def create
      render html: MarkdownRenderer.render(params[:markdown])
    end
  end
end
