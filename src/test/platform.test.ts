/**
 * Platform profiles (decision D12) — the suite that has to hold two claims at
 * once.
 *
 * The first claim is the interesting one: **Jekyll's answers did not move.**
 * Every literal that used to be inlined in `pageIndex.ts`, `slug.ts`,
 * `folders.ts`, `contract.ts`, `media.ts` and `governance/publish.ts` is now a
 * field of `JEKYLL_PROFILE`, and the tests below compare the profile against
 * the *other* module that still holds the same value — `THUMBNAIL_KEYS` from
 * publishing, `CONVENTIONAL_MODIFIED_KEYS` from `article.ts`, `SKIP_DIRS` from
 * `glob.ts`, the brief `media.ts` emits. A profile that drifts from one of
 * those is a profile that has quietly changed a Jekyll site's behaviour, and
 * the byte-identity golden (`fixtures/golden/platform/`) is the second half of
 * the same proof.
 *
 * The second claim is that the other five platforms are actually *read*, not
 * merely declared. So the fixtures under `fixtures/sites/` are written in each
 * platform's own idiom — TOML `+++` for Hugo, `published:`/`dateCreated:` for a
 * Wiki.js export, a number-prefixed filename and `sidebar_position` for
 * Docusaurus, `pubDate` under `src/content/` for Astro, a YAML anchor in the
 * fleet's `_config.yml` — and detection, the site-config reader and the
 * permalink derivation are asked about all six.
 *
 * No network, no writes, no `vscode`. Detection takes its readers as
 * parameters, so the only filesystem access in this file is the test's own
 * `readFile` over committed fixtures.
 */

import { strict as assert } from 'node:assert';
import * as fs from 'node:fs/promises';
import { readFileSync } from 'node:fs';
import * as path from 'node:path';

import { CONVENTIONAL_MODIFIED_KEYS } from '../core/content/article';
import { filePrefixFor } from '../core/content/folders';
import { splitFrontMatter, type FrontMatter } from '../core/content/frontmatter';
import { THUMBNAIL_KEYS } from '../core/governance/publish';
import { briefFor } from '../core/media/media';
import {
  applyOverrides,
  detectPlatform,
  PLATFORM_PROFILES,
  profileFor,
  toProfileJson,
  type PlatformIo,
} from '../core/platform/detect';
import {
  contentRootsFor,
  datePrefixRuleAt,
  permalinkFallback,
  permalinkOf,
  skipDirsFor,
} from '../core/platform/permalink';
import { readSiteConfigFacts } from '../core/platform/siteConfig';
import { ASTRO_PROFILE } from '../core/platform/profiles/astro';
import { DOCUSAURUS_PROFILE } from '../core/platform/profiles/docusaurus';
import { GENERIC_PROFILE } from '../core/platform/profiles/generic';
import { HUGO_PROFILE } from '../core/platform/profiles/hugo';
import { JEKYLL_PROFILE } from '../core/platform/profiles/jekyll';
import { MKDOCS_PROFILE } from '../core/platform/profiles/mkdocs';
import { WIKIJS_PROFILE } from '../core/platform/profiles/wikijs';
import { resolveConfig } from '../core/shared/config';
import { SKIP_DIRS } from '../core/shared/glob';
import { PLATFORM_IDS, type PlatformId, type PlatformProfile } from '../core/shared/types';

const FIXTURES = path.resolve(__dirname, '../../src/test/fixtures');
const SITES = path.join(FIXTURES, 'sites');
const WORKSPACE = path.join(FIXTURES, 'workspace');

/** The injected readers, over a real directory. Counts what it was asked for. */
/**
 * A site that exists only as a map of paths to text. Detection takes injected
 * I/O precisely so a probe can be tested against a file nobody had to write.
 */
function memoryIo(files: Readonly<Record<string, string>>): PlatformIo {
  return {
    async exists(rel: string): Promise<boolean> {
      return Object.prototype.hasOwnProperty.call(files, rel);
    },
    async read(rel: string): Promise<string | undefined> {
      return Object.prototype.hasOwnProperty.call(files, rel) ? files[rel] : undefined;
    },
  };
}

function ioFor(root: string): PlatformIo & { reads: string[] } {
  const reads: string[] = [];
  return {
    reads,
    async exists(rel: string): Promise<boolean> {
      try {
        await fs.stat(path.join(root, rel));
        return true;
      } catch {
        return false;
      }
    },
    async read(rel: string): Promise<string | undefined> {
      reads.push(rel);
      try {
        return await fs.readFile(path.join(root, rel), 'utf8');
      } catch {
        return undefined;
      }
    },
  };
}

/** A fixture page's front matter, parsed the way the CMS parses it. */
function frontMatterOf(site: string, rel: string): FrontMatter {
  const text = readFileSync(path.join(SITES, site, rel), 'utf8');
  return splitFrontMatter(text).block?.data ?? {};
}

/** `permalinkOf` for a fixture page, with that site's detected profile. */
async function urlOf(site: string, rel: string): Promise<string> {
  const root = path.join(SITES, site);
  const resolved = await detectPlatform(root, ioFor(root));
  return permalinkOf(resolved.profile, resolved.siteConfig, rel, frontMatterOf(site, rel));
}

/** Every value in a profile, so "a profile is data" can be asserted. */
function everyValue(value: unknown, out: unknown[] = []): unknown[] {
  out.push(value);
  if (Array.isArray(value)) {
    for (const item of value) {
      everyValue(item, out);
    }
  } else if (value !== null && typeof value === 'object' && !(value instanceof RegExp)) {
    for (const item of Object.values(value)) {
      everyValue(item, out);
    }
  }
  return out;
}

// ---------------------------------------------------------------------------

suite('platform detection', () => {
  test('every fixture site is identified from its own marker file', async () => {
    const table: Array<{ dir: string; id: PlatformId; marker: string }> = [
      { dir: 'jekyll-zer0-mistakes', id: 'jekyll', marker: '_config.yml' },
      { dir: 'mkdocs', id: 'mkdocs', marker: 'mkdocs.yml' },
      { dir: 'hugo', id: 'hugo', marker: 'hugo.toml' },
      { dir: 'docusaurus', id: 'docusaurus', marker: 'docusaurus.config.js' },
      { dir: 'astro', id: 'astro', marker: 'astro.config.mjs' },
      { dir: 'wikijs', id: 'wikijs', marker: 'docker-compose.yml' },
    ];
    for (const row of table) {
      const root = path.join(SITES, row.dir);
      const resolved = await detectPlatform(root, ioFor(root));
      assert.equal(resolved.profile.id, row.id, row.dir);
      assert.equal(resolved.source, 'detected', row.dir);
      assert.ok(
        resolved.evidence.some((line) => line.startsWith(row.marker)),
        `${row.dir}: expected ${row.marker} in ${JSON.stringify(resolved.evidence)}`,
      );
    }
  });

  test('zer0-mistakes is an overlay ON jekyll, never a sibling platform id', async () => {
    const root = path.join(SITES, 'jekyll-zer0-mistakes');
    const resolved = await detectPlatform(root, ioFor(root));
    // The whole of decision D12's overlay rule, in three assertions.
    assert.equal(resolved.profile.id, 'jekyll');
    assert.equal(resolved.profile.overlay, 'zer0-mistakes');
    assert.ok(
      resolved.evidence.includes('_config.yml contains "remote_theme: bamr87/zer0-mistakes"'),
    );
    // And what the overlay is actually for: the fleet's own front-matter keys.
    assert.equal(resolved.profile.frontMatter.typeKey, 'fmContentType');
    assert.equal(resolved.profile.frontMatter.thumbnailKeys[0], 'preview');
  });

  test('the profile table is exactly the seven ids, and `zer0-mistakes` is not one', () => {
    assert.deepEqual([...PLATFORM_IDS].sort(), Object.keys(PLATFORM_PROFILES).sort());
    assert.equal(PLATFORM_IDS.length, 7);
    assert.ok(!(PLATFORM_IDS as readonly string[]).includes('zer0-mistakes'));
    for (const id of PLATFORM_IDS) {
      assert.equal(PLATFORM_PROFILES[id].id, id, id);
      assert.equal(PLATFORM_PROFILES[id].overlay, null, id);
    }
  });

  test('an explicit `zer0.json` platform.id wins over a marker file that disagrees', async () => {
    // The mkdocs fixture has `mkdocs.yml` sitting in plain sight. A site that
    // has stated what it is has stated what it is.
    const root = path.join(SITES, 'mkdocs');
    const resolved = await detectPlatform(root, ioFor(root), {
      id: 'hugo',
      overlay: 'auto',
      overrides: {},
    });
    assert.equal(resolved.profile.id, 'hugo');
    assert.equal(resolved.source, 'zer0.json');
    assert.equal(resolved.evidence[0], 'zer0.json: platform.id = hugo (probes skipped)');
    assert.ok(!resolved.evidence.includes('mkdocs.yml'));
  });

  test('`overlay: null` is a real answer — the probe is skipped, not merely missed', async () => {
    const root = path.join(SITES, 'jekyll-zer0-mistakes');
    const resolved = await detectPlatform(root, ioFor(root), {
      id: 'auto',
      overlay: null,
      overrides: {},
    });
    assert.equal(resolved.profile.id, 'jekyll');
    assert.equal(resolved.profile.overlay, null);
    assert.ok(resolved.evidence.includes('zer0.json: platform.overlay = null (probe skipped)'));
    // Without the overlay, the platform's own type key is nothing at all.
    assert.equal(resolved.profile.frontMatter.typeKey, null);
  });

  test('evidence names the files that were actually found, not the guess', async () => {
    const root = path.join(SITES, 'jekyll-zer0-mistakes');
    const resolved = await detectPlatform(root, ioFor(root));
    assert.deepEqual(resolved.evidence, [
      '_config.yml',
      'Gemfile',
      'pages',
      '_config.yml contains "remote_theme: bamr87/zer0-mistakes"',
    ]);
  });

  test('a directory with no marker file is `generic`, and says so out loud', async () => {
    const root = path.join(SITES, 'mkdocs', 'docs', 'setup');
    const resolved = await detectPlatform(root, ioFor(root));
    assert.equal(resolved.profile.id, 'generic');
    assert.equal(resolved.source, 'default');
    assert.deepEqual(resolved.evidence, ['no platform marker file found']);
    // `generic` claims nothing: no roots, no serve command, no date prefix.
    assert.deepEqual(resolved.profile.contentRoots, []);
    assert.equal(resolved.profile.commands.serve, null);
    assert.equal(resolved.profile.frontMatter.filenameDate, null);
  });

  test('the fixture workspace is still read as Jekyll, which is why the golden holds', () => {
    const json = JSON.parse(readFileSync(path.join(WORKSPACE, 'zer0.json'), 'utf8')) as unknown;
    const cfg = resolveConfig(WORKSPACE, json, {});
    // `platform` defaults to `auto`/`auto` and the fixture says nothing about
    // it, so with no detection result the resolver falls back to the behaviour
    // every reader in this codebase had before D12 — Jekyll. "Nobody ran
    // detection" and "detection found nothing" are different states.
    assert.equal(cfg.platform.id, 'auto');
    assert.equal(profileFor(cfg), JEKYLL_PROFILE);
    assert.equal(profileFor(cfg).id, 'jekyll');
  });

  test('overrides are applied, and an uncompilable pattern costs the override only', () => {
    const widened = applyOverrides(JEKYLL_PROFILE, {
      outputDirs: ['_site', 'build'],
      frontMatter: { ...toProfileJson(JEKYLL_PROFILE).frontMatter, filenameDate: '^(\\d{8})-' },
    });
    assert.deepEqual(widened.outputDirs, ['_site', 'build']);
    assert.equal(widened.frontMatter.filenameDate?.source, '^(\\d{8})-');
    // Untouched groups survive: overriding one front-matter key must not blank
    // the other thirteen.
    assert.deepEqual(widened.frontMatter.thumbnailKeys, JEKYLL_PROFILE.frontMatter.thumbnailKeys);

    const broken = applyOverrides(JEKYLL_PROFILE, {
      frontMatter: { ...toProfileJson(JEKYLL_PROFILE).frontMatter, filenameDate: '^(unclosed' },
    });
    assert.equal(broken.frontMatter.filenameDate, JEKYLL_PROFILE.frontMatter.filenameDate);
  });

  test('the overlay is found however a person spaced and quoted the theme line', async () => {
    // Not fussiness. Of the six sites in this fleet that use the zer0-mistakes
    // theme, five write the key aligned and quoted —
    // `remote_theme             : "bamr87/zer0-mistakes"` — and one writes it
    // compactly. A literal substring probe matched exactly the one, and would
    // have silently denied the overlay to the five sites it exists for. A
    // detector that only recognises tidy files is a detector for fixtures.
    const spellings = [
      'remote_theme: bamr87/zer0-mistakes',
      'remote_theme             : "bamr87/zer0-mistakes"',
      "remote_theme:    'bamr87/zer0-mistakes'",
      'remote_theme :bamr87/zer0-mistakes',
      'REMOTE_THEME: BAMR87/ZER0-MISTAKES',
    ];
    for (const line of spellings) {
      const io = memoryIo({
        '_config.yml': `title: A site\n${line}\nbaseurl: ""\n`,
        Gemfile: 'source "https://rubygems.org"\n',
      });
      const resolved = await detectPlatform('/tmp/site', io);
      assert.equal(resolved.profile.id, 'jekyll', `${line} should still be a Jekyll site`);
      assert.equal(resolved.profile.overlay, 'zer0-mistakes', `${line} did not match the overlay probe`);
    }

    // And it does not match a site that merely mentions the theme in prose.
    const mentions = memoryIo({
      '_config.yml': 'title: A site\n# we used to use remote_theme bamr87/zer0-mistakes here\n',
      Gemfile: 'source "https://rubygems.org"\n',
    });
    const plain = await detectPlatform('/tmp/site', mentions);
    assert.equal(plain.profile.overlay, null, 'a comment is not a declaration');
  });

  test('a probe file is read once however many probes name it', async () => {
    const root = path.join(SITES, 'jekyll-zer0-mistakes');
    const io = ioFor(root);
    await detectPlatform(root, io);
    // Two overlay probes name `_config.yml`, and the site-config read wants it
    // a third time. One read.
    assert.equal(io.reads.filter((rel) => rel === '_config.yml').length, 1);
  });
});

// ---------------------------------------------------------------------------

suite('the Jekyll profile is a transcript of the constants it replaced', () => {
  test('the filename date rule is the expression `pageIndex` used to inline', () => {
    assert.equal(JEKYLL_PROFILE.frontMatter.filenameDate?.source, '^(\\d{4}-\\d{2}-\\d{2})-');
    // The capture is the date without its dash; the whole match includes it.
    const match = JEKYLL_PROFILE.frontMatter.filenameDate?.exec('2026-07-31-hello');
    assert.equal(match?.[1], '2026-07-31');
    assert.equal(match?.[0], '2026-07-31-');
  });

  test('the structural stems are the ones `pageToRecord` excluded from distribution', () => {
    assert.deepEqual(JEKYLL_PROFILE.frontMatter.structuralStems, ['index', '_index', 'readme']);
  });

  test('the thumbnail keys are publishing`s list, in publishing`s order', () => {
    // Imported from `governance/publish`, not restated: a page that looked
    // covered in the media report and then published without a thumbnail would
    // be worse than no report at all.
    assert.deepEqual(JEKYLL_PROFILE.frontMatter.thumbnailKeys, THUMBNAIL_KEYS);
  });

  test('the bundle names are the ones `alignedFilePath` refuses to rename', () => {
    assert.deepEqual(JEKYLL_PROFILE.frontMatter.bundleNames, ['index', '_index']);
  });

  test('the permalink keys are the ledger key`s list, in order', () => {
    assert.deepEqual(JEKYLL_PROFILE.frontMatter.permalinkKeys, [
      'permalink',
      'canonical_url',
      'canonicalUrl',
      'url',
    ]);
  });

  test('the modified-date keys are `CONVENTIONAL_MODIFIED_KEYS`, in order', () => {
    assert.deepEqual(JEKYLL_PROFILE.frontMatter.dateKeys.modified, [...CONVENTIONAL_MODIFIED_KEYS]);
    assert.deepEqual(JEKYLL_PROFILE.frontMatter.dateKeys.publish, ['date']);
  });

  test('`_posts` requires a date prefix and `_drafts` forbids one', () => {
    const posts = JEKYLL_PROFILE.contentRoots.find((root) => root.collection === 'posts');
    const drafts = JEKYLL_PROFILE.contentRoots.find((root) => root.collection === 'drafts');
    assert.equal(posts?.filename.datePrefix, 'required');
    assert.equal(drafts?.filename.datePrefix, 'forbidden');
    // And the rule survives a collections_dir and a section subfolder.
    assert.equal(datePrefixRuleAt(JEKYLL_PROFILE, 'pages/_posts/corp'), 'required');
    assert.equal(datePrefixRuleAt(JEKYLL_PROFILE, 'pages/_drafts'), 'forbidden');
    // A folder that matches no root gets no opinion, rather than permission.
    assert.equal(datePrefixRuleAt(JEKYLL_PROFILE, 'notes'), 'optional');
  });

  test('`outputDirs` feed the skip set, per platform', () => {
    const jekyll = skipDirsFor(JEKYLL_PROFILE, SKIP_DIRS);
    for (const dir of SKIP_DIRS) {
      assert.ok(jekyll.has(dir), dir);
    }
    assert.ok(jekyll.has('_site'));
    assert.ok(skipDirsFor(HUGO_PROFILE, SKIP_DIRS).has('public'));
    assert.ok(skipDirsFor(MKDOCS_PROFILE, SKIP_DIRS).has('site'));
    assert.ok(skipDirsFor(DOCUSAURUS_PROFILE, SKIP_DIRS).has('build'));
    assert.ok(skipDirsFor(ASTRO_PROFILE, SKIP_DIRS).has('.astro'));
    // The base set is never mutated — it is shared, and a scan for one site
    // must not teach the next one to skip `public/`.
    assert.ok(!SKIP_DIRS.has('public'));
  });

  test('the preview-image command is the one `briefFor` used to hard-code', () => {
    assert.equal(JEKYLL_PROFILE.commands.previewImages, 'jekyll preview-images');
    const record = { path: 'pages/_posts/2026-07-31-hello.md', title: 'Hello' };
    assert.equal(
      briefFor(record),
      'generate a preview image for pages/_posts/2026-07-31-hello.md (title: Hello); ' +
        'run: jekyll preview-images --only 2026-07-31-hello',
    );
    // A platform with no generator wired up names the article and stops. A
    // wrong command is worse than no command, because somebody will run it.
    assert.equal(
      briefFor(record, MKDOCS_PROFILE),
      'generate a preview image for pages/_posts/2026-07-31-hello.md (title: Hello).',
    );
  });

  test('a profile is data: no function is reachable from any of the seven', () => {
    for (const id of PLATFORM_IDS) {
      for (const value of everyValue(PLATFORM_PROFILES[id])) {
        assert.notEqual(typeof value, 'function', `${id} carries a function`);
      }
    }
    // And the JSON twin drops the one non-serialisable value it does hold.
    const json = toProfileJson(JEKYLL_PROFILE);
    assert.equal(json.frontMatter.filenameDate, '^(\\d{4}-\\d{2}-\\d{2})-');
    assert.equal(JSON.parse(JSON.stringify(json)).frontMatter.filenameDate, json.frontMatter.filenameDate);
  });
});

// ---------------------------------------------------------------------------

suite('reading a site`s own configuration', () => {
  test('an anchored value is read, and the file still says it uses anchors', () => {
    const text = readFileSync(
      path.join(SITES, 'jekyll-zer0-mistakes', '_config.yml'),
      'utf8',
    );
    const facts = readSiteConfigFacts(JEKYLL_PROFILE, text);
    // `title: &site_title lifehacker.dev` anchors the scalar it is attached
    // to, so the value is right there and reading it is not a guess. (An
    // alias, which points at a value defined elsewhere, still is unknown —
    // see the alias case below.)
    assert.equal(facts.title, 'lifehacker.dev');
    assert.ok(
      !facts.warnings.some((line) => line.includes('`title` is a YAML anchor')),
      'an anchored scalar warrants no per-key warning',
    );
    // The file-level note stays: a config built out of anchors and aliases has
    // constructs this parser does not resolve, and saying so is honest.
    assert.ok(facts.warnings.some((line) => line.includes('declares YAML anchors')));
    // Everything else is read as before.
    assert.equal(facts.url, 'https://lifehacker.dev');
    assert.equal(facts.collectionsDir, 'pages');
    assert.deepEqual(Object.keys(facts.collections), ['posts', 'docs']);
    assert.equal(facts.collections.posts?.permalink, '/posts/:year/:month/:day/:title/');
    assert.equal(facts.collections.posts?.output, true);
  });

  test('a merge key is reported even though nothing read here sits under one', () => {
    const facts = readSiteConfigFacts(
      JEKYLL_PROFILE,
      ['defaults: &base', '  layout: page', 'other:', '  <<: *base', 'url: https://x.dev'].join('\n'),
    );
    assert.equal(facts.url, 'https://x.dev');
    assert.ok(facts.warnings.some((line) => line.includes('merge keys')));
    assert.ok(facts.warnings.some((line) => line.includes('anchors')));
  });

  test('an aliased scalar is refused by name', () => {
    const facts = readSiteConfigFacts(JEKYLL_PROFILE, ['title: *site_title', 'baseurl: /docs'].join('\n'));
    assert.equal(facts.title, null);
    assert.equal(facts.baseurl, '/docs');
    assert.ok(facts.warnings.some((line) => line.includes('`title` is a YAML alias')));
  });

  test('MkDocs` own vocabulary maps onto the shared fact names', () => {
    const text = readFileSync(path.join(SITES, 'mkdocs', 'mkdocs.yml'), 'utf8');
    const facts = readSiteConfigFacts(MKDOCS_PROFILE, text);
    assert.equal(facts.title, 'Fixture docs');
    assert.equal(facts.url, 'https://bamr87.github.io/README/');
    assert.equal(facts.docsDir, 'docs');
    // The file does not say, so the fact does not either — the *default* is
    // the profile's business, not a value invented here.
    assert.equal(facts.useDirectoryUrls, null);
    assert.equal(
      readSiteConfigFacts(MKDOCS_PROFILE, 'use_directory_urls: false').useDirectoryUrls,
      false,
    );
    assert.deepEqual(facts.warnings, []);
  });

  test('Hugo`s `[permalinks]` table reads as collections', () => {
    const text = readFileSync(path.join(SITES, 'hugo', 'hugo.toml'), 'utf8');
    const facts = readSiteConfigFacts(HUGO_PROFILE, text);
    assert.equal(facts.title, 'Fixture Hugo site');
    assert.equal(facts.url, 'https://example.dev/');
    assert.equal(facts.collections.posts?.permalink, '/:year/:month/:slug/');
    assert.deepEqual(facts.warnings, []);
  });

  test('a JavaScript config is not read, and the warning says why', () => {
    const facts = readSiteConfigFacts(DOCUSAURUS_PROFILE, 'module.exports = { baseUrl: "/x/" };');
    assert.equal(facts.baseurl, null);
    assert.equal(facts.url, null);
    assert.equal(facts.warnings.length, 1);
    assert.ok(facts.warnings[0]?.includes('reads no JavaScript'));
    assert.ok(facts.warnings[0]?.includes('platform.overrides'));
  });

  test('a platform with no config file in the repository produces facts and no complaint', () => {
    const facts = readSiteConfigFacts(WIKIJS_PROFILE, undefined);
    assert.equal(facts.title, null);
    assert.deepEqual(facts.collections, {});
    // Absence is a normal state (decision D9): Wiki.js keeps its site settings
    // in a database, and warning about that every refresh would be noise.
    assert.deepEqual(facts.warnings, []);
  });
});

// ---------------------------------------------------------------------------

suite('reading a real site rather than a tidy one', () => {
  test('an anchored scalar is read; only an alias is unknown', () => {
    // `collections_dir: &collections_dir pages` is how it-journey.dev writes
    // it. An anchor is a *label on* a value, so the value is right there;
    // an alias points somewhere else and genuinely needs a real parser.
    // Treating the two the same made all 409 of that site's content files
    // invisible to this console, and a CMS that cannot see a page cannot help
    // with it.
    const anchored = readSiteConfigFacts(
      JEKYLL_PROFILE,
      'title: IT-Journey\ncollections_dir: &collections_dir pages\ncollections:\n  quests:\n    output: true\n',
    );
    assert.equal(anchored.collectionsDir, 'pages', 'the anchored value should be read');
    assert.deepEqual(
      anchored.warnings.filter((w) => w.includes('`collections_dir`')),
      [],
      'reading an anchored scalar is not a guess, so it warrants no warning',
    );

    // An alias still is unknown, and still says so rather than inventing one.
    const aliased = readSiteConfigFacts(
      JEKYLL_PROFILE,
      'title: IT-Journey\ncollections_dir: *collections_dir\n',
    );
    assert.equal(aliased.collectionsDir, null);
    assert.equal(
      aliased.warnings.some((w) => w.includes('alias')),
      true,
      'an alias must be reported, never guessed',
    );
  });

  test("Jekyll's loose pages are content too, not only its collections", () => {
    // Jekyll builds every markdown file under the source directory, not just
    // the ones inside a declared collection. Deriving collections alone left
    // fourteen of lifehacker.dev's 382 files unseen.
    const facts = readSiteConfigFacts(
      JEKYLL_PROFILE,
      'collections_dir: pages\ncollections:\n  posts:\n    output: true\n  docs:\n    output: true\n',
    );
    const roots = contentRootsFor(JEKYLL_PROFILE, facts, '/site');
    const rels = roots.map((r) => r.originalPath);
    assert.deepEqual(rels, ['pages/_posts', 'pages/_docs', 'pages']);
    // The collections come first, so a longest-prefix match still binds a post
    // to `_posts` rather than to the catch-all.
    assert.ok(rels.indexOf('pages') === rels.length - 1, 'the catch-all must be last');
  });
});

suite('permalinks', () => {
  test('a page`s own permalink wins verbatim — lifehacker`s `/hacks/<slug>/`', async () => {
    assert.equal(
      await urlOf('jekyll-zer0-mistakes', 'pages/_posts/2026-06-22-the-workflow-that-never-fired.md'),
      '/hacks/the-workflow-that-never-fired/',
    );
  });

  test('a Jekyll collection template expands with the site`s own tokens', async () => {
    // `/posts/:year/:month/:day/:title/`, dated from the front matter and
    // titled from the filename stem with its date prefix removed.
    assert.equal(
      await urlOf('jekyll-zer0-mistakes', 'pages/_posts/2026-07-01-tokei-honest-review.md'),
      '/posts/2026/07/01/tokei-honest-review/',
    );
    // A different collection, a different template, out of the same config.
    assert.equal(
      await urlOf('jekyll-zer0-mistakes', 'pages/_docs/getting-started.md'),
      '/docs/getting-started/',
    );
  });

  test('MkDocs honours `use_directory_urls` both ways, and the site_url base path', async () => {
    assert.equal(await urlOf('mkdocs', 'docs/setup/install.md'), '/README/setup/install/');
    assert.equal(await urlOf('mkdocs', 'docs/index.md'), '/README/');

    const ugly = readSiteConfigFacts(
      MKDOCS_PROFILE,
      ['site_url: https://x.dev/', 'use_directory_urls: false'].join('\n'),
    );
    assert.equal(permalinkOf(MKDOCS_PROFILE, ugly, 'docs/setup/install.md', {}), '/setup/install.html');
    assert.equal(permalinkOf(MKDOCS_PROFILE, ugly, 'docs/index.md', {}), '/index.html');
  });

  test('Hugo reads its section template, its `slug`, and its bundles', async () => {
    // `slug: 'hello'` replaces the last segment; the date is front matter.
    assert.equal(await urlOf('hugo', 'content/posts/hello-hugo.md'), '/2026/07/hello/');
    // Digits in a Hugo filename are part of the name, not a date: the page is
    // filed under its front-matter month and keeps every digit in its slug.
    assert.equal(
      await urlOf('hugo', 'content/posts/2026-01-01-not-a-date.md'),
      '/2026/07/2026-01-01-not-a-date/',
    );
    // A branch bundle IS its directory.
    assert.equal(await urlOf('hugo', 'content/docs/_index.md'), '/docs/');
  });

  test('Docusaurus strips a number prefix from every segment, and dates its blog from the path', async () => {
    assert.equal(await urlOf('docusaurus', 'docs/01-intro.md'), '/docs/intro/');
    assert.equal(await urlOf('docusaurus', 'docs/02-guides/03-deploy.md'), '/docs/guides/deploy/');
    assert.equal(
      await urlOf('docusaurus', 'blog/2026-07-04-hello-blog.md'),
      '/blog/2026/07/04/hello-blog/',
    );
    // An absolute `slug:` replaces the whole route below the base, not just the
    // last segment — the Docusaurus rule most easily got wrong.
    const facts = readSiteConfigFacts(DOCUSAURUS_PROFILE, undefined);
    assert.equal(
      permalinkOf(DOCUSAURUS_PROFILE, facts, 'docs/01-intro.md', { slug: '/start-here' }),
      '/docs/start-here/',
    );
  });

  test('an Astro entry`s route is its id inside the collection', async () => {
    assert.equal(await urlOf('astro', 'src/content/blog/first-post.md'), '/blog/first-post/');
    assert.equal(await urlOf('astro', 'src/content/blog/2026/nested.md'), '/blog/2026/nested/');
    // `src/pages` is file-based routing, which is a different thing.
    assert.equal(await urlOf('astro', 'src/pages/about.md'), '/about/');
  });

  test('a Wiki.js page has no extension and no trailing slash', async () => {
    assert.equal(
      await urlOf('wikijs', 'docs/setup/wikijs-setup.md'),
      '/docs/setup/wikijs-setup',
    );
    assert.equal(await urlOf('wikijs', 'docs/home.md'), '/docs');
  });

  test('the fallback is the path, and only Jekyll hides the collection underscore', () => {
    // The derivation the ledger key has always used.
    assert.equal(
      permalinkFallback(JEKYLL_PROFILE, 'pages/_posts/2026-07-31-hello.md'),
      '/pages/posts/hello/',
    );
    // `generic` claims nothing it cannot support: no date, no underscore rule.
    assert.equal(
      permalinkFallback(GENERIC_PROFILE, 'pages/_posts/2026-07-31-hello.md'),
      '/pages/_posts/2026-07-31-hello/',
    );
  });
});

// ---------------------------------------------------------------------------

suite('content roots and filename rules', () => {
  test('content folders are derived from the site`s own config, with no zer0.json', async () => {
    const cases: Array<{ dir: string; expected: string[] }> = [
      // The trailing `pages` is Jekyll's loose-pages root: it builds every
      // markdown file under the source directory, not only the collections.
      { dir: 'jekyll-zer0-mistakes', expected: ['pages/_posts', 'pages/_docs', 'pages'] },
      { dir: 'mkdocs', expected: ['docs'] },
      { dir: 'hugo', expected: ['content'] },
      { dir: 'docusaurus', expected: ['docs', 'blog', 'src/pages'] },
      { dir: 'astro', expected: ['src/content', 'src/pages'] },
    ];
    for (const row of cases) {
      const root = path.join(SITES, row.dir);
      const resolved = await detectPlatform(root, ioFor(root));
      const folders = contentRootsFor(resolved.profile, resolved.siteConfig, root);
      assert.deepEqual(
        folders.map((folder) => folder.originalPath),
        row.expected,
        row.dir,
      );
      // Paths come back absolute, under the root they were derived for.
      for (const folder of folders) {
        assert.ok(folder.path.startsWith(root), `${row.dir}: ${folder.path}`);
      }
    }
    // `generic` derives nothing — no marker file means no claim about content.
    assert.deepEqual(
      contentRootsFor(GENERIC_PROFILE, readSiteConfigFacts(GENERIC_PROFILE, undefined), '/tmp/x'),
      [],
    );
  });

  test('`filePrefixFor` forbids a date prefix on mkdocs, hugo and astro', () => {
    const root = '/site';
    const cfg = resolveConfig(root, { content: { filePrefix: '{{date|yyyy-MM-dd}}' } }, {});
    const folderIn = (rel: string) => ({ title: rel, path: `${root}/${rel}` });

    // Jekyll: unchanged, in both directions. The prefix survives.
    assert.equal(
      filePrefixFor(cfg, folderIn('pages/_posts/corp'), undefined, JEKYLL_PROFILE),
      '{{date|yyyy-MM-dd}}',
    );
    // The three platforms that read the date from front matter and treat
    // filename digits as part of the URL: the prefix is dropped.
    const forbidden: Array<[PlatformProfile, string]> = [
      [MKDOCS_PROFILE, 'docs'],
      [HUGO_PROFILE, 'content/posts'],
      [ASTRO_PROFILE, 'src/content/blog'],
    ];
    for (const [profile, rel] of forbidden) {
      assert.equal(filePrefixFor(cfg, folderIn(rel), undefined, profile), '', `${profile.id}/${rel}`);
    }
    // A Docusaurus blog post really does carry the date in its filename.
    assert.equal(
      filePrefixFor(cfg, folderIn('blog'), undefined, DOCUSAURUS_PROFILE),
      '{{date|yyyy-MM-dd}}',
    );
    // And a folder outside every content root keeps whatever was configured.
    assert.equal(filePrefixFor(cfg, folderIn('notes'), undefined, MKDOCS_PROFILE), '{{date|yyyy-MM-dd}}');
  });
});
