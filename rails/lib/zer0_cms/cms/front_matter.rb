# frozen_string_literal: true

require "date"
require "yaml"

module Zer0Cms
  module Cms
    # Parse and surgically update YAML front matter. Untouched lines stay
    # byte-identical so comments and hand-formatting survive — same contract
    # as the VS Code extension's updateFrontMatterKeys.
    module FrontMatter
      module_function

      Document = Struct.new(:data, :body, :raw, keyword_init: true)

      def parse(text)
        text = text.to_s
        return Document.new(data: {}, body: text, raw: text) unless text.start_with?("---")

        closer = text.index(/\n---[ \t]*\n/, 3)
        closer ||= text.index(/\n---[ \t]*\z/, 3)
        return Document.new(data: {}, body: text, raw: text) unless closer

        yaml_src = text[4...closer]
        body = text[(closer + 1)..] || ""
        body = body.sub(/\A---[ \t]*\n?/, "")
        data = YAML.safe_load(yaml_src, permitted_classes: [Date, Time], aliases: true)
        data = {} unless data.is_a?(Hash)
        Document.new(data: data, body: body, raw: text)
      rescue Psych::SyntaxError
        Document.new(data: {}, body: text, raw: text)
      end

      def update_keys(text, changes)
        changes = stringify_keys(changes).reject { |_, v| v.nil? }
        return text if changes.empty?

        doc = parse(text)
        unless text.start_with?("---")
          block = ["---", *changes.map { |k, v| "#{k}: #{yaml_value(v)}" }, "---", text]
          return block.join("\n")
        end

        closer = text.index(/\n---[ \t]*\n/, 3)
        closer ||= text.index(/\n---[ \t]*\z/, 3)
        return text unless closer

        head = text[0..closer]
        rest = text[(closer + 1)..] || ""
        lines = head.lines
        changes.each do |key, value|
          pattern = /\A#{Regexp.escape(key)}\s*:/
          idx = lines.index { |line| line.match?(pattern) }
          rendered = "#{key}: #{yaml_value(value)}\n"
          if idx
            lines[idx] = rendered
          else
            insert_at = lines.rindex { |line| line.start_with?("---") } || (lines.length - 1)
            lines.insert(insert_at, rendered)
          end
        end
        lines.join + rest.sub(/\A---[ \t]*\n?/, "")
      end

      def stringify_keys(hash)
        hash.to_h.transform_keys(&:to_s)
      end

      def yaml_value(value)
        case value
        when Array
          "[#{value.map { |item| yaml_value(item) }.join(", ")}]"
        when true, false
          value ? "true" : "false"
        else
          str = value.to_s
          str.match?(/[:#\n]|^\s|\s$/) ? str.inspect : str
        end
      end
    end
  end
end
