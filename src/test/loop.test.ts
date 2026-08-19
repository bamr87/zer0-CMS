/**
 * The feedback loop: analytics ingest, the portfolio, and media coverage.
 *
 * These three close the circuit catering left open. Catering could already turn
 * engagement into a worklist, but nothing turned a platform's statistics into
 * the `performance.json` it reads — so the assertions that matter most here are
 * about the *join* and about the boundary around it.
 *
 * Pure Node: no `vscode`, no network. Only the media suite touches disk, in a
 * fresh `os.tmpdir()` directory it removes again.
 *
 *   npm run compile-tests && node --test out/test/loop.test.js
 */

import { strict as assert } from 'node:assert';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

import {
  MEMBER_READS,
  ORGANIZATION_READS,
  type ReadCall,
  describeReadPlan,
  ingestPerformance,
  postIdIndex,
  readPlan,
  readSurfaceIsOwnContentOnly,
  unwrapStats,
} from '../core/analytics/analytics';
import { briefFor, mediaCoverage, renderCoverage, resolveMedia } from '../core/media/media';
import { buildPortfolio, renderPortfolio, streakOf } from '../core/portfolio/portfolio';
import type { Contract } from '../core/contract/contract';
import type { Ledger } from '../core/governance/ledger';
import type { ContentRecord } from '../core/shared/types';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function record(over: Partial<ContentRecord> & { path: string }): ContentRecord {
  return {
    collection: 'posts',
    title: 'A Title',
    descriptionLen: 140,
    titleLen: 30,
    wordCount: 900,
    headingCount: 4,
    health: 95,
    freshness: 'fresh',
    draft: false,
    generated: false,
    structural: false,
    readOnly: false,
    isNotebook: false,
    frontmatterPresent: true,
    date: '2026-06-01',
    lastmod: '2026-07-01',
    ageDays: 30,
    brokenLinks: 0,
    issues: [],
    ...over,
    path: over.path,
  } as ContentRecord;
}

function contractOf(records: ContentRecord[]): Contract {
  return {
    root: '.',
    dir: path.join('.', '.cms'),
    present: true,
    generatedAt: '',
    records,
    summary: {},
  };
}

/** Two shares plus a `_meta` block, which is never a share. */
function ledgerOf(): Ledger {
  return {
    _meta: { token_expires: '2026-12-01' },
    'https://example.com/a/': {
      urn: 'jekyll:posts/a.md',
      linkedin_urn: 'urn:li:share:101',
      posted_at: '2026-06-12T10:00:00Z',
      type: 'article',
      source_file: 'pages/_posts/a.md',
    },
    'https://example.com/b/': {
      urn: 'jekyll:posts/b.md',
      posted_at: '2026-07-14T10:00:00Z',
      type: 'article',
      source_file: 'pages/_notes/b.md',
    },
    // Published by hand, outside this lane: no page to attribute anything to.
    'https://example.com/orphan/': {
      urn: 'jekyll:posts/orphan.md',
      posted_at: '2026-07-20T10:00:00Z',
      type: 'update',
    },
  };
}

// ---------------------------------------------------------------------------
// Analytics — the read surface
// ---------------------------------------------------------------------------

suite('analytics: the read surface is declared, short, and own-content only', () => {
  test('both author kinds have a plan', () => {
    assert.equal(readPlan('member'), MEMBER_READS);
    assert.equal(readPlan('organization'), ORGANIZATION_READS);
    assert.ok(MEMBER_READS.length >= 2);
    assert.ok(ORGANIZATION_READS.length >= 2);
  });

  test('every shipped call returns only the author’s own content', () => {
    assert.ok(readSurfaceIsOwnContentOnly(MEMBER_READS));
    assert.ok(readSurfaceIsOwnContentOnly(ORGANIZATION_READS));
  });

  test('the guard actually rejects a call that reaches another person', () => {
    const overreaching: ReadCall[] = [
      ...MEMBER_READS,
      {
        what: 'list who follows the page',
        endpoint: 'GET /rest/connections',
        scope: 'r_network',
        returns: 'the profiles of members who follow the page',
      },
    ];
    assert.equal(
      readSurfaceIsOwnContentOnly(overreaching),
      false,
      'a follower-enumeration call must fail the boundary check',
    );
  });

  test('the description names what is not read', () => {
    const text = describeReadPlan('organization');
    assert.match(text, /aggregate counts only/);
    assert.match(text, /No profiles, connections, followers, or feeds/);
    for (const call of ORGANIZATION_READS) {
      assert.ok(text.includes(call.endpoint), `${call.endpoint} should appear`);
    }
  });
});

// ---------------------------------------------------------------------------
// Analytics — the join
// ---------------------------------------------------------------------------

suite('analytics: joining statistics onto content through the ledger', () => {
  test('every id key on an entry indexes to its source file', () => {
    const index = postIdIndex(ledgerOf());
    assert.equal(index.get('jekyll:posts/a.md'), 'pages/_posts/a.md');
    assert.equal(index.get('urn:li:share:101'), 'pages/_posts/a.md');
    assert.equal(index.get('jekyll:posts/b.md'), 'pages/_notes/b.md');
  });

  test('an entry with no source file is not indexed', () => {
    assert.equal(postIdIndex(ledgerOf()).get('jekyll:posts/orphan.md'), undefined);
  });

  test('the _meta block is never treated as a share', () => {
    for (const value of postIdIndex(ledgerOf()).values()) {
      assert.notEqual(value, '2026-12-01');
    }
  });

  test('known ids are applied, unknown ids are reported not dropped', () => {
    const result = ingestPerformance(ledgerOf(), {
      'urn:li:share:101': { impressions: 1000, reactions: 20, comments: 5, shares: 2 },
      'urn:li:share:999': { impressions: 9 },
    });
    assert.deepEqual(result.matched, ['urn:li:share:101']);
    assert.deepEqual(result.unmatched, ['urn:li:share:999']);
    assert.deepEqual(Object.keys(result.performance), ['pages/_posts/a.md']);
  });

  test('engagements are reactions + comments + shares, and junk is dropped', () => {
    const { performance } = ingestPerformance(ledgerOf(), {
      'urn:li:share:101': {
        impressions: '500',
        clicks: 12,
        reactions: 8,
        comments: 2,
        shares: 1,
        whoEngaged: ['a-person'],
      },
    });
    const stats = performance['pages/_posts/a.md'];
    assert.ok(stats, 'the matched row exists');
    assert.equal(stats.impressions, 500, 'numeric strings are coerced');
    assert.equal(stats.engagements, 11);
    assert.equal(
      Object.prototype.hasOwnProperty.call(stats, 'whoEngaged'),
      false,
      'per-reader fields must not survive the normaliser',
    );
  });

  test('a partial refresh updates its rows and keeps the rest', () => {
    const existing = {
      'pages/_notes/b.md': {
        impressions: 10,
        clicks: 1,
        reactions: 1,
        comments: 0,
        shares: 0,
        engagements: 1,
      },
    };
    const { performance } = ingestPerformance(
      ledgerOf(),
      { 'urn:li:share:101': { impressions: 42 } },
      existing,
    );
    assert.equal(performance['pages/_posts/a.md']?.impressions, 42, 'new row applied');
    assert.equal(performance['pages/_notes/b.md']?.impressions, 10, 'history preserved');
  });

  test('statistics that are not an object cannot become a row', () => {
    const result = ingestPerformance(ledgerOf(), {
      'urn:li:share:101': null,
      'jekyll:posts/b.md': [1, 2, 3],
    });
    assert.deepEqual(result.matched, []);
    assert.equal(result.unmatched.length, 2);
    assert.deepEqual(result.performance, {});
  });

  test('an ingest against an empty ledger matches nothing and says so', () => {
    const result = ingestPerformance({}, { 'urn:li:share:101': { impressions: 1 } });
    assert.deepEqual(result.matched, []);
    assert.deepEqual(result.unmatched, ['urn:li:share:101']);
  });

  test('unwrapStats accepts both the console export and a bare map', () => {
    assert.deepEqual(unwrapStats({ posts: { a: { impressions: 1 } } }), { a: { impressions: 1 } });
    assert.deepEqual(unwrapStats({ a: { impressions: 1 } }), { a: { impressions: 1 } });
    assert.deepEqual(unwrapStats(null), {});
    assert.deepEqual(unwrapStats([1, 2]), {});
  });
});

// ---------------------------------------------------------------------------
// Portfolio
// ---------------------------------------------------------------------------

suite('portfolio: the track record', () => {
  test('an empty ledger reports the next action, not a zero', () => {
    const portfolio = buildPortfolio({});
    assert.equal(portfolio.count, 0);
    assert.equal(portfolio.cadence, 0);
    assert.equal(portfolio.streak, 0);
    assert.match(renderPortfolio(portfolio), /starts at one/);
  });

  test('counts, kinds, months and the newest timestamp', () => {
    const portfolio = buildPortfolio(ledgerOf());
    assert.equal(portfolio.count, 3, '_meta is not a share');
    assert.equal(portfolio.byType.article, 2);
    assert.equal(portfolio.byType.update, 1);
    assert.deepEqual(Object.keys(portfolio.byMonth).sort(), ['2026-06', '2026-07']);
    assert.equal(portfolio.latest, '2026-07-20T10:00:00Z');
  });

  test('cadence is posts per active month, to one decimal', () => {
    const portfolio = buildPortfolio(ledgerOf());
    assert.equal(portfolio.monthsActive, 2);
    assert.equal(portfolio.cadence, 1.5);
  });

  test('collections come from the contract, and default without one', () => {
    const withContract = buildPortfolio(
      ledgerOf(),
      contractOf([
        record({ path: 'pages/_posts/a.md', collection: 'posts' }),
        record({ path: 'pages/_notes/b.md', collection: 'notes' }),
      ]),
    );
    assert.equal(withContract.byCollection.posts, 1);
    assert.equal(withContract.byCollection.notes, 1);
    assert.equal(withContract.byCollection.uncategorised, 1, 'the orphan has no page');
    assert.equal(buildPortfolio(ledgerOf()).byCollection.uncategorised, 3);
  });

  test('the streak counts back from the newest month in the data', () => {
    assert.equal(streakOf({ '2026-05': 1, '2026-06': 2, '2026-07': 1 }), 3);
  });

  test('a gap ends the streak', () => {
    assert.equal(streakOf({ '2026-01': 1, '2026-06': 1, '2026-07': 1 }), 2);
  });

  test('the streak rolls the year at January', () => {
    assert.equal(streakOf({ '2025-11': 1, '2025-12': 1, '2026-01': 1 }), 3);
  });

  test('a quiet present does not erase a past streak', () => {
    // Anchored to the data, not to today: the run really happened.
    assert.equal(streakOf({ '2020-01': 1, '2020-02': 1 }), 2);
  });

  test('the rendering carries the numbers', () => {
    const text = renderPortfolio(buildPortfolio(ledgerOf()));
    assert.match(text, /3 post\(s\) across 2 month\(s\)/);
    assert.match(text, /cadence:\s+1\.5 per active month/);
    assert.match(text, /article 2/);
  });
});

// ---------------------------------------------------------------------------
// Media
// ---------------------------------------------------------------------------

suite('media: reuse the image the site already made', () => {
  let root = '';

  setup(() => {
    root = fs.mkdtempSync(path.join(os.tmpdir(), 'zer0-media-'));
    fs.mkdirSync(path.join(root, 'assets', 'images', 'previews'), { recursive: true });
  });

  teardown(() => {
    fs.rmSync(root, { recursive: true, force: true });
  });

  function writeImage(rel: string, bytes = 32): void {
    const abs = path.join(root, rel);
    fs.mkdirSync(path.dirname(abs), { recursive: true });
    fs.writeFileSync(abs, Buffer.alloc(bytes));
  }

  test('a declared image wins, and site-absolute paths resolve', async () => {
    writeImage('assets/images/previews/declared.png', 64);
    const media = await resolveMedia(
      root,
      record({ path: 'pages/_posts/a.md' }),
      { preview: '/assets/images/previews/declared.png' },
    );
    assert.equal(media.source, 'frontmatter');
    assert.equal(media.bytes, 64);
    assert.equal(media.brief, '');
  });

  test('a declared image that is not on disk is not coverage', async () => {
    writeImage('assets/images/previews/a.png');
    const media = await resolveMedia(
      root,
      record({ path: 'pages/_posts/a.md' }),
      { preview: '/assets/images/previews/missing.png' },
    );
    assert.equal(media.source, 'convention', 'falls through to the conventional path');
    assert.equal(media.path, path.join('assets', 'images', 'previews', 'a.png'));
  });

  test('the conventional path is found without front matter', async () => {
    writeImage('assets/images/previews/b.webp');
    const media = await resolveMedia(root, record({ path: 'pages/_notes/b.md' }));
    assert.equal(media.source, 'convention');
    assert.match(media.path, /b\.webp$/);
  });

  test('no image yields the generator’s own command', async () => {
    const rec = record({ path: 'pages/_posts/none.md', title: 'No Image Here' });
    const media = await resolveMedia(root, rec);
    assert.equal(media.source, 'none');
    assert.equal(media.path, '');
    assert.match(media.brief, /jekyll preview-images --only none/);
    assert.match(media.brief, /No Image Here/);
    assert.equal(briefFor(rec), media.brief);
  });

  test('coverage counts both sides and reports only the gaps', async () => {
    writeImage('assets/images/previews/a.png');
    const coverage = await mediaCoverage(root, [
      record({ path: 'pages/_posts/a.md' }),
      record({ path: 'pages/_posts/none.md' }),
    ]);
    assert.equal(coverage.found, 1);
    assert.equal(coverage.missing, 1);

    const text = renderCoverage(coverage);
    assert.match(text, /1 of 2 page\(s\) have a preview image/);
    assert.match(text, /pages\/_posts\/none\.md/);
    assert.equal(text.includes('pages/_posts/a.md'), false, 'covered pages are not listed');
  });

  test('full coverage says so and lists nothing', async () => {
    writeImage('assets/images/previews/a.png');
    const coverage = await mediaCoverage(root, [record({ path: 'pages/_posts/a.md' })]);
    assert.equal(coverage.missing, 0);
    assert.equal(renderCoverage(coverage), 'media: 1 of 1 page(s) have a preview image.');
  });
});
