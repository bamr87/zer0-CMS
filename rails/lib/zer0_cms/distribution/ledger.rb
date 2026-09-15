# frozen_string_literal: true

require "digest"
require "fileutils"
require "json"
require "securerandom"
require "tmpdir"

module Zer0Cms
  module Distribution
    # The idempotency ledger: one flat JSON file recording what has already
    # been published, keyed by what was published — an article's canonical URL,
    # or `draft:<path>` for a text update, which has no URL of its own.
    #
    # The key is the coordination. Whichever surface publishes a URL first
    # writes the key; every other surface looks it up and skips. That only
    # works if they agree on the file, so:
    #
    # * an entry carries the post URN under both `linkedin_urn` (the name the
    #   Python publisher wrote, and the one already in live ledgers) and `urn`
    #   (the name the VS Code extension reads) — a reader accepts either;
    # * the file is written as Python's `json.dump(indent=2, sort_keys=True)`
    #   plus a newline, byte-identical to what the other lanes write;
    # * a write is a read-modify-write under an exclusive lock, then an atomic
    #   rename, so two publishes on one machine cannot drop each other's entry.
    #
    # An attempt LinkedIn did not confirm is written down too, as an entry with
    # `state: unconfirmed` and no URN (`mark_unconfirmed`), because a post that
    # may exist must not be sent again by the next run.
    #
    # One rule differs from the extension on purpose. An unreadable ledger —
    # present but not JSON — is not read as "nothing published". For a
    # file-writing target that answer is safe; for LinkedIn it would re-post
    # every accepted draft. `readable?` is false, and the pipeline refuses.
    class Ledger
      META = "_meta"

      attr_reader :path

      def initialize(path)
        @path = path.to_s
      end

      def exist?
        File.file?(@path)
      end

      def readable?
        return true unless exist?

        JSON.parse(File.read(@path, encoding: "UTF-8")).is_a?(Hash)
      rescue JSON::ParserError, SystemCallError
        false
      end

      # The entries: every top-level value that is an object.
      def load
        load_raw.select { |_, value| value.is_a?(Hash) }
      end

      # The whole file as parsed, so a rewrite keeps keys of any shape it does
      # not own.
      def load_raw
        return {} unless exist?

        data = JSON.parse(File.read(@path, encoding: "UTF-8"))
        data.is_a?(Hash) ? data : {}
      rescue JSON::ParserError, SystemCallError
        {}
      end

      def entry(key)
        load[key.to_s]
      end

      def urn_for(key)
        self.class.urn_of(entry(key))
      end

      def published?(key)
        !urn_for(key).nil?
      end

      # The entry for an attempt LinkedIn did not confirm, or nil.
      def unconfirmed(key)
        entry = entry(key)
        entry if entry && self.class.urn_of(entry).nil? && entry["state"] == "unconfirmed"
      end

      # A create that ended in a 5xx, a dropped connection or a success with no
      # post id: the post may exist. The entry has no URN, so no reader counts
      # it as published, and the pipeline refuses the key until a person
      # records the post or forces past it. A recorded post is never demoted.
      def mark_unconfirmed(key, error:, kind:, author: nil, source_file: nil, now: Time.now)
        entry = { "state" => "unconfirmed", "attempted_at" => now.utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "error" => error.to_s[0, 300], "target" => "linkedin", "type" => kind }
        entry["author"] = author if author
        entry["source_file"] = source_file if source_file
        mutate { |data| data[key.to_s] = entry unless self.class.urn_of(data[key.to_s]) }
        entry
      end

      def self.urn_of(entry)
        return nil unless entry.is_a?(Hash)

        [entry["linkedin_urn"], entry["urn"]].map(&:to_s).find { |urn| !urn.empty? }
      end

      # The published shares, and only those: `_`-prefixed metadata and rows
      # without a URN are skipped. The only correct way to enumerate the file.
      def shares
        load.filter_map do |key, entry|
          next if key.start_with?("_")

          urn = self.class.urn_of(entry)
          urn ? [key, entry.merge("urn" => urn)] : nil
        end
      end

      # Replace the entry for `key`. A re-publish is a new fact about the key,
      # so nothing from the old entry is merged in.
      def record(key, urn:, kind:, author: nil, source_file: nil, image_urn: nil, now: Time.now)
        raise ArgumentError, "ledger key is empty" if key.to_s.empty? || key.to_s.start_with?("_")

        entry = { "linkedin_urn" => urn, "urn" => urn, "posted_at" => now.utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "target" => "linkedin", "type" => kind }
        entry["author"] = author if author
        entry["source_file"] = source_file if source_file
        entry["image_urn"] = image_urn if image_urn
        mutate { |data| data[key.to_s] = entry }
        entry
      end

      def meta
        load.fetch(META, {})
      end

      def write_meta(patch)
        mutate { |data| data[META] = data.fetch(META, {}).merge(patch) }
      end

      def self.serialize(data)
        "#{PyJson.dump(data, indent: 2, sort_keys: true, ensure_ascii: true)}\n"
      end

      private

      def mutate
        FileUtils.mkdir_p(File.dirname(@path))
        File.open(lock_path, File::RDWR | File::CREAT, 0o600) do |lock|
          lock.flock(File::LOCK_EX)
          raise ConfigError, "#{@path} is not valid JSON — refusing to rewrite it" unless readable?

          data = load_raw
          yield data
          write_atomically(self.class.serialize(data))
        end
      end

      # The lock lives outside the repository so it never shows up in git status.
      def lock_path
        File.join(Dir.tmpdir, "zer0-cms-ledger-#{Digest::SHA256.hexdigest(File.expand_path(@path))[0, 16]}.lock")
      end

      def write_atomically(text)
        dir = File.dirname(@path)
        temp = File.join(dir, ".#{File.basename(@path)}.#{Process.pid}.#{SecureRandom.hex(4)}.tmp")
        mode = exist? ? File.stat(@path).mode & 0o777 : 0o644
        File.open(temp, File::WRONLY | File::CREAT | File::EXCL, mode) do |file|
          file.write(text)
          file.flush
          file.fsync
        end
        File.rename(temp, @path)
      ensure
        FileUtils.rm_f(temp) if temp && File.exist?(temp)
      end
    end
  end
end
