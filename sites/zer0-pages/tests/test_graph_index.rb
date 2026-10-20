# Unit tests for the Obsidian graph index generator
# (pages/_plugins/obsidian/graph_index.rb + the pure helpers of
# pages/_plugins/obsidian_graph_index.rb).
#
# Run from the repo root with system ruby (stdlib only):
#   ruby -Ipages/_plugins tests/test_graph_index.rb
#
# obsidian_graph_index.rb is required without Jekyll loaded, so only the
# pure helper module is defined -- exactly what these tests exercise.

require 'minitest/autorun'
require 'json'
require 'time'

require 'obsidian/graph_index'
require 'obsidian_graph_index'

GI = Obsidian::GraphIndex

# ---------------------------------------------------------------- fixtures

module GraphFixtures
  module_function

  def graph_doc
    {
      title: 'Graph View',
      path: '_docs/obsidian/graph.md',
      url: '/zer0-pages/docs/obsidian/graph/',
      collection: 'docs',
      tags: %w[obsidian graph],
      categories: %w[Documentation Obsidian],
      aliases: ['/docs/obsidian/graph/'],
      content: <<-MD
# Graph View

Every page and every [[_docs/obsidian/getting-started|getting started]]
link becomes a node. This one is dead: [[_docs/missing/page|gone]].

{% include obsidian/full-graph.html %}
      MD
    }
  end

  def getting_started_doc
    {
      title: 'Getting Started with the Obsidian Vault',
      path: '_docs/obsidian/getting-started.md',
      url: '/zer0-pages/docs/obsidian/getting-started/',
      collection: 'docs',
      tags: %w[obsidian setup],
      categories: %w[Documentation],
      aliases: ['/docs/obsidian/getting-started/'],
      content: <<-MD
# Getting Started

See the [[_docs/obsidian/graph]] and an anchored
[[_docs/obsidian/graph#Legend|legend link]] plus a transclusion
![[_notes/scratch]] and an image embed ![[assets/images/pic.png]].

```bash
# fenced code -- none of these become edges
if [[ -f setup.md ]]; then echo "[[_docs/never-a-page]]"; fi
```

Inline code is masked too: `[[_docs/also-never]]`.
      MD
    }
  end

  def post_doc
    {
      title: 'Hello World',
      path: '_posts/2026-01-01-hello-world.md',
      url: '/zer0-pages/posts/hello-world/',
      collection: 'posts',
      tags: %w[intro],
      categories: %w[Posts],
      aliases: nil,
      content: <<-MD
> [!tip] Welcome
> First post. Read [[_docs/obsidian/getting-started]] twice:
> [[_docs/obsidian/getting-started|again]].

#{'Lorem ipsum dolor sit amet, consectetur adipiscing elit. ' * 10}
      MD
    }
  end

  def scratch_note
    {
      title: 'Scratch',
      path: '_notes/scratch.md',
      url: '/zer0-pages/notes/scratch/',
      collection: 'notes',
      tags: [],
      categories: [],
      aliases: [],
      content: "A tiny note with no links.\n"
    }
  end

  def pool
    [graph_doc, getting_started_doc, post_doc, scratch_note]
  end
end

# Mirrors buildLookup + normalize in the theme's assets/js/obsidian-graph.js:
# keys are NORMALIZED title / basename / aliases, first entry wins.
module ClientLookup
  module_function

  def normalize(value)
    value.to_s.downcase.strip.gsub(/\s+/, ' ')
  end

  def by_key(entries)
    lookup = {}
    entries.each do |entry|
      next if entry['url'].to_s.empty?
      keys = [entry['title'], entry['basename']] + (entry['aliases'] || [])
      keys.each do |key|
        nk = normalize(key)
        next if nk.empty? || lookup.key?(nk)
        lookup[nk] = entry
      end
    end
    lookup
  end
end

# ----------------------------------------------------------------- payload

class TestGraphPayload < Minitest::Test
  def payload
    @payload ||= GI.build_payload(GraphFixtures.pool, Time.utc(2026, 7, 5, 12, 0, 0))
  end

  def test_json_is_valid_and_roundtrips
    parsed = JSON.parse(GI.to_json(GraphFixtures.pool, Time.utc(2026, 7, 5)))
    assert_equal %w[generated_at count entries].sort, parsed.keys.sort
    assert_kind_of Array, parsed['entries']
    assert_equal parsed['count'], parsed['entries'].length
  end

  def test_generated_at_is_iso8601
    assert_equal '2026-07-05T12:00:00Z', payload['generated_at']
  end

  def test_node_count_matches_doc_pool
    assert_equal GraphFixtures.pool.length, payload['count']
    assert_equal GraphFixtures.pool.length, payload['entries'].length
  end

  def test_entry_shape_matches_theme_contract
    entry = payload['entries'].first
    %w[title basename url collection tags categories aliases outgoing excerpt].each do |key|
      assert entry.key?(key), "entry must carry #{key}"
    end
    assert_equal 'Graph View', entry['title']
    assert_equal 'graph', entry['basename']
    assert_equal 'docs', entry['collection']
    assert_equal '/zer0-pages/docs/obsidian/graph/', entry['url']
  end

  def test_posts_collection_is_posts
    post = payload['entries'].find { |e| e['basename'] == '2026-01-01-hello-world' }
    assert_equal 'posts', post['collection']
  end
end

# ------------------------------------------------------------------- edges

class TestGraphEdges < Minitest::Test
  def entries
    @entries ||= GI.build_payload(GraphFixtures.pool)['entries']
  end

  def entry(basename)
    entries.find { |e| e['basename'] == basename }
  end

  def test_edge_extraction_skips_code_fences_and_inline_code
    outgoing = entry('getting-started')['outgoing']
    refute_includes outgoing, '_docs/never-a-page'
    refute_includes outgoing, '_docs/also-never'
  end

  def test_anchor_and_alias_are_stripped_and_targets_unique
    outgoing = entry('getting-started')['outgoing']
    assert_includes outgoing, '_docs/obsidian/graph'
    assert_equal 1, outgoing.count('_docs/obsidian/graph'),
                 'anchored + plain links to one target must dedupe'
    assert_equal 1, entry('2026-01-01-hello-world')['outgoing']
                    .count('_docs/obsidian/getting-started')
  end

  def test_note_embeds_are_edges_but_image_embeds_are_not
    outgoing = entry('getting-started')['outgoing']
    assert_includes outgoing, '_notes/scratch'
    refute_includes outgoing, 'assets/images/pic.png'
  end

  def test_wikilinks_inside_callouts_are_edges
    assert_includes entry('2026-01-01-hello-world')['outgoing'],
                    '_docs/obsidian/getting-started'
  end

  def test_path_qualified_targets_resolve_client_side
    by_key = ClientLookup.by_key(entries)
    # Every non-dead outgoing target in the fixture pool must resolve through
    # the SAME lookup the browser builds (title/basename/aliases).
    resolved = by_key[ClientLookup.normalize('_docs/obsidian/graph')]
    refute_nil resolved, 'vault path must be resolvable via aliases[]'
    assert_equal '/zer0-pages/docs/obsidian/graph/', resolved['url']
    assert_equal '/zer0-pages/notes/scratch/',
                 by_key[ClientLookup.normalize('_notes/scratch')]['url']
    assert_equal '/zer0-pages/docs/obsidian/getting-started/',
                 by_key[ClientLookup.normalize('_docs/obsidian/getting-started')]['url']
  end

  def test_vault_path_added_to_aliases_after_frontmatter_aliases
    aliases = entry('graph')['aliases']
    assert_equal ['/docs/obsidian/graph/', '_docs/obsidian/graph'], aliases
    # No duplicate when the frontmatter already carries the vault path.
    entry = GI.build_entry(title: 'X', path: '_docs/x.md', url: '/x/',
                           collection: 'docs', tags: [], categories: [],
                           aliases: ['_docs/x'], content: '')
    assert_equal ['_docs/x'], entry['aliases']
  end

  def test_dead_link_stays_in_outgoing_and_unresolved
    outgoing = entry('graph')['outgoing']
    assert_includes outgoing, '_docs/missing/page'
    by_key = ClientLookup.by_key(entries)
    assert_nil by_key[ClientLookup.normalize('_docs/missing/page')],
               'dead targets must stay unresolved (they render as red broken nodes)'
  end
end

# ----------------------------------------------------------------- excerpt

class TestGraphExcerpt < Minitest::Test
  def test_excerpt_drops_fences_markup_liquid_and_wikilink_syntax
    excerpt = GI.build_entry(GraphFixtures.graph_doc)['excerpt']
    refute_includes excerpt, '```'
    refute_includes excerpt, '[['
    refute_includes excerpt, ']]'
    refute_includes excerpt, '{%'
    refute_includes excerpt, '# Graph View'
    assert_includes excerpt, 'getting started'
    assert_includes excerpt, 'gone', 'wikilink display text must survive'
  end

  def test_excerpt_drops_fenced_code_content
    excerpt = GI.build_entry(GraphFixtures.getting_started_doc)['excerpt']
    refute_includes excerpt, 'echo'
    refute_includes excerpt, '_docs/also-never'
  end

  def test_excerpt_truncates_to_240_chars
    excerpt = GI.build_entry(GraphFixtures.post_doc)['excerpt']
    assert_operator excerpt.length, :<=, 240
    assert excerpt.end_with?('…'), 'long excerpts must end with an ellipsis'
  end

  def test_excerpt_strips_callout_and_blockquote_markers
    excerpt = GI.build_entry(GraphFixtures.post_doc)['excerpt']
    refute_includes excerpt, '[!tip]'
    refute_includes excerpt, '> '
    assert_includes excerpt, 'Welcome'
    assert_includes excerpt, 'First post.'
  end

  def test_short_excerpt_is_untouched
    assert_equal 'A tiny note with no links.',
                 GI.build_entry(GraphFixtures.scratch_note)['excerpt']
  end
end

# ------------------------------------------------------------- jekyll glue

class TestJekyllGlueHelpers < Minitest::Test
  FakeCollection = Struct.new(:label)

  class FakeDoc
    attr_reader :data, :url, :content, :relative_path

    def initialize(data:, url:, content:, relative_path:, collection: nil)
      @data = data
      @url = url
      @content = content
      @relative_path = relative_path
      @collection = collection
    end

    def collection
      @collection
    end
  end

  def test_doc_hash_prefixes_baseurl_and_maps_fields
    doc = FakeDoc.new(
      data: { 'title' => 'Setup', 'tags' => %w[t], 'categories' => %w[c],
              'aliases' => ['/old/'] },
      url: '/docs/setup/',
      content: 'See [[_docs/other]].',
      relative_path: '_docs/setup.md',
      collection: FakeCollection.new('docs')
    )
    hash = ObsidianGraphIndex.doc_hash(doc, '/zer0-pages')
    assert_equal '/zer0-pages/docs/setup/', hash[:url]
    assert_equal '_docs/setup.md', hash[:path]
    assert_equal 'docs', hash[:collection]
    entry = GI.build_entry(hash)
    assert_equal ['/old/', '_docs/setup'], entry['aliases']
    assert_equal ['_docs/other'], entry['outgoing']
  end

  def test_collection_label_nil_for_standalone_pages
    page = FakeDoc.new(data: { 'title' => 'Home' }, url: '/', content: '',
                       relative_path: 'index.md')
    assert_nil ObsidianGraphIndex.collection_label(page)
    assert_nil ObsidianGraphIndex.doc_hash(page)[:collection]
  end
end
