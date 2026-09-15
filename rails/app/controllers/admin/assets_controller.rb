# frozen_string_literal: true

module Admin
  # Read-only: images are indexed by sync, never edited here.
  class AssetsController < Admin::ApplicationController
    private

    def default_sorting_attribute
      :mtime
    end

    def default_sorting_direction
      :desc
    end
  end
end
