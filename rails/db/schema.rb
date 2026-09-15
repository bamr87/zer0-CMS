# This file is auto-generated from the current state of the database. Instead
# of editing this file, please use the migrations feature of Active Record to
# incrementally modify your database, and then regenerate this schema definition.
#
# This file is the source Rails uses to define your schema when running `bin/rails
# db:schema:load`. When creating a new database, `bin/rails db:schema:load` tends to
# be faster and is potentially less error prone than running all of your
# migrations from scratch. Old migrations may fail to apply correctly if those
# migrations use external dependencies or application code.
#
# It's strongly recommended that you check this file into your version control system.

ActiveRecord::Schema[8.1].define(version: 2026_09_15_000001) do
  create_table "assets", force: :cascade do |t|
    t.integer "bytes", default: 0, null: false
    t.datetime "created_at", null: false
    t.string "ext", default: "", null: false
    t.datetime "mtime"
    t.string "relative", null: false
    t.integer "site_id", null: false
    t.datetime "updated_at", null: false
    t.index ["site_id", "relative"], name: "index_assets_on_site_id_and_relative", unique: true
    t.index ["site_id"], name: "index_assets_on_site_id"
  end

  create_table "channels", force: :cascade do |t|
    t.text "access_token"
    t.string "author_urn", null: false
    t.datetime "checked_at"
    t.datetime "connected_at"
    t.datetime "created_at", null: false
    t.datetime "expires_at"
    t.text "last_error"
    t.string "member_urn", default: "", null: false
    t.string "name", default: "", null: false
    t.string "provider", default: "linkedin", null: false
    t.datetime "refresh_expires_at"
    t.text "refresh_token"
    t.string "scopes", default: "", null: false
    t.integer "site_id", null: false
    t.datetime "updated_at", null: false
    t.index ["site_id", "provider", "author_urn"], name: "index_channels_on_site_id_and_provider_and_author_urn", unique: true
    t.index ["site_id"], name: "index_channels_on_site_id"
  end

  create_table "pages", force: :cascade do |t|
    t.string "author", default: "", null: false
    t.integer "bytes", default: 0, null: false
    t.json "categories", default: [], null: false
    t.string "collection", null: false
    t.datetime "created_at", null: false
    t.datetime "date"
    t.text "description", default: "", null: false
    t.string "digest", null: false
    t.boolean "draft", default: false, null: false
    t.text "error"
    t.json "front_matter", default: {}, null: false
    t.boolean "future", default: false, null: false
    t.string "kind", null: false
    t.datetime "lastmod"
    t.string "layout", default: "", null: false
    t.datetime "mtime"
    t.string "permalink", default: "", null: false
    t.string "preview", default: "", null: false
    t.boolean "published", default: true, null: false
    t.string "relative", null: false
    t.integer "site_id", null: false
    t.string "source_relative", null: false
    t.string "status", default: "", null: false
    t.json "tags", default: [], null: false
    t.string "title", default: "", null: false
    t.datetime "updated_at", null: false
    t.index ["date"], name: "index_pages_on_date"
    t.index ["site_id", "collection"], name: "index_pages_on_site_id_and_collection"
    t.index ["site_id", "relative"], name: "index_pages_on_site_id_and_relative", unique: true
    t.index ["site_id", "source_relative"], name: "index_pages_on_site_id_and_source_relative", unique: true
    t.index ["site_id"], name: "index_pages_on_site_id"
  end

  create_table "sites", force: :cascade do |t|
    t.integer "assets_count", default: 0, null: false
    t.string "collections_dir", default: "", null: false
    t.datetime "created_at", null: false
    t.datetime "last_synced_at"
    t.string "name", null: false
    t.integer "pages_count", default: 0, null: false
    t.string "path", null: false
    t.string "source_subdir", default: "", null: false
    t.text "sync_error"
    t.datetime "updated_at", null: false
    t.index ["path"], name: "index_sites_on_path", unique: true
  end

  create_table "terms", force: :cascade do |t|
    t.datetime "created_at", null: false
    t.string "kind", null: false
    t.string "name", null: false
    t.integer "pages_count", default: 0, null: false
    t.integer "site_id", null: false
    t.datetime "updated_at", null: false
    t.index ["site_id", "kind", "name"], name: "index_terms_on_site_id_and_kind_and_name", unique: true
    t.index ["site_id"], name: "index_terms_on_site_id"
  end

  add_foreign_key "assets", "sites"
  add_foreign_key "channels", "sites"
  add_foreign_key "pages", "sites"
  add_foreign_key "terms", "sites"
end
