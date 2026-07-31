/**
 * The content model: all 18 field types, the `when` vocabulary, field-group
 * inlining, required-field validation, SEO limit derivation, and the
 * placeholder/slug pipeline that fills a new document in.
 *
 * Pure Node. Nothing here reads the disk except the fixture `zer0.json`, and
 * nothing here writes.
 */

import { strict as assert } from 'node:assert';
import * as fs from 'node:fs';
import * as path from 'node:path';

import {
  emptyValueFor,
  evaluateWhen,
  findField,
  inlineFieldCollections,
  isEmpty,
  labelOf,
  limitFor,
  validateFields,
  visibleFields,
} from '../core/content/fields';
import { processFields, resolveContentType } from '../core/content/contentType';
import { FAULTY_PLACEHOLDER, hasPlaceholder, processPlaceholders } from '../core/content/placeholders';
import { createSlug, decorateSlug } from '../core/content/slug';
import { resolveConfig } from '../core/shared/config';
import { readJsonc } from '../core/shared/jsonio';
import { FIELD_TYPES, WHEN_OPERATORS } from '../core/shared/types';
import type { Field, FieldType, WhenOperator, Zer0Config } from '../core/shared/types';

const WORKSPACE = path.resolve(__dirname, '../../src/test/fixtures/workspace');

function fixtureConfig(overrides: Record<string, unknown> = {}): Zer0Config {
  const file = readJsonc<Record<string, unknown>>(
    fs.readFileSync(path.join(WORKSPACE, 'zer0.json'), 'utf8'),
  );
  return resolveConfig(WORKSPACE, { ...file, ...overrides });
}

/** The fixture's `post` type, with its `fieldCollection` already expanded. */
function postFields(cfg: Zer0Config): Field[] {
  const post = cfg.contentTypes.find((ct) => ct.name === 'post');
  assert.ok(post !== undefined, 'the fixture declares a `post` content type');
  return inlineFieldCollections(post.fields, cfg.fieldGroups);
}

function field(name: string, type: FieldType, extra: Partial<Field> = {}): Field {
  return { name, type, ...extra };
}

// ---------------------------------------------------------------------------

suite('fields: the 18 types', () => {
  test('the fixture content type exercises every one of them', () => {
    const cfg = fixtureConfig();
    const post = cfg.contentTypes.find((ct) => ct.name === 'post');
    assert.ok(post !== undefined);
    const declared = new Set(post.fields.map((f) => f.type));
    assert.deepEqual(
      FIELD_TYPES.filter((type) => !declared.has(type)),
      [],
      'every supported field type appears in the fixture, so a regression has somewhere to show',
    );
    assert.equal(FIELD_TYPES.length, 18, 'decision D6: 18 types, not FM’s 22');
    assert.equal(FIELD_TYPES.includes('json' as FieldType), false);
  });

  test('emptyValueFor answers for all 18, and `multiple` changes four of them', () => {
    const cfg = fixtureConfig();
    const expected: Record<FieldType, unknown> = {
      string: '',
      number: 0,
      boolean: false,
      datetime: null,
      image: '',
      file: '',
      choice: '',
      tags: [],
      categories: [],
      taxonomy: [],
      draft: true,
      list: [],
      slug: '',
      fields: {},
      fieldCollection: null,
      divider: null,
      heading: null,
      contentRelationship: '',
    };
    for (const type of FIELD_TYPES) {
      assert.deepEqual(emptyValueFor(field('x', type), cfg), expected[type], `empty value for ${type}`);
    }
    for (const type of ['image', 'file', 'choice', 'contentRelationship'] as const) {
      assert.deepEqual(emptyValueFor(field('x', type, { multiple: true }), cfg), [], `${type}[]`);
    }
  });

  test('a `draft` field follows the configured draftField, including invert', () => {
    assert.equal(emptyValueFor(field('draft', 'draft'), fixtureConfig()), true);
    const inverted = fixtureConfig({ draftField: { name: 'published', type: 'boolean', invert: true } });
    assert.equal(
      emptyValueFor(field('published', 'draft'), inverted),
      false,
      'when the field marks *published*, "a new document is a draft" is `false`',
    );
    const choice = fixtureConfig({
      draftField: { name: 'status', type: 'choice', choices: ['draft', 'review', 'live'] },
    });
    assert.equal(emptyValueFor(field('status', 'draft'), choice), 'draft');
  });

  test('isEmpty: false and 0 are values; null, "", [], {} and the sentinel are not', () => {
    const cfg = fixtureConfig();
    const str = field('a', 'string');
    assert.equal(isEmpty(str, undefined), true, 'a missing key');
    assert.equal(isEmpty(str, null), true, 'an empty YAML value');
    assert.equal(isEmpty(str, ''), true, 'an explicitly empty string');
    assert.equal(isEmpty(str, '   '), true);
    assert.equal(isEmpty(str, FAULTY_PLACEHOLDER), true, 'a placeholder that failed to resolve');
    assert.equal(isEmpty(str, 'x'), false);
    assert.equal(isEmpty(field('b', 'boolean'), false), false, 'false is an answer');
    assert.equal(isEmpty(field('n', 'number'), 0), false, 'zero is an answer');
    assert.equal(isEmpty(field('t', 'tags'), []), true);
    assert.equal(isEmpty(field('t', 'tags'), ['x']), false);
    assert.equal(isEmpty(field('g', 'fields'), {}), true);
    assert.equal(isEmpty(field('d', 'divider'), 'anything'), true, 'presentation types hold nothing');
    assert.equal(emptyValueFor(field('d', 'divider'), cfg), null);
  });

  test('labelOf prefers the configured title and humanises the name otherwise', () => {
    assert.equal(labelOf(field('authorName', 'string', { title: 'Author' })), 'Author');
    assert.equal(labelOf(field('authorName', 'string')), 'AuthorName');
    assert.equal(labelOf(field('title', 'string', { title: '   ' })), 'Title');
  });
});

suite('fields: `when` clauses', () => {
  const data = {
    kind: 'Article',
    tags: ['governance', 'mcp'],
    weight: 10,
    featured: true,
  };
  const all: Field[] = [
    field('kind', 'string'),
    field('tags', 'tags'),
    field('weight', 'number'),
    field('featured', 'boolean'),
  ];

  const visible = (operator: WhenOperator, fieldRef: string, value: unknown): boolean =>
    evaluateWhen(field('target', 'string', { when: { fieldRef, operator, value } }), data, all);

  test('the ten operators are the whole vocabulary', () => {
    assert.equal(WHEN_OPERATORS.length, 10);
    assert.deepEqual([...WHEN_OPERATORS].sort(), [
      'contains',
      'endsWith',
      'eq',
      'gt',
      'gte',
      'lt',
      'lte',
      'neq',
      'notContains',
      'startsWith',
    ]);
  });

  test('string and list operators', () => {
    assert.equal(visible('eq', 'kind', 'Article'), true);
    assert.equal(visible('eq', 'kind', 'article'), false, 'comparisons are case-sensitive by default');
    assert.equal(visible('neq', 'kind', 'Note'), true);
    assert.equal(visible('contains', 'kind', 'rticl'), true);
    assert.equal(visible('contains', 'tags', 'mcp'), true, 'a list contains an element');
    assert.equal(visible('notContains', 'tags', 'jekyll'), true);
    assert.equal(visible('notContains', 'tags', 'mcp'), false);
    assert.equal(visible('startsWith', 'kind', 'Art'), true);
    assert.equal(visible('endsWith', 'kind', 'cle'), true);
    assert.equal(visible('endsWith', 'kind', 'xyz'), false);
  });

  test('caseSensitive: false lowers both sides', () => {
    const insensitive = field('target', 'string', {
      when: { fieldRef: 'kind', operator: 'eq', value: 'ARTICLE', caseSensitive: false },
    });
    assert.equal(evaluateWhen(insensitive, data, all), true);
  });

  test('the numeric operators need numbers on both sides, and stay visible otherwise', () => {
    assert.equal(visible('gt', 'weight', 5), true);
    assert.equal(visible('gt', 'weight', 10), false);
    assert.equal(visible('gte', 'weight', 10), true);
    assert.equal(visible('lt', 'weight', 20), true);
    assert.equal(visible('lte', 'weight', 10), true);
    assert.equal(
      visible('gt', 'weight', '5'),
      true,
      'a type mismatch shows the field — FM compared number against any; we refuse to guess',
    );
    assert.equal(visible('gt', 'kind', 5), true);
  });

  test('a field conditioned on a hidden field is hidden too, and a loop terminates', () => {
    const cascade: Field[] = [
      field('featured', 'boolean', { when: { fieldRef: 'kind', operator: 'eq', value: 'Note' } }),
      field('campaign', 'string', { when: { fieldRef: 'featured', operator: 'eq', value: true } }),
    ];
    const campaign = cascade[1];
    assert.ok(campaign !== undefined);
    assert.equal(
      evaluateWhen(campaign, data, cascade),
      false,
      'the parent’s own clause fails, so the child cannot be filled in either',
    );

    const loop: Field[] = [
      field('a', 'string', { when: { fieldRef: 'b', operator: 'eq', value: 'x' } }),
      field('b', 'string', { when: { fieldRef: 'a', operator: 'eq', value: 'x' } }),
    ];
    const a = loop[0];
    assert.ok(a !== undefined);
    assert.doesNotThrow(() => evaluateWhen(a, { a: 'x', b: 'x' }, loop));
  });

  test('visibleFields filters the fixture’s conditional field in declaration order', () => {
    const cfg = fixtureConfig();
    const fields = postFields(cfg);
    const hidden = visibleFields(fields, { featured: false });
    const shown = visibleFields(fields, { featured: true });
    assert.equal(
      hidden.some((f) => f.name === 'campaign'),
      false,
      'campaign is conditioned on featured === true',
    );
    assert.equal(
      shown.some((f) => f.name === 'campaign'),
      true,
    );
    assert.deepEqual(
      shown.map((f) => f.name),
      fields.map((f) => f.name),
      'declaration order is preserved',
    );
  });
});

suite('fields: field groups, validation and limits', () => {
  test('inlineFieldCollections splices the group in, is idempotent, and does not mutate', () => {
    const cfg = fixtureConfig();
    const post = cfg.contentTypes.find((ct) => ct.name === 'post');
    assert.ok(post !== undefined);
    const before = JSON.stringify(post.fields);

    const inlined = inlineFieldCollections(post.fields, cfg.fieldGroups);
    assert.equal(JSON.stringify(post.fields), before, 'the input settings object is never spliced');
    assert.equal(
      inlined.some((f) => f.type === 'fieldCollection'),
      false,
      'no collection survives the expansion',
    );
    assert.ok(findField(inlined, 'authorName') !== undefined);
    assert.ok(findField(inlined, 'authorEmail') !== undefined);
    assert.deepEqual(
      inlineFieldCollections(inlined, cfg.fieldGroups),
      inlined,
      'running it twice changes nothing',
    );
  });

  test('a collection naming an unknown group is dropped, not left unrenderable', () => {
    const fields: Field[] = [
      field('title', 'string'),
      field('ghost', 'fieldCollection', { fieldGroup: 'nope' }),
    ];
    const inlined = inlineFieldCollections(fields, []);
    assert.deepEqual(
      inlined.map((f) => f.name),
      ['title'],
    );
  });

  test('findField descends into nested `fields` groups', () => {
    const cfg = fixtureConfig();
    const fields = postFields(cfg);
    assert.equal(findField(fields, 'noindex')?.type, 'boolean', 'nested inside the `seo` group');
    assert.equal(findField(fields, 'nothing-like-this'), undefined);
  });

  test('validateFields reports every required empty field, with a leaf-addressed path', () => {
    const cfg = fixtureConfig();
    const fields = [
      field('title', 'string', { required: true, title: 'Title' }),
      field('seo', 'fields', {
        fields: [field('title', 'string', { required: true, title: 'SEO title' })],
      }),
      field('campaign', 'string', {
        required: true,
        when: { fieldRef: 'featured', operator: 'eq', value: true },
      }),
      field('featured', 'boolean'),
    ];

    const violations = validateFields(fields, { title: '', seo: {}, featured: false }, cfg);
    assert.deepEqual(
      violations.map((v) => v.path),
      [['title'], ['seo', 'title']],
      'depth-first, declaration order; an invisible field cannot be a violation',
    );
    assert.equal(violations[0]?.message, 'Title is required.');
    assert.equal(violations[1]?.message, 'SEO title is required.');

    const withCampaign = validateFields(fields, { title: 'T', seo: { title: 'S' }, featured: true }, cfg);
    assert.deepEqual(
      withCampaign.map((v) => v.path),
      [['campaign']],
      'making the parent true makes the conditional field required',
    );
  });

  test('validation.enabled: false silences the panel, the diagnostics and MCP together', () => {
    const cfg = fixtureConfig({ validation: { enabled: false } });
    const fields = [field('title', 'string', { required: true })];
    assert.deepEqual(validateFields(fields, {}, cfg), []);
  });

  test('limitFor derives the SEO character budget from the thresholds, not from the type', () => {
    const cfg = fixtureConfig();
    assert.equal(limitFor(field('title', 'string'), cfg), 60);
    assert.equal(limitFor(field('description', 'string'), cfg), 160);
    assert.equal(limitFor(field('body', 'string'), cfg), -1, 'no limit is -1, never 0');

    const zeroed = fixtureConfig({ seo: { titleField: 'title', titleLength: 0 } });
    assert.equal(
      limitFor(field('title', 'string'), zeroed),
      -1,
      'a threshold of 0 means the author switched the check off',
    );
    const off = fixtureConfig({ seo: { enabled: false } });
    assert.equal(limitFor(field('title', 'string'), off), -1);
  });
});

suite('fields: filling a new document in', () => {
  test('processFields writes defaults, honours `when`, and lets a template win', async () => {
    const cfg = fixtureConfig();
    const post = cfg.contentTypes.find((ct) => ct.name === 'post');
    assert.ok(post !== undefined);

    const data = await processFields(post, cfg, {}, 'Hello World');
    assert.equal(data.title, 'Hello World');
    assert.equal(data.draft, true, 'a new document is a draft');
    assert.equal(data.featured, false);
    assert.equal(data.weight, 0);
    assert.deepEqual(data.seo, { noindex: false }, 'nested groups are filled recursively');
    assert.equal('campaign' in data, false, 'featured is false, so campaign is not written');
    assert.equal('divider1' in data, false, 'a divider has no front-matter key');
    assert.equal('relatedHeading' in data, false);

    const seeded = await processFields(post, cfg, { weight: 99, extra: 'kept' }, 'Hello World');
    assert.equal(seeded.weight, 99, 'a template value beats a field default');
    assert.equal(seeded.extra, 'kept', 'a template key no field declares is appended, not dropped');
  });

  test('resolveContentType reads `type`, falling back to the folder and then to default', () => {
    const cfg = fixtureConfig();
    const corp = path.join(WORKSPACE, 'pages/_posts/corp/2026-07-08-governed-publishing.md');
    assert.equal(resolveContentType(cfg, { type: 'note' }, corp).name, 'note', 'the stamped key wins');
    assert.equal(resolveContentType(cfg, {}, corp).name, 'post', 'the folder’s first content type');
    assert.equal(
      resolveContentType(cfg, {}, path.join(WORKSPACE, 'elsewhere/x.md')).name,
      'default',
      'a file outside every registered folder gets the built-in type',
    );
  });

  test('placeholders resolve the calendar vocabulary and leave the unknown alone', async () => {
    const cfg = fixtureConfig();
    const date = new Date(Date.UTC(2026, 6, 31, 12, 0, 0));

    assert.equal(hasPlaceholder('{{year}}/{{month}}'), true);
    assert.equal(hasPlaceholder('no tokens here'), false);

    assert.equal(await processPlaceholders('{{year}}-{{month}}-{{day}}', { cfg, date }), '2026-07-31');
    assert.equal(
      await processPlaceholders('{{fm.slug}}', { cfg, date, data: { slug: 'governed-publishing' } }),
      'governed-publishing',
    );
    assert.equal(
      await processPlaceholders('{{siteName}}', { cfg, date }),
      'zer0 fixture site',
      'a static placeholder declared in zer0.json',
    );
    assert.equal(
      await processPlaceholders('{{nothingDefinesThis}}', { cfg, date }),
      '{{nothingDefinesThis}}',
      'an unresolvable token is left in the text rather than collapsing to an empty string',
    );
    assert.equal(
      await processPlaceholders('nothing to do here', { cfg, date }),
      'nothing to do here',
      'a string with no token never touches the disk or spawns anything',
    );
  });

  test('createSlug follows the content type’s template; decorateSlug wraps it', () => {
    const cfg = fixtureConfig();
    const post = cfg.contentTypes.find((ct) => ct.name === 'post');
    const note = cfg.contentTypes.find((ct) => ct.name === 'note');
    assert.ok(post !== undefined && note !== undefined);

    assert.equal(
      createSlug(cfg, 'Governed Publishing Without a Platform', post),
      'governed-publishing-without-a-platform',
      '`{{title}}` lowercases and hyphenates verbatim — no stop words are dropped',
    );
    assert.equal(
      createSlug(cfg, 'Some Title', note),
      'title',
      'slugTemplate: null means "no opinion" — it inherits the workspace template, here `slugify`',
    );
    assert.equal(createSlug(cfg, '', post), '', 'no title, no slug');

    assert.equal(decorateSlug(cfg, 'x'), 'x', 'no prefix or suffix configured');
    const decorated = fixtureConfig({ slug: { prefix: 'blog-', suffix: '-2026' } });
    assert.equal(decorateSlug(decorated, 'governed'), 'blog-governed-2026');
    assert.equal(decorateSlug(decorated, ''), '', 'an empty slug is left alone');
  });
});
