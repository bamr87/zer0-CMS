# frozen_string_literal: true

# Channel tokens are encrypted at rest. The keys are derived from
# secret_key_base — the value the Docker entrypoint generates once into the
# storage volume, or SECRET_KEY_BASE — so there is no second secret to manage,
# and no key is committed. Rotating secret_key_base makes stored tokens
# undecryptable; Channel reads that as "not connected", and the owner connects
# the account again.
generator = ActiveSupport::KeyGenerator.new(Rails.application.secret_key_base, iterations: 1000,
                                                                               hash_digest_class: OpenSSL::Digest::SHA256)
derive = ->(purpose) { generator.generate_key("zer0-cms active record encryption #{purpose}", 32).unpack1("H*") }

ActiveRecord::Encryption.configure(
  primary_key: derive.call("primary key"),
  deterministic_key: derive.call("deterministic key"),
  key_derivation_salt: derive.call("key derivation salt")
)
