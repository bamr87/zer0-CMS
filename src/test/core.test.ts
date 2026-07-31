/**
 * Unit tests for the pure-Node core: configuration, the front-matter engine,
 * line surgery, the shared primitives, the page index and the SEO metrics.
 *
 * No `vscode`, no network, and no writes anywhere — every assertion here reads
 * the checked-in fixture workspace or builds its input in memory. The tests
 * that do write live in `governance.test.ts` and `golden.test.ts`, and they
 * write into a fresh `os.tmpdir()` directory that they remove again.
 */

import { strict as assert } from 'node:assert';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

import { parseArticle, readArticle, setFieldValue, writeArticle } from '../core/content/article';
import {
  asBool,
  asList,
  asString,
  detectFormat,
  parseYamlSubset,
  splitFrontMatter,
} from '../core/content/frontmatter';
import { buildIndex, pageToRecord } from '../core/content/pageIndex';
import {
  DENSITY_MAX,
  DENSITY_MIN,
  KEYWORD_CHECK_NAMES,
  KEYWORD_CHECK_TOTAL,
  WORDS_PER_MINUTE,
  getArticleDetails,
  isHealthyDensity,
  keywordAnalysis,
  keywordDensity,
  seoInsights,
} from '../core/content/seo';
import {
  applyChanges,
  serializeFrontMatter,
  serializeOptions,
  stitch,
  updateFrontMatterKeys,
} from '../core/content/serialize';
import { roundHalfEven } from '../core/catering/catering';
import { formatPercent, formatThousands } from '../core/catering/worklist';
import { resolveConfig } from '../core/shared/config';
import type { Zer0Settings } from '../core/shared/config';
import { formatDate, parseDate } from '../core/shared/dates';
import { compileGlob, globMatches, toPosix } from '../core/shared/glob';
import { pyJsonDump, readJsonc } from '../core/shared/jsonio';
import { utcStamp } from '../core/shared/timestamp';
import { slugify, transliterate, truncate } from '../core/shared/text';
import type { Zer0Config } from '../core/shared/types';

// ---------------------------------------------------------------------------
// Fixture access. `__dirname` is `out/test`; the fixtures stay in `src/test`.
// ---------------------------------------------------------------------------

const FIXTURES = path.resolve(__dirname, '../../src/test/fixtures');
const WORKSPACE = path.join(FIXTURES, 'workspace');

function fixture(relative: string): string {
  return fs.readFileSync(path.join(WORKSPACE, relative), 'utf8');
}

/** The `zer0.json` layer, exactly as the extension reads it. */
function projectFile(): unknown {
  return readJsonc<unknown>(fixture('zer0.json'));
}

/**
 * The settings layer, derived from the fixture's own `.vscode/settings.json`
 * rather than restated here — a test that invented its own settings object
 * would prove the merge works on values no workspace actually holds.
 */
function workspaceSettings(): Zer0Settings {
  const raw = readJsonc<Record<string, unknown>>(fixture('.vscode/settings.json'));
  const settings: Zer0Settings = {};
  const publishAllow = raw['zer0Cms.governance.publishAllow'];
  const bannedPatternsFile = raw['zer0Cms.governance.bannedPatternsFile'];
  if (typeof publishAllow === 'boolean' || typeof bannedPatternsFile === 'string') {
    settings.governance = {};
    if (typeof publishAllow === 'boolean') {
      settings.governance.publishAllow = publishAllow;
    }
    if (typeof bannedPatternsFile === 'string') {
      settings.governance.bannedPatternsFile = bannedPatternsFile;
    }
  }
  return settings;
}

function fixtureConfig(settings: Zer0Settings = {}): Zer0Config {
  return resolveConfig(WORKSPACE, projectFile(), settings);
}

// ---------------------------------------------------------------------------

suite('core: configuration — the three layers (D2)', () => {
  test('a VS Code setting beats zer0.json', () => {
    const file = fixtureConfig();
    assert.equal(file.governance.publishAllow, true, 'zer0.json allows publishing');

    const merged = fixtureConfig(workspaceSettings());
    assert.equal(
      merged.governance.publishAllow,
      false,
      '.vscode/settings.json must win — the publish gate is the point of the layer order',
    );
  });

  test('zer0.json beats the built-in default', () => {
    const cfg = fixtureConfig(workspaceSettings());
    assert.deepEqual(cfg.frontMatter.commaSeparatedFields, ['keywords']);
    assert.equal(cfg.content.publicFolder, 'assets');
    assert.equal(cfg.content.autoUpdateModifiedDate, true);
    assert.deepEqual(cfg.taxonomy.categories, ['corp', 'tech']);
  });

  test('a key no layer names falls through to the default', () => {
    const cfg = fixtureConfig(workspaceSettings());
    assert.equal(cfg.slug.prefix, '');
    assert.equal(cfg.slug.template, null);
    assert.equal(cfg.agent.model, 'claude-opus-5', 'decision D10');
    assert.equal(cfg.dashboard.pageSize, 16);
  });

  test('a settings key present but undefined falls through to zer0.json', () => {
    // This is what `vscode.workspace.getConfiguration().get<T>()` hands back
    // for a key nobody set, so the merge has to read it as "absent".
    const cfg = fixtureConfig({ governance: { publishAllow: undefined } });
    assert.equal(cfg.governance.publishAllow, true);
  });

  test('[[workspace]] expands while originalPath keeps the configured spelling', () => {
    const cfg = fixtureConfig();
    const [corp, tech] = cfg.contentFolders;
    assert.ok(corp !== undefined && tech !== undefined, 'two content folders');
    assert.equal(corp.path, path.join(WORKSPACE, 'pages/_posts/corp'));
    assert.equal(corp.originalPath, '[[workspace]]/pages/_posts/corp');
    assert.ok(path.isAbsolute(tech.path));
    assert.deepEqual(tech.contentTypes, ['post', 'note']);
  });
});

suite('core: pyJsonDump — byte parity with json.dumps', () => {
  test("sort_keys orders by code point and the separators are Python's", () => {
    // Python emits `", "` and `": "` when no indent is given; a JS
    // `JSON.stringify` emits neither, which is the whole reason this exists.
    assert.equal(pyJsonDump({ b: 1, a: 2 }, { sortKeys: true }), '{"a": 2, "b": 1}');
    assert.equal(pyJsonDump({ Z: 1, a: 2, _m: 3 }, { sortKeys: true }), '{"Z": 1, "_m": 3, "a": 2}');
    assert.equal(pyJsonDump([1, 'two', true, null]), '[1, "two", true, null]');
  });

  test('ensure_ascii escapes everything above U+007E, including DEL', () => {
    assert.equal(pyJsonDump({ a: '\u007f' }, { ensureAscii: true }), '{"a": "\\u007f"}');
    assert.equal(pyJsonDump({ 'café': 1 }, { ensureAscii: true }), '{"caf\\u00e9": 1}');
    // An astral character is a surrogate pair in Python's output too.
    assert.equal(pyJsonDump(['\u{1f680}'], { ensureAscii: true }), '["\\ud83d\\ude80"]');
    assert.equal(pyJsonDump({ 'café': 1 }, { ensureAscii: false }), '{"café": 1}');
  });

  test('indent nests like json.dumps(indent=2), and empty containers stay flat', () => {
    assert.equal(
      pyJsonDump({ a: { b: [1, { c: 2 }] } }, { indent: 2 }),
      '{\n  "a": {\n    "b": [\n      1,\n      {\n        "c": 2\n      }\n    ]\n  }\n}',
    );
    assert.equal(pyJsonDump({}, { indent: 2 }), '{}');
    assert.equal(pyJsonDump([], { indent: 2 }), '[]');
  });
});

suite('core: front matter — three dialects, one shape', () => {
  test('YAML: nested maps, block scalars, flow collections and coercion', () => {
    const data = parseYamlSubset(
      [
        'title: Plain',
        'quoted: "with #hash and : colon"',
        'flow: [a, "b, c", d]',
        'block:',
        '  - one',
        '  - two',
        'seo:',
        '  title: Nested',
        '  noindex: false',
        'text: |',
        '  line one',
        '  line two',
        'n: 42',
        'f: 1.5',
        'yes: true',
        'trailing: value # a comment',
        'empty:',
      ].join('\n'),
    );
    assert.equal(data.title, 'Plain');
    assert.equal(data.quoted, 'with #hash and : colon');
    assert.deepEqual(data.flow, ['a', 'b, c', 'd'], 'a quoted comma does not split the flow list');
    assert.deepEqual(data.block, ['one', 'two']);
    assert.deepEqual(data.seo, { title: 'Nested', noindex: false });
    assert.equal(data.text, 'line one\nline two\n');
    assert.equal(data.n, 42);
    assert.equal(data.f, 1.5);
    assert.equal(data.yes, true);
    assert.equal(data.trailing, 'value');
    assert.equal(data.empty, null, 'an empty value is null, not an empty string');
  });

  test('the documented non-goals stay strings rather than being guessed at', () => {
    const data = parseYamlSubset('a: yes\nb: no\nc: 007\nd: 2026-07-08\ne: 99999999999999999999');
    assert.equal(data.a, 'yes', 'YAML 1.1 booleans stay strings — a field whose value is "no"');
    assert.equal(data.b, 'no');
    assert.equal(data.c, '007', 'a zero-padded integer is an identifier, not a number');
    assert.equal(data.d, '2026-07-08', 'date-shaped values stay strings');
    assert.equal(data.e, '99999999999999999999', 'past MAX_SAFE_INTEGER stays a string');
    assert.equal(asBool(data.a), true, 'asBool still reads it as truthy where a caller asks');
    assert.deepEqual(asList('draft'), ['draft'], 'a lone scalar reads as a one-element list');
    assert.deepEqual(asList(null), []);
    assert.equal(asString(undefined, 'fallback'), 'fallback');
  });

  test('TOML front matter parses from the fixture', () => {
    const raw = fixture('pages/_posts/tech/2026-07-20-toml-dialect.md');
    assert.equal(detectFormat(raw), 'toml');
    const { block } = splitFrontMatter(raw);
    assert.ok(block !== null);
    assert.equal(block.format, 'toml');
    assert.equal(block.data.title, 'The TOML dialect');
    assert.deepEqual(block.data.tags, ['jekyll', 'publishing']);
    assert.equal(block.data.weight, 40);
    assert.equal(block.data.featured, false);
  });

  test('JSON front matter parses from the fixture', () => {
    const raw = fixture('pages/_posts/tech/2026-07-22-json-dialect.md');
    assert.equal(detectFormat(raw), 'json');
    const { block, body } = splitFrontMatter(raw);
    assert.ok(block !== null);
    assert.equal(block.format, 'json');
    assert.equal(block.data.slug, 'json-dialect');
    assert.deepEqual(block.data.tags, ['mcp', 'jekyll']);
    assert.ok(body.includes('# The JSON dialect'), 'the body starts after the matching brace');
    assert.equal(
      block.data.featured,
      false,
      'the fixture description holds a `}` inside a string — the block must not end there',
    );
  });

  test('a file with no front matter is a normal answer, not an error', () => {
    const raw = fixture('pages/_posts/tech/README.md');
    const { block, body } = splitFrontMatter(raw);
    assert.equal(block, null);
    assert.equal(body, raw, 'the whole file is the body');

    const article = parseArticle('/tmp/none.md', raw);
    assert.deepEqual(article.data, {});
    assert.equal(article.block, null);
  });

  test('serialize → parse round-trips every value shape', () => {
    const cfg = fixtureConfig();
    const opts = serializeOptions(cfg, 'yaml');
    const data = {
      title: 'A plain title',
      quoted: 'no',
      tags: ['a', 'b'],
      count: 3,
      flag: false,
      nested: { title: 'T', depth: 2 },
      multiline: 'first\nsecond\n',
      nothing: null,
    };
    const emitted = serializeFrontMatter(data, opts);
    assert.deepEqual(parseYamlSubset(emitted), data);
    assert.ok(
      emitted.includes('quoted: "no"'),
      'a string a reader would coerce is quoted on emit, so Jekyll agrees with us',
    );
    assert.equal(parseYamlSubset(serializeFrontMatter(parseYamlSubset(emitted), opts)).quoted, 'no');
  });
});

suite('core: front matter is data, never a prototype', () => {
  const polluted = (): unknown => ({} as Record<string, unknown>).publishAllow;

  test('a TOML `[__proto__]` table does not reach Object.prototype', () => {
    // `descend()` walked into `node['__proto__']`, which on a plain object is
    // `Object.prototype` and passes every "is this a nested mapping?" test.
    // Assigning through it set a key every object in the extension host could
    // see — including the `{}` that `resolveConfig` reads `governance` off,
    // which flipped `publishAllow` from false to true.
    const { block } = splitFrontMatter('+++\ntitle = "Hello"\n[__proto__]\npublishAllow = true\n+++\nBody\n');
    assert.ok(block !== null);
    assert.equal(polluted(), undefined, 'Object.prototype is untouched');
    assert.deepEqual(block.data.__proto__, { publishAllow: true }, 'and the key is kept as data');
    assert.equal(
      Object.prototype.hasOwnProperty.call(block.data, '__proto__'),
      true,
      'as an own property, not a prototype swap',
    );
  });

  test('the other two spellings of the same walk are closed too', () => {
    const dotted = splitFrontMatter('+++\n__proto__.publishAllow = true\n+++\n').block;
    assert.ok(dotted !== null);
    assert.equal(polluted(), undefined);

    const nested = splitFrontMatter('+++\n[a.__proto__]\npublishAllow = true\n+++\n').block;
    assert.ok(nested !== null);
    assert.equal(polluted(), undefined);

    const yaml = parseYamlSubset('__proto__:\n  publishAllow: true\n');
    assert.equal(polluted(), undefined);
    assert.deepEqual(yaml.__proto__, { publishAllow: true });

    const json = splitFrontMatter('{"__proto__": {"publishAllow": true}}\nBody\n').block;
    assert.ok(json !== null);
    assert.equal(polluted(), undefined);
  });

  test('a `__proto__` KeyChange cannot escape the object it addresses', () => {
    const out = applyChanges({ title: 'x' }, [{ key: '__proto__.publishAllow', value: true }]);
    assert.equal(polluted(), undefined);
    assert.deepEqual(out.__proto__, { publishAllow: true });

    const emitted = updateFrontMatterKeys(
      'title: x',
      [{ key: '__proto__.publishAllow', value: true }],
      serializeOptions(fixtureConfig(), 'yaml'),
    );
    assert.equal(polluted(), undefined);
    assert.equal(emitted, 'title: x\n__proto__:\n  publishAllow: true');
  });

  test('the publish gate is unreachable through a content file', () => {
    // The end of the chain the pollution reached: a `zer0.json` with no
    // `governance` section at all inherited the polluted `true`.
    splitFrontMatter('+++\n[__proto__]\npublishAllow = true\n+++\n');
    const cfg = resolveConfig('/tmp/ws', { contentFolders: [] }, {});
    assert.equal(cfg.governance.publishAllow, false, 'the default, not an inherited true');
  });
});

suite('core: line surgery preserves what it did not touch (D7)', () => {
  const source = (): { raw: string; blockRaw: string; body: string } => {
    const raw = fixture('pages/_posts/corp/2026-07-12-house-style.md');
    const { block, body } = splitFrontMatter(raw);
    assert.ok(block !== null);
    return { raw, blockRaw: block.raw, body };
  };

  test('changing one key changes exactly one line, comments untouched', () => {
    const cfg = fixtureConfig();
    const { raw, blockRaw, body } = source();
    const next = updateFrontMatterKeys(
      blockRaw,
      [{ key: 'title', value: 'A different title' }],
      serializeOptions(cfg, 'yaml'),
    );
    assert.ok(next !== null, 'a top-level YAML key is always locatable');

    const { block } = splitFrontMatter(raw);
    assert.ok(block !== null);
    const rebuilt = stitch(block, next, body, 'yaml');

    const before = raw.split('\n');
    const after = rebuilt.split('\n');
    assert.equal(after.length, before.length, 'the line count never moves');
    const changed = before
      .map((line, i) => (line === after[i] ? null : i))
      .filter((i): i is number => i !== null);
    assert.equal(changed.length, 1, `exactly one line differs (got ${changed.length})`);
    assert.equal(after[changed[0] as number], 'title: A different title');

    // The three comment forms the fixture carries, all still byte-identical.
    assert.ok(rebuilt.includes("# House style is checked by the guard, not by a reviewer's memory."));
    assert.ok(rebuilt.includes('slug: house-style          # keep this stem'));
    assert.ok(rebuilt.includes('  - governance   # the only tag the guard cares about'));
    assert.ok(rebuilt.includes('\n\n# Taxonomy below.'), 'the blank line survives too');
  });

  test('a key the block does not have is appended before the closing fence', () => {
    const cfg = fixtureConfig();
    const { blockRaw } = source();
    const next = updateFrontMatterKeys(
      blockRaw,
      [{ key: 'audience', value: 'executives' }],
      serializeOptions(cfg, 'yaml'),
    );
    assert.ok(next !== null);
    const lines = next.split('\n');
    assert.equal(lines.length, blockRaw.split('\n').length + 1);
    assert.equal(lines[lines.length - 1], 'audience: executives');
    assert.ok(next.startsWith(blockRaw), 'every pre-existing byte is carried through unchanged');
  });

  test('an empty change set is byte-identical in all three dialects', () => {
    const cfg = fixtureConfig();
    for (const [file, format] of [
      ['pages/_posts/corp/2026-07-12-house-style.md', 'yaml'],
      ['pages/_posts/tech/2026-07-20-toml-dialect.md', 'toml'],
      ['pages/_posts/tech/2026-07-22-json-dialect.md', 'json'],
    ] as const) {
      const { block } = splitFrontMatter(fixture(file));
      assert.ok(block !== null);
      assert.equal(block.format, format);
      assert.equal(
        updateFrontMatterKeys(block.raw, [], serializeOptions(cfg, format)),
        block.raw,
        `${format}: an edit-free save must not rewrite a byte`,
      );
    }
  });

  test('TOML and JSON blocks answer null so the caller re-serialises', () => {
    const cfg = fixtureConfig();
    for (const [file, format] of [
      ['pages/_posts/tech/2026-07-20-toml-dialect.md', 'toml'],
      ['pages/_posts/tech/2026-07-22-json-dialect.md', 'json'],
    ] as const) {
      const { block } = splitFrontMatter(fixture(file));
      assert.ok(block !== null);
      assert.equal(
        updateFrontMatterKeys(block.raw, [{ key: 'title', value: 'x' }], serializeOptions(cfg, format)),
        null,
        `${format}: line surgery is YAML-only by design`,
      );
    }
  });

  test('a nested path whose parent is missing grows the nesting in place', () => {
    const cfg = fixtureConfig();
    const opts = serializeOptions(cfg, 'yaml');
    const { blockRaw } = source();

    // The fixture block has no `seo:` map. Answering `null` here handed the
    // whole block to a full re-emit, which rebuilds it from what the parser
    // understood — deleting every comment in it for the sake of one new key.
    const next = updateFrontMatterKeys(blockRaw, [{ key: 'seo.title', value: 'X' }], opts);
    assert.ok(next !== null);
    assert.ok(next.startsWith(blockRaw), 'every pre-existing byte is carried through unchanged');
    assert.equal(next.slice(blockRaw.length), '\nseo:\n  title: X');
    assert.deepEqual(parseYamlSubset(next).seo, { title: 'X' });

    // With the parent present the same change is placed inside it.
    const withParent = 'title: T\nseo:\n  noindex: false\n';
    const inside = updateFrontMatterKeys(withParent, [{ key: 'seo.title', value: 'X' }], opts);
    assert.ok(inside !== null);
    assert.deepEqual(parseYamlSubset(inside).seo, { noindex: false, title: 'X' });

    // A parent holding a scalar is the one shape no writer can place a child
    // in. That is the remaining `null`, and `writeArticle` turns it into a
    // refusal rather than a rewrite — see the article suite.
    assert.equal(
      updateFrontMatterKeys('title: T\nseo: a string\n', [{ key: 'seo.title', value: 'X' }], opts),
      null,
    );
  });

  test('deleting a duplicated key removes every occurrence, not just the last', () => {
    const opts = serializeOptions(fixtureConfig(), 'yaml');
    // The parser resolves duplicates last-wins, so this block reads
    // `{draft: false}`. Splicing out only the last range resurrected the
    // earlier one: clearing the field returned a published page to draft.
    const raw = 'draft: true\ntitle: x\ndraft: false';
    assert.equal(parseYamlSubset(raw).draft, false);

    const next = updateFrontMatterKeys(raw, [{ key: 'draft', value: undefined }], opts);
    assert.equal(next, 'title: x');
    assert.equal('draft' in parseYamlSubset(next ?? ''), false, 'the field is cleared, not flipped');

    // Setting is unaffected: it rewrites the range the parser reads.
    assert.equal(
      updateFrontMatterKeys(raw, [{ key: 'draft', value: true }], opts),
      'draft: true\ntitle: x\ndraft: true',
    );
  });

  test('the block’s own line ending is the only one that decides the block’s', () => {
    const opts = serializeOptions(fixtureConfig(), 'yaml');

    // A one-line CRLF block: `raw` has had its trailing `\r\n` removed, so
    // there is no CRLF left in it to detect. Guessing LF rewrote every line
    // ending in the file on the first metadata save.
    const crlf = splitFrontMatter('---\r\nstatus: draft\r\n---\r\nBody\r\n');
    assert.ok(crlf.block !== null);
    assert.equal(crlf.block.eol, '\r\n');
    assert.equal(crlf.block.raw.includes('\r\n'), false, 'nothing in `raw` could have said so');
    const flipped = updateFrontMatterKeys(
      crlf.block.raw,
      [{ key: 'status', value: 'published' }],
      opts,
      crlf.block.eol,
    );
    assert.ok(flipped !== null);
    assert.equal(
      stitch(crlf.block, flipped, crlf.body, 'yaml'),
      '---\r\nstatus: published\r\n---\r\nBody\r\n',
    );

    // And the reverse: CRLF *in the body* must not put CRs on the fences of a
    // pure-LF front-matter block.
    const mixed = splitFrontMatter('---\ntitle: x\nstatus: draft\n---\n\n```\nwindows\r\nline\r\n```\n');
    assert.ok(mixed.block !== null);
    assert.equal(mixed.block.eol, '\n');
    const kept = updateFrontMatterKeys(
      mixed.block.raw,
      [{ key: 'status', value: 'published' }],
      opts,
      mixed.block.eol,
    );
    assert.ok(kept !== null);
    const rebuilt = stitch(mixed.block, kept, mixed.body, 'yaml');
    assert.equal(rebuilt.slice(0, rebuilt.indexOf('```')).includes('\r'), false);
    assert.ok(rebuilt.includes('windows\r\nline\r\n'), 'the body keeps its own endings');
  });

  test('inserting a key into a CRLF block does not leave one line without a CR', () => {
    const opts = serializeOptions(fixtureConfig(), 'yaml');
    const { block } = splitFrontMatter('---\r\na: 1\r\nb: 2\r\n---\r\n');
    assert.ok(block !== null);
    const next = updateFrontMatterKeys(block.raw, [{ key: 'c', value: 4 }], opts, block.eol);
    assert.equal(next, 'a: 1\r\nb: 2\r\nc: 4');
  });
});

suite('core: writeArticle never rebuilds a YAML block from the parse', () => {
  const scratch = (): string => fs.mkdtempSync(path.join(os.tmpdir(), 'zer0-cms-article-'));

  /**
   * The exact shape from the audit: an anchored mapping (which the parser reads
   * as the literal string `"&series"`, dropping its two children), a comment,
   * and a plain scalar wrapped onto a second line (which the parser truncates).
   * All three survive on disk only because surgery never re-emits them.
   */
  const LOSSY =
    '---\n' +
    '# Shared defaults for this series\n' +
    'defaults: &series\n' +
    '  layout: post\n' +
    '  author: Amr\n' +
    'description: a long description that the author\n' +
    '  wrapped onto a second line\n' +
    'title: Real post\n' +
    '---\n' +
    '\nBody\n';

  test('editing a nested key in a file full of unreadable YAML keeps every byte of it', async () => {
    const dir = scratch();
    try {
      const file = path.join(dir, 'post.md');
      fs.writeFileSync(file, LOSSY, 'utf8');

      const article = await readArticle(file);
      assert.equal(article.data.defaults, '&series', 'the parser really cannot read this');
      assert.equal(article.data.layout, undefined);

      // What the panel sends when someone types an SEO title.
      await writeArticle(article, setFieldValue(article.data, ['seo', 'title'], 'X'), fixtureConfig());

      const written = fs.readFileSync(file, 'utf8');
      for (const line of ['# Shared defaults for this series', 'defaults: &series', '  layout: post', '  author: Amr', '  wrapped onto a second line']) {
        assert.ok(written.includes(line), `"${line}" survived`);
      }
      assert.ok(written.includes('seo:\n  title: X'), 'and the edit landed');
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test('a change that cannot be placed is refused, not written around', async () => {
    const dir = scratch();
    try {
      const file = path.join(dir, 'blocked.md');
      const source = '---\n# keep me\nseo: a plain string\n---\n\nBody\n';
      fs.writeFileSync(file, source, 'utf8');

      const article = await readArticle(file);
      await assert.rejects(
        writeArticle(article, [{ key: 'seo.title', value: 'X' }], fixtureConfig()),
        /scalar or a sequence/,
        'the old fallback rewrote the whole block without even making this change',
      );
      assert.equal(fs.readFileSync(file, 'utf8'), source, 'the file is untouched');
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test('a file with no front matter still gets a block, and TOML still re-emits', async () => {
    const dir = scratch();
    try {
      const bare = path.join(dir, 'bare.md');
      fs.writeFileSync(bare, 'Just prose.\n', 'utf8');
      const article = await readArticle(bare);
      await writeArticle(article, [{ key: 'title', value: 'T' }], fixtureConfig());
      assert.equal(fs.readFileSync(bare, 'utf8'), '---\ntitle: T\n---\nJust prose.\n');

      const toml = path.join(dir, 'toml.md');
      fs.writeFileSync(toml, '+++\ntitle = "T"\n+++\n\nBody\n', 'utf8');
      const tomlArticle = await readArticle(toml);
      await writeArticle(tomlArticle, [{ key: 'title', value: 'U' }], fixtureConfig());
      assert.ok(fs.readFileSync(toml, 'utf8').includes('title = "U"'));
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});

suite('core: shared primitives', () => {
  test('compileGlob translates a base and matches on whole segments', () => {
    const glob = compileGlob('pages/**/*.md');
    assert.equal(glob.base, 'pages');
    assert.equal(globMatches('pages/a/b.md', [glob]), true);
    assert.equal(globMatches('pages/a/b/c.md', [glob]), true);
    assert.equal(globMatches('pages/a/b.txt', [glob]), false);
    assert.equal(globMatches('other/a/b.md', [glob]), false);
    assert.equal(toPosix(path.join('a', 'b', 'c.md')), 'a/b/c.md');
  });

  test('slugify drops FM’s stop words and transliterates', () => {
    assert.equal(slugify('The Big Thing'), 'big', '"the" and "thing" are stop words');
    assert.equal(slugify('Zero-CMS'), 'cms', 'FM’s list contains "zero" — inherited, deliberate');
    assert.equal(slugify('Café Métier'), 'cafe-metier');
    assert.equal(transliterate('Café métier'), 'Cafe metier');
    assert.equal(truncate('abcdefghij', 5), 'abcd…');
  });

  test('formatDate/parseDate round-trip on both sides of a DST boundary', () => {
    const summer = new Date(Date.UTC(2026, 6, 8, 15, 30));
    const winter = new Date(Date.UTC(2026, 0, 8, 15, 30));
    const zone = 'America/New_York';

    assert.equal(formatDate(summer, 'yyyy-MM-dd HH:mm XXX', zone), '2026-07-08 11:30 -04:00');
    assert.equal(formatDate(winter, 'yyyy-MM-dd HH:mm XXX', zone), '2026-01-08 10:30 -05:00');
    assert.equal(formatDate(summer, 'MMM EEEE aaa', 'UTC'), 'Jul Wednesday pm');

    for (const date of [summer, winter]) {
      const text = formatDate(date, "yyyy-MM-dd'T'HH:mm:ssXXX", zone);
      const back = parseDate(text);
      assert.ok(back !== null, `parseDate reads back ${text}`);
      assert.equal(back.getTime(), date.getTime());
    }
    assert.equal(parseDate('not a date'), null);
  });

  test('the number and timestamp formatters agree with Python', () => {
    assert.equal(roundHalfEven(0.5, 0), 0);
    assert.equal(roundHalfEven(1.5, 0), 2);
    assert.equal(roundHalfEven(2.5, 0), 2);
    assert.equal(roundHalfEven(0.12345, 4), 0.1234);
    assert.equal(formatThousands(12000), '12,000');
    assert.equal(formatThousands(999), '999');
    assert.equal(formatPercent(0.031234), '3.12%');
    assert.match(utcStamp(new Date(Date.UTC(2026, 6, 31, 9, 5, 3))), /^2026-07-31T09:05:03Z$/);
  });
});

suite('core: the page index', () => {
  test('the first run indexes the fixture and skips what is not a page', async () => {
    const cfg = fixtureConfig(workspaceSettings());
    const { pages, cache } = await buildIndex(cfg);

    assert.equal(pages.length, 6, 'six markdown pages across the two content folders');
    assert.deepEqual(
      pages.map((page) => page.relPath),
      [
        'pages/_posts/corp/2026-07-08-governed-publishing.md',
        'pages/_posts/corp/2026-07-12-house-style.md',
        'pages/_posts/corp/2026-07-25-work-in-progress.md',
        'pages/_posts/tech/2026-07-06-mcp-for-the-back-office.md',
        'pages/_posts/tech/2026-07-20-toml-dialect.md',
        'pages/_posts/tech/2026-07-22-json-dialect.md',
      ],
      'sorted by workspace-relative path; README.md carries no front matter',
    );
    assert.deepEqual(
      Object.keys(cache.skipped ?? {}).map((file) => path.basename(file)),
      ['README.md'],
      'the skipped file keeps its mtime so it is not re-read next time',
    );

    const first = pages[0];
    assert.ok(first !== undefined);
    assert.equal(first.title, 'Governed publishing without a platform');
    assert.equal(first.slug, 'governed-publishing');
    assert.equal(first.date, '2026-07-08');
    assert.equal(first.draft, false);
    assert.deepEqual(first.tags, ['governance', 'publishing']);
    assert.equal(first.previewImage, 'assets/images/governed-publishing.png');

    const draft = pages.find((page) => page.slug === 'work-in-progress');
    assert.ok(draft !== undefined);
    assert.equal(draft.draft, true);
  });

  test('a second run over an unchanged tree re-parses zero files', async () => {
    const cfg = fixtureConfig(workspaceSettings());
    const first = await buildIndex(cfg);

    const lines: string[] = [];
    const log = {
      info: () => undefined,
      warn: () => undefined,
      error: () => undefined,
      verbose: (message: string) => void lines.push(message),
    };
    const second = await buildIndex(cfg, first.cache, log);

    assert.equal(second.pages.length, first.pages.length);
    assert.equal(
      second.pages[0],
      first.pages[0],
      'a cache hit reuses the PageEntry object itself — the cheapest correct answer',
    );
    const summary = lines.find((line) => line.includes('pages='));
    assert.ok(summary !== undefined, 'buildIndex logs one summary line per run');
    assert.match(summary, /parsed=0 /, `nothing was re-read: ${summary}`);
    assert.match(summary, /cached=6 /);
    assert.match(summary, /skipped=1 /);
  });

  test('pageToRecord degrades honestly when the engine has not scored a page (D9)', async () => {
    const cfg = fixtureConfig(workspaceSettings());
    const { pages } = await buildIndex(cfg);
    const page = pages[0];
    assert.ok(page !== undefined);

    const record = pageToRecord(cfg, page);
    assert.equal(record.health, -1, 'unknown, not zero');
    assert.equal(record.freshness, 'unknown');
    assert.equal(record.draft, false);
    assert.equal(record.structural, false);
    assert.equal(record.frontmatterPresent, true);
    assert.equal(record.path, 'pages/_posts/corp/2026-07-08-governed-publishing.md');
    assert.equal(record.date, '2026-07-08');
    assert.equal(record.lastmod, '2026-07-09');
  });
});

suite('core: SEO metrics', () => {
  const article = (): { data: ReturnType<typeof parseYamlSubset>; body: string } => {
    const raw = fixture('pages/_posts/tech/2026-07-06-mcp-for-the-back-office.md');
    const { block, body } = splitFrontMatter(raw);
    assert.ok(block !== null);
    return { data: block.data, body };
  };

  test('insights render in order, and a threshold of 0 switches its row off', () => {
    const cfg = fixtureConfig();
    const { data, body } = article();
    const details = getArticleDetails(body);
    const rows = seoInsights(cfg, data, cfg.contentTypes[0], details);

    assert.deepEqual(
      rows.map((row) => row.label),
      [
        'Title',
        'slug',
        'Description',
        'Article length',
        'Headings',
        'Paragraphs',
        'Internal links',
        'External links',
        'Images',
      ],
      'the content type’s own field titles, then the raw counts',
    );
    assert.equal(rows[0]?.recommendation, '60 chars');
    assert.equal(rows[0]?.isValid, true);
    const articleLength = rows[3];
    assert.ok(articleLength !== undefined);
    assert.equal(
      'isValid' in articleLength,
      false,
      'Article length is a target, never a verdict — it renders as an em dash',
    );

    const off = resolveConfig(WORKSPACE, {
      ...(projectFile() as Record<string, unknown>),
      seo: { titleLength: 0, descriptionLength: 0 },
    });
    const suppressed = seoInsights(off, data, off.contentTypes[0], details);
    assert.equal(suppressed.length, rows.length - 2, 'a threshold of 0 means "stop telling me"');
    assert.equal(
      suppressed.some((row) => row.label === 'Title'),
      false,
    );
  });

  test('getArticleDetails is a line scan, with its documented divergences', () => {
    const prose = [
      '# Heading one',
      '',
      'First paragraph with words in it.',
      '',
      '## Heading two',
      '',
      '![alt](/assets/a.png)',
      '',
      'See [inside](/pages/x/) and [outside](https://example.test/).',
    ];
    const fenced = [...prose];
    fenced.splice(4, 0, '```ts', 'const ignored = "these words are not prose";', '```', '');

    const details = getArticleDetails(fenced.join('\n'));
    assert.equal(details.headings, 2);
    assert.deepEqual(details.headingsText, ['Heading one', 'Heading two']);
    assert.equal(details.images, 1);
    assert.equal(details.internalLinks, 1);
    assert.equal(details.externalLinks, 1);
    assert.equal(details.firstParagraph, 'First paragraph with words in it.');
    assert.equal(
      details.paragraphs,
      2,
      'a line holding only an image counts as an image, not as a paragraph — mdast would disagree',
    );
    assert.equal(
      details.wordCount,
      getArticleDetails(prose.join('\n')).wordCount,
      'a fenced block is skipped whole, so adding one does not move the word count',
    );
    assert.ok(details.readingTime >= 1, `whole minutes at ${WORDS_PER_MINUTE} words per minute`);

    // `content` is the keyword-check surface: shortcodes removed, nothing else.
    assert.equal(getArticleDetails('Body with {{< note >}} in it.').content, 'Body with  in it.');
  });

  test('the six keyword checks, and density only where there is something to divide by', () => {
    const cfg = fixtureConfig();
    const { data, body } = article();
    const details = getArticleDetails(body);

    assert.equal(KEYWORD_CHECK_TOTAL, 6);
    assert.deepEqual(KEYWORD_CHECK_NAMES, [
      'Title',
      'Description',
      'Slug',
      'Content',
      'Headings',
      'First paragraph',
    ]);

    const info = keywordAnalysis('back office', data, details, cfg);
    assert.equal(info.total, 6);
    assert.equal(info.checks.length, 6);
    assert.deepEqual(
      info.checks.map((check) => check.passed),
      [true, false, true, true, true, false],
      'title/slug/content/headings hit; the description says "small-business systems"',
    );
    assert.equal(info.passed, 4);

    // A keyword containing a regex metacharacter must not throw — FM's version
    // interpolated it raw and took the panel down with a SyntaxError.
    assert.doesNotThrow(() => keywordAnalysis('back (office)', data, details, cfg));

    assert.equal(keywordDensity('', details), null);
    assert.equal(keywordAnalysis('', data, details, cfg).passed, 0);
    assert.equal(isHealthyDensity(null), false);
    assert.equal(isHealthyDensity(DENSITY_MIN), true);
    assert.equal(isHealthyDensity(DENSITY_MAX), false, 'the green band is half-open');
    assert.equal(isHealthyDensity(DENSITY_MIN - 0.01), false);
  });
});
