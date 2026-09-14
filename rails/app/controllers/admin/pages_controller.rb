# frozen_string_literal: true

module Admin
  # Pages are an index of files. Index and show are Administrate's; every
  # write — edit, create, duplicate, destroy — goes to disk through
  # PageEditor or Zer0Cms::Cms::Writer and then re-syncs the path.
  class PagesController < Admin::ApplicationController
    EDIT_PARAMS = (PageEditor::SCALAR_KEYS.values + PageEditor::BOOLEAN_DEFAULTS.keys +
                   PageEditor::LIST_KEYS + %w[body base_digest]).freeze
    NEW_PARAMS = %i[site_id collection section title slug description author tags draft body].freeze

    def show
      begin
        requested_resource.body = PageEditor.new(requested_resource).body
      rescue PageEditor::Error => e
        flash.now[:alert] = e.message
      end
      super
    end

    def edit
      editor = PageEditor.new(requested_resource)
      requested_resource.assign_attributes(editor.form_values)
      locked = editor.locked_keys
      flash.now[:notice] = "Not editable here (structured values): #{locked.join(", ")}." if locked.any?
      render_form
    rescue PageEditor::Error => e
      @editor_error = e
      flash.now[:alert] = e.message
      render_form(status: e.is_a?(PageEditor::Stale) ? :conflict : :unprocessable_entity)
    end

    def update
      result = PageEditor.new(requested_resource).save(edit_params)
      notice = if result.changed?
                 changed = result.changed_keys + (result.body_changed ? ["body"] : [])
                 "Saved #{requested_resource.relative} (#{changed.join(", ")})."
               else
                 "No changes — #{requested_resource.relative} was not written."
               end
      redirect_to [namespace, result.page], notice: notice, status: :see_other
    rescue PageEditor::Error => e
      @editor_error = e
      requested_resource.assign_attributes(edit_params.to_h.slice(*EDIT_PARAMS).merge("tags" => split(edit_params[:tags]),
                                                                                        "categories" => split(edit_params[:categories])))
      flash.now[:alert] = e.message
      render_form(status: e.is_a?(PageEditor::Stale) ? :conflict : :unprocessable_entity)
    end

    def new
      @site = Site.find_by(id: params[:site_id])
      @collections = @site ? @site.writable_collections : {}
      @values = {}
      render :new, locals: { sites: Site.named }
    end

    def create
      values = params.require(:page).permit(*NEW_PARAMS)
      @site = Site.find(values[:site_id])
      path = Zer0Cms::Cms::Writer.create(
        @site.path,
        collection: values[:collection].to_s, section: values[:section].to_s,
        title: values[:title].to_s, slug: values[:slug].to_s,
        extras: new_page_extras(values), body: values[:body].to_s.gsub("\r\n", "\n")
      )
      relative = @site.site_path.relative_for(path.realpath)
      @site.sync_path!(relative)
      created = @site.pages.find_by(relative: relative)
      target = created ? [:edit, namespace, created] : [namespace, @site]
      redirect_to target, notice: "Created #{relative}.", status: :see_other
    rescue ArgumentError, Zer0Cms::Cms::UnsafePath, Zer0Cms::Cms::FrontMatter::EditError, SiteSync::Failed => e
      @collections = @site.writable_collections
      @values = values.to_h
      flash.now[:alert] = e.message
      render :new, locals: { sites: Site.named }, status: :unprocessable_entity
    end

    def duplicate
      copy = PageEditor.new(requested_resource).duplicate!
      if copy
        redirect_to [:edit, namespace, copy], notice: "Duplicated to #{copy.relative} as a draft.", status: :see_other
      else
        redirect_to [namespace, requested_resource], notice: "Duplicated; Jekyll does not read the copy as content.", status: :see_other
      end
    rescue PageEditor::Error, SiteSync::Failed => e
      redirect_to [namespace, requested_resource], alert: e.message, status: :see_other
    end

    def destroy
      relative = requested_resource.relative
      PageEditor.new(requested_resource).destroy!
      redirect_to admin_pages_path, notice: "Deleted #{relative}.", status: :see_other
    rescue PageEditor::Error, SiteSync::Failed => e
      redirect_to [namespace, requested_resource], alert: e.message, status: :see_other
    end

    private

    def render_form(status: :ok)
      render :edit, locals: { page: Administrate::Page::Form.new(dashboard, requested_resource) }, status: status
    end

    def edit_params
      @edit_params ||= params.require(:page).permit(*EDIT_PARAMS)
    end

    def new_page_extras(values)
      extras = {}
      extras["description"] = values[:description].to_s if values[:description].present?
      extras["author"] = values[:author].to_s if values[:author].present?
      tags = split(values[:tags])
      extras["tags"] = tags if tags.any?
      extras["draft"] = true if ActiveModel::Type::Boolean.new.cast(values[:draft])
      extras
    end

    def split(value)
      value.to_s.split(",").map(&:strip).reject(&:empty?)
    end

    def default_sorting_attribute
      :date
    end

    def default_sorting_direction
      :desc
    end
  end
end
