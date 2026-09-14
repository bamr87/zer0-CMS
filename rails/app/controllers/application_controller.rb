# frozen_string_literal: true

class ApplicationController < ActionController::Base
  include Pagy::Backend

  protect_from_forgery with: :exception
  before_action :load_nav

  private

  def load_nav
    @nav_sites = Site.named
  rescue ActiveRecord::StatementInvalid, ActiveRecord::NoDatabaseError
    @nav_sites = []
  end
end
