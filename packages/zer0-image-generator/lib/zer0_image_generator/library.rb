# frozen_string_literal: true

require "json"
require "fileutils"

module Zer0ImageGenerator
  # Byte-exact re-implementation of CPython's `json.dumps(obj, indent=2)`.
  #
  # The example library's MANIFEST.json is a committed artifact produced by
  # `tools/svg/freesvg.py`'s `_write_json` (json.dump indent=2 + a trailing
  # newline). Promoting from Ruby has to yield a byte-for-byte identical file so
  # the git diff is only the new entry — which rules out Ruby's own
  # JSON.pretty_generate: its empty-container layout, its float rendering and,
  # above all, its non-ASCII handling all differ from CPython. This encoder
  # pins every one of those to CPython's, so the manifest round-trips cleanly no
  # matter which language wrote it last.
  module PyJson
    module_function

    def dump(obj)
      out = +""
      encode(obj, 0, out)
      out
    end

    # `indent` is the column the CURRENT value's closing bracket sits at; child
    # members are written at indent + 2, matching json.dumps(indent=2).
    def encode(obj, indent, out)
      case obj
      when Hash then encode_object(obj, indent, out)
      when Array then encode_array(obj, indent, out)
      when String then out << encode_string(obj)
      when Integer then out << obj.to_s
      when Float then out << float_repr(obj)
      when true then out << "true"
      when false then out << "false"
      when nil then out << "null"
      else
        # json.dumps would raise TypeError here; keep the failure explicit
        # rather than silently coercing something the manifest never contains.
        raise ArgumentError, "PyJson cannot encode #{obj.class}"
      end
    end

    def encode_object(hash, indent, out)
      # json.dumps(indent=2) collapses empty containers to `{}` / `[]` with no
      # inner newline; every non-empty container opens a newline-delimited block.
      if hash.empty?
        out << "{}"
        return
      end
      inner = indent + 2
      pad = " " * inner
      out << "{\n"
      first = true
      hash.each do |key, value|
        out << ",\n" unless first
        first = false
        out << pad << encode_string(key.to_s) << ": "
        encode(value, inner, out)
      end
      out << "\n" << (" " * indent) << "}"
    end

    def encode_array(array, indent, out)
      if array.empty?
        out << "[]"
        return
      end
      inner = indent + 2
      pad = " " * inner
      out << "[\n"
      first = true
      array.each do |value|
        out << ",\n" unless first
        first = false
        out << pad
        encode(value, inner, out)
      end
      out << "\n" << (" " * indent) << "]"
    end

    # The named short escapes json.dumps emits; everything else in the control
    # range falls through to \u00xx below.
    ESCAPES = {
      "\"" => '\\"', "\\" => "\\\\", "\b" => "\\b", "\f" => "\\f",
      "\n" => "\\n", "\r" => "\\r", "\t" => "\\t"
    }.freeze

    # Mirrors json.encoder.py_encode_basestring_ascii (ensure_ascii=True): only
    # 0x20..0x7e survive literally; 0x7f and every non-ASCII codepoint is
    # escaped, astral characters as a UTF-16 surrogate pair.
    def encode_string(str)
      out = +'"'
      str.each_char do |ch|
        if (esc = ESCAPES[ch])
          out << esc
          next
        end
        cp = ch.ord
        if cp < 0x20
          out << format("\\u%04x", cp)
        elsif cp < 0x7f
          out << ch
        elsif cp > 0xffff
          value = cp - 0x10000
          out << format("\\u%04x\\u%04x", 0xd800 + (value >> 10), 0xdc00 + (value & 0x3ff))
        else
          out << format("\\u%04x", cp)
        end
      end
      out << '"'
      out
    end

    # json.dumps renders floats via float.__repr__ (shortest round-tripping
    # form). Ruby's Float#to_s is also shortest-round-trip and agrees with
    # CPython across the whole non-exponent range the manifest uses (size_kb is
    # always a small positive value like 0.1 or 148.1). The two disagree only on
    # exponent formatting (Ruby "1.0e+20" vs CPython "1e+20") and the special
    # values, which manifest data never contains — guarded here for honesty.
    def float_repr(value)
      return "NaN" if value.nan?
      return value.positive? ? "Infinity" : "-Infinity" if value.infinite?

      value.to_s
    end
  end

  # Reader/writer for the SVG example library manifest (tools/svg/library/
  # MANIFEST.json). One entry per example — first-party samples and vetted
  # external art alike — each carrying provenance, license and lint status so a
  # tag search covers the whole library from one place (see library/README.md).
  #
  # Writes go through PyJson so a Ruby-authored manifest is byte-identical to
  # what freesvg.py's `_write_json` produces; reads use stdlib JSON, which is a
  # faithful stand-in for Python's json.load (both preserve key insertion order
  # and the Integer/Float distinction that the manifest's size_kb relies on).
  class Library
    attr_reader :path

    def initialize(path)
      @path = path
    end

    # Parsed manifest, or nil when the file is missing or corrupt — mirroring
    # freesvg.py's `_read_json`, which swallows exactly OSError/ValueError and
    # returns None so a damaged manifest degrades to "empty" rather than
    # crashing the caller.
    def read
      JSON.parse(File.read(@path))
    rescue JSON::ParserError, SystemCallError, IOError
      nil
    end

    # The `_read_json(...) or {"entries": []}` default freesvg.py falls back to.
    def load
      read || { "entries" => [] }
    end

    def entries
      Array(load["entries"])
    end

    def has_file?(file)
      entries.any? { |entry| entry["file"] == file }
    end

    def find(file)
      entries.find { |entry| entry["file"] == file }
    end

    # Tag search is the library's primary lookup (README: "Search MANIFEST.json
    # by tags"). Case-insensitive, since manifest tags are stored lowercased.
    def by_tag(tag)
      needle = tag.to_s.downcase
      entries.select do |entry|
        Array(entry["tags"]).any? { |t| t.to_s.downcase == needle }
      end
    end

    # Append one entry, re-sort by file, and rewrite byte-identically. Matches
    # freesvg.py's promote tail: it reads the manifest fresh, appends, sorts by
    # the "file" key, and writes with indent=2 + trailing newline. Returns the
    # entry. Callers guard against duplicates via #has_file? first.
    def add_entry(entry)
      manifest = load
      manifest["entries"] ||= []
      manifest["entries"] << entry
      manifest["entries"] = manifest["entries"].sort_by { |e| e["file"] }
      write(manifest)
      entry
    end

    def write(manifest)
      FileUtils.mkdir_p(File.dirname(@path))
      # _write_json: json.dump(..., indent=2) then a single trailing newline.
      File.write(@path, PyJson.dump(manifest) + "\n")
    end
  end
end
