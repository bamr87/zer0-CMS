# frozen_string_literal: true

require "date"
require "psych"
require "time"
require "yaml"

module Zer0Cms
  module Cms
    # Reading and surgically editing a Jekyll front-matter block, in stdlib Ruby.
    #
    # This is the Ruby port of the VS Code extension's line surgery
    # (src/core/content/serialize.ts `updateFrontMatterKeys`) and keeps its
    # contract:
    #
    # * Only the lines a change touches are rewritten. Comments, blank lines,
    #   key order, quoting and every other key stay byte-identical.
    # * A key owns a *range* of lines — its own line plus every line its value
    #   spans (block sequences, nested mappings, block scalars, wrapped quoted
    #   scalars). Blank lines and comments after a value stay outside it.
    # * A new key goes in before the closing fence, after the last line with
    #   content. A `nil` value deletes the key — every duplicate of it, so an
    #   earlier duplicate is not resurrected.
    # * Scalars are quoted by YAML's rules, not Ruby's (`needsQuotes` /
    #   `quoteScalar`), and a list is written in the style the file already
    #   uses for that key (flow `[a, b]` or a block sequence).
    # * Dates stay strings: a value equal to what the file already holds —
    #   including the raw text of a date or a number — is not a change.
    #
    # Where the extension hand-rolls a YAML subset, this port locates key
    # ranges with Psych's own node marks — the parser Jekyll reads the block
    # with — so the two can never disagree about where a value ends. Every
    # edit is verified by re-reading the block: if the result does not load
    # back to exactly the intended data, `update_keys` raises `EditError`
    # rather than write a file Jekyll would read differently.
    module FrontMatter
      # Jekyll 4.4's own detection (Jekyll::Document::YAML_FRONT_MATTER_REGEXP):
      # the opening `---`, the block, and a closing `---` or `...` line.
      BLOCK = /\A(---\s*\n.*?\n?)^((---|\.\.\.)\s*$\n?)/m
      BOM = "\uFEFF"
      PERMITTED = [Date, Time, Symbol].freeze

      # `nil` in a change set deletes a key; `NULL` writes an explicit null.
      NULL = Object.new.tap { |o| o.define_singleton_method(:inspect) { "FrontMatter::NULL" } }.freeze

      # An edit that cannot be placed without guessing: an unclosed fence, a
      # block that is not a YAML mapping or does not parse, or an emitted value
      # that would not read back as itself.
      class EditError < StandardError; end

      # The block parsed, but to something other than a mapping (Jekyll raises
      # InvalidYAMLFrontMatterError for the same file).
      class NotAMapping < Psych::Exception; end

      # The parsed file. `raw` is the YAML between the fences (nil without a
      # block); `fence_style` is the closing fence token (`---` or `...`);
      # `newline` is the opening fence's line ending; `raw_values` maps each
      # top-level key holding a scalar to its text as written, before YAML
      # typed it — so a form shows `2025-11-29T16:46:02.000Z`, not a Time.
      class Document
        attr_reader :data, :body, :raw, :fence_style, :newline, :bom, :errors

        def initialize(data:, body:, raw:, fence_style:, newline:, bom:, errors:, yaml: nil)
          @data = data
          @body = body
          @raw = raw
          @fence_style = fence_style
          @newline = newline
          @bom = bom
          @errors = errors
          @yaml = yaml
        end

        def front_matter?
          !fence_style.nil?
        end

        def raw_values
          @raw_values ||= begin
            values = {}
            root = @yaml && errors.empty? ? FrontMatter.parse_tree(@yaml) : nil
            if root.is_a?(Psych::Nodes::Mapping)
              root.children.each_slice(2) do |key, value|
                next unless key.is_a?(Psych::Nodes::Scalar) && value.is_a?(Psych::Nodes::Scalar)

                values[key.value] = value.value
              end
            end
            values
          rescue Psych::Exception
            {}
          end
        end
      end

      module_function

      # Parse `text`. With `strict: false` (the default) a block that does not
      # load leaves `data` empty and the reason in `errors`; with `strict: true`
      # the Psych exception (SyntaxError, DisallowedClass, BadAlias, or
      # NotAMapping) is raised instead.
      def parse(text, strict: false)
        text = text.to_s
        bom = text.start_with?(BOM)
        src = bom ? text.delete_prefix(BOM) : text
        match = BLOCK.match(src)
        unless match
          newline = src.include?("\r\n") ? "\r\n" : "\n"
          return Document.new(data: {}, body: src, raw: nil, fence_style: nil, newline: newline, bom: bom, errors: [])
        end

        head = match[1]
        opening_end = head.index("\n")
        newline = head[0, opening_end].end_with?("\r") ? "\r\n" : "\n"
        errors = []
        data = {}
        begin
          data = load_data(head)
        rescue Psych::Exception => e
          raise if strict

          errors << "#{e.class.name.split("::").last}: #{e.message.lines.first.to_s.strip}"
          data = {}
        end
        Document.new(
          data: data, body: match.post_match, raw: head[(opening_end + 1)..], fence_style: match[3],
          newline: newline, bom: bom, errors: errors, yaml: head
        )
      end

      # Load a YAML block the way Jekyll sees it: dates and times typed, a
      # `:symbol`-looking plain scalar kept as the string it is written as
      # (SafeYAML never builds a Symbol), an empty block as `{}`.
      def load_data(yaml)
        loaded = YAML.safe_load(yaml, permitted_classes: PERMITTED, aliases: true)
        loaded = {} if loaded.nil? || loaded == false
        raise NotAMapping, "front matter is a #{loaded.class}, not a mapping" unless loaded.is_a?(Hash)

        desymbolize(loaded)
      end

      def parse_tree(yaml)
        tree = Psych.parse(yaml)
        tree ? tree.root : nil
      end

      def desymbolize(value)
        case value
        when Hash then value.each_with_object({}) { |(k, v), out| out[desymbolize(k)] = desymbolize(v) }
        when Array then value.map { |item| desymbolize(item) }
        when Symbol then ":#{value}"
        else value
        end
      end

      # Rewrite only the keys in `changes` (a Hash of key => value; `nil`
      # deletes, `NULL` writes a null). Returns the new text; an empty or no-op change set returns
      # `text` itself. A file without front matter gains a block. Raises
      # EditError instead of guessing.
      def update_keys(text, changes)
        text = text.to_s
        changes = changes.to_h.each_with_object({}) { |(k, v), out| out[k.to_s] = normalize(v) }
        return text if changes.empty?

        bom = text.start_with?(BOM) ? BOM : ""
        src = text.delete_prefix(BOM)
        match = BLOCK.match(src)
        return bom + new_block(src, changes) unless match

        head = match[1]
        opening_end = head.index("\n") + 1
        eol = head[0, opening_end].end_with?("\r\n") ? "\r\n" : "\n"
        lines = head[opening_end..].scan(/[^\n]*\n|[^\n]+\z/)
        edited = Surgery.new(lines, eol).apply(changes)
        return text if edited.nil?

        bom + head[0, opening_end] + edited.join + match[2] + match.post_match
      end

      # Front matter for a file that has none: keys in the order given, with
      # the text's own line ending.
      def new_block(src, changes)
        raise EditError, "the file opens with an unclosed `---` fence" if src.match?(/\A---[ \t]*\r?\n/)

        sets = changes.reject { |_, v| v.nil? }
        return src if sets.empty?

        eol = src.include?("\r\n") ? "\r\n" : "\n"
        edited = Surgery.new([], eol).apply(sets)
        "---#{eol}#{edited.join}---#{eol}#{src}"
      end

      # A whole block for `data` (fences included), e.g. for a new file.
      def dump(data, eol = "\n")
        new_block("", data.to_h.transform_keys(&:to_s).transform_values { |v| normalize(v) })
          .then { |out| eol == "\n" ? out : out.gsub("\n", eol) }
      end

      def normalize(value)
        case value
        when Symbol then value.to_s
        when DateTime then value.to_time
        when Hash then value.each_with_object({}) { |(k, v), out| out[k.is_a?(Symbol) ? k.to_s : k] = normalize(v) }
        when Array then value.map { |item| normalize(item) }
        else value
        end
      end

      # Semantic equality that does not let `1 == 1.0` or a Date equal a Time.
      def same_value?(left, right)
        case left
        when Hash
          right.is_a?(Hash) && left.size == right.size &&
            left.all? { |k, v| right.key?(k) && same_value?(v, right[k]) }
        when Array
          right.is_a?(Array) && left.size == right.size &&
            left.each_index.all? { |i| same_value?(left[i], right[i]) }
        when Float
          right.is_a?(Float) && (left == right || (left.nan? && right.nan?))
        when Integer then right.is_a?(Integer) && left == right
        when Time then right.is_a?(Time) && left == right
        when Date then right.instance_of?(left.class) && left == right
        else left.instance_of?(right.class) && left == right
        end
      end

      # ---- scalar rules (serialize.ts needsStructuralQuotes / needsQuotes) ----

      LEADING_INDICATOR = /\A[,\[\]{}#&*!|>'"%@`]/
      INDICATOR_PAIR = /\A[-?:](?:\s|\z)/
      UNPRINTABLE = /[\u0000-\u0008\u000a-\u001f\u007f\u0085\u2028\u2029\ufeff]/
      ESCAPES = {
        "\\" => "\\\\", '"' => '\\"', "\n" => "\\n", "\r" => "\\r", "\t" => "\\t"
      }.freeze

      # The text would not survive as a plain scalar at all.
      def needs_structural_quotes?(value)
        value.empty? || value != value.strip || LEADING_INDICATOR.match?(value) ||
          INDICATOR_PAIR.match?(value) || value.match?(/:(?:\s|\z)/) || value.match?(/\s#/) ||
          value.match?(/[\u0000-\u001f\u007f\u0085\u2028\u2029\ufeff]/)
      end

      # Plain is safe when the text is structurally plain AND YAML would type
      # it back as this very string (not true, 3, 2026-01-01, null, …).
      def plain_ok?(value, flow: false)
        return false if needs_structural_quotes?(value)
        return false if flow && value.match?(/[,\[\]{}]/)

        resolved = scalar_scanner.tokenize(value)
        resolved.is_a?(String) && resolved == value
      rescue StandardError
        false
      end

      def scalar_scanner
        @scalar_scanner ||= Psych::ScalarScanner.new(Psych::ClassLoader.new)
      end

      # A double-quoted YAML scalar. Backslash first, then quotes — the other
      # order double-escapes. No Ruby escapes (`\#{`) ever reach the file.
      def double_quote(value)
        escaped = value.gsub(/[\\"\n\r\t]|#{UNPRINTABLE}/o) do |char|
          ESCAPES[char] || format("\\u%04X", char.ord)
        end
        %("#{escaped}")
      end

      def single_quote(value)
        return nil if value.match?(UNPRINTABLE) || value.include?("\t")

        "'#{value.gsub("'", "''")}'"
      end

      # ---- the line surgery ---------------------------------------------------

      # One pass of edits over a block's lines (each line with its own ending).
      class Surgery
        Pair = Struct.new(:key, :key_node, :value, :first, :last, keyword_init: true)

        def initialize(lines, eol)
          @lines = lines.dup
          @eol = eol
        end

        # Returns the edited lines, or nil when nothing changed.
        def apply(changes)
          data, = analyze
          expected = data.dup
          changed = false
          changes.each do |key, value|
            data, pairs, root = analyze
            matches = pairs.select { |pair| pair.key == key }
            delete = value.nil?
            value = nil if value.equal?(NULL)
            if delete
              next if matches.empty?

              guard_line_breaks!
              matches.reverse_each { |pair| @lines.slice!(pair.first..pair.last) }
              expected.delete(key)
            elsif (pair = matches.last)
              next if unchanged?(pair.value, data[key], value)

              guard_line_breaks!
              replacement, value_read = emit_existing(pair, value, root, pairs)
              @lines[pair.first..pair.last] = replacement.map { |line| line + @eol }
              expected[key] = value_read
            else
              guard_line_breaks!
              lines, value_read = emit_new(key, value, root, pairs)
              @lines.insert(insertion_point(pairs), *lines.map { |line| line + @eol })
              expected[key] = value_read
            end
            changed = true
          end
          return nil unless changed

          verify!(expected)
          @lines
        end

        private

        def yaml
          @lines.join
        end

        def analyze
          text = yaml
          data = FrontMatter.load_data(text)
          root = FrontMatter.parse_tree(text)
          return [data, [], nil] if root.nil?
          unless root.is_a?(Psych::Nodes::Mapping) && root.style != Psych::Nodes::Mapping::FLOW
            raise EditError, "front matter is not a block mapping"
          end

          pairs = root.children.each_slice(2).filter_map do |key, value|
            next unless key.is_a?(Psych::Nodes::Scalar)

            Pair.new(key: key.value, key_node: key, value: value, first: key.start_line, last: last_line(key, value))
          end
          [data, pairs, root]
        rescue Psych::Exception => e
          raise EditError, "front matter does not parse: #{e.message.lines.first.to_s.strip}"
        end

        # Psych marks a block value's end at the start of the line after it;
        # the range then gives back trailing blank lines and comments that sit
        # no deeper than the key, so they stay between keys.
        def last_line(key, value)
          last = value.end_line
          last -= 1 if value.end_column.zero? && last > key.start_line
          last = [last, @lines.size - 1].min
          while last > key.start_line
            content = @lines[last].chomp.chomp("\r")
            stripped = content.lstrip
            break unless stripped.empty? || (stripped.start_with?("#") && content.size - stripped.size <= key.start_column)

            last -= 1
          end
          last
        end

        # Line numbers come from Psych, which also breaks lines at a bare CR,
        # NEL, LS and PS; our lines split at LF only. Refuse rather than
        # rewrite the wrong line.
        def guard_line_breaks!
          return unless yaml.match?(/\r(?!\n)|[\u0085\u2028\u2029]/)

          raise EditError, "front matter contains a bare CR or a Unicode line separator"
        end

        def insertion_point(pairs)
          last_content = @lines.rindex { |line| !line.strip.empty? }
          at = last_content ? last_content + 1 : 0
          tail = pairs.last
          if tail&.value.is_a?(Psych::Nodes::Scalar) && keep_chomped?(tail)
            at = @lines.size
          end
          at
        end

        def keep_chomped?(pair)
          header = @lines[pair.key_node.start_line].to_s
          header.match?(/:\s*[|>][0-9]*\+/)
        end

        def unchanged?(node, current, value)
          return true if FrontMatter.same_value?(current, value)

          node.is_a?(Psych::Nodes::Scalar) && value.is_a?(String) && node.value == value && !current.is_a?(String)
        end

        # ---- emission ---------------------------------------------------------

        def emit_existing(pair, value, root, pairs)
          indent = pair.key_node.start_column
          token = key_token(pair.key_node)
          hints = hints_for(pair.value, root, pairs, indent)
          if typed_plain?(pair.value, value)
            read = FrontMatter.scalar_scanner.tokenize(value)
            return [["#{" " * indent}#{token}: #{value}"], read]
          end
          emit_verified(token, value, indent, hints)
        end

        def emit_new(key, value, root, pairs)
          indent = pairs.first ? pairs.first.key_node.start_column : 0
          token = FrontMatter.plain_ok?(key) ? key : FrontMatter.double_quote(key)
          emit_verified(token, value, indent, hints_for(nil, root, pairs, indent))
        end

        # A plain scalar that YAML typed (a date, a number, a boolean) given
        # back as text of the same type keeps its plain spelling: the file said
        # `date: 2026-01-01`, the form sends "2026-02-01", the file keeps a date.
        def typed_plain?(node, value)
          return false unless node.is_a?(Psych::Nodes::Scalar) && node.plain && value.is_a?(String)
          return false if value.include?("\n") || FrontMatter.needs_structural_quotes?(value)

          current = FrontMatter.scalar_scanner.tokenize(node.value)
          read = FrontMatter.scalar_scanner.tokenize(value)
          family(current) && family(current) == family(read)
        rescue StandardError
          false
        end

        def family(value)
          case value
          when true, false then :boolean
          when Integer, Float then :number
          when Date, Time then :date
          end
        end

        def emit_verified(token, value, indent, hints)
          attempts = [hints]
          attempts << hints.merge(block_scalars: false) if value.is_a?(String) && value.include?("\n")
          attempts.each do |attempt|
            lines = Emitter.new(attempt).key_lines(token, value, indent)
            return [lines, value] if reads_back?(lines, indent, value)
          end
          raise EditError, "could not write #{token} so that it reads back unchanged"
        end

        def reads_back?(lines, indent, value)
          text = lines.map { |line| line[indent..] || "" }.join("\n") << "\n"
          loaded = FrontMatter.load_data(text)
          loaded.size == 1 && FrontMatter.same_value?(loaded.values.first, value)
        rescue Psych::Exception, EditError
          false
        end

        def key_token(node)
          case node.style
          when Psych::Nodes::Scalar::SINGLE_QUOTED then FrontMatter.single_quote(node.value) || FrontMatter.double_quote(node.value)
          when Psych::Nodes::Scalar::DOUBLE_QUOTED then FrontMatter.double_quote(node.value)
          else FrontMatter.plain_ok?(node.value) ? node.value : FrontMatter.double_quote(node.value)
          end
        end

        # How this file writes things: the key's own style first, then the
        # file's habit (the first list, the most common quote), then defaults.
        def hints_for(node, root, pairs, indent)
          hints = { quote: file_quote(root), list: :block, list_indent: 2, map_indent: 2, block_scalars: true }
          sample = pairs.map(&:value).find { |v| v.is_a?(Psych::Nodes::Sequence) }
          apply_sequence_hints(hints, sample, indent) if sample
          sample_map = pairs.map(&:value).find { |v| v.is_a?(Psych::Nodes::Mapping) && v.children.any? }
          hints[:map_indent] = sample_map.children.first.start_column - indent if sample_map
          case node
          when Psych::Nodes::Sequence then apply_sequence_hints(hints, node, indent, own: true)
          when Psych::Nodes::Mapping
            hints[:map_indent] = node.children.first.start_column - indent if node.children.any?
          when Psych::Nodes::Scalar
            hints[:quote] = :single if node.style == Psych::Nodes::Scalar::SINGLE_QUOTED
            hints[:quote] = :double if node.style == Psych::Nodes::Scalar::DOUBLE_QUOTED
            hints[:scalar] = quoted_style?(node) ? :quoted : :plain
          end
          hints[:map_indent] = 2 unless hints[:map_indent].positive?
          hints
        end

        def apply_sequence_hints(hints, node, indent, own: false)
          if node.style == Psych::Nodes::Sequence::FLOW
            hints[:list] = :flow
          else
            hints[:list] = :block
            first = node.children.first
            if first
              line = @lines[first.start_line].to_s
              hints[:list_indent] = [line[/\A */].size - indent, 0].max
            end
          end
          quoted = node.children.find { |c| c.is_a?(Psych::Nodes::Scalar) && quoted_style?(c) }
          if quoted && own
            hints[:item_quote] = quoted.style == Psych::Nodes::Scalar::SINGLE_QUOTED ? :single : :double
          end
        end

        def quoted_style?(node)
          [Psych::Nodes::Scalar::SINGLE_QUOTED, Psych::Nodes::Scalar::DOUBLE_QUOTED].include?(node.style)
        end

        def file_quote(root)
          counts = Hash.new(0)
          walk(root) do |node|
            next unless node.is_a?(Psych::Nodes::Scalar)

            counts[:single] += 1 if node.style == Psych::Nodes::Scalar::SINGLE_QUOTED
            counts[:double] += 1 if node.style == Psych::Nodes::Scalar::DOUBLE_QUOTED
          end
          counts[:single] > counts[:double] ? :single : :double
        end

        def walk(node, &block)
          return unless node

          yield node
          node.children&.each { |child| walk(child, &block) }
        end

        def verify!(expected)
          actual = FrontMatter.load_data(yaml)
          return if FrontMatter.same_value?(actual, expected)

          raise EditError, "the edited front matter would not read back as intended"
        rescue Psych::Exception => e
          raise EditError, "the edited front matter does not parse: #{e.message.lines.first.to_s.strip}"
        end
      end

      # Emits `key: value` and everything under it as lines (no line endings),
      # following serialize.ts `emitKeyLines`, with the file's hints.
      class Emitter
        def initialize(hints)
          @hints = hints
        end

        def key_lines(token, value, indent)
          label = "#{" " * indent}#{token}:"
          case value
          when nil then [label]
          when Array then list_lines(label, value, indent)
          when Hash then map_lines(label, value, indent)
          when String
            if value.include?("\n") && @hints[:block_scalars]
              head, body = literal(value, indent + 2)
              ["#{label} #{head}", *body]
            else
              ["#{label} #{string(value, quote: @hints[:quote], prefer_plain: @hints[:scalar] != :quoted)}"]
            end
          else ["#{label} #{scalar(value)}"]
          end
        end

        private

        def list_lines(label, items, indent)
          return ["#{label} []"] if items.empty?

          if @hints[:list] == :flow && items.all? { |item| flow_scalar?(item) }
            return ["#{label} [#{items.map { |item| flow_item(item) }.join(", ")}]"]
          end

          pad = indent + @hints[:list_indent]
          [label, *items.flat_map { |item| sequence_item(item, pad) }]
        end

        def map_lines(label, map, indent)
          return ["#{label} {}"] if map.empty?

          child = indent + @hints[:map_indent]
          [label, *map.flat_map { |k, v| nested_key_lines(child_key(k), v, child) }]
        end

        def sequence_item(item, pad)
          prefix = "#{" " * pad}- "
          case item
          when Hash
            return ["#{prefix}{}"] if item.empty?

            inner = item.flat_map { |k, v| nested_key_lines(child_key(k), v, pad + 2) }
            inner[0] = prefix + inner[0][(pad + 2)..]
            inner
          when Array
            return ["#{prefix}[]"] if item.empty?
            return ["#{prefix}[#{item.map { |i| flow_item(i) }.join(", ")}]"] if item.all? { |i| flow_scalar?(i) }

            inner = item.flat_map { |sub| sequence_item(sub, pad + 2) }
            inner[0] = prefix + inner[0].lstrip
            inner
          when String
            ["#{prefix}#{string(item, quote: @hints[:item_quote] || @hints[:quote], prefer_plain: true, multiline: true)}"]
          else ["#{prefix}#{scalar(item)}"]
          end
        end

        # Children of a list item or a nested map never use block scalars —
        # their indentation rules are where hand-written YAML goes wrong.
        def nested_key_lines(token, value, indent)
          Emitter.new(@hints.merge(block_scalars: false, scalar: nil)).key_lines(token, value, indent)
        end

        def child_key(key)
          text = key.to_s
          return text if key.is_a?(String) && FrontMatter.plain_ok?(text)
          return text if key.is_a?(Integer) && FrontMatter.scalar_scanner.tokenize(text) == key

          FrontMatter.double_quote(text)
        end

        def flow_scalar?(item)
          !(item.is_a?(Array) || item.is_a?(Hash)) && !(item.is_a?(String) && item.include?("\n"))
        end

        def flow_item(item)
          return scalar(item) unless item.is_a?(String)
          return item if FrontMatter.plain_ok?(item, flow: true)

          quoted(item, @hints[:item_quote] || @hints[:quote])
        end

        def string(value, quote:, prefer_plain:, multiline: false)
          return FrontMatter.double_quote(value) if multiline && value.include?("\n")
          return value if prefer_plain && FrontMatter.plain_ok?(value)

          quoted(value, quote)
        end

        def quoted(value, quote)
          (quote == :single && FrontMatter.single_quote(value)) || FrontMatter.double_quote(value)
        end

        def scalar(value)
          case value
          when nil then "null"
          when true then "true"
          when false then "false"
          when Integer then value.to_s
          when Float then float(value)
          when Time then time(value)
          when Date then value.iso8601
          when String then FrontMatter.plain_ok?(value) ? value : FrontMatter.double_quote(value)
          else raise EditError, "cannot write a #{value.class} as front matter"
          end
        end

        def float(value)
          return ".nan" if value.nan?
          return value.positive? ? ".inf" : "-.inf" if value.infinite?

          text = value.to_s
          text.match?(/\A-?\d+\.\d+(e[+-]\d+)?\z/i) ? text : format("%.17g", value)
        end

        def time(value)
          digits = value.nsec.zero? ? 0 : 9
          value.iso8601(digits).sub(/(\.\d*?)0+(?=Z|[+-]\d\d:\d\d\z)/, '\1').sub(/\.(?=Z|[+-])/, "")
        end

        # A literal block scalar: `|` keeps one trailing newline, `|-` none,
        # `|+` several; an explicit indentation indicator when the first line
        # starts with a space.
        def literal(value, indent)
          chomp = if value.end_with?("\n\n") then "+"
                  elsif value.end_with?("\n") then ""
                  else "-"
                  end
          parts = value.split("\n", -1)
          parts.pop if value.end_with?("\n")
          first = parts.find { |part| !part.empty? }.to_s
          indicator = first.start_with?(" ") ? "2" : ""
          body = parts.map { |part| part.empty? ? "" : (" " * indent) + part }
          ["|#{indicator}#{chomp}", body]
        end
      end
    end
  end
end
