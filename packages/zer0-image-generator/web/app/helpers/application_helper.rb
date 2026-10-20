module ApplicationHelper
  def disk_file_url(path)
    return if path.blank?

    pathname = Pathname.new(path.to_s)
    return unless pathname.exist?

    file_path(path: pathname.realpath.to_s.sub(%r{\A/}, ""))
  end

  def preview_image_url(entry)
    return entry.preview if entry.respond_to?(:remote?) && entry.remote?
    return entry.preview if entry.preview.to_s.start_with?("http://", "https://")

    disk_file_url(entry.disk_path)
  end

  def site_tab_class(active)
    active ? "active" : ""
  end
end
