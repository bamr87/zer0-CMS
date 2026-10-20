# frozen_string_literal: true

require "rexml/document"
require_relative "sanitizer" # SVG_NS / SVG_WIDTH — the shared geometry contract

module Zer0ImageGenerator
  module Svg
    # <text> → <path> with a bundled font — a port of the "SVG text → paths"
    # section of preview_generator.py, which stays the oracle.
    #
    # Two layers, held to two different contracts (the sanitizer's precedent):
    #
    #   - the GEOMETRY — the TrueType reader, glyph_run_path, text_advance,
    #     baseline_shift, fit_headline and the _fmt2 number format — is pinned
    #     BYTE-FOR-BYTE: the same run of text yields the same path data in both
    #     languages. Every float is computed in the oracle's order; numbers go
    #     through fmt2 (floor(x*100+0.5) on IEEE doubles), never Float#round;
    #   - the DOCUMENT walk (REXML here, ElementTree there) is pinned on what it
    #     produces — the same `d` strings, labels and counts in document order —
    #     not on serialized bytes, which the two XML libraries format
    #     differently.
    #
    # test/ruby/test_text_to_paths.rb runs both against text_to_paths_oracle.py.
    module TextToPaths
      FONTS_DIR = File.expand_path("../fonts", __dir__)

      # family key → [file, CSS family names that select it]
      BUNDLED_FONTS = {
        "press-start-2p" => ["PressStart2P-Regular.ttf", ["press start 2p", "press start", "pressstart2p"]],
        "inter" => ["Inter-Regular.ttf", ["inter"]],
        "inter-bold" => ["Inter-Bold.ttf", []],
      }.freeze
      DEFAULT_FONT_FAMILY = "inter"
      CARD_FONTS = { "retro-pixel" => "press-start-2p" }.freeze

      DEFAULT_TEXT_SIZE = 16.0
      TEXT_FIT_FRACTION = 0.94

      TEXT_LAYOUT_PROPS = %w[
        font font-family font-size font-weight font-style font-variant
        font-stretch text-anchor letter-spacing word-spacing
        dominant-baseline alignment-baseline baseline-shift writing-mode
        text-rendering white-space text-decoration
        x y dx dy rotate textLength lengthAdjust xml:space
      ].freeze

      CSS_RULE = /([^{}]+)\{([^{}]*)\}/.freeze
      CSS_SELECTOR = /\A(text|tspan)?(?:\.([A-Za-z_][\w-]*))?\z/.freeze
      NUM = /-?\d*\.?\d+(?:[eE][-+]?\d+)?/.freeze
      LENGTH = /\A(-?\d*\.?\d+(?:e[-+]?\d+)?)\s*(px|pt|em|rem|%)?\z/.freeze

      # Just enough of a TrueType font to draw Latin headlines. Port of the
      # oracle's TrueTypeFont, table for table.
      class Font
        attr_reader :path, :units_per_em, :ascender, :descender, :x_height, :cmap, :num_glyphs

        def initialize(path)
          @path = path
          @data = File.binread(path)
          @tables = {}
          u16(4).times do |i|
            rec = 12 + 16 * i
            @tables[@data[rec, 4]] = [u32(rec + 8), u32(rec + 12)]
          end
          %w[head hhea hmtx maxp cmap loca glyf].each do |required|
            raise ArgumentError, "#{File.basename(path)}: missing #{required} table" unless @tables.key?(required)
          end
          head = @tables["head"][0]
          @units_per_em = u16(head + 18)
          @long_loca = s16(head + 50) == 1
          hhea = @tables["hhea"][0]
          @ascender = s16(hhea + 4)
          @descender = s16(hhea + 6)
          @num_hmetrics = u16(hhea + 34)
          @num_glyphs = u16(@tables["maxp"][0] + 4)
          @x_height = @units_per_em / 2 # Python `//`: both operands non-negative
          if @tables.key?("OS/2")
            os2, os2_len = @tables["OS/2"]
            if u16(os2) >= 2 && os2_len >= 88
              xh = s16(os2 + 86)
              @x_height = xh unless xh.zero?
            end
          end
          @cmap = read_cmap
          @glyph_cache = {}
        end

        def glyph_id(char)
          @cmap.fetch(char.ord, 0)
        end

        def advance(gid)
          hmtx = @tables["hmtx"][0]
          index = gid < @num_hmetrics ? gid : @num_hmetrics - 1
          u16(hmtx + 4 * index)
        end

        # Contours as arrays of [x, y, on_curve] in font units (y up).
        def contours(gid, depth = 0)
          return @glyph_cache[gid] if @glyph_cache.key?(gid)
          return [] if gid >= @num_glyphs || depth > 8

          off, length = glyph_range(gid)
          result = if length.zero?
                     []
                   elsif s16(off) >= 0
                     simple_glyph(off)
                   else
                     composite_glyph(off, depth)
                   end
          @glyph_cache[gid] = result
        end

        private

        def u8(off) = @data.getbyte(off)
        def u16(off) = (@data.getbyte(off) << 8) | @data.getbyte(off + 1)
        def u32(off) = (u16(off) << 16) | u16(off + 2)

        def s16(off)
          v = u16(off)
          v >= 0x8000 ? v - 0x10000 : v
        end

        def read_cmap
          base = @tables["cmap"][0]
          chosen = nil
          u16(base + 2).times do |i|
            rec = base + 4 + 8 * i
            platform = u16(rec)
            encoding = u16(rec + 2)
            sub = base + u32(rec + 4)
            next unless u16(sub) == 4

            chosen = sub if [platform, encoding] == [3, 1] || (platform.zero? && chosen.nil?)
          end
          raise ArgumentError, "#{File.basename(@path)}: no cmap format 4 subtable" if chosen.nil?

          seg_x2 = u16(chosen + 6)
          ends = chosen + 14
          starts = ends + seg_x2 + 2
          deltas = starts + seg_x2
          ranges = deltas + seg_x2
          mapping = {}
          (seg_x2 / 2).times do |seg|
            last = u16(ends + 2 * seg)
            start = u16(starts + 2 * seg)
            delta = u16(deltas + 2 * seg)
            range_off = u16(ranges + 2 * seg)
            next if start == 0xFFFF

            (start..last).each do |cp|
              if range_off.zero?
                gid = (cp + delta) & 0xFFFF
              else
                gid = u16(ranges + 2 * seg + range_off + 2 * (cp - start))
                gid = (gid + delta) & 0xFFFF unless gid.zero?
              end
              mapping[cp] = gid unless gid.zero?
            end
          end
          mapping
        end

        def glyph_range(gid)
          loca = @tables["loca"][0]
          if @long_loca
            start = u32(loca + 4 * gid)
            last = u32(loca + 4 * gid + 4)
          else
            start = 2 * u16(loca + 2 * gid)
            last = 2 * u16(loca + 2 * gid + 2)
          end
          [@tables["glyf"][0] + start, last - start]
        end

        def simple_glyph(off)
          n_contours = s16(off)
          p = off + 10
          end_pts = Array.new(n_contours) { |i| u16(p + 2 * i) }
          p += 2 * n_contours
          n_points = end_pts.empty? ? 0 : end_pts.last + 1
          p += 2 + u16(p) # skip instructions
          flags = []
          while flags.length < n_points
            flag = u8(p)
            p += 1
            flags << flag
            next unless flag & 0x08 != 0

            repeat = u8(p)
            p += 1
            repeat.times { flags << flag }
          end
          flags = flags[0, n_points]

          read = lambda do |short_bit, same_bit|
            value = 0
            flags.map do |flag|
              if flag & short_bit != 0
                delta = u8(p)
                p += 1
                value += flag & same_bit != 0 ? delta : -delta
              elsif flag & same_bit == 0
                value += s16(p)
                p += 2
              end
              value
            end
          end
          xs = read.call(0x02, 0x10)
          ys = read.call(0x04, 0x20)
          start = 0
          end_pts.map do |last|
            contour = (start..last).map { |i| [xs[i].to_f, ys[i].to_f, flags[i] & 0x01 != 0] }
            start = last + 1
            contour
          end
        end

        def composite_glyph(off, depth)
          p = off + 10
          result = []
          loop do
            flags = u16(p)
            gid = u16(p + 2)
            p += 4
            if flags & 0x0001 != 0
              a1 = s16(p)
              a2 = s16(p + 2)
              p += 4
            else
              a1 = u8(p)
              a2 = u8(p + 1)
              a1 -= 256 if a1 >= 128
              a2 -= 256 if a2 >= 128
              p += 2
            end
            dx, dy = flags & 0x0002 != 0 ? [a1.to_f, a2.to_f] : [0.0, 0.0]
            xx = 1.0
            xy = 0.0
            yx = 0.0
            yy = 1.0
            if flags & 0x0008 != 0
              xx = yy = s16(p) / 16_384.0
              p += 2
            elsif flags & 0x0040 != 0
              xx = s16(p) / 16_384.0
              yy = s16(p + 2) / 16_384.0
              p += 4
            elsif flags & 0x0080 != 0
              xx = s16(p) / 16_384.0
              yx = s16(p + 2) / 16_384.0
              xy = s16(p + 4) / 16_384.0
              yy = s16(p + 6) / 16_384.0
              p += 8
            end
            contours(gid, depth + 1).each do |contour|
              result << contour.map { |(x, y, on)| [xx * x + xy * y + dx, yx * x + yy * y + dy, on] }
            end
            break if flags & 0x0020 == 0
          end
          result
        end
      end

      @font_cache = {}
      @font_lock = Mutex.new

      module_function

      # The bundled font for a family key, or nil when fonts/ is absent.
      def load_font(family)
        entry = BUNDLED_FONTS[family]
        return nil if entry.nil?

        path = File.join(FONTS_DIR, entry[0])
        TextToPaths.instance_variable_get(:@font_lock).synchronize do
          cache = TextToPaths.instance_variable_get(:@font_cache)
          unless cache.key?(family)
            return nil unless File.file?(path)

            cache[family] = Font.new(path)
          end
          cache[family]
        end
      end

      def fonts_available?
        BUNDLED_FONTS.values.all? { |(file, _names)| File.file?(File.join(FONTS_DIR, file)) }
      end

      def resolve_font_family(css_family, weight, default_family)
        chosen = BUNDLED_FONTS.key?(default_family) ? default_family : DEFAULT_FONT_FAMILY
        css_family.to_s.split(",").each do |name|
          # str.strip("'\"") — any run of either quote, both ends.
          wanted = name.strip.gsub(/\A['"]+|['"]+\z/, "").downcase
          hit = BUNDLED_FONTS.find { |_key, (_file, names)| names.include?(wanted) }
          next unless hit

          chosen = hit[0]
          break
        end
        chosen = "inter-bold" if chosen == "inter" && bold?(weight)
        chosen
      end

      def bold?(weight)
        w = weight.to_s.strip.downcase
        return true if %w[bold bolder].include?(w)

        w.match?(/\A\d+\z/) && w.to_i >= 600
      end

      # One closed TrueType contour → absolute SVG path commands.
      def contour_path(contour, ox, oy, scale)
        return "" if contour.empty?

        pt = ->(x, y) { "#{fmt2(ox + x * scale)} #{fmt2(oy - y * scale)}" }
        if contour[0][2]
          start = contour[0]
          seq = contour[1..] + [contour[0]]
        elsif contour[-1][2]
          start = contour[-1]
          seq = contour.dup
        else
          first = contour[0]
          last = contour[-1]
          start = [(first[0] + last[0]) / 2.0, (first[1] + last[1]) / 2.0, true]
          seq = contour + [start]
        end
        out = ["M#{pt.call(start[0], start[1])}"]
        ctrl = nil
        seq.each do |point|
          if point[2]
            if ctrl
              out << "Q#{pt.call(ctrl[0], ctrl[1])} #{pt.call(point[0], point[1])}"
              ctrl = nil
            else
              out << "L#{pt.call(point[0], point[1])}"
            end
          else
            if ctrl
              mid_x = (ctrl[0] + point[0]) / 2.0
              mid_y = (ctrl[1] + point[1]) / 2.0
              out << "Q#{pt.call(ctrl[0], ctrl[1])} #{pt.call(mid_x, mid_y)}"
            end
            ctrl = point
          end
        end
        out.pop if out.length > 1 && out[-1] == "L#{pt.call(start[0], start[1])}"
        out << "Z"
        out.join
      end

      # Port of _fmt2: two decimals, trailing zeros dropped, "-0" → "0".
      def fmt2(value)
        n = (value * 100 + 0.5).floor
        sign = n.negative? ? "-" : ""
        n = n.abs
        whole, frac = n.divmod(100)
        return(whole.zero? ? "0" : "#{sign}#{whole}") if frac.zero?

        "#{sign}#{whole}.#{format('%02d', frac).sub(/0+\z/, '')}"
      end

      def text_advance(font, text, size, letter_spacing = 0.0)
        return 0.0 if text.empty?

        scale = size.to_f / font.units_per_em
        width = text.each_char.inject(0) { |acc, ch| acc + font.advance(font.glyph_id(ch)) * scale }
        width + letter_spacing * (text.length - 1)
      end

      # [d, advance, missing] for `text` with its baseline-left at (x, y).
      def glyph_run_path(font, text, x, y, size, letter_spacing = 0.0)
        scale = size.to_f / font.units_per_em
        pen = x
        parts = []
        missing = 0
        chars = text.chars
        chars.each_with_index do |ch, i|
          gid = font.glyph_id(ch)
          if gid.zero? && !ch.match?(/[[:space:]]/)
            missing += 1
          else
            font.contours(gid).each { |contour| parts << contour_path(contour, pen, y, scale) }
          end
          pen += font.advance(gid) * scale
          pen += letter_spacing if i < chars.length - 1
        end
        [parts.join, pen - x, missing]
      end

      def baseline_shift(font, baseline, size)
        scale = size.to_f / font.units_per_em
        case baseline.to_s.strip.downcase
        when "middle" then font.x_height * scale / 2.0
        when "central" then (font.ascender + font.descender) * scale / 2.0
        when "hanging", "text-before-edge", "text-top" then font.ascender * scale
        when "text-after-edge", "text-bottom", "ideographic" then font.descender * scale
        else 0.0
        end
      end

      # Port of fit_headline: word-boundary line breaks at the largest size that
      # fits width (and block height); never splits a word.
      def fit_headline(font, text, max_width, max_lines, max_size, min_size,
                       max_height: 0.0, leading: 1.25, step: 2.0)
        words = text.to_s.strip.split(/\s+/).reject(&:empty?)
        return [[], max_size.to_f] if words.empty?

        size = max_size.to_f
        while size >= min_size - 1e-9
          lines = greedy_lines(font, words, size, max_width)
          fits_height = max_height <= 0 || lines.length * size * leading <= max_height
          if fits_height && lines.length <= max_lines &&
             lines.all? { |line| text_advance(font, line, size) <= max_width }
            return [lines, size]
          end

          size -= step
        end
        lines = greedy_lines(font, words, min_size.to_f, max_width)
        lines = lines[0, max_lines - 1] + [lines[(max_lines - 1)..].join(" ")] if lines.length > max_lines
        [lines, min_size.to_f]
      end

      def greedy_lines(font, words, size, max_width)
        lines = []
        current = ""
        words.each do |word|
          trial = current.empty? ? word : "#{current} #{word}"
          if current.empty? || text_advance(font, trial, size) <= max_width
            current = trial
          else
            lines << current
            current = word
          end
        end
        lines << current
        lines
      end

      # --- the document walk ---------------------------------------------------

      Result = Struct.new(:svg, :converted, :stripped, :fitted, :missing_glyphs, :notes,
                          keyword_init: true)

      def style_decls(style)
        decls = {}
        style.to_s.split(";").each do |part|
          next unless part.include?(":")

          key, value = part.split(":", 2)
          decls[key.strip.downcase] = value.strip unless key.strip.empty?
        end
        decls
      end

      def css_rules(root)
        rules = []
        each_element(root) do |el|
          next unless el.name == "style"

          text = el.texts.map(&:value).join
          next if text.empty?

          css = text.gsub(%r{/\*.*?\*/}m, "")
          css.scan(CSS_RULE) do |selectors, body|
            decls = style_decls(body)
            selectors.split(",").each do |selector|
              m = CSS_SELECTOR.match(selector.strip)
              rules << [m[1], m[2], decls] if m && (m[1] || m[2])
            end
          end
        end
        rules
      end

      # root.iter(): the element itself, then every descendant, depth-first.
      def each_element(root, &block)
        yield root
        root.each_element { |child| each_element(child, &block) }
      end

      def css_matches?(el, tag, cls)
        return false if tag && el.name != tag

        cls.nil? || el.attributes["class"].to_s.split.include?(cls)
      end

      def length(value, reference)
        m = LENGTH.match(value.to_s.strip.downcase)
        return nil if m.nil?

        number = Float(m[1])
        case m[2]
        when "pt" then number * 4.0 / 3.0
        when "em" then number * reference
        when "rem" then number * DEFAULT_TEXT_SIZE
        when "%" then number * reference / 100.0
        else number
        end
      end

      def first_number(value)
        return nil if value.nil?

        m = NUM.match(value.to_s)
        m ? Float(m[0]) : nil
      end

      # Computed text properties: inline style > CSS rule > attribute > parent.
      class Styler
        attr_reader :rules

        def initialize(root)
          @root = root
          @rules = TextToPaths.css_rules(root)
        end

        def own(el, prop)
          inline = TextToPaths.style_decls(el.attributes["style"])
          return inline[prop] if inline.key?(prop)

          value = nil
          @rules.each { |tag, cls, decls| value = decls[prop] if decls.key?(prop) && TextToPaths.css_matches?(el, tag, cls) }
          return value unless value.nil?

          el.attributes[prop]
        end

        # REXML::Document is itself an Element; the walk stops below it, where
        # ElementTree's parent map runs out.
        def element?(node) = node.is_a?(REXML::Element) && !node.is_a?(REXML::Document)

        def computed(el, prop)
          while element?(el)
            value = own(el, prop)
            return value if !value.nil? && value != "inherit"

            el = el.parent
          end
          nil
        end

        def font_size(el)
          chain = []
          while element?(el)
            chain << el
            el = el.parent
          end
          size = DEFAULT_TEXT_SIZE
          chain.reverse_each do |node|
            value = own(node, "font-size")
            next if value.nil?

            parsed = TextToPaths.length(value, size)
            size = parsed if parsed && parsed.positive?
          end
          size
        end

        def transformed?(el)
          node = el
          while element?(node) && !node.equal?(@root)
            return true if node.attributes["transform"]

            node = node.parent
          end
          false
        end

        def tag_rule_decls(el)
          decls = {}
          @rules.each { |tag, cls, rule| decls.update(rule) if tag && TextToPaths.css_matches?(el, tag, cls) }
          decls
        end
      end

      def carry_attributes(el, styler)
        carried = {}
        el.attributes.each_attribute do |attr|
          name = attr.expanded_name
          next if name == "xmlns" || name.start_with?("xmlns:")
          next if TEXT_LAYOUT_PROPS.include?(name)

          if name == "style"
            kept = style_decls(attr.value).reject { |k, _v| TEXT_LAYOUT_PROPS.include?(k) }
            carried["style"] = kept.map { |k, v| "#{k}:#{v}" }.join(";") unless kept.empty?
            next
          end
          carried[name] = attr.value
        end
        styler.tag_rule_decls(el).each do |key, value|
          carried[key] = value if !TEXT_LAYOUT_PROPS.include?(key) && !carried.key?(key)
        end
        carried
      end

      def collapse_ws(text)
        text.to_s.gsub(/[\t\r\n]/, " ").gsub(/ {2,}/, " ")
      end

      # Port of svg_text_to_paths over a SANITIZED banner.
      def svg_text_to_paths(svg_text, mode = "paths", default_family = DEFAULT_FONT_FAMILY,
                            frame_width = SVG_WIDTH)
        result = Result.new(svg: svg_text, converted: 0, stripped: 0, fitted: 0,
                            missing_glyphs: 0, notes: [])
        return result if mode == "keep"

        if mode == "paths" && !fonts_available?
          result.notes << "bundled fonts not found — <text> stripped instead of converted"
          mode = "forbid"
        end
        doc = REXML::Document.new(svg_text)
        root = doc.root
        styler = Styler.new(root)
        texts = []
        each_element(root) { |el| texts << el if el.name == "text" }
        return result if texts.empty?

        texts.each do |text_el|
          parent = text_el.parent
          next unless parent.is_a?(REXML::Element)

          replacement = mode == "paths" ? convert_text(text_el, styler, default_family, frame_width, result) : nil
          if replacement.nil?
            result.stripped += 1
          else
            result.converted += 1
            parent.insert_before(text_el, replacement)
          end
          parent.delete(text_el)
        end
        out = +""
        REXML::Formatters::Default.new.write(root, out)
        result.svg = out
        result.notes << "converted #{result.converted} <text> to paths" if result.converted.positive?
        result.notes << "stripped #{result.stripped} <text>" if result.stripped.positive?
        result.notes << "scaled #{result.fitted} overlong line(s) to fit the frame" if result.fitted.positive?
        if result.missing_glyphs.positive?
          result.notes << "#{result.missing_glyphs} character(s) had no glyph in the bundled font"
        end
        result
      end

      def convert_text(text_el, styler, default_family, frame_width, result)
        font_for = lambda do |el|
          family = resolve_font_family(styler.computed(el, "font-family").to_s,
                                       styler.computed(el, "font-weight").to_s, default_family)
          font = load_font(family)
          raise ArgumentError, "bundled font #{family} unavailable" if font.nil?

          font
        end
        anchor_of = lambda do |el|
          value = (styler.computed(el, "text-anchor") || "start").strip.downcase
          %w[start middle end].include?(value) ? value : "start"
        end

        size0 = styler.font_size(text_el)
        x0 = (first_number(text_el.attributes["x"]) || 0.0) + (first_number(text_el.attributes["dx"]) || 0.0)
        y0 = (first_number(text_el.attributes["y"]) || 0.0) +
             (length(text_el.attributes["dy"].to_s, size0) || 0.0)
        chunks = [{ x: x0, y: y0, anchor: anchor_of.call(text_el), runs: [] }]

        chunk_end = lambda do |chunk|
          width = chunk[:runs].inject(0.0) do |acc, run|
            acc + text_advance(font_for.call(run[:el]), run[:text], styler.font_size(run[:el]))
          end
          chunk[:x] + width
        end
        add_run = lambda do |owner, raw|
          text = collapse_ws(raw)
          chunks[-1][:runs] << { el: owner, text: text } unless text.empty?
        end
        walk = lambda do |el|
          el.children.each do |child|
            case child
            when REXML::Text
              add_run.call(el, child.value)
            when REXML::Element
              if child.name == "tspan"
                size = styler.font_size(child)
                cx = child.attributes["x"]
                cy = child.attributes["y"]
                dx = first_number(child.attributes["dx"]) || 0.0
                dy = length(child.attributes["dy"].to_s, size) || 0.0
                current = chunks[-1]
                if !cx.nil? || !cy.nil? || dx != 0 || dy != 0
                  nx = cx.nil? ? chunk_end.call(current) : first_number(cx)
                  ny = cy.nil? ? current[:y] : first_number(cy)
                  chunks << { x: (nx || 0.0) + dx, y: (ny || 0.0) + dy,
                              anchor: anchor_of.call(child), runs: [] }
                end
                walk.call(child)
              elsif child.name == "textPath"
                result.notes << "<textPath> is not supported — its text was dropped"
              end
            end
          end
        end
        walk.call(text_el)

        group = REXML::Element.new("g")
        carry_attributes(text_el, styler).each { |k, v| group.add_attribute(k, v) }
        labels = []
        fittable = !styler.transformed?(text_el)
        chunks.each do |chunk|
          runs = chunk[:runs]
          next if runs.empty?

          runs[0][:text] = runs[0][:text].sub(/\A +/, "")
          runs[-1][:text] = runs[-1][:text].sub(/ +\z/, "")
          measured = []
          total = 0.0
          runs.each do |run|
            font = font_for.call(run[:el])
            size = styler.font_size(run[:el])
            spacing = length(styler.computed(run[:el], "letter-spacing").to_s, size) || 0.0
            total += text_advance(font, run[:text], size, spacing)
            measured << [run, font, size, spacing]
          end
          next if total <= 0

          factor = 1.0
          limit = frame_width * TEXT_FIT_FRACTION
          if fittable && total > limit
            factor = limit / total
            result.fitted += 1
          end
          span = total * factor
          start = chunk[:x] - span * { "start" => 0.0, "middle" => 0.5, "end" => 1.0 }[chunk[:anchor]]
          if fittable && (start.negative? || start + span > frame_width)
            margin = (frame_width - limit) / 2.0
            start = [[start, margin].max, frame_width - margin - span].min
          end
          pen = start
          measured.each do |run, font, size, spacing|
            next if run[:text].empty?

            scaled = size * factor
            shift = baseline_shift(font, styler.computed(run[:el], "dominant-baseline").to_s, scaled)
            d, advance, missing = glyph_run_path(font, run[:text], pen, chunk[:y] + shift, scaled, spacing * factor)
            pen += advance
            result.missing_glyphs += missing
            labels << run[:text]
            next if d.empty?

            path = REXML::Element.new("path")
            unless run[:el].equal?(text_el)
              carry_attributes(run[:el], styler).each { |k, v| path.add_attribute(k, v) }
            end
            path.add_attribute("d", d)
            group.add_element(path)
          end
        end
        return nil unless group.has_elements?

        group.add_attribute("aria-label", labels.map(&:strip).reject(&:empty?).join(" "))
        group
      end
    end
  end
end
