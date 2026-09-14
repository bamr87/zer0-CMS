/**
 * Generate the Jekyll projection golden.
 *
 * Decision D12 moves every Jekyll literal in the core — the `_posts` date rule,
 * the structural stems, the thumbnail keys, the permalink derivation, the
 * skipped output directories — behind a platform profile. That refactor is only
 * safe if Jekyll's answers do not move, and "does not move" is a claim that
 * needs evidence rather than a promise.
 *
 * So this file is run ONCE, against the code as it was before the refactor, and
 * its output is committed. Afterwards it is run again and the two are compared:
 * a byte difference is a behaviour change, and has to be either a bug or a
 * deliberate decision somebody wrote down.
 *
 *   node src/test/fixtures/golden/platform/generate.mjs > .../jekyll-projection.json
 *
 * It reads the fixture workspace plus three pages copied verbatim from real
 * sister sites, because the fixture's six pages are tidier than reality and the
 * interesting cases (a wire dispatch with `sources:`, a quest page, a dated
 * filename that disagrees with its front matter) only exist in the wild.
 */

import { createRequire } from 'node:module';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, '../../../../..');
const OUT = path.join(REPO, 'out');

const { resolveConfig } = require(path.join(OUT, 'core/shared/config.js'));
const { buildIndex } = require(path.join(OUT, 'core/content/pageIndex.js'));
const { canonicalUrl } = require(path.join(OUT, 'core/governance/publish.js'));
const { filePrefixFor } = require(path.join(OUT, 'core/content/folders.js'));
const { pageToRecord } = require(path.join(OUT, 'core/content/pageIndex.js'));
const { createSlug } = require(path.join(OUT, 'core/content/slug.js'));

const WORKSPACE = path.join(REPO, 'src/test/fixtures/workspace');

const cfg = resolveConfig(WORKSPACE, require(path.join(WORKSPACE, 'zer0.json')), {});

const { pages } = await buildIndex(cfg, undefined, {
  info: () => {}, warn: () => {}, error: () => {}, verbose: () => {},
});

const rows = pages
  .map((page) => ({
    relPath: page.relPath,
    title: page.title,
    slug: page.slug,
    computedSlug: createSlug(cfg, page.title ?? ''),
    date: page.date ?? null,
    draft: page.draft ?? null,
    collection: pageToRecord(cfg, page).collection ?? null,
    previewImage: page.previewImage ?? null,
    canonicalUrl: canonicalUrl(cfg, page.relPath, page.data ?? {}),
    filePrefix: filePrefixFor(cfg, page.path) ?? null,
  }))
  .sort((a, b) => a.relPath.localeCompare(b.relPath));

process.stdout.write(JSON.stringify({ generatedFrom: 'pre-D12 core', rows }, null, 2) + '\n');
