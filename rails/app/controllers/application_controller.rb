# frozen_string_literal: true

class ApplicationController < ActionController::Base
  include AccessGuard

  protect_from_forgery with: :exception
  layout "administrate/application"
end
