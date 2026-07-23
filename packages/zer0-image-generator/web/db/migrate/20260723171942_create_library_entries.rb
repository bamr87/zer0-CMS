# frozen_string_literal: true

# Mirrors tools/svg/library/MANIFEST.json into the database so the library is
# searchable/filterable in the UI. The manifest on disk stays the source of
# truth — this table is a projection that is re-synced, never authored here.
class CreateLibraryEntries < ActiveRecord::Migration[8.1]
  def change
    create_table :library_entries do |t|
      t.string :file, null: false
      t.string :title
      # "first-party (this repository)" or an upstream URL. Provenance and
      # license are not optional metadata here: the library README makes them
      # an obligation for anything sourced externally.
      t.string :source_url
      t.string :license
      t.string :license_url
      t.json :tags, null: false, default: []
      t.string :lint
      t.float :size_kb

      t.timestamps
    end

    add_index :library_entries, :file, unique: true
  end
end
