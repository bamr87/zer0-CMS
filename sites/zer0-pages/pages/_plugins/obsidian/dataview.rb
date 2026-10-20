# Obsidian bridge -- Dataview query engine (pure Ruby, no Jekyll required).
#
# Parses and renders the subset of the Obsidian Dataview query language used
# in this vault. Supported grammar (every real query in pages/ is covered by
# the test suite):
#
#   TABLE <col>[, <col>...] | LIST [<expr>]
#     col  := expr [AS label]        label := ident | "quoted"
#   FROM "folder" [OR "folder"...]   |  FROM "" AND -"excluded" [AND -"..."]
#   WHERE clause [AND clause...]     clause := expr [=|!= expr] | expr (truthy)
#   FLATTEN expr AS alias            (repeatable)
#   GROUP BY expr [AS alias]
#   SORT key [ASC|DESC][, key ...]
#   LIMIT n
#
#   expr := field.path | "literal" | number | true|false|null | fn(args...)
#   fns  := length, default, choice, dateformat, regexreplace, lower, upper
#   file fields := file.name, file.folder, file.link, file.path
#   rows.<path> (after GROUP BY) maps the path over the grouped rows.
#
# `parse` returns nil for anything outside this grammar so callers can fall
# back gracefully. `render(parsed, docs)` takes plain doc hashes
# {title:, url:, path:, fm: {...}} so this file stays Jekyll-free.
# Ruby 2.6 compatible.

require 'date'

module Obsidian
  module Dataview
    Link = Struct.new(:href, :text)
    Token = Struct.new(:type, :value)

    class ParseError < StandardError; end

    class Query
      attr_accessor :mode, :columns, :from, :where, :flatten, :group_by, :sort, :limit

      def initialize
        @mode = nil
        @columns = []
        @from = { include: [''], exclude: [] }
        @where = []
        @flatten = []
        @group_by = nil
        @sort = []
        @limit = nil
      end
    end

    class TokenStream
      def initialize(tokens)
        @tokens = tokens
        @pos = 0
      end

      def peek
        @tokens[@pos]
      end

      def next_token
        t = @tokens[@pos]
        @pos += 1
        t
      end

      def eof?
        @pos >= @tokens.length
      end
    end

    # Evaluation context: a plain doc row, a flattened row (extra bindings),
    # or a group (bindings hold the group key, rows hold member contexts).
    class Context
      attr_reader :doc, :bindings, :rows

      def initialize(doc, bindings = {}, rows = nil)
        @doc = doc
        @bindings = bindings
        @rows = rows
      end

      def with_binding(name, value)
        b = @bindings.dup
        b[name] = value
        Context.new(@doc, b, @rows)
      end
    end

    KEYWORD_RE = /\A(TABLE|LIST|FROM|WHERE|FLATTEN|GROUP\s+BY|SORT|LIMIT)\b/i

    module_function

    # ------------------------------------------------------------------ parse

    def parse(text)
      clauses = clause_lines(text)
      return nil if clauses.nil? || clauses.empty?
      q = Query.new
      clauses.each do |clause|
        case clause
        when /\ATABLE\s*(.*)\z/i
          return nil if q.mode
          q.mode = :table
          rest = Regexp.last_match(1).strip
          unless rest.empty?
            cols = split_top(rest, :comma).map { |c| parse_column(c) }
            return nil if cols.empty? || cols.any?(&:nil?)
            q.columns = cols
          end
        when /\ALIST\s*(.*)\z/i
          return nil if q.mode
          q.mode = :list
          rest = Regexp.last_match(1).strip
          unless rest.empty?
            col = parse_column(rest)
            return nil unless col
            q.columns = [col]
          end
        when /\AFROM\s+(.*)\z/i
          f = parse_from(Regexp.last_match(1))
          return nil unless f
          q.from = f
        when /\AWHERE\s+(.*)\z/i
          split_top(Regexp.last_match(1), :and).each do |part|
            e = parse_full_expr(part)
            return nil unless e
            q.where << e
          end
        when /\AFLATTEN\s+(.*)\z/i
          fl = parse_aliased(Regexp.last_match(1))
          return nil unless fl
          fl[:alias] ||= default_alias(fl[:expr])
          return nil unless fl[:alias]
          q.flatten << fl
        when /\AGROUP\s+BY\s+(.*)\z/i
          g = parse_aliased(Regexp.last_match(1))
          return nil unless g
          q.group_by = g
        when /\ASORT\s+(.*)\z/i
          split_top(Regexp.last_match(1), :comma).each do |part|
            s = parse_sort_key(part)
            return nil unless s
            q.sort << s
          end
        when /\ALIMIT\s+(\d+)\s*\z/i
          q.limit = Regexp.last_match(1).to_i
        else
          return nil
        end
      end
      q.mode ? q : nil
    rescue StandardError
      nil
    end

    # Best-effort extraction of the FROM clause even when the full query does
    # not parse -- used by callers to build a fallback listing.
    def extract_from(text)
      text.to_s.each_line do |line|
        m = line.strip.match(/\AFROM\s+(.*)\z/i)
        next unless m
        f = parse_from(m[1])
        return f if f
      end
      nil
    end

    def clause_lines(text)
      clauses = []
      text.to_s.each_line do |line|
        l = line.strip
        next if l.empty?
        if l =~ KEYWORD_RE
          clauses << l
        else
          return nil if clauses.empty?
          clauses[-1] = clauses[-1] + ' ' + l
        end
      end
      clauses
    end

    def parse_from(rest)
      inc = []
      exc = []
      found = false
      rest.scan(/(-?)"((?:[^"\\]|\\.)*)"/) do |neg, folder|
        found = true
        if neg == '-'
          exc << folder
        else
          inc << folder
        end
      end
      return nil unless found
      inc << '' if inc.empty?
      { include: inc, exclude: exc }
    end

    def parse_column(text)
      text = text.strip
      return nil if text.empty?
      st = TokenStream.new(tokenize(text))
      expr = parse_expr(st)
      return nil unless expr
      label = nil
      if keyword?(st.peek, 'AS')
        st.next_token
        t = st.next_token
        return nil unless t && (t.type == :ident || t.type == :str)
        label = t.value
      end
      return nil unless st.eof?
      { expr: expr, label: label || text }
    rescue ParseError
      nil
    end

    def parse_aliased(text)
      st = TokenStream.new(tokenize(text.strip))
      expr = parse_expr(st)
      return nil unless expr
      al = nil
      if keyword?(st.peek, 'AS')
        st.next_token
        t = st.next_token
        return nil unless t && (t.type == :ident || t.type == :str)
        al = t.value
      end
      return nil unless st.eof?
      { expr: expr, alias: al }
    rescue ParseError
      nil
    end

    def parse_sort_key(text)
      st = TokenStream.new(tokenize(text.strip))
      expr = parse_expr(st)
      return nil unless expr
      dir = :asc
      if keyword?(st.peek, 'ASC') || keyword?(st.peek, 'DESC')
        dir = st.next_token.value.upcase == 'DESC' ? :desc : :asc
      end
      return nil unless st.eof?
      { expr: expr, dir: dir }
    rescue ParseError
      nil
    end

    def parse_full_expr(text)
      st = TokenStream.new(tokenize(text.strip))
      expr = parse_expr(st)
      return nil unless expr
      return nil unless st.eof?
      expr
    rescue ParseError
      nil
    end

    def default_alias(expr)
      expr[0] == :field ? expr[1].last : nil
    end

    def keyword?(token, word)
      token && token.type == :ident && token.value.upcase == word
    end

    # -------------------------------------------------------- expression AST

    def parse_expr(st)
      left = parse_primary(st)
      return nil unless left
      t = st.peek
      if t && t.type == :op && (t.value == '=' || t.value == '!=')
        op = st.next_token.value
        right = parse_primary(st)
        return nil unless right
        return [:cmp, op, left, right]
      end
      left
    end

    def parse_primary(st)
      t = st.next_token
      return nil unless t
      case t.type
      when :str, :num
        [:lit, t.value]
      when :ident
        word = t.value
        case word.downcase
        when 'true' then return [:lit, true]
        when 'false' then return [:lit, false]
        when 'null' then return [:lit, nil]
        end
        nxt = st.peek
        if nxt && nxt.type == :op && nxt.value == '('
          st.next_token
          args = []
          unless st.peek && st.peek.type == :op && st.peek.value == ')'
            loop do
              a = parse_expr(st)
              return nil unless a
              args << a
              break unless st.peek && st.peek.type == :op && st.peek.value == ','
              st.next_token
            end
          end
          return nil unless st.peek && st.peek.type == :op && st.peek.value == ')'
          st.next_token
          [:call, word.downcase, args]
        else
          [:field, word.split('.')]
        end
      end
    end

    def tokenize(text)
      toks = []
      s = text.to_s
      i = 0
      len = s.length
      while i < len
        ch = s[i]
        if ch =~ /\s/
          i += 1
        elsif ch == '"'
          j = i + 1
          buf = String.new
          while j < len && s[j] != '"'
            if s[j] == '\\' && j + 1 < len
              buf << s[j + 1]
              j += 2
            else
              buf << s[j]
              j += 1
            end
          end
          raise ParseError, 'unterminated string' if j >= len
          toks << Token.new(:str, buf)
          i = j + 1
        elsif s[i, 2] == '!='
          toks << Token.new(:op, '!=')
          i += 2
        elsif ch == '=' || ch == '(' || ch == ')' || ch == ','
          toks << Token.new(:op, ch)
          i += 1
        elsif ch =~ /[A-Za-z_]/
          j = i
          j += 1 while j < len && s[j] =~ /[A-Za-z0-9_\-.]/
          toks << Token.new(:ident, s[i...j])
          i = j
        elsif ch =~ /[0-9]/
          j = i
          j += 1 while j < len && s[j] =~ /[0-9.]/
          num = s[i...j]
          toks << Token.new(:num, num.include?('.') ? num.to_f : num.to_i)
          i = j
        else
          raise ParseError, "unexpected character #{ch.inspect}"
        end
      end
      toks
    end

    # Splits at top-level commas (:comma) or top-level AND keywords (:and),
    # respecting parentheses and quoted strings.
    def split_top(text, mode)
      parts = []
      buf = String.new
      depth = 0
      i = 0
      len = text.length
      while i < len
        ch = text[i]
        if ch == '"'
          j = i + 1
          while j < len
            break if text[j] == '"' && text[j - 1] != '\\'
            j += 1
          end
          stop = j < len ? j : len - 1
          buf << text[i..stop]
          i = stop + 1
          next
        end
        depth += 1 if ch == '('
        depth -= 1 if ch == ')'
        if depth == 0
          if mode == :comma && ch == ','
            parts << buf
            buf = String.new
            i += 1
            next
          end
          if mode == :and && (ch == 'A' || ch == 'a') &&
             text[i, 3].to_s.upcase == 'AND' &&
             (i == 0 || text[i - 1] =~ /\s/) &&
             (i + 3 >= len || text[i + 3] =~ /\s/)
            parts << buf
            buf = String.new
            i += 3
            next
          end
        end
        buf << ch
        i += 1
      end
      parts << buf
      parts.map(&:strip).reject(&:empty?)
    end

    # ----------------------------------------------------------------- render

    # Renders the parsed query against +docs+, an array of plain hashes
    # {title:, url:, path:, fm: {...}}. Returns an HTML string, or nil when
    # evaluation fails (callers should fall back).
    def render(parsed, docs)
      rows = docs.map { |d| Context.new(d) }
      parsed.flatten.each do |fl|
        rows = rows.flat_map do |r|
          v = eval_expr(fl[:expr], r)
          if v.is_a?(Array)
            v.empty? ? [r.with_binding(fl[:alias], nil)] : v.map { |el| r.with_binding(fl[:alias], el) }
          else
            [r.with_binding(fl[:alias], v)]
          end
        end
      end
      rows = rows.select { |r| parsed.where.all? { |w| truthy?(eval_expr(w, r)) } }
      if parsed.group_by
        render_grouped(parsed, rows)
      else
        rows = apply_sort(rows, parsed.sort)
        rows = rows.first(parsed.limit) if parsed.limit
        if parsed.mode == :table
          render_table(parsed, rows, nil)
        else
          render_list(parsed, rows, nil)
        end
      end
    rescue StandardError
      nil
    end

    def render_grouped(parsed, rows)
      alias_name = parsed.group_by[:alias] || default_alias(parsed.group_by[:expr])
      groups = {}
      order = []
      rows.each do |r|
        k = eval_expr(parsed.group_by[:expr], r)
        unless groups.key?(k)
          groups[k] = []
          order << k
        end
        groups[k] << r
      end
      gctxs = order.map do |k|
        b = { 'key' => k }
        b[alias_name] = k if alias_name
        Context.new(nil, b, groups[k])
      end
      gctxs = if parsed.sort.empty?
                gctxs.sort { |a, b| compare_values(a.bindings['key'], b.bindings['key'], :asc) }
              else
                apply_sort(gctxs, parsed.sort)
              end
      gctxs = gctxs.first(parsed.limit) if parsed.limit
      header = alias_name ? alias_name.to_s : 'Group'
      if parsed.mode == :table
        render_table(parsed, gctxs, header)
      else
        render_list(parsed, gctxs, header)
      end
    end

    def render_table(parsed, ctxs, group_header)
      heads = [group_header || 'File']
      parsed.columns.each { |c| heads << c[:label] }
      html = String.new
      html << "<div class=\"obsidian-dataview table-responsive\">\n"
      html << "<table class=\"table dataview-table\">\n<thead>\n<tr>"
      heads.each { |h| html << "<th>#{escape_html(h.to_s)}</th>" }
      html << "</tr>\n</thead>\n<tbody>\n"
      ctxs.each do |ctx|
        html << '<tr>'
        first = group_header ? render_group_key(ctx.bindings['key']) : render_value(file_link(ctx))
        html << "<td>#{first}</td>"
        parsed.columns.each do |c|
          html << "<td>#{render_value(eval_expr(c[:expr], ctx))}</td>"
        end
        html << "</tr>\n"
      end
      html << "</tbody>\n</table>\n</div>\n"
      html
    end

    def render_list(parsed, ctxs, group_header)
      col = parsed.columns[0]
      html = String.new
      html << "<ul class=\"obsidian-dataview dataview-list\">\n"
      ctxs.each do |ctx|
        if group_header
          html << "<li><strong>#{render_group_key(ctx.bindings['key'])}</strong>\n<ul>\n"
          items = col ? eval_expr(col[:expr], ctx) : ctx.rows.map { |r| file_link(r) }
          items = [items] unless items.is_a?(Array)
          items.each { |v| html << "<li>#{render_value(v)}</li>\n" }
          html << "</ul>\n</li>\n"
        else
          v = col ? eval_expr(col[:expr], ctx) : file_link(ctx)
          html << "<li>#{render_value(v)}</li>\n"
        end
      end
      html << "</ul>\n"
      html
    end

    def render_group_key(key)
      key.nil? || key.to_s.strip.empty? ? '&#8212;' : render_value(key)
    end

    def render_value(v)
      case v
      when nil
        ''
      when Link
        "<a href=\"#{escape_html(v.href.to_s)}\">#{escape_html(v.text.to_s)}</a>"
      when Array
        if !v.empty? && v.all? { |e| e.is_a?(Link) }
          '<ul class="dataview-cell-list">' +
            v.map { |e| "<li>#{render_value(e)}</li>" }.join + '</ul>'
        else
          v.map { |e| render_value(e) }.join(', ')
        end
      when Time
        escape_html(v.strftime('%Y-%m-%d'))
      when Date
        escape_html(v.strftime('%Y-%m-%d'))
      else
        escape_html(v.to_s)
      end
    end

    # ------------------------------------------------------------- evaluation

    def eval_expr(node, ctx)
      case node[0]
      when :lit
        node[1]
      when :field
        eval_field(node[1], ctx)
      when :cmp
        l = eval_expr(node[2], ctx)
        r = eval_expr(node[3], ctx)
        node[1] == '=' ? values_equal(l, r) : !values_equal(l, r)
      when :call
        eval_call(node[1], node[2], ctx)
      end
    end

    def eval_field(parts, ctx)
      head = parts[0]
      rest = parts[1..-1]
      if head == 'rows' && ctx.rows
        return ctx.rows if rest.empty?
        return ctx.rows.map { |r| eval_field(rest, r) }
      end
      return dig_value(ctx.bindings[head], rest) if ctx.bindings.key?(head)
      return nil unless ctx.doc
      return file_field(rest, ctx.doc) if head == 'file'
      dig_value(fm_fetch(ctx.doc, head), rest)
    end

    def file_field(rest, doc)
      case rest[0]
      when 'name'
        File.basename(doc_path(doc), '.*')
      when 'folder'
        d = File.dirname(doc_path(doc))
        d == '.' ? '' : d
      when 'link'
        file_link_for(doc)
      when 'path'
        doc_path(doc)
      end
    end

    def file_link(ctx)
      ctx.doc ? file_link_for(ctx.doc) : nil
    end

    def file_link_for(doc)
      Link.new(doc_get(doc, :url).to_s, doc_title(doc))
    end

    def doc_path(doc)
      doc_get(doc, :path).to_s
    end

    def doc_title(doc)
      t = doc_get(doc, :title)
      t = fm_fetch(doc, 'title') if t.nil?
      t = File.basename(doc_path(doc), '.*') if t.nil? || t.to_s.empty?
      t.to_s
    end

    def doc_get(doc, key)
      return doc[key] if doc.key?(key)
      doc[key.to_s]
    end

    def fm_fetch(doc, key)
      fm = doc_get(doc, :fm) || {}
      return fm[key] if fm.key?(key)
      fm[key.to_sym]
    end

    def dig_value(value, parts)
      parts.each do |p|
        return nil unless value.is_a?(Hash)
        value = value.key?(p) ? value[p] : value[p.to_sym]
      end
      value
    end

    def eval_call(name, args, ctx)
      case name
      when 'length'
        v = args[0] ? eval_expr(args[0], ctx) : nil
        return 0 if v.nil?
        v.respond_to?(:length) ? v.length : 1
      when 'default'
        v = eval_expr(args[0], ctx)
        empty = v.nil? || (v.respond_to?(:empty?) && v.empty?)
        empty ? eval_expr(args[1], ctx) : v
      when 'choice'
        truthy?(eval_expr(args[0], ctx)) ? eval_expr(args[1], ctx) : eval_expr(args[2], ctx)
      when 'dateformat'
        dateformat(eval_expr(args[0], ctx), eval_expr(args[1], ctx).to_s)
      when 'regexreplace'
        s = eval_expr(args[0], ctx)
        return nil if s.nil?
        pattern = Regexp.new(eval_expr(args[1], ctx).to_s)
        replacement = eval_expr(args[2], ctx).to_s
        s.to_s.gsub(pattern) { replacement }
      when 'lower'
        eval_expr(args[0], ctx).to_s.downcase
      when 'upper'
        eval_expr(args[0], ctx).to_s.upcase
      end
    end

    DATEFORMAT_TOKENS = [
      %w[yyyy %Y], %w[yy %y], %w[MM %m], %w[dd %d],
      %w[HH %H], %w[mm %M], %w[ss %S]
    ].freeze

    def dateformat(value, fmt)
      t = to_time(value)
      return '' unless t
      out = fmt.dup
      DATEFORMAT_TOKENS.each { |token, strf| out = out.gsub(token, strf) }
      t.strftime(out)
    end

    def to_time(value)
      case value
      when Time then value
      when Date then value.to_time
      when String
        begin
          Date.parse(value).to_time
        rescue ArgumentError
          nil
        end
      end
    end

    def values_equal(a, b)
      return true if a.nil? && b.nil?
      a == b
    end

    def truthy?(value)
      !(value.nil? || value == false)
    end

    def apply_sort(ctxs, sorts)
      return ctxs if sorts.empty?
      ctxs.sort do |a, b|
        res = 0
        sorts.each do |s|
          res = compare_values(eval_expr(s[:expr], a), eval_expr(s[:expr], b), s[:dir])
          break if res != 0
        end
        res
      end
    end

    # nils always sort last, regardless of direction.
    def compare_values(a, b, dir)
      return 0 if a.nil? && b.nil?
      return 1 if a.nil?
      return -1 if b.nil?
      c = sort_token(a) <=> sort_token(b)
      c = a.to_s <=> b.to_s if c.nil?
      dir == :desc ? -c : c
    end

    def sort_token(v)
      case v
      when Numeric then [0, v.to_f, '']
      when Time then [1, v.to_f, '']
      when Date then [1, v.to_time.to_f, '']
      when TrueClass, FalseClass then [2, v ? 1.0 : 0.0, '']
      else [3, 0.0, v.to_s.downcase]
      end
    end

    def escape_html(text)
      text.to_s.gsub('&', '&amp;').gsub('<', '&lt;').gsub('>', '&gt;').gsub('"', '&quot;')
    end
  end
end
