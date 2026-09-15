# frozen_string_literal: true

# Resolves a root-relative path inside one site for a read or a write.
#
# The path must name an existing regular file, reached without `..`, without
# an absolute prefix, and without a symlink at ANY component below the site
# root; its realpath must then be inside the root's realpath. This is the one
# confinement check the file server, the editor and destroy all share.
class SitePath
  class Refused < StandardError; end
  class NotFound < Refused; end

  attr_reader :root

  def initialize(root)
    @root = Pathname.new(File.realpath(root.to_s))
  rescue SystemCallError
    raise NotFound, "the site directory is not reachable"
  end

  def file!(relative)
    parts = segments!(relative)
    current = root
    parts.each do |part|
      current = current.join(part)
      raise Refused, "#{relative} goes through a symlink" if File.lstat(current).symlink?
    end
    raise Refused, "#{relative} is not a regular file" unless File.lstat(current).file?

    real = current.realpath
    raise Refused, "#{relative} resolves outside the site" unless inside?(real)

    real
  rescue Errno::ENOENT, Errno::ENOTDIR
    raise NotFound, "#{relative} does not exist"
  rescue SystemCallError => e
    raise Refused, "#{relative} cannot be read (#{e.class.name.split("::").last})"
  end

  # The root-relative path for an absolute path under the root, or nil.
  def relative_for(absolute)
    text = absolute.to_s
    prefix = "#{root}/"
    text.start_with?(prefix) ? text.delete_prefix(prefix) : nil
  end

  def inside?(real)
    real.to_s.start_with?("#{root}/")
  end

  private

  def segments!(relative)
    text = relative.to_s
    parts = text.split("/", -1)
    if text.empty? || text.start_with?("/") || text.include?("\0") || parts.any? { |p| p.empty? || p == "." || p == ".." }
      raise Refused, "#{text.inspect} is not a plain path inside the site"
    end

    parts
  end
end
