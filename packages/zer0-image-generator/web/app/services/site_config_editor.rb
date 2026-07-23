# frozen_string_literal: true

# Reads and writes the `preview_images:` block of a site's _config.yml.
#
# Writing a whole _config.yml back through a YAML dumper would strip every
# comment and reorder every key in the file — unacceptable for a file the user
# hand-maintains. So the writer surgically replaces only the `preview_images:`
# block (from its top-level key to the next top-level key), leaving the rest of
# the file byte-for-byte intact. This mirrors how the engine's
# update_front_matter treats a post: touch one region, preserve everything else.
class SiteConfigEditor
  class Error < StandardError; end

  # The block keys the form exposes, with their kind so the view can render the
  # right control and the writer can coerce values back.
  STRING_KEYS = %w[provider model size quality style style_modifiers output_dir
                   assets_prefix front_matter_key authors_file collections_dir
                   prompt_engine review_engine claude_model claude_effort].freeze
  BOOL_KEYS = %w[enabled auto_prefix].freeze
  # collections is a list or the literal "auto".
  LIST_KEYS = %w[collections].freeze

  def initialize(site)
    @site = site
    @path = site.config_file
  end

  # Current values for the block, defaults filled in, so the form always shows
  # the effective configuration rather than a sea of blanks.
  def current
    block = full_config["preview_images"]
    block = {} unless block.is_a?(Hash)
    defaults = Zer0ImageGenerator::DEFAULTS
    values = {}
    (STRING_KEYS + BOOL_KEYS).each { |k| values[k] = block.fetch(k, defaults[k]) }
    LIST_KEYS.each do |k|
      raw = block.fetch(k, defaults[k])
      values[k] = raw.is_a?(Array) ? raw.join(", ") : raw.to_s
    end
    values
  end

  # Apply a params hash and rewrite the block in place. Returns nothing;
  # raises Error on a malformed file the writer refuses to touch.
  def update(params)
    block = build_block(params)
    text = read
    rewritten = replace_block(text, serialize(block))
    write_atomically(rewritten)
    @site.update(last_scanned_at: Time.current)
  end

  private

  def full_config
    EngineBridge.read_config(@site.root)
  rescue EngineBridge::Error => e
    raise Error, e.message
  end

  def read
    raise Error, "#{@path} does not exist" unless @path.file?

    @path.read
  end

  # Coerce the incoming form params into a typed block hash. Only keys the user
  # actually set to a non-default-empty value are written, so the block stays as
  # small as the user's intent — the engine fills the rest from its defaults.
  def build_block(params)
    block = {}
    STRING_KEYS.each do |k|
      v = params[k]
      block[k] = v.to_s unless v.nil?
    end
    BOOL_KEYS.each { |k| block[k] = ActiveModel::Type::Boolean.new.cast(params[k]) unless params[k].nil? }
    LIST_KEYS.each do |k|
      next if params[k].nil?

      raw = params[k].to_s.strip
      block[k] = raw == "auto" ? "auto" : raw.split(",").map(&:strip).reject(&:empty?)
    end
    block
  end

  # Serialize just the block's body (its child lines), two-space indented under
  # a `preview_images:` header the caller re-adds.
  def serialize(block)
    yaml = { "preview_images" => block }.to_yaml
    # Psych emits a leading "---\n"; drop it — we are splicing, not writing a
    # standalone document.
    yaml.sub(/\A---\n/, "")
  end

  # Replace the existing top-level `preview_images:` block, or append a fresh
  # one if the file has none. A top-level key is one with no leading whitespace;
  # the block runs until the next such key or EOF.
  def replace_block(text, block_yaml)
    lines = text.lines
    start = lines.index { |l| l =~ /\Apreview_images\s*:/ }
    block_yaml = "#{block_yaml}\n" unless block_yaml.end_with?("\n")

    if start.nil?
      sep = text.empty? || text.end_with?("\n") ? "" : "\n"
      return "#{text}#{sep}\n#{block_yaml}"
    end

    stop = start + 1
    stop += 1 while stop < lines.length && !top_level_key?(lines[stop])
    (lines[0...start] + [block_yaml] + lines[stop..]).join
  end

  # A non-blank, non-comment line that starts in column zero begins a new
  # top-level key — the boundary of the block we are replacing.
  def top_level_key?(line)
    return false if line.strip.empty?
    return false if line.lstrip.start_with?("#")

    line == line.lstrip && line.include?(":")
  end

  def write_atomically(text)
    tmp = @path.sub_ext(".yml.tmp")
    tmp.write(text)
    tmp.rename(@path.to_s)
  rescue SystemCallError => e
    raise Error, "could not write #{@path}: #{e.message}"
  end
end
