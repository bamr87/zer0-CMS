# frozen_string_literal: true

class CreateSites < ActiveRecord::Migration[8.1]
  def change
    create_table :sites do |t|
      t.string :name, null: false
      # Absolute path to the Jekyll site root on this machine. This is a local
      # single-user tool, so sites are read in place rather than cloned.
      t.string :path, null: false
      # Jekyll's own top-level `source:` key, cached from _config.yml: disk
      # paths resolve inside it while front-matter values keep their URL form.
      t.string :source_subdir, default: "", null: false
      t.datetime :last_scanned_at
      t.text :notes

      t.timestamps
    end

    add_index :sites, :path, unique: true
  end
end
