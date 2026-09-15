# frozen_string_literal: true

module Admin
  # Base for every dashboard controller. Administrate supplies index (search,
  # sort, filters, pagination), show and the generated forms; this adds the
  # access guard and the zer0 layout.
  class ApplicationController < Administrate::ApplicationController
    include AccessGuard

    layout "administrate/application"

    private

    def filter_resources(resources, search_term:)
      DashboardSearch.new(resources, dashboard, search_term).run
    end

    def records_per_page
      requested = params[:per_page].to_i
      requested.positive? ? [requested, 200].min : 50
    end
  end
end
