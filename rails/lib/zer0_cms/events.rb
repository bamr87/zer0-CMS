# frozen_string_literal: true

require "json"
require "securerandom"
require "time"

module Zer0Cms
  # The experience plane's half of the event contract between the two planes
  # (schemas/events/, ADR 0001). Stdlib only, like the rest of rails/lib.
  #
  # `Events.envelope` builds a CloudEvents 1.0 envelope the way the content
  # plane does (content/outbox/models.py), with `source` "zer0-cms/app";
  # `Events.interaction` is the one event this plane publishes today,
  # `app.user.interaction`. `Events.validate` checks an envelope — one this
  # plane built or one it received — against the shared JSON Schemas with
  # `Events::Schema`, a validator for exactly the keywords those schemas use;
  # `Events::Schema::KEYWORDS` is that list, and a test fails when a schema
  # starts using a keyword it does not know.
  #
  # The outbox that will carry these onto Redis Streams, and the consumers of
  # `content.page.published`, are milestone M16; this module is the contract
  # they will be written against, tested from this side now.
  module Events
    SOURCE = "zer0-cms/app"
    SCHEMA_BASE = "https://github.com/bamr87/zer0-CMS/blob/main/schemas/events/"
    TRACEPARENT = /\A00-(\h{32})-\h{16}-\h{2}\z/

    def self.schema_dir
      ENV.fetch("ZER0_EVENTS_SCHEMA_DIR") { File.expand_path("../../../schemas/events", __dir__) }
    end

    def self.envelope(type:, data:, subject: nil, trace_id: nil, version: 1, id: SecureRandom.uuid, time: Time.now.utc)
      env = {
        "specversion" => "1.0",
        "id" => id,
        "source" => SOURCE,
        "type" => type,
        "time" => time.utc.iso8601,
        "datacontenttype" => "application/json",
        "dataschema" => "#{SCHEMA_BASE}#{type}.v#{version}.json",
        "data" => data
      }
      env["subject"] = subject if subject
      env["traceparent"] = "00-#{trace_id}-#{"0" * 15}1-01" if trace_id
      env
    end

    # A reader did something with a page. `anon_id` is minted and rotated by
    # this plane; the content plane aggregates and never stores it.
    def self.interaction(anon_id:, page_id:, kind: "view", session_page_ids: [], trace_id: nil)
      data = { "anon_id" => anon_id, "page_id" => page_id, "kind" => kind }
      data["session_page_ids"] = session_page_ids unless session_page_ids.empty?
      envelope(type: "app.user.interaction", data: data, subject: "page:#{page_id}", trace_id: trace_id)
    end

    def self.trace_id(envelope)
      envelope["traceparent"].to_s[TRACEPARENT, 1]
    end

    # Errors for `envelope` and its data, as "path: message" strings.
    def self.validate(envelope, dir: schema_dir)
      errors = Schema.load(File.join(dir, "cloudevent.v1.json")).errors(envelope).map { |e| "envelope #{e}" }
      return errors unless errors.empty?

      name = File.basename(envelope["dataschema"].to_s)
      path = File.join(dir, name)
      return ["dataschema #{name} is not in #{dir}"] unless File.file?(path)

      Schema.load(path).errors(envelope["data"]).map { |e| "#{name.sub(/\.json\z/, "")} #{e}" }
    end

    # The JSON Schema keywords the shared event schemas use, and nothing more.
    class Schema
      KEYWORDS = %w[$schema $id title description type required properties additionalProperties enum const
                    pattern format minimum minLength maxLength items maxItems].freeze
      DATE_TIME = /\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})\z/

      def self.load(path)
        new(JSON.parse(File.read(path, encoding: "UTF-8")))
      end

      # Every keyword used anywhere in `schema`.
      def self.keywords(schema)
        return [] unless schema.is_a?(Hash)

        schema.flat_map do |key, value|
          nested = case key
                   when "properties" then value.values.flat_map { |v| keywords(v) }
                   when "items" then keywords(value)
                   else []
                   end
          [key, *nested]
        end.uniq
      end

      def initialize(schema)
        @schema = schema
      end

      def errors(value, schema = @schema, path = "(root)")
        out = []
        types = Array(schema["type"])
        unless types.empty? || types.any? { |t| type?(value, t) }
          return ["#{path}: #{value.inspect} is not #{types.join(" or ")}"]
        end

        out << "#{path}: must be #{schema["const"].inspect}" if schema.key?("const") && value != schema["const"]
        out << "#{path}: #{value.inspect} is not one of #{schema["enum"].inspect}" if schema.key?("enum") && !schema["enum"].include?(value)
        if value.is_a?(String)
          out << "#{path}: does not match #{schema["pattern"]}" if schema["pattern"] && !Regexp.new(schema["pattern"]).match?(value)
          out << "#{path}: is not a date-time" if schema["format"] == "date-time" && !DATE_TIME.match?(value)
          out << "#{path}: is shorter than #{schema["minLength"]}" if schema["minLength"] && value.length < schema["minLength"]
          out << "#{path}: is longer than #{schema["maxLength"]}" if schema["maxLength"] && value.length > schema["maxLength"]
        end
        out << "#{path}: is less than #{schema["minimum"]}" if value.is_a?(Numeric) && schema["minimum"] && value < schema["minimum"]
        if value.is_a?(Hash)
          Array(schema["required"]).each { |key| out << "#{path}: #{key} is required" unless value.key?(key) }
          props = schema["properties"] || {}
          value.each do |key, item|
            if props.key?(key)
              out.concat(errors(item, props[key], "#{path == "(root)" ? "" : "#{path}/"}#{key}"))
            elsif schema["additionalProperties"] == false
              out << "#{path}: #{key} is not allowed"
            end
          end
        end
        if value.is_a?(Array)
          out << "#{path}: has more than #{schema["maxItems"]} items" if schema["maxItems"] && value.length > schema["maxItems"]
          value.each_with_index { |item, i| out.concat(errors(item, schema["items"], "#{path}/#{i}")) } if schema["items"]
        end
        out
      end

      private

      def type?(value, type)
        case type
        when "object" then value.is_a?(Hash)
        when "array" then value.is_a?(Array)
        when "string" then value.is_a?(String)
        when "integer" then value.is_a?(Integer)
        when "number" then value.is_a?(Numeric)
        when "boolean" then [true, false].include?(value)
        when "null" then value.nil?
        else false
        end
      end
    end
  end
end
