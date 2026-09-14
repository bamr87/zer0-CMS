# frozen_string_literal: true

# The index of every registered Jekyll site. Git is the source of truth: each
# row is rebuilt from disk by Site#sync!, so `force: :cascade` is safe — it
# replaces the schema-version-1 `sites` registry an older build created, and
# Sites -> Discover re-registers those roots.
class CreateTheIndex < ActiveRecord::Migration[8.1]
  def change
    create_table :sites, force: :cascade do |t|
      t.string :name, null: false
      t.string :path, null: false
      t.string :source_subdir, null: false, default: ""
      t.string :collections_dir, null: false, default: ""
      t.datetime :last_synced_at
      t.text :sync_error
      t.integer :pages_count, null: false, default: 0
      t.integer :assets_count, null: false, default: 0
      t.timestamps
    end
    add_index :sites, :path, unique: true

    create_table :pages, force: :cascade do |t|
      t.references :site, null: false, foreign_key: true
      t.string :source_relative, null: false
      t.string :relative, null: false
      t.string :kind, null: false
      t.string :collection, null: false
      t.string :title, null: false, default: ""
      t.text :description, null: false, default: ""
      t.string :author, null: false, default: ""
      t.datetime :date
      t.datetime :lastmod
      t.string :layout, null: false, default: ""
      t.string :permalink, null: false, default: ""
      t.string :preview, null: false, default: ""
      t.string :status, null: false, default: ""
      t.boolean :draft, null: false, default: false
      t.boolean :published, null: false, default: true
      t.boolean :future, null: false, default: false
      t.json :tags, null: false, default: []
      t.json :categories, null: false, default: []
      t.json :front_matter, null: false, default: {}
      t.text :error
      t.string :digest, null: false
      t.integer :bytes, null: false, default: 0
      t.datetime :mtime
      t.timestamps
    end
    add_index :pages, %i[site_id source_relative], unique: true
    add_index :pages, %i[site_id relative], unique: true
    add_index :pages, %i[site_id collection]
    add_index :pages, :date

    create_table :assets, force: :cascade do |t|
      t.references :site, null: false, foreign_key: true
      t.string :relative, null: false
      t.string :ext, null: false, default: ""
      t.integer :bytes, null: false, default: 0
      t.datetime :mtime
      t.timestamps
    end
    add_index :assets, %i[site_id relative], unique: true

    create_table :terms, force: :cascade do |t|
      t.references :site, null: false, foreign_key: true
      t.string :kind, null: false
      t.string :name, null: false
      t.integer :pages_count, null: false, default: 0
      t.timestamps
    end
    add_index :terms, %i[site_id kind name], unique: true
  end
end
