# frozen_string_literal: true

Rails.application.routes.draw do
  root "dashboard#show"
  get "search", to: "search#show"

  resources :sites do
    collection { post :import_discovered }
    resources :pages, only: %i[index new create], controller: "site_pages" do
      collection do
        get :item, action: :show
        patch :item, action: :update
        delete :item, action: :destroy
        post :duplicate
        post :preview_markdown
      end
    end
    resources :media, only: :index, controller: "site_media"
    resource :taxonomy, only: :show, controller: "site_taxonomies"
    resource :config, only: :show, controller: "site_configs"
    member { post :rescan }
  end

  get "files/*path", to: "files#show", as: :file, format: false

  get  "abc/new",     to: "abc_books#new",     as: :new_abc_book
  post "abc/preview", to: "abc_books#preview", as: :preview_abc_book
  post "abc/export",  to: "abc_books#export",  as: :export_abc_book
  get  "abc/catalog.json", to: "abc_books#catalog"
end
