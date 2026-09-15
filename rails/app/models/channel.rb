# frozen_string_literal: true

# A LinkedIn account a site publishes as — a page (urn:li:organization:…) or a
# member's own profile (urn:li:person:…) — and the token its owner granted.
#
# The token is the only secret the CMS stores, and only because a person
# connected the account through LinkedIn's own consent screen here. It is
# encrypted at rest (Active Record encryption, keys derived from
# secret_key_base), never rendered, never logged, and never written to a site's
# files. The app credentials (LINKEDIN_CLIENT_ID / _SECRET) stay in the
# environment. Without a connected channel, the lane falls back to the
# environment's LINKEDIN_ACCESS_TOKEN — the same credential CI uses.
class Channel < ApplicationRecord
  PROVIDERS = %w[linkedin].freeze

  belongs_to :site

  encrypts :access_token, :refresh_token

  validates :provider, inclusion: { in: PROVIDERS }
  validates :author_urn, presence: true, uniqueness: { scope: %i[site_id provider] }
  validate :author_is_a_linkedin_author

  # A token belongs to the account and site it was granted for.
  before_update :forget_token_on_identity_change

  def to_s
    name.presence || author_urn
  end

  def author_type
    Zer0Cms::LinkedIn.author_type(author_urn)
  end

  def connected?
    token_value(:access_token).present?
  end

  # Whole days, rounded up: a token issued a moment ago has 60, one expiring
  # this afternoon has 1.
  def days_left(now = Time.current)
    expires_at && ((expires_at - now) / 1.day).ceil
  end

  def scope_list
    scopes.to_s.split(/[\s,]+/).reject(&:blank?)
  end

  # The channel's own token when it has one, else the environment's; the app
  # credentials always come from the environment.
  def credentials(env = ENV)
    base = Zer0Cms::Distribution::Credentials.from_env(env)
    return base unless connected?

    Zer0Cms::Distribution::Credentials.new(access_token: token_value(:access_token), refresh_token: token_value(:refresh_token).to_s,
                                           client_id: base.client_id, client_secret: base.client_secret)
  end

  def store_token!(token, member: nil)
    update!(access_token: token.access_token, refresh_token: token.refresh_token, expires_at: token.expires_at,
            refresh_expires_at: token.refresh_expires_at, scopes: token.scopes.join(" "), connected_at: Time.current,
            member_urn: member ? member["urn"] : member_urn, last_error: nil)
  end

  def disconnect!
    update!(access_token: nil, refresh_token: nil, expires_at: nil, refresh_expires_at: nil, scopes: "", connected_at: nil)
  end

  # A token that no longer decrypts (secret_key_base changed) reads as
  # absent, so the channel shows as disconnected instead of raising.
  def token_value(attribute)
    public_send(attribute)
  rescue ActiveRecord::Encryption::Errors::Decryption
    nil
  end

  private

  def forget_token_on_identity_change
    return unless will_save_change_to_site_id? || will_save_change_to_author_urn?

    self.access_token = nil
    self.refresh_token = nil
    self.expires_at = nil
    self.refresh_expires_at = nil
    self.scopes = ""
    self.connected_at = nil
    self.member_urn = ""
  end

  def author_is_a_linkedin_author
    return if author_urn.blank? || author_type

    errors.add(:author_urn, "must be urn:li:organization:{id} or urn:li:person:{id}")
  end
end
