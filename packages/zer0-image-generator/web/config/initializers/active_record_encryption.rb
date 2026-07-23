# frozen_string_literal: true

# Configure ActiveRecord::Encryption (used for the encrypted `Credential#api_key`)
# from the environment, with development/test defaults.
#
# Why not Rails credentials: this is a self-hosted, single-user local tool. If
# the encryption keys lived in config/credentials.yml.enc, the app could not
# boot on a fresh clone or in CI without the git-ignored master.key — and the
# whole point is `docker compose up` just works. So the keys come from ENV, and
# in development/test fall back to fixed local defaults (the DB sits on the
# user's own disk; the encryption guards against casual plaintext exposure, not
# a remote attacker).
#
# In production these MUST be provided as real secrets:
#   ACTIVE_RECORD_ENCRYPTION_PRIMARY_KEY
#   ACTIVE_RECORD_ENCRYPTION_DETERMINISTIC_KEY
#   ACTIVE_RECORD_ENCRYPTION_KEY_DERIVATION_SALT
Rails.application.configure do
  dev_defaults = {
    primary_key: "dev_only_primary_key_change_in_production_00",
    deterministic_key: "dev_only_deterministic_key_change_in_prod0",
    key_derivation_salt: "dev_only_key_derivation_salt_change_in_pro",
  }

  # `assets:precompile` boots the production environment with a dummy secret and
  # no real credentials, so don't demand encryption secrets during that phase.
  precompiling = ENV["SECRET_KEY_BASE_DUMMY"].present?

  fetch = lambda do |env_name, default_key|
    value = ENV[env_name].presence
    next value if value

    if Rails.env.production? && !precompiling
      raise "#{env_name} must be set in production (ActiveRecord::Encryption)."
    end

    dev_defaults.fetch(default_key)
  end

  config.active_record.encryption.primary_key =
    fetch.call("ACTIVE_RECORD_ENCRYPTION_PRIMARY_KEY", :primary_key)
  config.active_record.encryption.deterministic_key =
    fetch.call("ACTIVE_RECORD_ENCRYPTION_DETERMINISTIC_KEY", :deterministic_key)
  config.active_record.encryption.key_derivation_salt =
    fetch.call("ACTIVE_RECORD_ENCRYPTION_KEY_DERIVATION_SALT", :key_derivation_salt)
end
