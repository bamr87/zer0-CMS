# Unit tests for the Obsidian -> Jekyll bridge core.
#
# Run from the repo root with system ruby (no gems beyond stdlib needed):
#   ruby -Ipages/_plugins tests/test_obsidian_bridge.rb
#
# obsidian_bridge.rb is required too: without Jekyll loaded it only defines
# the pure helper module, which is exactly what these tests exercise.

require 'minitest/autorun'
require 'date'

require 'obsidian/fence_mask'
require 'obsidian/wikilinks'
require 'obsidian/callouts'
require 'obsidian/dataview'
require 'obsidian_bridge'

# ---------------------------------------------------------------- fixtures

module Fixtures
  module_function

  def doc(path, fm = {})
    base = File.basename(path, '.*')
    {
      title: fm['title'] || base,
      url: '/' + path.sub(/\.md\z/, '') + '/',
      path: path,
      fm: fm
    }
  end

  def posts
    [
      doc('_posts/2026-01-10-alpha.md',
          'title' => 'Alpha', 'type' => 'post', 'date' => Date.new(2026, 1, 10),
          'categories' => %w[Dev], 'tags' => %w[ruby jekyll], 'description' => 'First post'),
      doc('_posts/2025-06-01-beta.md',
          'title' => 'Beta', 'type' => 'post', 'date' => Date.new(2025, 6, 1),
          'categories' => %w[Dev Notes], 'tags' => %w[obsidian], 'description' => 'Second post'),
      doc('_posts/2024-03-05-gamma.md',
          'title' => 'Gamma', 'type' => 'post', 'date' => Date.new(2024, 3, 5),
          'categories' => %w[Life], 'tags' => %w[ruby], 'description' => 'Third post'),
      doc('_posts/2026-02-01-hidden.md',
          'title' => 'Hidden', 'type' => 'post', 'date' => Date.new(2026, 2, 1),
          'draft' => true, 'categories' => %w[Dev], 'description' => 'Draft post')
    ]
  end

  def docs_collection
    [
      doc('_docs/setup.md',
          'title' => 'Setup', 'type' => 'doc', 'date' => Date.new(2025, 1, 1),
          'lastmod' => Date.new(2026, 3, 1), 'difficulty' => 'beginner',
          'description' => 'Setup guide', 'tags' => %w[setup]),
      doc('_docs/features/mermaid.md',
          'title' => 'Mermaid', 'type' => 'doc', 'date' => Date.new(2025, 2, 1),
          'difficulty' => 'advanced', 'description' => 'Diagrams',
          'estimated_reading_time' => '5 min', 'tags' => %w[diagrams]),
      doc('_docs/jekyll/plugins.md',
          'title' => 'Plugins', 'type' => 'doc', 'date' => Date.new(2025, 5, 1),
          'description' => 'Plugin guide', 'tags' => %w[jekyll]),
      doc('_docs/features/index.md',
          'title' => 'Features', 'type' => 'doc', 'date' => Date.new(2025, 1, 1),
          'description' => 'Feature index')
    ]
  end

  def quickstart
    [
      doc('_quickstart/second.md',
          'title' => 'Second Step', 'type' => 'quickstart',
          'quickstart' => { 'step' => 2 }, 'description' => 'Then this'),
      doc('_quickstart/first.md',
          'title' => 'First Step', 'type' => 'quickstart',
          'quickstart' => { 'step' => 1 }, 'description' => 'Start here')
    ]
  end

  def about
    [
      doc('_about/features/one.md',
          'title' => 'Bravo', 'type' => 'about', 'order' => 1, 'description' => 'B'),
      doc('_about/features/two.md',
          'title' => 'Alpha2', 'type' => 'about', 'order' => 1, 'description' => 'A'),
      doc('_about/index.md',
          'title' => 'About', 'type' => 'about', 'order' => 2, 'description' => 'Idx')
    ]
  end

  def site_pool
    posts + docs_collection + quickstart + about + [
      doc('index.md', 'title' => 'Home', 'type' => 'landing'),
      doc('wiki/topic.md', 'title' => 'Topic', 'type' => 'wiki'),
      doc('_templates/quest.md', 'title' => 'Quest Template'),
      doc('_moc/Home.md', 'title' => 'Home MOC', 'type' => 'moc')
    ]
  end
end

# Every unique real dataview query found in pages/**/*.md (2026-07-05), plus
# the pinned quest-board query. The parser must handle ALL of them.
REAL_QUERIES = [
  %(TABLE description AS Summary\nFROM "_about"\nWHERE type = "about" AND file.name != "index"\nSORT order ASC, title ASC),
  %(TABLE rows.file.link AS Notes, length(rows) AS Count\nFROM "_about"\nWHERE file.name != "index" AND file.name != "README"\nGROUP BY file.folder AS Section\nSORT Section ASC),
  %(TABLE type AS Type, description AS Summary\nFROM "_about"\nWHERE file.name != "index" AND file.name != "README"\nSORT file.folder ASC, title ASC),
  %(TABLE rows.file.link AS Notes\nFROM "_about"\nWHERE file.name != "index" AND file.name != "README"\nFLATTEN tags AS tag\nGROUP BY tag\nSORT tag ASC),
  %(TABLE rows.file.link AS "Documents", length(rows) AS "Count"\nFROM "_docs"\nWHERE type = "doc"\nGROUP BY choice(file.folder = "_docs", "General", regexreplace(file.folder, "^_docs/", "")) AS Section\nSORT Section ASC),
  %(TABLE choice(file.folder = "_docs", "General", regexreplace(file.folder, "^_docs/", "")) AS Section, description AS Summary\nFROM "_docs"\nWHERE type = "doc"\nSORT default(lastmod, date) DESC\nLIMIT 15),
  %(TABLE rows.file.link AS "Documents"\nFROM "_docs"\nWHERE type = "doc" AND difficulty\nGROUP BY difficulty AS Level\nSORT Level ASC),
  %(TABLE date AS Date, description AS Summary\nFROM "_posts"\nWHERE type = "post" AND draft != true\nSORT date DESC\nLIMIT 8),
  %(TABLE difficulty AS Difficulty, date AS Date, description AS Summary\nFROM "_notebooks"\nWHERE type = "notebook" AND draft != true\nSORT date DESC),
  %(TABLE rows.file.link AS Notebooks\nFROM "_notebooks"\nWHERE type = "notebook" AND draft != true\nFLATTEN default(difficulty, "intermediate") AS level\nGROUP BY level\nSORT level ASC),
  %(TABLE rows.file.link AS Notebooks\nFROM "_notebooks"\nWHERE type = "notebook" AND draft != true\nFLATTEN tags AS tag\nGROUP BY tag\nSORT tag ASC),
  %(TABLE rows.file.link AS Notebooks\nFROM "_notebooks"\nWHERE type = "notebook" AND draft != true\nFLATTEN categories AS category\nGROUP BY category\nSORT category ASC),
  %(TABLE description AS Summary, difficulty AS Difficulty, date AS Date\nFROM "_notes"\nWHERE type = "note" AND draft != true\nSORT date DESC),
  %(TABLE rows.file.link AS Notes\nFROM "_notes"\nWHERE type = "note" AND draft != true\nFLATTEN tags AS tag\nGROUP BY tag\nSORT tag ASC),
  %(TABLE rows.file.link AS Notes\nFROM "_notes"\nWHERE type = "note" AND draft != true\nFLATTEN categories AS category\nGROUP BY category\nSORT category ASC),
  %(TABLE rows.file.link AS Notes\nFROM "_notes"\nWHERE type = "note" AND draft != true\nFLATTEN difficulty AS level\nGROUP BY level\nSORT level ASC),
  %(TABLE date AS Date, tags AS Tags\nFROM "_posts"\nWHERE type = "post" AND draft != true\nSORT date DESC),
  %(TABLE rows.file.link AS Notes, length(rows) AS Count\nFROM "_posts"\nWHERE type = "post" AND draft != true\nFLATTEN categories AS category\nGROUP BY category\nSORT category ASC),
  %(TABLE difficulty AS Difficulty, xp AS XP, estimated_time AS Time, description AS Summary\nFROM "_quests"\nWHERE type = "quest" AND draft != true\nSORT file.name ASC),
  %(TABLE description AS Summary, quickstart.step AS Step\nFROM "_quickstart"\nWHERE type = "quickstart"\nSORT quickstart.step ASC),
  %(TABLE description AS Summary\nFROM "_quickstart"\nWHERE type = "quickstart" AND draft != true\nSORT file.name ASC),
  %(TABLE date AS Date, description AS Summary\nFROM "_posts"\nWHERE type = "post" AND draft != true\nSORT date DESC),
  %(TABLE rows.file.link AS Posts\nFROM "_posts"\nFLATTEN categories AS category\nWHERE type = "post" AND draft != true\nGROUP BY category),
  %(TABLE rows.file.link AS Posts\nFROM "_posts"\nWHERE type = "post" AND draft != true\nFLATTEN dateformat(date, "yyyy") AS year\nGROUP BY year\nSORT year DESC),
  %(TABLE rows.file.link AS Posts, rows.date AS Date\nFROM "_posts"\nWHERE type = "post" AND draft != true\nFLATTEN dateformat(date, "yyyy") AS year\nGROUP BY year\nSORT year DESC),
  %(TABLE rows.file.link AS Notes, length(rows) AS Count\nFROM "_posts" OR "_notebooks"\nFLATTEN categories AS category\nGROUP BY category\nSORT category ASC),
  %(TABLE\n  description AS Description,\n  difficulty AS Difficulty,\n  estimated_reading_time AS "Read Time"\nFROM "_docs/features"\nWHERE type = "doc" AND file.name != "index"\nSORT title ASC),
  %(TABLE rows.file.link AS Features\nFROM "_docs/features"\nWHERE file.name != "index"\nFLATTEN tags AS tag\nGROUP BY tag\nSORT tag ASC),
  %(TABLE rows.file.link AS Features\nFROM "_docs/features"\nWHERE type = "doc" AND file.name != "index" AND difficulty\nGROUP BY difficulty\nSORT difficulty ASC),
  %(TABLE description AS Description, tags AS Tags\nFROM "_about/features"\nWHERE file.name != "index" AND draft != true\nSORT title ASC),
  %(LIST rows.file.link\nFROM "" AND -"wiki" AND -"_templates" AND -"_moc"\nGROUP BY file.folder AS Folder\nSORT Folder ASC),
  %(TABLE rows.file.link AS Notes\nFROM "_posts" OR "_notebooks"\nFLATTEN tags AS tag\nGROUP BY tag\nSORT tag ASC)
].freeze

# --------------------------------------------------------------- FenceMask

class TestFenceMask < Minitest::Test
  FM = Obsidian::FenceMask

  def test_transform_applies_only_outside_fences
    md = "before [[x]]\n```ruby\ncode [[x]]\n```\nafter [[x]]\n"
    out = FM.apply_outside(md) { |t| t.gsub('[[x]]', 'LINK') }
    assert_includes out, "before LINK\n"
    assert_includes out, "code [[x]]\n"
    assert_includes out, "after LINK\n"
  end

  def test_fence_at_beginning_and_end_of_text
    md = "```\nraw [[x]]\n```"
    out = FM.apply_outside(md) { |t| t.gsub('[[x]]', 'LINK') }
    assert_equal md, out
  end

  def test_tilde_fences
    md = "~~~\ntilde [[x]]\n~~~\ntail [[x]]\n"
    out = FM.apply_outside(md) { |t| t.gsub('[[x]]', 'LINK') }
    assert_includes out, 'tilde [[x]]'
    assert_includes out, 'tail LINK'
  end

  def test_unclosed_fence_runs_to_eof
    md = "start [[x]]\n```\nnever closed [[x]]\n"
    out = FM.apply_outside(md) { |t| t.gsub('[[x]]', 'LINK') }
    assert_includes out, 'start LINK'
    assert_includes out, 'never closed [[x]]'
  end

  def test_inline_code_masked
    md = "use `[[x]]` here and [[x]] there\n"
    out = FM.apply_outside(md) { |t| t.gsub('[[x]]', 'LINK') }
    assert_equal "use `[[x]]` here and LINK there\n", out
  end

  def test_double_backtick_inline_span_with_nested_backtick
    md = "a ``code ` tick [[x]]`` b [[x]]\n"
    out = FM.apply_outside(md) { |t| t.gsub('[[x]]', 'LINK') }
    assert_includes out, '``code ` tick [[x]]``'
    assert_includes out, 'b LINK'
  end

  def test_inline_masking_can_be_disabled
    md = "a `[[x]]` b\n"
    out = FM.apply_outside(md, false) { |t| t.gsub('[[x]]', 'LINK') }
    assert_equal "a `LINK` b\n", out
  end

  def test_replace_fences_targets_info_string
    md = "intro\n```dataview\nLIST\n```\noutro\n"
    out = FM.replace_fences(md) { |info, body| info == 'dataview' ? "<div>#{body.strip}</div>\n" : nil }
    assert_equal "intro\n<div>LIST</div>\noutro\n", out
  end

  def test_replace_fences_skips_nested_fence_inside_outer_fence
    md = "````markdown\n```dataview\nLIST\n```\n````\n"
    out = FM.replace_fences(md) { |info, _body| info == 'dataview' ? 'REPLACED' : nil }
    assert_equal md, out
  end
end

# --------------------------------------------------------------- Wikilinks

class TestWikilinks < Minitest::Test
  RESOLVER = lambda do |target|
    {
      '_docs/setup' => '/docs/setup/',
      '_notes/My Note' => '/notes/my-note/',
      'assets/images/pic.png' => '/assets/images/pic.png'
    }[target]
  end

  def convert(md)
    Obsidian::Wikilinks.convert(md, RESOLVER)
  end

  def test_plain_link
    out = convert('See [[_docs/setup]].')
    assert_includes out, '<a href="/docs/setup/" class="wikilink">setup</a>'
  end

  def test_alias_link
    out = convert('See [[_docs/setup|the setup guide]].')
    assert_includes out, '<a href="/docs/setup/" class="wikilink">the setup guide</a>'
  end

  def test_anchor_link_slugifies_fragment
    out = convert('See [[_docs/setup#Install Steps]].')
    assert_includes out, '<a href="/docs/setup/#install-steps" class="wikilink">setup</a>'
  end

  def test_anchor_link_with_alias
    out = convert('See [[_docs/setup#Install Steps|installation]].')
    assert_includes out, '<a href="/docs/setup/#install-steps" class="wikilink">installation</a>'
  end

  def test_same_page_anchor
    out = convert('Jump to [[#The Heading]].')
    assert_includes out, '<a href="#the-heading" class="wikilink">The Heading</a>'
  end

  def test_image_embed_resolved
    out = convert('Look: ![[assets/images/pic.png]]')
    assert_includes out, '![](/assets/images/pic.png)'
  end

  def test_image_embed_unresolved_keeps_path
    out = convert('Look: ![[missing.png]]')
    assert_includes out, '![](missing.png)'
  end

  def test_note_embed_becomes_link
    out = convert('Inline: ![[_docs/setup]]')
    assert_includes out, '<a href="/docs/setup/" class="wikilink">setup</a>'
  end

  def test_unresolved_link_becomes_span
    out = convert('See [[_docs/nowhere|Nowhere]].')
    assert_includes out, '<span class="wikilink-unresolved">Nowhere</span>'
  end

  def test_display_text_is_html_escaped
    out = convert('See [[_docs/nowhere|a <b> & "q"]].')
    assert_includes out, 'a &lt;b&gt; &amp; &quot;q&quot;'
  end

  def test_links_inside_fences_and_inline_code_untouched
    md = "```\n[[_docs/setup]]\n```\nand `[[_docs/setup]]` but [[_docs/setup]]\n"
    out = convert(md)
    assert_includes out, "```\n[[_docs/setup]]\n```"
    assert_includes out, '`[[_docs/setup]]`'
    assert_includes out, '<a href="/docs/setup/" class="wikilink">setup</a>'
  end

  def test_target_with_spaces
    out = convert('Read [[_notes/My Note]].')
    assert_includes out, '<a href="/notes/my-note/" class="wikilink">My Note</a>'
  end
end

# ---------------------------------------------------------------- Callouts

class TestCallouts < Minitest::Test
  def convert(md)
    Obsidian::Callouts.convert(md)
  end

  def test_github_caps_style_without_title
    out = convert("> [!NOTE]\n> Remember this.\n")
    assert_includes out, 'class="alert alert-info obsidian-callout obsidian-callout-note" markdown="1"'
    assert_includes out, '<strong class="obsidian-callout-title">Note</strong>'
    assert_includes out, "Remember this.\n"
    refute_includes out, '> Remember'
  end

  def test_obsidian_style_with_title
    out = convert("> [!tip] Pro Tip\n> Do the thing.\n")
    assert_includes out, 'alert-success'
    assert_includes out, '<strong class="obsidian-callout-title">Pro Tip</strong>'
    assert_includes out, "Do the thing.\n"
  end

  def test_type_mapping
    assert_includes convert("> [!warning]\n> w\n"), 'alert-warning'
    assert_includes convert("> [!CAUTION]\n> c\n"), 'alert-warning'
    assert_includes convert("> [!danger]\n> d\n"), 'alert-danger'
    assert_includes convert("> [!IMPORTANT]\n> i\n"), 'alert-danger'
    assert_includes convert("> [!quote]\n> q\n"), 'alert-secondary'
    assert_includes convert("> [!example]\n> e\n"), 'alert-light'
    assert_includes convert("> [!question]\n> ?\n"), 'alert-info'
    assert_includes convert("> [!mystery]\n> m\n"), 'alert-info'
  end

  def test_fold_markers_are_stripped
    out = convert("> [!tip]+ Folded Open\n> body\n")
    assert_includes out, '<strong class="obsidian-callout-title">Folded Open</strong>'
    refute_includes out, ']+'
    out = convert("> [!warning]- Folded Closed\n> body\n")
    assert_includes out, 'alert-warning'
  end

  def test_multi_line_body_kept_as_markdown
    out = convert("> [!note] Steps\n> - one\n> - two\n>\n> **bold** tail\n")
    assert_includes out, "- one\n- two\n"
    assert_includes out, '**bold** tail'
  end

  def test_plain_blockquote_untouched
    md = "> just a quote\n> second line\n"
    assert_equal md, convert(md)
  end

  def test_callout_inside_fence_untouched
    md = "```markdown\n> [!note] Example\n> body\n```\n"
    assert_equal md, convert(md)
  end

  def test_text_after_callout_continues
    out = convert("> [!note]\n> body\n\nplain paragraph\n")
    assert_includes out, "</div>\n"
    assert_includes out, 'plain paragraph'
  end
end

# ----------------------------------------------------------- Dataview parse

class TestDataviewParse < Minitest::Test
  DV = Obsidian::Dataview

  def test_every_real_query_parses
    REAL_QUERIES.each_with_index do |q, i|
      parsed = DV.parse(q)
      refute_nil parsed, "query ##{i} failed to parse:\n#{q}"
      assert_includes [:table, :list], parsed.mode
    end
  end

  def test_table_structure
    q = DV.parse(%(TABLE date AS Date, description AS Summary\nFROM "_posts"\nWHERE type = "post" AND draft != true\nSORT date DESC))
    assert_equal :table, q.mode
    assert_equal %w[Date Summary], q.columns.map { |c| c[:label] }
    assert_equal ['_posts'], q.from[:include]
    assert_equal 2, q.where.length
    assert_equal [{ expr: [:field, ['date']], dir: :desc }], q.sort
  end

  def test_multiline_columns_and_quoted_label
    q = DV.parse(%(TABLE\n  description AS Description,\n  estimated_reading_time AS "Read Time"\nFROM "_docs/features"))
    refute_nil q
    assert_equal ['Description', 'Read Time'], q.columns.map { |c| c[:label] }
    assert_equal ['_docs/features'], q.from[:include]
  end

  def test_from_or_folders
    q = DV.parse(%(TABLE date AS Date\nFROM "_posts" OR "_notebooks"))
    assert_equal %w[_posts _notebooks], q.from[:include]
    assert_empty q.from[:exclude]
  end

  def test_from_with_negations
    q = DV.parse(%(LIST rows.file.link\nFROM "" AND -"wiki" AND -"_templates" AND -"_moc"\nGROUP BY file.folder AS Folder\nSORT Folder ASC))
    assert_equal [''], q.from[:include]
    assert_equal %w[wiki _templates _moc], q.from[:exclude]
    assert_equal 'Folder', q.group_by[:alias]
  end

  def test_group_by_function_expression
    q = DV.parse(%(TABLE rows.file.link AS "Documents", length(rows) AS "Count"\nFROM "_docs"\nWHERE type = "doc"\nGROUP BY choice(file.folder = "_docs", "General", regexreplace(file.folder, "^_docs/", "")) AS Section\nSORT Section ASC))
    refute_nil q
    assert_equal 'Section', q.group_by[:alias]
    assert_equal :call, q.group_by[:expr][0]
    assert_equal 'choice', q.group_by[:expr][1]
  end

  def test_limit_and_multi_sort
    q = DV.parse(%(TABLE description AS Summary\nFROM "_about"\nSORT order ASC, title ASC\nLIMIT 15))
    assert_equal 15, q.limit
    assert_equal 2, q.sort.length
    assert_equal :asc, q.sort[0][:dir]
  end

  def test_flatten_before_where_order_tolerated
    q = DV.parse(%(TABLE rows.file.link AS Posts\nFROM "_posts"\nFLATTEN categories AS category\nWHERE type = "post" AND draft != true\nGROUP BY category))
    refute_nil q
    assert_equal 1, q.flatten.length
    assert_equal 'category', q.flatten[0][:alias]
  end

  def test_bare_truthy_where_clause
    q = DV.parse(%(TABLE rows.file.link AS X\nFROM "_docs"\nWHERE type = "doc" AND difficulty\nGROUP BY difficulty))
    assert_equal 2, q.where.length
    assert_equal [:field, ['difficulty']], q.where[1]
  end

  def test_unsupported_queries_return_nil
    assert_nil DV.parse('TASK FROM "_posts"')
    assert_nil DV.parse('not a query at all')
    assert_nil DV.parse('')
    assert_nil DV.parse(%(TABLE date AS\nFROM "_posts"))
  end

  def test_extract_from_survives_parse_failure
    from = DV.extract_from(%(TASK something\nFROM "_posts" OR "_notes"\nWEIRD))
    assert_equal %w[_posts _notes], from[:include]
    assert_nil DV.extract_from('no from here')
  end
end

# ---------------------------------------------------------- Dataview render

class TestDataviewRender < Minitest::Test
  DV = Obsidian::Dataview

  def render(query, docs)
    parsed = DV.parse(query)
    refute_nil parsed, "query failed to parse:\n#{query}"
    html = DV.render(parsed, docs)
    refute_nil html, "query failed to render:\n#{query}"
    html
  end

  def test_flat_table_filters_drafts_and_sorts_desc
    html = render(%(TABLE date AS Date, description AS Summary\nFROM "_posts"\nWHERE type = "post" AND draft != true\nSORT date DESC), Fixtures.posts)
    assert_includes html, '<th>File</th><th>Date</th><th>Summary</th>'
    refute_includes html, 'Hidden'
    a = html.index('Alpha')
    b = html.index('Beta')
    g = html.index('Gamma')
    assert a && b && g, 'all three posts should render'
    assert a < b && b < g, 'posts must be date-descending'
    assert_includes html, '<a href="/_posts/2026-01-10-alpha/">Alpha</a>'
    assert_includes html, '2026-01-10'
  end

  def test_limit_truncates_rows
    html = render(%(TABLE date AS Date\nFROM "_posts"\nWHERE type = "post" AND draft != true\nSORT date DESC\nLIMIT 2), Fixtures.posts)
    assert_includes html, 'Alpha'
    assert_includes html, 'Beta'
    refute_includes html, 'Gamma'
  end

  def test_group_by_category_with_length
    html = render(%(TABLE rows.file.link AS Notes, length(rows) AS Count\nFROM "_posts"\nWHERE type = "post" AND draft != true\nFLATTEN categories AS category\nGROUP BY category\nSORT category ASC), Fixtures.posts)
    assert_includes html, '<th>category</th><th>Notes</th><th>Count</th>'
    dev = html.index('<td>Dev</td>')
    life = html.index('<td>Life</td>')
    notes = html.index('<td>Notes</td>')
    assert dev && life && notes
    assert dev < life && life < notes, 'groups must sort ascending'
    dev_row = html[dev, html.index("</tr>", dev) - dev]
    assert_includes dev_row, 'Alpha'
    assert_includes dev_row, 'Beta'
    assert_includes dev_row, '<td>2</td>'
  end

  def test_group_by_year_via_dateformat_desc
    html = render(%(TABLE rows.file.link AS Posts\nFROM "_posts"\nWHERE type = "post" AND draft != true\nFLATTEN dateformat(date, "yyyy") AS year\nGROUP BY year\nSORT year DESC), Fixtures.posts)
    y26 = html.index('<td>2026</td>')
    y25 = html.index('<td>2025</td>')
    y24 = html.index('<td>2024</td>')
    assert y26 && y25 && y24
    assert y26 < y25 && y25 < y24, 'years must be descending'
  end

  def test_rows_field_projection
    html = render(%(TABLE rows.file.link AS Posts, rows.date AS Date\nFROM "_posts"\nWHERE type = "post" AND draft != true\nFLATTEN dateformat(date, "yyyy") AS year\nGROUP BY year\nSORT year DESC), Fixtures.posts)
    assert_includes html, '2026-01-10'
  end

  def test_choice_and_regexreplace_section_column
    html = render(%(TABLE choice(file.folder = "_docs", "General", regexreplace(file.folder, "^_docs/", "")) AS Section, description AS Summary\nFROM "_docs"\nWHERE type = "doc"\nSORT default(lastmod, date) DESC\nLIMIT 15), Fixtures.docs_collection)
    assert_includes html, '<td>General</td>'
    assert_includes html, '<td>features</td>'
    assert_includes html, '<td>jekyll</td>'
    setup_i = html.index('Setup')
    plugins_i = html.index('Plugins')
    mermaid_i = html.index('Mermaid')
    assert setup_i < plugins_i, 'lastmod fallback must win over date'
    assert plugins_i < mermaid_i
  end

  def test_group_by_function_expression_render
    html = render(%(TABLE rows.file.link AS "Documents", length(rows) AS "Count"\nFROM "_docs"\nWHERE type = "doc"\nGROUP BY choice(file.folder = "_docs", "General", regexreplace(file.folder, "^_docs/", "")) AS Section\nSORT Section ASC), Fixtures.docs_collection)
    assert_includes html, '<th>Section</th><th>Documents</th><th>Count</th>'
    assert_includes html, '<td>General</td>'
    assert_includes html, '<td>features</td>'
  end

  def test_bare_truthy_where_drops_docs_without_field
    html = render(%(TABLE rows.file.link AS "Documents"\nFROM "_docs"\nWHERE type = "doc" AND difficulty\nGROUP BY difficulty AS Level\nSORT Level ASC), Fixtures.docs_collection)
    assert_includes html, '<td>advanced</td>'
    assert_includes html, '<td>beginner</td>'
    refute_includes html, 'Plugins', 'doc without difficulty must be filtered'
  end

  def test_flatten_default_fills_missing_value
    html = render(%(TABLE rows.file.link AS Docs\nFROM "_docs"\nWHERE type = "doc"\nFLATTEN default(difficulty, "intermediate") AS level\nGROUP BY level\nSORT level ASC), Fixtures.docs_collection)
    assert_includes html, '<td>intermediate</td>'
  end

  def test_flatten_tags_group
    html = render(%(TABLE rows.file.link AS Notes\nFROM "_posts"\nWHERE type = "post" AND draft != true\nFLATTEN tags AS tag\nGROUP BY tag\nSORT tag ASC), Fixtures.posts)
    jekyll_i = html.index('<td>jekyll</td>')
    obsidian_i = html.index('<td>obsidian</td>')
    ruby_i = html.index('<td>ruby</td>')
    assert jekyll_i && obsidian_i && ruby_i
    assert jekyll_i < obsidian_i && obsidian_i < ruby_i
    ruby_row = html[ruby_i, html.index('</tr>', ruby_i) - ruby_i]
    assert_includes ruby_row, 'Alpha'
    assert_includes ruby_row, 'Gamma'
  end

  def test_nested_frontmatter_field
    html = render(%(TABLE description AS Summary, quickstart.step AS Step\nFROM "_quickstart"\nWHERE type = "quickstart"\nSORT quickstart.step ASC), Fixtures.quickstart)
    first_i = html.index('First Step')
    second_i = html.index('Second Step')
    assert first_i && second_i
    assert first_i < second_i, 'must sort by nested quickstart.step'
    assert_includes html, '<td>1</td>'
  end

  def test_multi_key_sort_breaks_ties
    html = render(%(TABLE description AS Summary\nFROM "_about"\nWHERE type = "about" AND file.name != "index"\nSORT order ASC, title ASC), Fixtures.about)
    alpha_i = html.index('Alpha2')
    bravo_i = html.index('Bravo')
    assert alpha_i && bravo_i
    assert alpha_i < bravo_i, 'title must break the order tie'
    refute_includes html, '>Idx<'
  end

  def test_grouped_list_render
    html = render(%(LIST rows.file.link\nFROM "" AND -"wiki" AND -"_templates" AND -"_moc"\nGROUP BY file.folder AS Folder\nSORT Folder ASC), Fixtures.posts + [Fixtures.doc('index.md', 'title' => 'Home')])
    assert_includes html, '<ul class="obsidian-dataview dataview-list">'
    assert_includes html, '<strong>_posts</strong>'
    assert_includes html, '<a href="/_posts/2026-01-10-alpha/">Alpha</a>'
    assert_includes html, '&#8212;', 'root files group under an em dash'
  end

  def test_tags_array_renders_comma_joined
    html = render(%(TABLE date AS Date, tags AS Tags\nFROM "_posts"\nWHERE type = "post" AND draft != true\nSORT date DESC), Fixtures.posts)
    assert_includes html, 'ruby, jekyll'
  end

  def test_every_real_query_renders_against_pool
    pool = Fixtures.site_pool
    REAL_QUERIES.each_with_index do |q, i|
      parsed = DV.parse(q)
      refute_nil parsed, "query ##{i} failed to parse"
      docs = ObsidianBridge.docs_for(pool, parsed.from)
      html = DV.render(parsed, docs)
      refute_nil html, "query ##{i} failed to render:\n#{q}"
      assert_includes html, 'obsidian-dataview'
    end
  end
end

# ------------------------------------------------------------------ Bridge

class TestBridgeHelpers < Minitest::Test
  def index
    @index ||= ObsidianBridge.build_index([
      { path: '_docs/jekyll/index.md', url: '/docs/jekyll/', aliases: ['/old-jekyll/'] },
      { path: '_docs/setup.md', url: '/docs/setup/', aliases: nil },
      { path: '_notes/setup.md', url: '/notes/setup/', aliases: [] },
      { path: '_quests/forge-a-quest.md', url: '/quests/forge-a-quest/', aliases: '/quests/forge/' },
      { path: 'assets/images/pic.png', url: '/assets/images/pic.png', aliases: [] }
    ])
  end

  def resolver
    @resolver ||= ObsidianBridge.resolver_for(index)
  end

  def test_resolves_by_vault_path_without_extension
    assert_equal '/docs/jekyll/', resolver.call('_docs/jekyll/index')
  end

  def test_resolves_with_md_extension
    assert_equal '/docs/jekyll/', resolver.call('_docs/jekyll/index.md')
  end

  def test_resolves_case_insensitively
    assert_equal '/docs/jekyll/', resolver.call('_DOCS/Jekyll/Index')
  end

  def test_unique_basename_resolves
    assert_equal '/quests/forge-a-quest/', resolver.call('forge-a-quest')
  end

  def test_ambiguous_basename_does_not_resolve
    assert_nil resolver.call('setup')
  end

  def test_alias_resolves
    assert_equal '/docs/jekyll/', resolver.call('/old-jekyll/')
    assert_equal '/quests/forge-a-quest/', resolver.call('/quests/forge/')
  end

  def test_static_file_resolves_by_basename_and_path
    assert_equal '/assets/images/pic.png', resolver.call('pic.png')
    assert_equal '/assets/images/pic.png', resolver.call('assets/images/pic.png')
  end

  def test_unknown_target_is_nil
    assert_nil resolver.call('_docs/never-written')
  end

  def test_docs_for_include_exclude
    pool = Fixtures.site_pool
    posts = ObsidianBridge.docs_for(pool, include: ['_posts'], exclude: [])
    assert_equal 4, posts.length
    nested = ObsidianBridge.docs_for(pool, include: ['_docs/features'], exclude: [])
    assert_equal 2, nested.length
    multi = ObsidianBridge.docs_for(pool, include: %w[_posts _quickstart], exclude: [])
    assert_equal 6, multi.length
    all = ObsidianBridge.docs_for(pool, include: [''], exclude: %w[wiki _templates _moc])
    assert(all.none? { |d| d[:path].start_with?('wiki/', '_templates/', '_moc/') })
    assert(all.any? { |d| d[:path] == 'index.md' })
  end
end

class TestBridgeTransform < Minitest::Test
  def setup
    @pool = Fixtures.site_pool
    @index = ObsidianBridge.build_index(
      @pool.map { |d| { path: d[:path], url: d[:url], aliases: d[:fm]['aliases'] } }
    )
    @resolver = ObsidianBridge.resolver_for(@index)
  end

  def transform(md)
    ObsidianBridge.transform(md, @resolver, @pool)
  end

  def test_full_pipeline
    md = <<-MD
# Page

See [[_docs/setup|Setup]] and [[_docs/missing]].

> [!tip] Hint
> Use `[[_docs/setup]]` syntax.

```dataview
TABLE date AS Date, description AS Summary
FROM "_posts"
WHERE type = "post" AND draft != true
SORT date DESC
```

```ruby
puts "[[_docs/setup]] stays raw"
```
    MD
    out = transform(md)
    assert_includes out, '<a href="/_docs/setup/" class="wikilink">Setup</a>'
    assert_includes out, '<span class="wikilink-unresolved">missing</span>'
    assert_includes out, 'alert-success'
    assert_includes out, '`[[_docs/setup]]`'
    assert_includes out, 'dataview-table'
    assert_includes out, 'Alpha'
    refute_includes out, '```dataview'
    assert_includes out, "puts \"[[_docs/setup]] stays raw\""
  end

  def test_unsupported_dataview_falls_back_to_link_list
    md = "```dataview\nTASK\nFROM \"_posts\"\nWHERE !completed\n```\n"
    out = transform(md)
    assert_includes out, 'unsupported dataview query'
    assert_includes out, 'dataview-fallback'
    assert_includes out, 'Alpha'
  end

  def test_dataview_sample_inside_outer_fence_is_preserved
    md = "````markdown\n```dataview\nTABLE date AS Date\nFROM \"_posts\"\n```\n````\n"
    out = transform(md)
    assert_includes out, "```dataview"
    refute_includes out, 'dataview-table'
  end
end

class TestPostprocessHtml < Minitest::Test
  BASE = '/zer0-pages'.freeze

  def post(html)
    ObsidianBridge.postprocess_html(html, BASE, 'https://bamr87.github.io')
  end

  def test_prefixes_root_relative_href_and_src
    out = post('<a href="/docs/setup/">x</a><img src="/assets/pic.png">')
    assert_includes out, 'href="/zer0-pages/docs/setup/"'
    assert_includes out, 'src="/zer0-pages/assets/pic.png"'
  end

  def test_does_not_double_prefix
    out = post('<a href="/zer0-pages/docs/">x</a>')
    assert_equal '<a href="/zer0-pages/docs/">x</a>', out
  end

  def test_skips_protocol_relative_and_absolute
    out = post('<a href="//cdn.example.com/x.js">x</a><a href="https://a.b/">y</a>')
    assert_includes out, 'href="//cdn.example.com/x.js"'
    assert_includes out, 'href="https://a.b/"'
  end

  def test_skips_pre_and_code_blocks
    html = '<p><a href="/docs/">go</a></p><pre><code>&lt;a href="/docs/"&gt;raw</code></pre><code>href="/x/"</code>'
    out = post(html)
    assert_includes out, 'href="/zer0-pages/docs/">go'
    assert_includes out, '<pre><code>&lt;a href="/docs/"&gt;raw</code></pre>'
    assert_includes out, '<code>href="/x/"</code>'
  end

  def test_replaces_literal_liquid_leftovers
    out = post('<p>{{ site.url }}/x and {{ site.baseurl }}/y</p><code>{{ site.url }}</code>')
    assert_includes out, 'https://bamr87.github.io/zer0-pages/x'
    assert_includes out, '/zer0-pages/y'
    assert_includes out, '<code>{{ site.url }}</code>'
  end

  def test_noop_when_baseurl_empty
    html = '<a href="/docs/">x</a>'
    assert_equal html, ObsidianBridge.postprocess_html(html, '', 'https://x')
  end

  def test_single_quoted_attributes
    out = post("<a href='/docs/'>x</a>")
    assert_includes out, "href='/zer0-pages/docs/'"
  end
end
