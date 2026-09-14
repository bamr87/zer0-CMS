# frozen_string_literal: true

# Where an ABC book export may write: an explicit, existing Jekyll root (a
# directory holding a regular _config.yml). With SITES_DIR set it must be a
# site strictly inside the mount — never the mount itself.
module AbcExportTarget
  class Refused < StandardError; end

  module_function

  def resolve!(value, sites_dir: Site.sites_dir)
    text = value.to_s.strip
    raise Refused, "Choose the target site directory (a Jekyll root with _config.yml) to export into." if text.empty?

    path = Pathname.new(text)
    raise Refused, "The export target must be an absolute path." unless path.absolute?
    raise Refused, "#{text} is not a directory." unless path.directory?

    real = path.realpath
    config = real.join("_config.yml")
    raise Refused, "#{text} has no _config.yml, so it is not a Jekyll site root." unless config.file? && !config.symlink?
    unless Site.inside_sites_dir?(real.to_s, sites_dir)
      raise Refused, "#{text} is not a site inside SITES_DIR (#{sites_dir})."
    end

    real
  rescue SystemCallError => e
    raise Refused, "The export target cannot be used: #{e.message}"
  end
end
