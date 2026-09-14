# frozen_string_literal: true

class SitePagesController < ApplicationController
  before_action :set_site

  def index
    @catalog = @site.catalog
    @q = params[:q].to_s.strip
    @collection = params[:collection].to_s
    @status = params[:status].to_s
    @entries = @catalog.entries
    @entries = @entries.select { |e| e.collection == @collection } if @collection.present?
    @entries = @entries.select { |e| e.tags.map(&:to_s).include?(params[:tag]) } if params[:tag].present?
    @entries = @entries.select { |e| e.categories.map(&:to_s).include?(params[:category]) } if params[:category].present?
    @entries = @entries.select { |e| e.author == params[:author] } if params[:author].present?
    case @status
    when "draft" then @entries = @entries.select { |e| e.draft || e.status.to_s == "draft" }
    when "live" then @entries = @entries.reject { |e| e.draft || e.status.to_s == "draft" }
    end
    if @q.present?
      needle = @q.downcase
      @entries = @entries.select { |e| "#{e.title} #{e.relative} #{e.author} #{e.description}".downcase.include?(needle) }
    end
    @pagy, @entries = pagy_array(@entries)
  rescue StandardError => e
    @scan_error = e.message
  end

  def new
    @catalog = @site.catalog
    @title = params[:title].to_s
  end

  def create
    extras = {
      "author" => params[:author].to_s,
      "description" => params[:description].to_s,
      "draft" => ActiveModel::Type::Boolean.new.cast(params[:draft])
    }
    extras["categories"] = csv(params[:categories]) if params[:categories].present?
    extras["tags"] = csv(params[:tags]) if params[:tags].present?
    path = Zer0Cms::Cms::Writer.create(
      @site.root,
      collection: params[:collection].presence || "posts",
      title: params[:title].to_s,
      slug: params[:slug].to_s,
      extras: extras,
      body: params[:body].to_s
    )
    relative = path.relative_path_from(@site.root).to_s
    @site.update_column(:last_scanned_at, Time.current)
    redirect_to item_site_pages_path(@site, file: relative), notice: "Created #{relative}."
  rescue ArgumentError => e
    @catalog = @site.catalog
    @title = params[:title].to_s
    flash.now[:alert] = e.message
    render :new, status: :unprocessable_entity
  end

  def show
    @catalog = @site.catalog
    @entry = find_entry!
    return unless @entry

    @doc = Zer0Cms::Cms::FrontMatter.parse(File.read(@entry.path))
    @html = markdown_html_safe(@doc.body)
  rescue StandardError => e
    redirect_to site_pages_path(@site), alert: e.message
  end

  def update
    @entry = find_entry!
    return unless @entry

    raw = File.read(@entry.path)
    updated = Zer0Cms::Cms::FrontMatter.update_keys(raw, page_changes)
    if params[:body].is_a?(String) && params[:page].blank?
      fence = updated[/\A---\n.*?\n---\n/m]
      updated = "#{fence}#{params[:body]}" if fence
    end
    File.write(@entry.path, updated)
    @site.update_column(:last_scanned_at, Time.current)
    redirect_to item_site_pages_path(@site, file: @entry.relative), notice: "Saved #{@entry.relative}."
  end

  def destroy
    @entry = find_entry!
    return unless @entry

    File.delete(@entry.path)
    @site.update_column(:last_scanned_at, Time.current)
    redirect_to site_pages_path(@site), notice: "Deleted #{@entry.relative}."
  end

  def duplicate
    @entry = find_entry!
    return unless @entry

    copy = Zer0Cms::Cms::Writer.duplicate(@entry.path)
    relative = copy.relative_path_from(@site.root).to_s
    redirect_to item_site_pages_path(@site, file: relative), notice: "Duplicated to #{relative}."
  end

  def preview_markdown
    html = helpers.markdown_html(params[:markdown])
    render html: html.html_safe
  end

  private

  def set_site
    @site = Site.find(params[:site_id])
  end

  def find_entry!
    @catalog ||= @site.catalog
    entry = @catalog.entries.find { |e| e.relative == params[:file].to_s }
    redirect_to site_pages_path(@site), alert: "No content file matched that path." unless entry
    entry
  end

  def markdown_html_safe(text)
    helpers.markdown_html(text)
  end

  def page_changes
    permitted = params.fetch(:page, {}).permit(
      :title, :description, :date, :author, :excerpt, :status, :draft, :preview, :tags, :categories
    )
    changes = {}
    %w[title description date author excerpt status preview].each do |key|
      changes[key] = permitted[key] if permitted.key?(key)
    end
    changes["draft"] = ActiveModel::Type::Boolean.new.cast(permitted[:draft]) if permitted.key?(:draft)
    changes["tags"] = csv(permitted[:tags]) if permitted.key?(:tags)
    changes["categories"] = csv(permitted[:categories]) if permitted.key?(:categories)
    changes
  end

  def csv(value)
    value.to_s.split(",").map(&:strip).reject(&:empty?)
  end
end
