# frozen_string_literal: true

Rails.application.routes.draw do
  namespace :admin do
    resources :sites do
      post :sync, on: :member
      post :discover, on: :collection
    end
    resources :pages do
      post :duplicate, on: :member
    end
    resources :assets, only: %i[index show]
    resources :terms, only: %i[index show]
    post "markdown_preview", to: "markdown_previews#create", as: :markdown_preview

    root to: "sites#index"
  end

  root to: redirect("/admin")

  # Images inside a registered site, by absolute path (thumbnails, media).
  get "files/*path", to: "files#show", as: :file, format: false

  get  "abc/new",          to: "abc_books#new",     as: :new_abc_book
  post "abc/preview",      to: "abc_books#preview", as: :preview_abc_book
  post "abc/export",       to: "abc_books#export",  as: :export_abc_book
  get  "abc/catalog.json", to: "abc_books#catalog", as: :abc_catalog

  get "up", to: "rails/health#show", as: :rails_health_check
end
