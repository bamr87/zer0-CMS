# frozen_string_literal: true

# Where LinkedIn sends the account owner's browser after consent.
#
# The callback is accepted only when it answers a connection started here in
# this session: the `state` must match (constant-time), the attempt must be
# younger than ten minutes, and the session entry is consumed on first use, so
# a replayed or forged callback is refused before any code is exchanged.
class LinkedinCallbacksController < ApplicationController
  def show
    pending = session.delete(:linkedin_oauth) || {}
    channel = Channel.find_by(id: pending["channel_id"])
    fresh = pending["at"].to_i > Time.current.to_i - Zer0Cms::LinkedIn::OAuth::STATE_TTL
    unless channel && fresh && Zer0Cms::LinkedIn::OAuth.state_matches?(pending["state"], params[:state])
      return render plain: "This LinkedIn callback does not answer a connection started here. Start again from the channel page.\n",
                    status: :forbidden
    end

    if params[:error].present?
      reason = params[:error_description].presence || params[:error]
      channel.update!(last_error: "LinkedIn: #{reason}".truncate(500))
      return redirect_to admin_channel_path(channel), alert: "LinkedIn did not connect the account: #{reason}", status: :see_other
    end

    token = LinkedinGateway.oauth.exchange(code: params[:code].to_s, redirect_uri: LinkedinGateway.redirect_uri(request))
    member = if token.scopes.include?("openid")
               Zer0Cms::LinkedIn::OAuth.member(Zer0Cms::LinkedIn::Client.new(token: token.access_token, transport: LinkedinGateway.transport))
             end
    channel.store_token!(token, member: member)
    redirect_to admin_channel_path(channel), status: :see_other,
                                             notice: "Connected #{channel}. The token expires #{token.expires_at&.to_date || "in 60 days"}."
  rescue Zer0Cms::LinkedIn::Error, ArgumentError => e
    channel&.update(last_error: e.message.truncate(500))
    redirect_to channel ? admin_channel_path(channel) : admin_root_path, alert: "LinkedIn: #{e.message}", status: :see_other
  end
end
