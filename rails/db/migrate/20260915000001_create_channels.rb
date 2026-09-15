# frozen_string_literal: true

# A connected publishing account for a site: a LinkedIn page or member the CMS
# may post as. Unlike the index tables this is real state — a token is not on
# disk anywhere else — so it is never rebuilt by a sync. The two token columns
# are encrypted by Active Record encryption (see Channel).
class CreateChannels < ActiveRecord::Migration[8.1]
  def change
    create_table :channels do |t|
      t.references :site, null: false, foreign_key: true
      t.string :provider, null: false, default: "linkedin"
      t.string :name, null: false, default: ""
      t.string :author_urn, null: false
      t.string :member_urn, null: false, default: ""
      t.text :access_token
      t.text :refresh_token
      t.datetime :expires_at
      t.datetime :refresh_expires_at
      t.string :scopes, null: false, default: ""
      t.datetime :connected_at
      t.datetime :checked_at
      t.text :last_error
      t.timestamps
    end
    add_index :channels, %i[site_id provider author_urn], unique: true
  end
end
