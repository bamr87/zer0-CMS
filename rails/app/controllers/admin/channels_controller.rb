# frozen_string_literal: true

module Admin
  # Index, show, new, edit and destroy are Administrate's. The three member
  # actions talk to LinkedIn: `connect` starts the account owner's consent,
  # `check` asks LinkedIn whether the stored token still works, and
  # `disconnect` forgets it here.
  class ChannelsController < Admin::ApplicationController
    def connect
      channel = requested_resource
      unless LinkedinGateway.oauth_ready?
        return redirect_to [namespace, channel], status: :see_other,
                                                 alert: "Set LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET for the CMS before connecting an account."
      end

      state = Zer0Cms::LinkedIn::OAuth.new_state
      session[:linkedin_oauth] = { "state" => state, "channel_id" => channel.id, "at" => Time.current.to_i }
      url = LinkedinGateway.oauth.authorize_url(redirect_uri: LinkedinGateway.redirect_uri(request), state: state,
                                                scopes: LinkedinGateway.scopes_for(channel))
      redirect_to url, allow_other_host: true, status: :see_other
    end

    def check
      channel = requested_resource
      report = LinkedinGateway.pipeline(channel.site, channel: channel).check_token
      expires = report["expires_at"] ? Time.iso8601(report["expires_at"]) : channel.expires_at
      channel.update!(checked_at: Time.current, expires_at: expires,
                      last_error: report["ok"] ? nil : Array(report["problems"]).join("; ").truncate(500))
      if report["ok"]
        notes = Array(report["notes"])
        redirect_to [namespace, channel], status: :see_other,
                                          notice: ["The token works#{report["days_left"] ? " (#{report["days_left"]} days left)" : ""}.", *notes].join(" ")
      else
        redirect_to [namespace, channel], alert: "The token needs attention: #{channel.last_error}", status: :see_other
      end
    end

    def disconnect
      channel = requested_resource
      channel.disconnect!
      redirect_to [namespace, channel], status: :see_other,
                                        notice: "The token is removed from the CMS. It stays valid at LinkedIn until it expires or the member removes the app."
    end

    private

    def default_sorting_attribute
      :name
    end
  end
end
