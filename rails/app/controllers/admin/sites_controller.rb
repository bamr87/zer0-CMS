# frozen_string_literal: true

module Admin
  class SitesController < Admin::ApplicationController
    def create
      super { |site| sync_with_flash(site) }
    end

    def update
      if requested_resource.update(resource_params)
        sync_with_flash(requested_resource) if requested_resource.saved_change_to_path?
        redirect_to [namespace, requested_resource], notice: "Site updated.", status: :see_other
      else
        render :edit, locals: { page: Administrate::Page::Form.new(dashboard, requested_resource) },
                      status: :unprocessable_entity
      end
    end

    def destroy
      name = requested_resource.name
      requested_resource.destroy
      redirect_to admin_sites_path, notice: "#{name} removed from the index. No file on disk was touched.", status: :see_other
    end

    def sync
      result = requested_resource.sync!
      redirect_to [namespace, requested_resource], status: :see_other,
                  notice: "Synced #{result.pages} pages, #{result.assets} images, #{result.terms} terms."
    rescue SiteSync::Failed => e
      redirect_to [namespace, requested_resource], alert: "Sync failed: #{e.message}", status: :see_other
    end

    def discover
      registered = Site.discover_roots.filter_map do |root|
        site = Site.new(name: File.basename(root), path: root)
        next unless site.save

        sync_with_flash(site)
        site
      end
      notice = registered.any? ? "Registered #{registered.map(&:name).to_sentence}." : "No unregistered sites under #{Site.sites_dir || "SITES_DIR"}."
      redirect_to admin_sites_path, notice: notice, status: :see_other
    end

    private

    def default_sorting_attribute
      :name
    end

    def sync_with_flash(site)
      site.sync!
    rescue SiteSync::Failed => e
      flash[:alert] = "#{site.name} registered, but the sync failed: #{e.message}"
    end
  end
end
