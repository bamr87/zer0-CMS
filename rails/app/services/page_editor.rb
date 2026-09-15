# frozen_string_literal: true

require "digest"
require "securerandom"

# The only path from the browser to a content file on disk.
#
# Every write re-reads the file, refuses when its bytes no longer match the
# digest the index holds (the file changed since the last sync), sends
# Zer0Cms::Cms::FrontMatter.update_keys ONLY the keys whose submitted value
# differs from what the file says, optionally replaces the body, writes
# atomically (a temp file in the same directory, then rename), and re-syncs
# that one path. A submission that changes nothing writes nothing.
class PageEditor
  class Error < StandardError; end
  class Stale < Error; end
  class Refused < Error; end
  class Invalid < Error; end

  # Front-matter keys the form edits as one line of text, and the form
  # attribute each one is shown in.
  SCALAR_KEYS = {
    "title" => "title", "description" => "description", "author" => "author", "date" => "date_text",
    "layout" => "layout", "permalink" => "permalink", "preview" => "preview", "status" => "status"
  }.freeze
  BOOLEAN_DEFAULTS = { "draft" => false, "published" => true }.freeze
  LIST_KEYS = %w[tags categories].freeze

  Result = Struct.new(:page, :changed_keys, :body_changed, keyword_init: true) do
    def changed?
      changed_keys.any? || body_changed
    end
  end

  attr_reader :page

  def initialize(page)
    @page = page
  end

  # The values the edit form shows, read from the file (not the index).
  def form_values
    _, doc = read
    values_for(doc).merge("base_digest" => page.digest)
  end

  # Keys the form cannot edit because the file holds a structured value.
  def locked_keys
    _, doc = read
    (SCALAR_KEYS.keys + LIST_KEYS).select { |key| locked?(doc, key) }
  end

  def body
    read.last.body
  end

  def save(params)
    params = params.to_h.stringify_keys
    text, doc = read(expected: params["base_digest"])
    changes = key_changes(doc, params)
    new_text = changes.empty? ? text : update_keys(text, changes)
    new_text, body_changed = replace_body(new_text, params["body"]) if params.key?("body")
    return Result.new(page: page, changed_keys: [], body_changed: false) if new_text == text

    write_atomically(text, new_text)
    page.site.sync_path!(page.relative)
    Result.new(page: page.site.pages.find_by(relative: page.relative) || page,
               changed_keys: changes.keys, body_changed: body_changed ? true : false)
  end

  def destroy!
    text, = read
    path = confined_path
    ensure_unchanged!(path, text)
    File.delete(path)
    page.site.sync_path!(page.relative)
  rescue SystemCallError => e
    raise Refused, "could not delete #{page.relative}: #{e.message}"
  end

  # A draft copy next to the file; returns the copy's Page row (or nil when
  # Jekyll would not read the copy as content).
  def duplicate!
    read
    copy = Zer0Cms::Cms::Writer.duplicate(confined_path, root: page.site.path)
    relative = page.site.site_path.relative_for(copy)
    raise Refused, "the copy landed outside the site" unless relative

    page.site.sync_path!(relative)
    page.site.pages.find_by(relative: relative)
  rescue ArgumentError, Zer0Cms::Cms::UnsafePath, Zer0Cms::Cms::FrontMatter::EditError => e
    raise Invalid, e.message
  end

  # The file's bytes as the index knows them; raises Stale when the file
  # changed since the last sync.
  def current_text
    read.first
  end

  def file_path
    confined_path
  end

  # The image engine wrote `key:` into the file itself (`engine_text`). That
  # edit goes through the same path as a form save: the key alone is applied
  # to the bytes the index knew (`original`) by FrontMatter.update_keys and
  # written atomically over the engine's bytes, then the path is re-synced.
  # When the engine changed anything besides that key, or its value cannot be
  # written back, the original bytes are restored and the edit is refused.
  # Returns the key's new value.
  def replace_engine_write!(original, engine_text, key)
    before = Zer0Cms::Cms::FrontMatter.parse(original)
    after = Zer0Cms::Cms::FrontMatter.parse(engine_text)
    value = after.data[key]
    only_key = after.errors.empty? && value.is_a?(String) && after.body == before.body &&
               after.data.except(key) == before.data.except(key)
    edited = begin
      only_key ? update_keys(original, { key => value }) : nil
    rescue Invalid
      nil
    end
    write_atomically(engine_text, edited || original)
    page.site.sync_path!(page.relative)
    raise Refused, "the image engine changed more than #{key}: in #{page.relative}; its edit was undone" unless edited

    value
  end

  private

  def confined_path
    page.site.site_path.file!(page.relative)
  rescue SitePath::Refused => e
    raise Refused, e.message
  end

  # [text, document] — refuses a file that changed since the last sync, and
  # (with `expected`) a form opened before the index last changed.
  def read(expected: nil)
    return @read if @read && expected.nil?

    text = File.binread(confined_path)
    if Digest::SHA256.hexdigest(text) != page.digest
      raise Stale, "#{page.relative} changed on disk since the last sync. Sync the site, then make your edit again."
    end
    if expected.present? && expected != page.digest
      raise Stale, "#{page.relative} was re-indexed after this form was opened. Reload the page and make your edit again."
    end

    text.force_encoding(Encoding::UTF_8)
    raise Invalid, "#{page.relative} is not valid UTF-8" unless text.valid_encoding?

    @read = [text, Zer0Cms::Cms::FrontMatter.parse(text)]
  rescue SystemCallError => e
    raise Refused, "#{page.relative} cannot be read: #{e.message}"
  end

  def values_for(doc)
    values = {}
    SCALAR_KEYS.each { |key, attr| values[attr] = locked?(doc, key) ? "" : scalar_text(doc, key) }
    BOOLEAN_DEFAULTS.each { |key, default| values[key] = boolean(doc, key, default) }
    LIST_KEYS.each { |key| values[key] = locked?(doc, key) ? [] : list(doc, key) }
    values["body"] = doc.body
    values
  end

  def key_changes(doc, params)
    current = values_for(doc)
    changes = {}
    SCALAR_KEYS.each do |key, attr|
      next unless params.key?(attr) && !locked?(doc, key)

      submitted = params[attr].to_s.gsub("\r\n", "\n")
      next if submitted == current[attr]

      changes[key] = submitted.empty? ? nil : submitted
    end
    BOOLEAN_DEFAULTS.each_key do |key|
      next unless params.key?(key)

      submitted = ActiveModel::Type::Boolean.new.cast(params[key]) ? true : false
      changes[key] = submitted unless submitted == current[key]
    end
    LIST_KEYS.each do |key|
      next unless params.key?(key) && !locked?(doc, key)

      submitted = split_list(params[key])
      next if submitted == current[key]

      original = Array(doc.data[key])
      changes[key] = submitted.empty? ? nil : submitted.map { |item| original.find { |o| o.to_s == item } || item }
    end
    changes
  end

  def update_keys(text, changes)
    Zer0Cms::Cms::FrontMatter.update_keys(text, changes)
  rescue Zer0Cms::Cms::FrontMatter::EditError => e
    raise Invalid, "front matter not saved: #{e.message}"
  end

  # Browsers submit a textarea with CRLF line breaks; compare and write in the
  # file's own line ending.
  def replace_body(text, submitted)
    doc = Zer0Cms::Cms::FrontMatter.parse(text)
    current = doc.body
    wanted = submitted.to_s.gsub("\r\n", "\n")
    return [text, false] if wanted == current.gsub("\r\n", "\n")

    wanted = wanted.gsub("\n", "\r\n") if doc.newline == "\r\n"
    [text[0, text.length - current.length] + wanted, true]
  end

  def write_atomically(original, text)
    path = confined_path
    ensure_unchanged!(path, original)
    mode = File.stat(path).mode & 0o7777
    tmp = path.dirname.join(".#{path.basename}.zer0-cms-#{SecureRandom.hex(6)}.tmp")
    File.open(tmp, File::WRONLY | File::CREAT | File::EXCL, mode) do |file|
      file.write(text.b)
      file.flush
      file.fsync
    end
    ensure_unchanged!(confined_path, original)
    File.rename(tmp, path)
    tmp = nil
  rescue SystemCallError => e
    raise Refused, "could not write #{page.relative}: #{e.message}"
  ensure
    File.unlink(tmp) if tmp && File.exist?(tmp)
  end

  def ensure_unchanged!(path, original)
    return if File.binread(path) == original.b

    raise Stale, "#{page.relative} changed on disk while saving. Sync the site, then make your edit again."
  end

  def locked?(doc, key)
    return false unless doc.data.key?(key)

    value = doc.data[key]
    if LIST_KEYS.include?(key)
      !(value.nil? || value.is_a?(String) || (value.is_a?(Array) && value.none? { |item| item.is_a?(Hash) || item.is_a?(Array) }))
    else
      value.is_a?(Hash) || value.is_a?(Array)
    end
  end

  def scalar_text(doc, key)
    return "" unless doc.data.key?(key)

    doc.raw_values.fetch(key) { doc.data[key].to_s }
  end

  def boolean(doc, key, default)
    return default unless doc.data.key?(key)

    key == "published" ? doc.data[key] != false : [true, "true", 1, "1"].include?(doc.data[key])
  end

  def list(doc, key)
    Array(doc.data[key]).map(&:to_s)
  end

  def split_list(value)
    value.to_s.split(",").map(&:strip).reject(&:empty?)
  end
end
