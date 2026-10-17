# frozen_string_literal: true

class CreateCredentials < ActiveRecord::Migration[8.1]
  def change
    create_table :credentials do |t|
      # openai | xai | stability | gemini | anthropic — one row per provider.
      t.string :provider, null: false
      t.string :label
      # Encrypted at rest via ActiveRecord::Encryption (see the Credential
      # model). Text rather than string because the ciphertext envelope is far
      # longer than the key it wraps.
      t.text :api_key
      t.datetime :last_used_at

      t.timestamps
    end

    add_index :credentials, :provider, unique: true
  end
end
