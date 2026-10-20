# Obsidian bridge -- callout converter (pure Ruby, no Jekyll required).
#
# Converts Obsidian / GitHub callout blockquotes into Bootstrap alert divs:
#   > [!note] Optional Title        > [!NOTE]        > [!tip]+ Folded
#   > body markdown...
# The div carries markdown="1" so kramdown still processes the inner markdown.
# Ruby 2.6 compatible.

require_relative 'fence_mask'

module Obsidian
  module Callouts
    TYPE_MAP = {
      'note' => 'info', 'info' => 'info', 'todo' => 'info',
      'tip' => 'success', 'hint' => 'success', 'success' => 'success', 'check' => 'success',
      'warning' => 'warning', 'caution' => 'warning', 'attention' => 'warning',
      'danger' => 'danger', 'error' => 'danger', 'bug' => 'danger',
      'failure' => 'danger', 'important' => 'danger',
      'question' => 'info', 'help' => 'info', 'faq' => 'info',
      'quote' => 'secondary', 'cite' => 'secondary',
      'example' => 'light', 'abstract' => 'light', 'summary' => 'light'
    }.freeze
    DEFAULT_CLASS = 'info'.freeze

    HEAD_RE = /\A {0,3}> ?\[!([A-Za-z][A-Za-z0-9_-]*)\]([+-]?)[ \t]*(.*)\z/
    BODY_RE = /\A {0,3}>/
    BODY_STRIP_RE = /\A {0,3}> ?/

    module_function

    # Converts every callout outside code fences. Inline code spans are not
    # masked here because callout heads are matched at line starts.
    def convert(md)
      FenceMask.apply_outside(md, false) { |chunk| convert_chunk(chunk) }
    end

    def convert_chunk(text)
      lines = text.lines
      out = []
      i = 0
      while i < lines.length
        m = lines[i].chomp.match(HEAD_RE)
        if m
          type = m[1].downcase
          title = m[3].strip
          title = type.capitalize if title.empty?
          body = []
          i += 1
          while i < lines.length && lines[i] =~ BODY_RE
            body << lines[i].sub(BODY_STRIP_RE, '')
            i += 1
          end
          css = TYPE_MAP.fetch(type, DEFAULT_CLASS)
          out << "<div class=\"alert alert-#{css} obsidian-callout obsidian-callout-#{type}\" markdown=\"1\">\n"
          out << "<strong class=\"obsidian-callout-title\">#{title}</strong>\n"
          unless body.empty?
            out << "\n"
            body.each { |l| out << l }
            out << "\n" unless body.last.end_with?("\n")
          end
          out << "</div>\n"
        else
          out << lines[i]
          i += 1
        end
      end
      out.join
    end
  end
end
