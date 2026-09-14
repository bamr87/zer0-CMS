/**
 * The site-wide front-matter audit (WP2.3 / decision D-D): the thirteen rule
 * ids, the parser's warnings channel, schema ingestion from the two sister
 * sites' own files, and the fix-it that never writes.
 *
 * Three properties are load-bearing here and each one is a test rather than a
 * comment:
 *
 *   1. **The rule ids are lifehacker.dev's, character for character.** They are
 *      asserted as literals — not built from `AUDIT_RULE_IDS`, which would only
 *      prove this file and `types.ts` agree with each other. An issue filed by
 *      that site's CI and one raised in this editor have to dedupe.
 *   2. **`src/test/fixtures/workspace/` is a well-formed site and stays one.**
 *      It yields zero errors. A rule that fires there is a rule that would fire
 *      on hundreds of good files somewhere real.
 *   3. **Nothing is written.** The whole audit fixture tree is hashed before
 *      and after every fix-it this suite runs, and compared byte for byte.
 *
 * No `vscode`, no network, no writes. The only `Date` is a fixed one, so
 * `future-date` means the same thing in June as it does in December.
 */

import { strict as assert } from 'node:assert';
import * as crypto from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';

import { parseArticle } from '../core/content/article';
import {
  AUDIT_RULE_SPECS,
  auditPage,
  auditSite,
  datePartOf,
  dryRunFix,
  filenameDateOf,
  fixFor,
  lineOfKey,
} from '../core/content/audit';
import { resolveContentType } from '../core/content/contentType';
import { violationToIssue } from '../core/content/fields';
import { splitFrontMatter } from '../core/content/frontmatter';
import type { FmBlock } from '../core/content/frontmatter';
import { buildIndex, pageToRecord } from '../core/content/pageIndex';
import {
  SCHEMA_SOURCE_RANK,
  mergeSchemas,
  readSiteSchema,
  schemaFromCmsConfig,
  schemaFromFrontmatterSchemaYml,
  schemaFromProfile,
  schemaFromProjectConfig,
} from '../core/content/schema';
import { resolveConfig } from '../core/shared/config';
import { readJsonc } from '../core/shared/jsonio';
import { AUDIT_RULE_IDS } from '../core/shared/types';
import type {
  AuditIssue,
  ContentType,
  PageEntry,
  PlatformProfile,
  SiteAudit,
  SiteSchema,
  Zer0Config,
} from '../core/shared/types';

const FIXTURES = path.resolve(__dirname, '../../src/test/fixtures');
const AUDIT = path.join(FIXTURES, 'audit');
const WORKSPACE = path.join(FIXTURES, 'workspace');
const SCHEMAS = path.join(AUDIT, 'schemas');

/**
 * A fixed clock. `future-date` compares a string against today, so a suite that
 * asked the wall clock would pass in 2026 and fail in 2100 — and, worse, would
 * turn a rule that is about *the site's* content into one about the calendar.
 */
const NOW = new Date(2026, 8, 1, 12, 0, 0);

/**
 * A Jekyll-shaped `PlatformProfile`, built here rather than imported.
 *
 * `src/core/platform/` is another work package's, and the audit only ever takes
 * a profile as a parameter — which is the point: the rules are the platform's
 * data, not this module's constants. A change to the real Jekyll profile is
 * that package's test to make, not this one's.
 */
function testProfile(): PlatformProfile {
  return {
    id: 'jekyll',
    overlay: null,
    probes: [{ file: '_config.yml' }],
    siteConfig: { file: '_config.yml', format: 'yaml' },
    contentRoots: [
      {
        collection: '_posts',
        path: 'pages/_posts',
        mode: 'authored',
        filename: { datePrefix: 'required', bundles: 'none' },
        permalink: '/:categories/:year/:month/:day/:title:output_ext',
        requiredKeys: ['title', 'description', 'date'],
        recommendedKeys: ['tags', 'categories'],
        layoutAllowed: [],
      },
    ],
    outputDirs: ['_site'],
    frontMatter: {
      dialects: ['yaml', 'toml', 'json'],
      typeKey: 'type',
      draft: { name: 'draft', type: 'boolean' },
      draftFolders: ['_drafts'],
      dateKeys: { publish: ['date'], modified: ['lastmod', 'last_modified_at'] },
      dateFormat: 'date',
      filenameDate: /^(\d{4})-(\d{2})-(\d{2})-/,
      taxonomyKeys: ['tags', 'categories'],
      slugKey: 'slug',
      permalinkKeys: ['permalink'],
      thumbnailKeys: ['image', 'preview', 'thumbnail'],
      structuralStems: ['readme', 'index'],
      bundleNames: ['index'],
    },
    commands: {
      serve: ['bundle', 'exec', 'jekyll', 'serve'],
      build: null,
      previewUrl: 'http://localhost:4000',
      port: 4000,
      previewImages: null,
    },
    governanceTarget: 'jekyll',
    validators: [],
  };
}

const PROFILE = testProfile();

function configFor(root: string): Zer0Config {
  return resolveConfig(root, readJsonc<unknown>(fs.readFileSync(path.join(root, 'zer0.json'), 'utf8')), {});
}

function readerFor(root: string): (rel: string) => Promise<string | undefined> {
  return async (rel: string): Promise<string | undefined> => {
    try {
      return await fs.promises.readFile(path.join(root, rel), 'utf8');
    } catch {
      // Absence is the normal state for a schema file (D9), and the reader's
      // whole contract is that it answers `undefined` instead of throwing.
      return undefined;
    }
  };
}

interface SiteRun {
  cfg: Zer0Config;
  pages: readonly PageEntry[];
  blocks: Map<string, FmBlock>;
  schema: SiteSchema;
  audit: SiteAudit;
}

/** One `auditSite` pass over a fixture site, blocks and all. Reads only. */
async function runSite(root: string): Promise<SiteRun> {
  const cfg = configFor(root);
  const { pages, cache } = await buildIndex(cfg);
  const blocks = new Map<string, FmBlock>();
  for (const page of pages) {
    const { block } = splitFrontMatter(fs.readFileSync(page.filePath, 'utf8'));
    if (block !== null) {
      blocks.set(page.relPath, block);
    }
  }
  const schema = await readSiteSchema(root, PROFILE, readerFor(root));
  const skipped = Object.keys(cache.skipped ?? {});
  return { cfg, pages, blocks, schema, audit: auditSite(cfg, PROFILE, pages, skipped, schema, NOW, undefined, blocks) };
}

let cached: SiteRun | undefined;

/** The audit fixture is read-only, so one pass answers every rule test. */
async function auditFixture(): Promise<SiteRun> {
  cached = cached ?? (await runSite(AUDIT));
  return cached;
}

function post(name: string): string {
  return `pages/_posts/${name}`;
}

function on(audit: SiteAudit, relPath: string): AuditIssue[] {
  return audit.issues.filter((issue) => issue.path === relPath);
}

function articleAt(relPath: string): { article: ReturnType<typeof parseArticle>; ct: ContentType; cfg: Zer0Config } {
  const cfg = configFor(AUDIT);
  const filePath = path.join(AUDIT, relPath);
  const article = parseArticle(filePath, fs.readFileSync(filePath, 'utf8'));
  return { article, ct: resolveContentType(cfg, article.data, filePath), cfg };
}

/** Every file under `dir`, as `relative path → sha256`. */
function treeDigest(dir: string): Record<string, string> {
  const out: Record<string, string> = {};
  const walk = (current: string): void => {
    for (const entry of fs.readdirSync(current, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) {
        walk(full);
      } else if (entry.isFile()) {
        out[path.relative(dir, full)] = crypto.createHash('sha256').update(fs.readFileSync(full)).digest('hex');
      }
    }
  };
  walk(dir);
  return out;
}

// ---------------------------------------------------------------------------

suite('audit: the thirteen rule ids are lifehacker.dev/scripts/ci/lint_frontmatter.rb', () => {
  test('no-front-matter: an absent block AND no projected keys, never one alone', async () => {
    const { schema } = await auditFixture();
    const relPath = post('2026-01-23-no-front-matter.md');
    const { article, ct, cfg } = articleAt(relPath);
    assert.equal(article.block, null, 'the fixture really has no block');

    const bare: PageEntry = {
      filePath: article.filePath,
      relPath,
      folder: path.join(AUDIT, 'pages/_posts'),
      contentType: 'post',
      title: '',
      description: '',
      slug: '',
      date: null,
      modified: 0,
      published: null,
      draft: false,
      tags: [],
      categories: [],
      previewImage: '',
      data: {},
    };
    const issues = auditPage(cfg, PROFILE, bare, ct, undefined, schema, NOW);
    assert.deepEqual(
      issues.map((issue) => issue.kind),
      ['no-front-matter'],
      'and nothing else: a file with no front matter has no keys to be missing',
    );
    assert.equal(issues[0]?.severity, 'error');
    assert.equal(issues[0]?.fixable, false, 'a whole block is not a mechanical repair');

    // The other half of the rule: an absent block WITH projected keys means the
    // caller handed us the index, not the bytes. Saying `no-front-matter` there
    // would be inventing a fact about a file nobody opened (D9).
    const { pages } = await auditFixture();
    const clean = pages.find((page) => page.relPath === post('2026-01-01-clean.md'));
    assert.ok(clean !== undefined);
    const projected = auditPage(cfg, PROFILE, clean, ct, undefined, schema, NOW);
    assert.equal(
      projected.filter((issue) => issue.rule === 'no-front-matter').length,
      0,
      'no block plus real keys is a projection, not an empty file',
    );
  });

  test('missing-key:<k> — the colon-suffixed kind, and the lane the fix decides', async () => {
    const { audit } = await auditFixture();
    const substantive = on(audit, post('2026-01-02-missing-key.md'));
    assert.deepEqual(
      substantive.map((issue) => issue.kind),
      ['missing-key:description'],
      'the kind carries the key; the coarse rule id does not',
    );
    assert.equal(substantive[0]?.rule, 'missing-key');
    assert.equal(substantive[0]?.severity, 'error');
    assert.equal(substantive[0]?.field, 'description');
    assert.equal(substantive[0]?.lane, 'substantive', 'nothing in the file supplies a description');
    assert.equal(substantive[0]?.fixable, false);

    const mechanical = on(audit, post('2026-01-04-missing-date.md'));
    assert.deepEqual(mechanical.map((issue) => issue.kind), ['missing-key:date']);
    assert.equal(mechanical[0]?.lane, 'mechanical', "the file's own name carries the date");
    assert.equal(mechanical[0]?.fixable, true);
  });

  test('invalid-date: a shape check and a calendar check, never a Date round trip', async () => {
    const { audit } = await auditFixture();
    const issues = on(audit, post('2026-01-03-invalid-date.md'));
    assert.deepEqual(issues.map((issue) => issue.kind), ['invalid-date']);
    assert.equal(issues[0]?.severity, 'error');
    assert.match(issues[0]?.message ?? '', /sometime last spring/);

    assert.equal(datePartOf('2026-02-29'), null, '2026 is not a leap year');
    assert.equal(datePartOf('2024-02-29'), '2024-02-29', '2024 is');
    assert.equal(datePartOf('2026-13-01'), null);
    assert.equal(datePartOf('2026-01-15T09:30:00Z'), '2026-01-15');
    assert.equal(datePartOf('2026-01-15 09:30:00 -0500'), '2026-01-15', "Jekyll's own spelling");
    assert.equal(datePartOf(20260115), null, 'a number is not a date');
    assert.equal(
      datePartOf('2026-01-15T09:30:00.000Z'),
      '2026-01-15',
      'and what comes back is a slice of the string that was already there',
    );
  });

  test('future-date: a string comparison against today, not a timestamp', async () => {
    const { audit } = await auditFixture();
    const issues = on(audit, post('2099-01-01-future-date.md'));
    assert.deepEqual(issues.map((issue) => issue.kind), ['future-date']);
    assert.equal(issues[0]?.severity, 'error');
    assert.match(issues[0]?.message ?? '', /2099-01-01/);
    assert.match(issues[0]?.message ?? '', /2026-09-01/, "today, from the caller's clock");
  });

  test('filename-date-mismatch: the two dates disagree, and neither one is guessed at', async () => {
    const { audit } = await auditFixture();
    const issues = on(audit, post('2026-01-05-filename-date-mismatch.md'));
    assert.deepEqual(issues.map((issue) => issue.kind), ['filename-date-mismatch']);
    assert.equal(issues[0]?.severity, 'error');
    assert.equal(issues[0]?.lane, 'substantive', 'renaming and editing are both valid; picking is judgment');
    assert.equal(issues[0]?.fixable, false);
    assert.equal(filenameDateOf(PROFILE, '/x/2026-01-05-a.md'), '2026-01-05');
    assert.equal(filenameDateOf(PROFILE, '/x/2026-02-30-a.md'), null, 'February has no thirtieth');
    assert.equal(filenameDateOf(PROFILE, '/x/undated.md'), null);
  });

  test('tags-not-array: a scalar where the site reads a list', async () => {
    const { audit, cfg } = await auditFixture();
    const issues = on(audit, post('2026-01-06-tags-not-array.md'));
    assert.deepEqual(issues.map((issue) => issue.kind), ['tags-not-array']);
    assert.equal(issues[0]?.severity, 'error');
    assert.equal(issues[0]?.lane, 'mechanical');
    assert.equal(issues[0]?.line, 9, 'the `tags:` line, past the comments above it');

    // A key the project declared comma-separated holds a scalar on purpose.
    const declared = resolveConfig(AUDIT, { frontMatter: { commaSeparatedFields: ['tags'] } }, {});
    const page = (await auditFixture()).pages.find(
      (candidate) => candidate.relPath === post('2026-01-06-tags-not-array.md'),
    );
    assert.ok(page !== undefined);
    const ct = resolveContentType(cfg, {}, page.filePath);
    const quiet = auditPage(declared, PROFILE, page, ct, undefined, (await auditFixture()).schema, NOW);
    assert.equal(
      quiet.filter((issue) => issue.rule === 'tags-not-array').length,
      0,
      "the site's own convention is not a defect",
    );
  });

  test('unknown-choice: a layout outside the schema, and a choice outside the content type', async () => {
    const { audit } = await auditFixture();
    const issues = on(audit, post('2026-01-07-unknown-choice.md'));
    assert.deepEqual(issues.map((issue) => issue.kind), ['unknown-choice', 'unknown-choice']);
    assert.deepEqual(issues.map((issue) => issue.field), ['layout', 'audience']);
    assert.equal(issues[0]?.severity, 'warning');
    assert.match(issues[0]?.message ?? '', /gallery/);
    assert.match(issues[1]?.message ?? '', /nobody/);
  });

  test('title-too-long: only against a cap the site declared', async () => {
    const { audit, pages, cfg, blocks } = await auditFixture();
    const issues = on(audit, post('2026-01-08-title-too-long.md'));
    assert.deepEqual(issues.map((issue) => issue.kind), ['title-too-long']);
    assert.equal(issues[0]?.severity, 'warning');
    assert.match(issues[0]?.message ?? '', /cap is 60/, "the cap came from the site's own .cms/ constraints");

    // With no declared cap the rule is silent — the SEO panel's default budget
    // is not a finding on every page.
    const page = pages.find((candidate) => candidate.relPath === post('2026-01-08-title-too-long.md'));
    assert.ok(page !== undefined);
    const bare = schemaFromProfile(PROFILE);
    assert.equal(bare.constraints.titleMax, null);
    const quiet = auditPage(
      cfg,
      PROFILE,
      page,
      resolveContentType(cfg, {}, page.filePath),
      blocks.get(page.relPath),
      bare,
      NOW,
    );
    assert.equal(quiet.filter((issue) => issue.rule === 'title-too-long').length, 0);
  });

  test('description-too-long: warning, at the 160 every site in this fleet uses', async () => {
    const { audit } = await auditFixture();
    const issues = on(audit, post('2026-01-09-description-too-long.md'));
    assert.deepEqual(issues.map((issue) => issue.kind), ['description-too-long']);
    assert.equal(issues[0]?.severity, 'warning', 'lifehacker keeps its own gate green on existing content');
    assert.match(issues[0]?.message ?? '', /the SEO cap is 160/);
  });

  test('unknown-key: only where a site declared a closed vocabulary', async () => {
    const { audit, pages, cfg, blocks } = await auditFixture();
    const issues = on(audit, post('2026-01-10-unknown-key.md'));
    assert.deepEqual(issues.map((issue) => issue.kind), ['unknown-key']);
    assert.equal(issues[0]?.severity, 'info');
    assert.equal(issues[0]?.field, 'mood');

    const page = pages.find((candidate) => candidate.relPath === post('2026-01-10-unknown-key.md'));
    assert.ok(page !== undefined);
    const quiet = auditPage(
      cfg,
      PROFILE,
      page,
      resolveContentType(cfg, {}, page.filePath),
      blocks.get(page.relPath),
      schemaFromProfile(PROFILE),
      NOW,
    );
    assert.equal(
      quiet.filter((issue) => issue.rule === 'unknown-key').length,
      0,
      'a site that declared nothing is not a site where every key is unknown',
    );
  });

  test('duplicate-slug is genuinely cross-file, and per directory', async () => {
    const { audit, cfg, pages, blocks, schema } = await auditFixture();
    const a = on(audit, post('2026-01-11-duplicate-slug-a.md'));
    const b = on(audit, post('2026-01-12-duplicate-slug-b.md'));
    assert.deepEqual(a.map((issue) => issue.kind), ['duplicate-slug']);
    assert.deepEqual(b.map((issue) => issue.kind), ['duplicate-slug']);
    assert.match(a[0]?.message ?? '', /2026-01-12-duplicate-slug-b\.md/, 'each names the other');
    assert.match(b[0]?.message ?? '', /2026-01-11-duplicate-slug-a\.md/);
    assert.equal(a[0]?.severity, 'error');

    // Auditing either file ALONE cannot produce it: it is a fact about a site.
    const single = pages.find((page) => page.relPath === post('2026-01-11-duplicate-slug-a.md'));
    assert.ok(single !== undefined);
    const alone = auditPage(
      cfg,
      PROFILE,
      single,
      resolveContentType(cfg, {}, single.filePath),
      blocks.get(single.relPath),
      schema,
      NOW,
    );
    assert.equal(alone.length, 0, 'one page in isolation has no collision to report');

    // And two files in different directories are two namespaces, not a clash.
    const spread = auditSite(
      cfg,
      PROFILE,
      pages.map((page) =>
        page.relPath === post('2026-01-12-duplicate-slug-b.md')
          ? { ...page, relPath: page.relPath.replace('_posts/', '_posts/elsewhere/') }
          : page,
      ),
      [],
      schema,
      NOW,
    );
    assert.equal(
      spread.issues.filter((issue) => issue.rule === 'duplicate-slug').length,
      0,
      '`/hacks/:slug/` and `/tools/:slug/` are two routes, not one',
    );
  });

  test('duplicate-permalink: a trailing slash is not a difference', async () => {
    const { audit } = await auditFixture();
    const a = on(audit, post('2026-01-13-duplicate-permalink-a.md'));
    const b = on(audit, post('2026-01-14-duplicate-permalink-b.md'));
    assert.deepEqual(a.map((issue) => issue.kind), ['duplicate-permalink']);
    assert.deepEqual(b.map((issue) => issue.kind), ['duplicate-permalink']);
    assert.equal(a[0]?.severity, 'error');
    assert.match(a[0]?.message ?? '', /\/shared/);
    assert.equal(a[0]?.line, 6, 'the permalink line, so a UI can jump to it');
  });

  test('unreadable-frontmatter suppresses every other check on that file', async () => {
    const { audit } = await auditFixture();
    const issues = on(audit, post('2026-02-01-anchor.md'));
    assert.deepEqual(issues.map((issue) => issue.kind), ['unreadable-frontmatter']);
    assert.equal(issues[0]?.severity, 'warning');
    assert.equal(issues[0]?.line, 1);
    assert.match(issues[0]?.message ?? '', /anchor/);
    assert.equal(
      issues.filter((issue) => issue.rule === 'missing-key').length,
      0,
      'the anchor was meant to supply `layout`; reporting it missing would be confidently wrong',
    );
  });
});

suite("audit: the parser's warnings channel", () => {
  const warningsOf = (relPath: string): string[] => {
    const { block } = splitFrontMatter(fs.readFileSync(path.join(AUDIT, relPath), 'utf8'));
    assert.ok(block !== null, `${relPath} still has a block — the parser never throws`);
    return block.warnings;
  };

  test('an anchor is named, on its line, and the block still parses', () => {
    const warnings = warningsOf(post('2026-02-01-anchor.md'));
    assert.equal(warnings.length, 1);
    assert.match(warnings[0] ?? '', /^line 1: a YAML anchor \(`&series`\)/);
  });

  test('an alias and a merge key are two findings on two lines', () => {
    const warnings = warningsOf(post('2026-02-02-alias.md'));
    assert.equal(warnings.length, 2);
    assert.match(warnings[0] ?? '', /^line 5: a YAML alias \(`\*base`\)/);
    assert.match(warnings[1] ?? '', /^line 6: a YAML merge key \(`<<`\)/);
  });

  test('a quoted scalar that closes on a later line is reported as truncated', () => {
    const warnings = warningsOf(post('2026-02-03-multiline-quote.md'));
    assert.equal(warnings.length, 1);
    assert.match(warnings[0] ?? '', /^line 1: a quoted scalar that closes on a later line/);
  });

  test('a multi-line flow collection is reported as truncated', () => {
    const warnings = warningsOf(post('2026-02-04-multiline-flow.md'));
    assert.equal(warnings.length, 1);
    assert.match(warnings[0] ?? '', /^line 6: a flow collection that closes on a later line/);
  });

  test("TOML's array-of-tables and ''' string are both named", () => {
    const warnings = warningsOf(post('2026-02-05-toml-array-tables.md'));
    assert.equal(warnings.length, 3, "one ''' and two [[authors]] headers");
    assert.match(warnings[0] ?? '', /^line 6: a TOML multi-line literal string/);
    assert.match(warnings[1] ?? '', /^line 9: a TOML array-of-tables \(`\[\[authors\]\]`\)/);
    assert.match(warnings[2] ?? '', /^line 11: a TOML array-of-tables/);
  });
});

suite('audit: the site pass, and what it refuses to claim', () => {
  test('every rule id has a spec, and the control page is silent', async () => {
    const { audit } = await auditFixture();
    for (const id of AUDIT_RULE_IDS) {
      assert.ok(AUDIT_RULE_SPECS[id] !== undefined, `${id} has a severity and a lane`);
    }
    assert.equal(Object.keys(AUDIT_RULE_SPECS).length, 13);

    const fired = new Set(audit.issues.map((issue) => issue.rule));
    for (const id of AUDIT_RULE_IDS) {
      if (id === 'no-front-matter') {
        continue; // Not a page: `buildIndex` skips it, and its own test covers it.
      }
      assert.ok(fired.has(id), `${id} fires somewhere in the fixture site`);
    }
    assert.deepEqual(on(audit, post('2026-01-01-clean.md')), [], 'the control stays a control');
    assert.deepEqual(on(audit, post('2026-01-20-toml-dialect.md')), [], 'and so does the TOML one');
    assert.deepEqual(on(audit, post('2026-01-21-json-dialect.md')), [], 'and the JSON one');
    assert.equal(audit.counts.error + audit.counts.warning + audit.counts.info, audit.issues.length);
    assert.equal(audit.byRule['duplicate-slug'], 2, 'byRule groups by the coarse id, both sides counted');
  });

  test('the well-formed fixture workspace yields zero errors, and health stays -1 (D9)', async () => {
    const { audit, cfg, pages } = await runSite(WORKSPACE);
    assert.equal(audit.scanned, 6);
    assert.equal(audit.counts.error, 0, `a rule fired on a good site: ${JSON.stringify(audit.byRule)}`);
    assert.equal(audit.issues.length, 0);
    assert.deepEqual(
      audit.skipped.map((file) => path.basename(file)),
      ['README.md'],
      'a file with no front matter is skipped, not accused',
    );
    assert.equal(audit.root, WORKSPACE);
    assert.equal(audit.generatedAt, NOW.toISOString());
    assert.ok(!('health' in audit), 'the audit never invents a health score');

    const first = pages[0];
    assert.ok(first !== undefined);
    assert.equal(pageToRecord(cfg, first).health, -1, 'issues are real; the engine’s judgement is not');

    // The panel's own validation speaks the same vocabulary.
    const issue = violationToIssue({
      path: ['seo', 'title'],
      field: { name: 'title', type: 'string' },
      message: 'SEO title is required.',
    });
    assert.equal(issue.kind, 'missing-key:seo.title');
    assert.equal(issue.lane, 'substantive');
    assert.equal(
      violationToIssue({
        path: ['layout'],
        field: { name: 'layout', type: 'string', default: 'post' },
        message: 'Layout is required.',
      }).lane,
      'mechanical',
      'a declared default is a fix a script may apply',
    );
  });
});

suite('audit: the fix-it', () => {
  test('mechanical where the file itself supplies the value, null where it does not', async () => {
    const { audit } = await auditFixture();

    const dateIssue = on(audit, post('2026-01-04-missing-date.md'))[0];
    assert.ok(dateIssue !== undefined);
    const dated = articleAt(post('2026-01-04-missing-date.md'));
    assert.deepEqual(
      fixFor(dateIssue, dated.cfg, PROFILE, dated.ct, dated.article, NOW),
      [{ key: 'date', value: '2026-01-04' }],
      "the date in the file's own name, as a string, never a Date",
    );

    // The slug is computed from the title, the way `createSlug` computes it —
    // and only when the key is actually absent.
    const slugIssue: AuditIssue = {
      kind: 'missing-key:slug',
      rule: 'missing-key',
      severity: 'error',
      field: 'slug',
      message: 'required key `slug` is missing or empty',
      lane: 'mechanical',
      suggestion: null,
      path: post('2026-01-02-missing-key.md'),
      line: null,
      fixable: true,
    };
    const unslugged = articleAt(post('2026-01-02-missing-key.md'));
    assert.equal(
      fixFor(slugIssue, unslugged.cfg, PROFILE, unslugged.ct, unslugged.article, NOW),
      null,
      'the file changed since the audit ran and already has one',
    );
    const stripped = { ...unslugged.article, data: { ...unslugged.article.data } };
    delete stripped.data.slug;
    assert.deepEqual(fixFor(slugIssue, unslugged.cfg, PROFILE, unslugged.ct, stripped, NOW), [
      { key: 'slug', value: 'the-missing-key' },
    ]);

    const tagIssue = on(audit, post('2026-01-06-tags-not-array.md'))[0];
    assert.ok(tagIssue !== undefined);
    const tagged = articleAt(post('2026-01-06-tags-not-array.md'));
    assert.deepEqual(fixFor(tagIssue, tagged.cfg, PROFILE, tagged.ct, tagged.article, NOW), [
      { key: 'tags', value: ['governance'] },
    ]);

    // Substantive: nothing in the file can supply a description, and writing
    // `description: ''` is the same violation in quieter clothes.
    const missing = on(audit, post('2026-01-02-missing-key.md'))[0];
    assert.ok(missing !== undefined);
    const bare = articleAt(post('2026-01-02-missing-key.md'));
    assert.equal(fixFor(missing, bare.cfg, PROFILE, bare.ct, bare.article, NOW), null);

    // And no rule outside the two mechanical ones ever answers.
    for (const relPath of [
      post('2026-01-03-invalid-date.md'),
      post('2026-01-05-filename-date-mismatch.md'),
      post('2026-01-07-unknown-choice.md'),
      post('2026-01-09-description-too-long.md'),
      post('2026-01-11-duplicate-slug-a.md'),
      post('2099-01-01-future-date.md'),
    ]) {
      const target = articleAt(relPath);
      for (const issue of on(audit, relPath)) {
        assert.equal(
          fixFor(issue, target.cfg, PROFILE, target.ct, target.article, NOW),
          null,
          `${issue.kind} on ${relPath} is a person's decision`,
        );
      }
    }
  });

  test('dryRunFix renders through line surgery, so the comments survive', async () => {
    const { audit } = await auditFixture();
    const relPath = post('2026-01-06-tags-not-array.md');
    const issue = on(audit, relPath)[0];
    assert.ok(issue !== undefined);
    const { article, ct, cfg } = articleAt(relPath);
    const changes = fixFor(issue, cfg, PROFILE, ct, article, NOW);
    assert.ok(changes !== null);

    const preview = dryRunFix(article, changes, cfg);
    assert.ok(!('refused' in preview), 'a YAML block with no warnings is exactly the surgical case');
    assert.equal(preview.before, article.raw);
    assert.notEqual(preview.after, preview.before);
    assert.match(preview.after, /the stem is load-bearing/, 'the inline comment is untouched');
    assert.match(preview.after, /# The tag below is a scalar on purpose\./);
    assert.match(preview.after, /tags:\n {2}- governance/, 'the scalar became a list');
    assert.match(preview.after, /The list is the fix/, 'and the body came back whole');

    // One line in, one line out: the scalar `tags: governance` becomes a key
    // plus one item. Everything before it, and the whole body, is untouched —
    // which is the property a full re-emit would have destroyed.
    const beforeLines = preview.before.split('\n');
    const afterLines = preview.after.split('\n');
    assert.equal(afterLines.length, beforeLines.length + 1, 'exactly one line was added');
    const tagsAt = beforeLines.indexOf('tags: governance');
    assert.ok(tagsAt > 0);
    assert.deepEqual(afterLines.slice(0, tagsAt), beforeLines.slice(0, tagsAt), 'nothing above it moved');
    assert.deepEqual(
      afterLines.slice(tagsAt + 2),
      beforeLines.slice(tagsAt + 1),
      'and nothing below it changed either',
    );
  });

  test('it refuses TOML, JSON, and a nested path under a scalar — exactly what surgery declines', () => {
    const toml = articleAt(post('2026-01-20-toml-dialect.md'));
    const tomlResult = dryRunFix(toml.article, [{ key: 'slug', value: 'x' }], toml.cfg);
    assert.ok('refused' in tomlResult);
    assert.match(tomlResult.refused, /TOML/);

    const json = articleAt(post('2026-01-21-json-dialect.md'));
    const jsonResult = dryRunFix(json.article, [{ key: 'slug', value: 'x' }], json.cfg);
    assert.ok('refused' in jsonResult);
    assert.match(jsonResult.refused, /JSON/);

    const clean = articleAt(post('2026-01-01-clean.md'));
    const nested = dryRunFix(clean.article, [{ key: 'title.sub', value: 'x' }], clean.cfg);
    assert.ok('refused' in nested, 'title holds a scalar; there is no safe place for title.sub');
    assert.match(nested.refused, /nested path/);

    const none = parseArticle('/nowhere/plain.md', 'no front matter at all\n');
    const empty = dryRunFix(none, [{ key: 'title', value: 'x' }], clean.cfg);
    assert.ok('refused' in empty);
  });

  test('a block the parser could not read refuses the fix-it outright', async () => {
    const { audit } = await auditFixture();
    const relPath = post('2026-02-01-anchor.md');
    const { article, ct, cfg } = articleAt(relPath);
    assert.ok(article.block !== null && article.block.warnings.length > 0);

    const refusal = dryRunFix(article, [{ key: 'layout', value: 'post' }], cfg);
    assert.ok('refused' in refusal);
    assert.match(refusal.refused, /could not read/);
    assert.match(refusal.refused, /anchor/, 'and it says which construct');

    // `fixFor` refuses one step earlier, so a caller that only asks "is there a
    // fix?" gets the same answer as one that asks for the preview.
    const invented: AuditIssue = {
      kind: 'missing-key:layout',
      rule: 'missing-key',
      severity: 'error',
      field: 'layout',
      message: 'required key `layout` is missing or empty',
      lane: 'mechanical',
      suggestion: null,
      path: relPath,
      line: null,
      fixable: true,
    };
    assert.equal(fixFor(invented, cfg, PROFILE, ct, article, NOW), null);
    assert.equal(
      on(audit, relPath).every((issue) => !issue.fixable),
      true,
      'and the audit never offered one in the first place',
    );
  });
});

suite('audit: nothing is written', () => {
  test('the whole fixture tree is byte-identical after every fix-it in this suite', async () => {
    const before = treeDigest(AUDIT);
    const { audit } = await auditFixture();

    for (const issue of audit.issues) {
      const target = articleAt(issue.path);
      const changes = fixFor(issue, target.cfg, PROFILE, target.ct, target.article, NOW);
      if (changes === null) {
        continue;
      }
      const preview = dryRunFix(target.article, changes, target.cfg);
      assert.ok('refused' in preview || preview.after.length > 0);
    }
    // Plus a change nothing asked for, to prove the preview itself is inert.
    const clean = articleAt(post('2026-01-01-clean.md'));
    dryRunFix(clean.article, [{ key: 'title', value: 'rewritten' }], clean.cfg);

    assert.deepEqual(treeDigest(AUDIT), before, 'dryRunFix renders; it does not write');
    assert.ok(Object.keys(before).length > 20, 'and the tree it did not write to is a real one');
  });
});

suite('audit: the sites declare their own schemas', () => {
  test("zer0-mistakes' frontmatter_schema.yml, read verbatim", () => {
    const text = fs.readFileSync(path.join(SCHEMAS, 'zer0-mistakes/frontmatter_schema.yml'), 'utf8');
    const schema = schemaFromFrontmatterSchemaYml(text);

    assert.equal(schema.source, 'frontmatter_schema.yml');
    assert.deepEqual(schema.global.required, ['title', 'lastmod']);
    assert.equal(schema.global.draftType, 'boolean');
    assert.deepEqual(Object.keys(schema.collections), [
      'posts',
      'docs',
      'notes',
      'notebooks',
      'quickstart',
      'about',
      'pages',
      'quests',
      'hobbies',
    ]);

    const posts = schema.collections.posts;
    assert.ok(posts !== undefined);
    assert.equal(posts.pathPattern, 'pages/_posts/**/*.md');
    assert.deepEqual(posts.required, [
      'title',
      'date',
      'lastmod',
      'description',
      'layout',
      'categories',
      'tags',
      'author',
    ]);
    assert.deepEqual(posts.layoutAllowed, ['article', 'section', 'news']);
    assert.equal(posts.dateFormat, 'iso-ms', 'from `global.date_format: iso8601`');
    // `global.canonical_fields` has no slot on SiteSchema; both spellings land
    // in the vocabulary so `unknown-key` does not fire on a renamed key.
    assert.ok(posts.optional.includes('estimated_time'));
    assert.ok(posts.optional.includes('estimated_reading_time'));
    assert.ok(posts.optional.includes('updated'));
    assert.ok(posts.optional.includes('sub-title'), 'a hyphenated key survives the subset parser');
  });

  test("it-journey's .cms/config.yml and content-schema.json, read verbatim", () => {
    const configYml = fs.readFileSync(path.join(SCHEMAS, 'it-journey/cms-config.yml'), 'utf8');
    const schemaJson = fs.readFileSync(path.join(SCHEMAS, 'it-journey/content-schema.json'), 'utf8');
    const schema = schemaFromCmsConfig(configYml, schemaJson);

    assert.equal(schema.source, 'cms-config');
    assert.deepEqual(schema.global.required, ['title', 'description', 'date', 'author', 'categories', 'tags']);
    assert.deepEqual(schema.constraints, { titleMax: 60, descriptionMin: 50, descriptionMax: 160 });

    const quests = schema.collections.quests;
    assert.ok(quests !== undefined);
    assert.equal(quests.pathPattern, 'pages/_quests/**', 'a directory is every file under it');
    assert.equal(quests.fmContentType, 'quest');
    assert.deepEqual(quests.required, [
      'title',
      'description',
      'date',
      'author',
      'categories',
      'tags',
      'level',
      'difficulty',
      'estimated_time',
      'permalink',
    ]);
    assert.ok(quests.optional.includes('skill_focus'));

    // A generated file mid-write is a normal state, never an exception.
    const yamlOnly = schemaFromCmsConfig(configYml, '{ not json');
    assert.equal(yamlOnly.source, 'cms-config');
    assert.deepEqual(yamlOnly.global.required, ['title', 'description', 'date', 'author', 'categories', 'tags']);
    assert.equal(yamlOnly.collections.quests?.required.includes('level'), true, 'required_extra still applies');
  });

  test('precedence: the source that gates CI wins, per collection, and caps fill in', async () => {
    assert.deepEqual(SCHEMA_SOURCE_RANK, {
      'frontmatter_schema.yml': 3,
      'cms-config': 2,
      'zer0.json': 1,
      'profile-default': 0,
      none: -1,
    });

    const { schema } = await auditFixture();
    assert.equal(schema.source, 'frontmatter_schema.yml', 'the CI lint reads that file, so it wins');
    assert.deepEqual(
      schema.collections.posts?.required,
      ['title', 'description', 'date'],
      "the .cms/ contract also names `posts` and adds `author` — and does not get to, because CI does not",
    );
    assert.deepEqual(schema.global.required, [], "an empty list said 'none'; a lower source cannot raise it");
    assert.deepEqual(
      schema.constraints,
      { titleMax: 60, descriptionMin: 50, descriptionMax: 160 },
      'a cap nobody stated is genuinely unstated, so it is borrowed from the next source down',
    );
    assert.deepEqual(
      Object.keys(schema.collections),
      ['posts'],
      "the profile's own `pages/_posts` root is the same content root written twice",
    );

    // Order of arrival does not decide it; rank does.
    const ci = schemaFromFrontmatterSchemaYml(
      fs.readFileSync(path.join(AUDIT, '.github/config/frontmatter_schema.yml'), 'utf8'),
    );
    const cms = schemaFromCmsConfig(
      fs.readFileSync(path.join(AUDIT, '.cms/config.yml'), 'utf8'),
      fs.readFileSync(path.join(AUDIT, '.cms/schema/content-schema.json'), 'utf8'),
    );
    assert.equal(mergeSchemas(cms, ci).source, 'frontmatter_schema.yml');
    assert.equal(mergeSchemas(ci, cms).source, 'frontmatter_schema.yml');
    assert.equal(mergeSchemas().source, 'none', 'nothing found is a normal state');
    assert.equal(mergeSchemas(schemaFromProfile(PROFILE)).source, 'profile-default');

    // A collection only the advisory source names survives the merge.
    const merged = mergeSchemas(ci, cms, schemaFromProfile(PROFILE));
    assert.equal(merged.collections.posts?.required.includes('author'), false);
    assert.equal(lineOfKey(undefined, 'title'), null, 'no block, no line — never a guess');

    // `zer0.json` is a schema source too — a field marked `required: true` is a
    // required key — and it ranks below both site files, so a project file
    // cannot lower or raise the bar a contributor is judged by.
    const project = schemaFromProjectConfig(configFor(AUDIT));
    assert.equal(project.source, 'zer0.json');
    assert.deepEqual(project.collections.Posts?.required, ['title', 'description']);
    assert.equal(project.collections.Posts?.fmContentType, 'post');
    assert.ok(project.collections.Posts?.optional.includes('audience'), 'a declared field is a known key');
    assert.equal(
      mergeSchemas(project, ci).source,
      'frontmatter_schema.yml',
      'and the CI file still wins however the two arrive',
    );
  });
});
