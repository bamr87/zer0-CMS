# frozen_string_literal: true

module Admin
  # Read-only: tags, categories and authors are counted by sync.
  class TermsController < Admin::ApplicationController
    private

    def default_sorting_attribute
      :pages_count
    end

    def default_sorting_direction
      :desc
    end
  end
end
