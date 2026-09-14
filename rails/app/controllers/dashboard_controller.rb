# frozen_string_literal: true

class DashboardController < ApplicationController
  def show
    @sites = Site.named
    @unregistered = Site.discover_roots
  end
end
