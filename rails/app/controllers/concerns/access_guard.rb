# frozen_string_literal: true

# Who may use the app (RFC §3): with ZER0_CMS_PASSWORD set, anyone who passes
# HTTP basic auth; without it, only requests from this machine. Included by
# both controller trees (the app's and Administrate's).
module AccessGuard
  extend ActiveSupport::Concern

  included do
    before_action :guard_access
  end

  private

  def guard_access
    password = ENV["ZER0_CMS_PASSWORD"].to_s
    if password.empty?
      refuse_remote unless LocalNetwork.local_request?(request)
    else
      user = ENV.fetch("ZER0_CMS_USER", "zer0")
      authenticate_or_request_with_http_basic("zer0-CMS") do |given_user, given_password|
        user_ok = ActiveSupport::SecurityUtils.secure_compare(given_user.to_s, user)
        password_ok = ActiveSupport::SecurityUtils.secure_compare(given_password.to_s, password)
        user_ok & password_ok
      end
    end
  end

  def refuse_remote
    render plain: "zer0-CMS answers requests from this machine only. Set ZER0_CMS_PASSWORD to allow other clients.\n",
           status: :forbidden
  end
end
