# Obsidian bridge -- fence masking utility (pure Ruby, no Jekyll required).
#
# Splits markdown into segments that are inside fenced code blocks (``` / ~~~),
# inside inline code spans (`...`), or outside of both, so converters can
# transform prose without ever touching code samples. Ruby 2.6 compatible.

module Obsidian
  module FenceMask
    OPEN_FENCE_RE = /\A {0,3}(`{3,}|~{3,})(.*)\z/

    module_function

    # Applies the given block to every chunk of text that is OUTSIDE fenced
    # code blocks (and, when +mask_inline+ is true, outside inline code spans
    # too). Returns the reassembled string.
    def apply_outside(text, mask_inline = true)
      segments(text).map { |kind, chunk|
        if kind == :code
          chunk
        elsif mask_inline
          split_inline(chunk).map { |k, c| k == :code ? c : yield(c) }.join
        else
          yield(chunk)
        end
      }.join
    end

    # Splits +text+ into [[:outside|:code, chunk], ...] where :code chunks are
    # whole fenced blocks (fence lines included). An unterminated fence runs to
    # the end of the text, per CommonMark.
    def segments(text)
      segs = []
      outside = []
      code = nil
      fence_char = nil
      fence_len = 0
      text.to_s.each_line do |line|
        if code
          code << line
          stripped = line.strip
          if !stripped.empty? && stripped[0] == fence_char &&
             stripped.length >= fence_len && stripped == fence_char * stripped.length
            segs << [:code, code.join]
            code = nil
          end
        else
          m = line.chomp.match(OPEN_FENCE_RE)
          # A backtick fence may not carry backticks in its info string.
          if m && !(m[1][0] == '`' && m[2].include?('`'))
            unless outside.empty?
              segs << [:outside, outside.join]
              outside = []
            end
            code = [line]
            fence_char = m[1][0]
            fence_len = m[1].length
          else
            outside << line
          end
        end
      end
      segs << [:code, code.join] if code
      segs << [:outside, outside.join] unless outside.empty?
      segs
    end

    # Splits a fence-free chunk into [[:outside|:code, chunk], ...] where :code
    # chunks are inline code spans delimited by equal-length backtick runs.
    def split_inline(text)
      return [] if text.nil? || text.empty?
      runs = []
      idx = 0
      while (start = text.index('`', idx))
        stop = start
        stop += 1 while stop < text.length && text[stop] == '`'
        runs << [start, stop - start]
        idx = stop
      end
      parts = []
      cursor = 0
      i = 0
      while i < runs.length
        start, len = runs[i]
        j = i + 1
        j += 1 while j < runs.length && runs[j][1] != len
        if j < runs.length
          close_start, close_len = runs[j]
          parts << [:outside, text[cursor...start]] if start > cursor
          parts << [:code, text[start...(close_start + close_len)]]
          cursor = close_start + close_len
          i = j + 1
        else
          i += 1
        end
      end
      parts << [:outside, text[cursor..-1]] if cursor < text.length
      parts
    end

    # Walks every fenced code block; yields (info_string, body) and replaces
    # the whole block (fence lines included) with the block's return value
    # unless it returns nil. Blocks nested inside other fences are never
    # yielded (the outer fence wins), which keeps teaching material intact.
    def replace_fences(text)
      segments(text).map { |kind, chunk|
        if kind == :outside
          chunk
        else
          lines = chunk.lines
          m = lines.first.chomp.match(OPEN_FENCE_RE)
          info = m ? m[2].strip : ''
          closed = false
          if lines.length > 1
            last = lines.last.strip
            closed = !last.empty? && last[0] == m[1][0] &&
                     last.length >= m[1].length && last == last[0] * last.length
          end
          body = closed ? lines[1..-2].join : lines[1..-1].join
          replacement = yield(info, body)
          replacement.nil? ? chunk : replacement
        end
      }.join
    end
  end
end
