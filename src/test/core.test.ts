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
import {
  asIndexCache,
  buildIndex,
  emptyIndexCache,
  pageToRecord,
  slimPage,
} from '../core/content/pageIndex';
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
import { EXEC_VECTORS, evaluateExecGate, insideWorkspace } from '../core/shared/trust';
import { formatDate, parseDate } from '../core/shared/dates';
import { compileGlob, globMatches, toPosix } from '../core/shared/glob';
import { pyJsonDump, readJsonc } from '../core/shared/jsonio';
import { utcStamp } from '../core/shared/timestamp';
import {
  MINIMAL_STOP_WORDS,
  NO_STOP_WORDS,
  STOP_WORDS,
  slugify,
  transliterate,
  truncate,
} from '../core/shared/text';
import {
  UNKNOWN_COUNT,
  countLabel,
  isMeasured,
  type ExecGateInput,
  type PageEntry,
  type Zer0Config,
} from '../core/shared/types';

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

  test('YAML: a plain scalar folds its more-indented continuation lines', () => {
    // The shape `wtd fleet adopt` writes: a `summary:` wrapped at 80 columns.
    const data = parseYamlSubset(
      [
        'summary: A self-growing encyclopedia of irony — the germinate engine scouts candidates,',
        '  scores them at the Alanis Gate, and drafts passes into vault/nursery/ for a human to merge.',
        'after: next',
        'paragraphs: first line',
        '  still first',
        '',
        '  second paragraph # with a comment',
        'nested:',
        '  inner: wraps onto',
        '    a deeper line',
        '  sibling: 1',
        'items:',
        '- one that',
        '  wraps',
        '- two',
        'stops: at a',
        '  looks: like a key',
        'number: 42',
        '  and text',
      ].join('\n'),
    );
    assert.equal(
      data.summary,
      'A self-growing encyclopedia of irony — the germinate engine scouts candidates, ' +
        'scores them at the Alanis Gate, and drafts passes into vault/nursery/ for a human to merge.',
      'a line break inside a plain scalar folds to one space',
    );
    assert.equal(data.after, 'next', 'the key after the wrapped value is still read');
    assert.equal(
      data.paragraphs,
      'first line still first\nsecond paragraph',
      'a blank line folds to a newline and a trailing comment is stripped',
    );
    assert.deepEqual(data.nested, { inner: 'wraps onto a deeper line', sibling: 1 });
    assert.deepEqual(data.items, ['one that wraps', 'two'], 'sequence items fold the same way');
    assert.equal(
      data.stops,
      'at a',
      'a more-indented line that reads as a key ends the scalar and is skipped, as before',
    );
    assert.equal(data.number, '42 and text', 'a value that wraps is prose, never coerced');
    assert.equal(parseYamlSubset('n: 42\n').n, 42, 'a single-line value still coerces');
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

  test('slugify drops only function words by default, and transliterates', () => {
    assert.equal(slugify('The Big Thing'), 'big-thing', '"the" goes, "thing" is a word');
    assert.equal(slugify('Zero-CMS'), 'zero-cms', 'nothing meaningful is dropped');
    assert.equal(slugify('Café Métier'), 'cafe-metier');
    assert.equal(transliterate('Café métier'), 'Cafe metier');
    assert.equal(truncate('abcdefghij', 5), 'abcd…');
  });

  /**
   * The three cases that made `minimal` the default. Every one of these is a
   * real title from a site this extension was run against, and under FM's list
   * every one of them loses a word it cannot afford to lose — the third does
   * not merely shorten the URL, it reverses the claim.
   */
  test('slugify presets: minimal keeps the words a title needs, smart is FM verbatim', () => {
    const cases: ReadonlyArray<readonly [string, string, string]> = [
      ['MCP for the back office', 'mcp-back-office', 'mcp-office'],
      [
        'From prompts to pipelines: agentic AI in VS Code',
        'prompts-pipelines-agentic-ai-vs-code',
        'prompts-pipelines-agentic-ai-code',
      ],
      [
        'Migrating to QAD without losing data',
        'migrating-qad-without-losing-data',
        'migrating-qad-losing-data',
      ],
    ];
    for (const [title, minimal, smart] of cases) {
      assert.equal(slugify(title, MINIMAL_STOP_WORDS), minimal, `minimal: ${title}`);
      assert.equal(slugify(title, STOP_WORDS), smart, `smart: ${title}`);
      assert.equal(slugify(title), minimal, `minimal is the default: ${title}`);
    }

    assert.equal(
      slugify('MCP for the back office', NO_STOP_WORDS),
      'mcp-for-the-back-office',
      '"none" keeps every word',
    );
    assert.equal(
      slugify('MCP for the back office', new Set(['mcp'])),
      'for-the-back-office',
      'a literal list replaces the preset outright',
    );
    assert.equal(slugify('The And Of', STOP_WORDS), '', 'all-stop-words still yields the empty slug');
  });

  test('slug.stopWords resolves presets, and a typo falls back to the default', () => {
    const preset = (value: unknown) => resolveConfig('/w', { slug: { stopWords: value } }).slug.stopWords;

    assert.ok(preset('smart').has('back'), '"smart" is FM’s list');
    assert.ok(!preset('minimal').has('back'), '"minimal" keeps "back"');
    assert.equal(preset('none').size, 0, '"none" drops nothing');
    assert.equal(preset('  SMART  ').size, STOP_WORDS.size, 'the name is trimmed and case-folded');

    assert.deepEqual([...preset(['Foo', ' BAR '])], ['foo', 'bar'], 'a literal list is normalised');
    assert.equal(preset([]).size, 0, 'an empty array is honoured — it means "drop nothing"');

    // A typo must not silently change every future permalink of the site.
    assert.equal(preset('mininal').size, MINIMAL_STOP_WORDS.size, 'an unknown name keeps the default');
    assert.equal(preset(42).size, MINIMAL_STOP_WORDS.size, 'so does a value of the wrong type');
    assert.equal(
      resolveConfig('/w', {}).slug.stopWords,
      MINIMAL_STOP_WORDS,
      'and so does saying nothing at all',
    );
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

  /**
   * A scan reads front matter and never bodies, so it has no word count. It
   * used to say `0`, which is not "we did not look" — it is "this article is
   * empty", and it reached the content tree and the MCP `zer0_get_content`
   * answer as a fact about a two-thousand-word page.
   */
  test('an uncounted body reports UNKNOWN_COUNT, never a confident zero', async () => {
    const cfg = fixtureConfig(workspaceSettings());
    const { pages } = await buildIndex(cfg);
    const page = pages[0];
    assert.ok(page !== undefined);

    const scanned = pageToRecord(cfg, page);
    assert.equal(scanned.wordCount, UNKNOWN_COUNT, 'the same sentinel health uses');
    assert.equal(scanned.headingCount, UNKNOWN_COUNT);
    assert.equal(isMeasured(scanned.wordCount), false);
    assert.equal(countLabel(scanned.wordCount), 'unknown');
    assert.equal(countLabel(scanned.wordCount, 'uncounted'), 'uncounted');

    // Hand it the details and the same record reports the real numbers.
    const details = getArticleDetails(fixture(scanned.path));
    const counted = pageToRecord(cfg, page, details);
    assert.ok(counted.wordCount > 0, 'a body that was read is reported');
    assert.equal(isMeasured(counted.wordCount), true);
    assert.equal(countLabel(counted.wordCount), String(details.wordCount));

    // Zero is still a legitimate measurement and must not read as unknown.
    assert.equal(countLabel(0), '0');
    assert.equal(isMeasured(0), true);
  });

  /**
   * `changed` exists so the shell can skip a `workspaceState` write. On a real
   * site that cache is megabytes, and a rebuild fires on every file save — most
   * of them reusing every page. `false` has to mean "I have nothing new to
   * store", and it has to be *false* only then.
   */
  test('a cache from before the platform existed is refused, not trusted', () => {
    // Version 2 is not bookkeeping. A v1 entry was built by code that could not
    // tell a Jekyll site from an MkDocs one, so its slug, its date and its
    // draft flag are not answers this version would give. Reusing one would
    // show a person a page list computed under the wrong rules, which is worse
    // than rescanning.
    const current = emptyIndexCache();
    assert.equal(current.version, 2);
    assert.notEqual(asIndexCache(current), undefined, 'a current cache is usable');
    assert.equal(asIndexCache({ ...current, version: 1 }), undefined, 'a v1 cache must be refused');
  });

  test('changed is false over an unchanged tree, and true once an mtime has moved', async () => {
    const cfg = fixtureConfig(workspaceSettings());
    const cold = await buildIndex(cfg);
    assert.equal(cold.changed, true, 'the first run built a cache nobody was holding');

    const warm = await buildIndex(cfg, cold.cache);
    assert.equal(warm.changed, false, 'every candidate reused and the same set of them');
    assert.equal(warm.pages.length, cold.pages.length);

    // A touch, to `buildIndex`, is exactly "the cache remembers an mtime this
    // file no longer has" — so the cache is what moves here. This suite reads
    // the fixture and never writes it; the tests that write live elsewhere.
    const entries = { ...cold.cache.entries };
    const [touchedPath] = Object.keys(entries);
    assert.ok(touchedPath !== undefined);
    const stale = entries[touchedPath];
    assert.ok(stale !== undefined);
    entries[touchedPath] = { mtime: stale.mtime - 1_000, page: stale.page };

    const touched = await buildIndex(cfg, { ...cold.cache, entries });
    assert.equal(touched.changed, true, 'one re-parsed page is a cache worth writing');
    assert.notEqual(touched.pages[0], cold.pages[0], 'the touched page was read again');
    assert.deepEqual(
      touched.pages.map((page) => page.relPath),
      cold.pages.map((page) => page.relPath),
      'and it came back in its own place, not at the front',
    );

    // A file that left the tree parses nothing and still changes the cache: the
    // rebuilt one is smaller than the one that was passed in.
    const withGhost = { ...cold.cache, entries: { ...cold.cache.entries } };
    const ghost = cold.pages[0];
    assert.ok(ghost !== undefined);
    withGhost.entries['/nowhere/deleted-yesterday.md'] = { mtime: 1, page: ghost };
    const shrunk = await buildIndex(cfg, withGhost);
    assert.equal(shrunk.changed, true, 'a deletion is a change even though nothing was parsed');
    assert.equal(shrunk.pages.length, cold.pages.length);
  });

  /**
   * The cold path stats and reads eight candidates at a time, so results arrive
   * out of order. They are folded back **by candidate index**, which is what
   * keeps this true: the page list is sorted by path, not by whichever file the
   * disk answered first, and a cache hit is still the same object.
   */
  test('the concurrent cold path keeps page order and cached identity', async () => {
    const cfg = fixtureConfig(workspaceSettings());
    const [left, right] = await Promise.all([buildIndex(cfg), buildIndex(cfg)]);
    assert.ok(left !== undefined && right !== undefined);

    const order = left.pages.map((page) => page.relPath);
    assert.deepEqual(order, right.pages.map((page) => page.relPath), 'two cold scans agree');
    assert.deepEqual(order, [...order].sort(), 'completion order never reaches the result');

    const warm = await buildIndex(cfg, left.cache);
    assert.equal(warm.pages.length, left.pages.length);
    for (let index = 0; index < left.pages.length; index += 1) {
      assert.equal(warm.pages[index], left.pages[index], `page ${index} came back by identity`);
    }
  });

  /**
   * `PageEntry.data` is the whole front-matter block — right for the panel,
   * which edits arbitrary fields, and wrong for a search reply, where it is
   * about 1.2 MB of payload nothing on the other side reads.
   */
  test('slimPage is the row a view draws, without the front matter behind it', async () => {
    const cfg = fixtureConfig(workspaceSettings());
    const { pages } = await buildIndex(cfg);
    const page = pages[0];
    assert.ok(page !== undefined);

    const slim = slimPage(page);
    assert.deepEqual(Object.keys(slim), [
      'relPath',
      'path',
      'title',
      'slug',
      'date',
      'draft',
      'collection',
      'modified',
    ]);
    assert.equal('data' in slim, false, 'the whole point: the front matter stays host-side');
    assert.equal(slim.relPath, page.relPath);
    assert.equal(slim.path, page.filePath, 'absolute, for the command that opens it');
    assert.equal(slim.title, 'Governed publishing without a platform');
    assert.equal(slim.slug, 'governed-publishing');
    assert.equal(slim.date, '2026-07-08', 'the date is the string that was written');
    assert.equal(slim.draft, false);
    assert.equal(slim.modified, page.modified);

    // `collection` is the answer `pageToRecord` gives, reached without a config
    // to strip the workspace root with.
    const nested: PageEntry = {
      ...page,
      folder: path.join(WORKSPACE, 'pages/_posts'),
      relPath: 'pages/_posts/corp/2026-07-08-governed-publishing.md',
    };
    assert.equal(slimPage(nested).collection, 'corp');
    assert.equal(slimPage(nested).collection, pageToRecord(cfg, nested).collection);
    assert.equal(slimPage(page).collection, pageToRecord(cfg, page).collection);
  });

  /**
   * The summary line is the only place a run reports what it did, and both a
   * human reading the log and the cache test above read it by shape. Concurrency
   * changed how the work is done and must not change a character of this.
   */
  test('the summary line keeps its parsed/cached/skipped format', async () => {
    const cfg = fixtureConfig(workspaceSettings());
    const lines: string[] = [];
    const log = {
      info: () => undefined,
      warn: () => undefined,
      error: () => undefined,
      verbose: (message: string) => void lines.push(message),
    };

    const cold = await buildIndex(cfg, undefined, log);
    const first = lines.find((line) => line.startsWith('page index: pages='));
    assert.ok(first !== undefined, 'one summary line per run');
    assert.match(
      first,
      /^page index: pages=6 parsed=7 cached=0 skipped=1 folders=2 ms=\d+$/,
      `the cold run reads all seven files, six of which are pages: ${first}`,
    );

    lines.length = 0;
    await buildIndex(cfg, cold.cache, log);
    const second = lines.find((line) => line.startsWith('page index: pages='));
    assert.ok(second !== undefined);
    assert.match(second, /^page index: pages=6 parsed=0 cached=6 skipped=1 folders=2 ms=\d+$/, second);
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

suite('core: the execution gate (D13)', () => {
  /** A gate input for one vector, over the fixture workspace. */
  const gateFor = (vector: (typeof EXEC_VECTORS)[number], trusted: boolean): ExecGateInput => ({
    trusted,
    workspaceRoot: WORKSPACE,
    scriptPath: path.join(WORKSPACE, 'scripts/cms/cms.py'),
    interpreter: 'python3',
    layer: 'zer0.json',
    vector,
  });

  test('an untrusted workspace refuses all five execution vectors', () => {
    assert.deepEqual(
      [...EXEC_VECTORS],
      ['engine', 'normalizer', 'placeholder', 'agent', 'verify'],
      'the doc claims five paths can start a process; this is the list it means',
    );

    for (const vector of EXEC_VECTORS) {
      const blocker = evaluateExecGate(gateFor(vector, false));
      assert.ok(blocker !== undefined, `${vector} must refuse in an untrusted workspace`);
      assert.equal(blocker.reason, 'untrusted-workspace');
      assert.ok(
        blocker.message.includes('not trusted'),
        'the refusal names the thing the person has to change',
      );
      // Trust is the OUTER gate: it is reported even though the path is fine.
      assert.equal(evaluateExecGate(gateFor(vector, true)), undefined, `${vector} runs when trusted`);
    }
  });

  test('insideWorkspace rejects traversal and absolute paths outside the root', () => {
    assert.equal(insideWorkspace(WORKSPACE, path.join(WORKSPACE, 'scripts/x.py')), true);
    assert.equal(insideWorkspace(WORKSPACE, WORKSPACE), true, 'the root is inside itself');
    assert.equal(insideWorkspace(WORKSPACE, 'scripts/x.py'), true, 'relative resolves against the root');

    // `../` traversal, however it is spelled.
    assert.equal(insideWorkspace(WORKSPACE, '../../evil.py'), false);
    assert.equal(insideWorkspace(WORKSPACE, path.join(WORKSPACE, '..', 'evil.py')), false);
    assert.equal(insideWorkspace(WORKSPACE, 'scripts/../../../evil.py'), false);

    // Absolute, and outside.
    assert.equal(insideWorkspace(WORKSPACE, path.join(os.tmpdir(), 'evil.py')), false);

    // A sibling whose name merely starts the same way is not inside: the
    // comparison is on path boundaries, the bug `folderForFile` also fixes.
    assert.equal(insideWorkspace(WORKSPACE, `${WORKSPACE}-old/x.py`), false);

    // No root means no inside, and an empty path is not a path.
    assert.equal(insideWorkspace('', path.join(WORKSPACE, 'x.py')), false);
    assert.equal(insideWorkspace(WORKSPACE, ''), false);

    // A refusal survives a TRUSTED workspace: a `zer0.json` arrives with the
    // clone, and trusting the folder is not consent to run something outside it.
    const escaped = evaluateExecGate({
      trusted: true,
      workspaceRoot: WORKSPACE,
      scriptPath: path.join(WORKSPACE, '../../evil.py'),
      interpreter: 'python3',
      layer: 'zer0.json',
      vector: 'engine',
    });
    assert.equal(escaped?.reason, 'outside-workspace');
  });

  test('agent.permissionMode from zer0.json is clamped to the three-value enum', () => {
    // `asString` used to hand whatever the file said straight to the SDK.
    for (const mode of ['default', 'acceptEdits', 'plan']) {
      const cfg = resolveConfig(WORKSPACE, { agent: { permissionMode: mode } }, {});
      assert.equal(cfg.agent.permissionMode, mode, 'a legal value survives the file layer');
    }
    for (const mode of ['dontAsk', 'auto', 'bypassPermissions', '', 42]) {
      const cfg = resolveConfig(WORKSPACE, { agent: { permissionMode: mode } }, {});
      assert.equal(
        cfg.agent.permissionMode,
        'default',
        `a repository must not be able to reach the SDK with "${String(mode)}"`,
      );
    }
  });

  test('configFile is not read from zer0.json — the file cannot rename itself', () => {
    const cfg = resolveConfig(WORKSPACE, { configFile: 'somewhere-else.json' }, {});
    assert.equal(cfg.configFile, 'zer0.json', 'two layers, not three: settings, then the default');

    const named = resolveConfig(WORKSPACE, { configFile: 'somewhere-else.json' }, {
      configFile: 'cms.json',
    });
    assert.equal(named.configFile, 'cms.json', 'the settings layer still names it');
  });
});

suite("core: the parser's warnings channel — what it had to guess at (WP2.3)", () => {
  /** The block for a body, with the fences added. Never throws, by contract. */
  function block(body: string, fence = '---'): { warnings: string[]; data: Record<string, unknown> } {
    const { block: parsed } = splitFrontMatter(`${fence}\n${body}\n${fence}\nbody\n`);
    assert.ok(parsed !== null, 'the parser still returns a block — it never throws');
    return { warnings: parsed.warnings, data: parsed.data };
  }

  test('a clean block warns about nothing, which is the normal state', () => {
    const clean = block(
      [
        'title: Hello',
        'tags: [a, b]',
        'nested:',
        '  key: value',
        'folded: >',
        '  prose with & and * and [an unclosed bracket',
        '  and a second line',
        'list:',
        '  - a & b',
        '  - "quoted, with a comma"',
      ].join('\n'),
    );
    assert.deepEqual(clean.warnings, [], `an ampersand in prose is an ampersand: ${clean.warnings.join(' | ')}`);
    assert.equal(clean.data.title, 'Hello');
  });

  test('anchors and aliases are named, each on its own line', () => {
    const anchored = block(['defaults: &series', '  layout: post', 'title: x'].join('\n'));
    assert.equal(anchored.warnings.length, 1);
    assert.match(anchored.warnings[0] ?? '', /^line 1: a YAML anchor \(`&series`\)/);
    assert.equal(anchored.data.defaults, '&series', 'and the value really is the literal text');

    const aliased = block(['title: x', 'meta: *series'].join('\n'));
    assert.equal(aliased.warnings.length, 1);
    assert.match(aliased.warnings[0] ?? '', /^line 2: a YAML alias \(`\*series`\)/);

    // `*emphasis*` is markdown, not an alias, and must not be reported as one.
    assert.deepEqual(block('title: a *bold* claim about 5 > 3').warnings, []);
  });

  test('merge keys and tags are named', () => {
    const merged = block(['title: x', '<<: *defaults'].join('\n'));
    assert.equal(merged.warnings.length, 1, 'the merge subsumes the alias on the same line');
    assert.match(merged.warnings[0] ?? '', /^line 2: a YAML merge key \(`<<`\)/);

    const tagged = block(['count: !!str 5', 'thing: !Custom {a: 1}'].join('\n'));
    assert.equal(tagged.warnings.length, 2);
    assert.match(tagged.warnings[0] ?? '', /^line 1: a YAML tag \(`!!str`\)/);
    assert.match(tagged.warnings[1] ?? '', /^line 2: a YAML tag \(`!Custom`\)/);
  });

  test('a value truncated to its first line says so — quoted or flow', () => {
    const quoted = block(['title: "one', '  two"', 'date: 2026-01-01'].join('\n'));
    assert.equal(quoted.warnings.length, 1);
    assert.match(quoted.warnings[0] ?? '', /^line 1: a quoted scalar that closes on a later line/);
    assert.equal(quoted.data.title, '"one', 'which is exactly what the caller could not otherwise tell');

    const flow = block(['tags: [a,', '  b]'].join('\n'));
    assert.equal(flow.warnings.length, 1);
    assert.match(flow.warnings[0] ?? '', /^line 1: a flow collection that closes on a later line/);
  });

  test('an undecoded escape, and the two TOML constructs', () => {
    const escaped = block('title: "caf\\u00e9"');
    assert.equal(escaped.warnings.length, 1);
    assert.match(escaped.warnings[0] ?? '', /^line 1: a `\\u` escape is not decoded/);
    assert.deepEqual(block('title: "a \\n b \\" c"').warnings, [], 'the eight escapes we do decode are silent');

    const toml = block(
      ['title = "x"', "note = '''", 'over two lines', "'''", '[[items]]', 'name = "a"'].join('\n'),
      '+++',
    );
    assert.equal(toml.warnings.length, 2);
    assert.match(toml.warnings[0] ?? '', /^line 2: a TOML multi-line literal string/);
    assert.match(toml.warnings[1] ?? '', /^line 5: a TOML array-of-tables \(`\[\[items\]\]`\)/);
    assert.deepEqual(block(['title = "x"', '[meta]', 'a = 1'].join('\n'), '+++').warnings, []);
  });
});
