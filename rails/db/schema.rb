# frozen_string_literal: true

ActiveRecord::Schema[7.1].define(version: 1) do
  create_table :sites, force: :cascade do |t|
    t.string :name, null: false
    t.string :path, null: false
    t.string :source_subdir, default: "", null: false
    t.text :notes
    t.datetime :last_scanned_at
    t.timestamps
  end
  add_index :sites, :path, unique: true
end
