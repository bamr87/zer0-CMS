/**
 * Golden cross-lane tests — the proof of file-level compatibility.
 *
 * Every file in `fixtures/golden/` was written by **Python** (see
 * `generate.py`). The TypeScript core has to reproduce those bytes exactly, so
 * these tests prove lane compatibility rather than self-consistency. When one
 * fails, the fix is a real bug in our serializer or a re-run of `generate.py`
 * against a changed Python lane — never an edit to the fixture.
 *
 * `worklist-inputs.json` and `worklist.md` are inherited verbatim from
 * BASH-CMS, whose Python lane produced them; our renderer already reproduces
 * them byte for byte, which is what makes them worth keeping.
 */

import { strict as assert } from 'node:assert';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

import { buildCatering } from '../core/catering/catering';
import { renderWorklist } from '../core/catering/worklist';
import { markStatus } from '../core/governance/drafts';
import { pyJsonDump } from '../core/shared/jsonio';
import type { Contract } from '../core/contract/contract';
import type { ContentRecord, Freshness, PerfStats } from '../core/shared/types';

const FIXTURES = path.resolve(__dirname, '../../src/test/fixtures');
const GOLDEN = path.join(FIXTURES, 'golden');

function golden(name: string): string {
  return fs.readFileSync(path.join(GOLDEN, name), 'utf8');
}

/** The shape `generate.py` writes into `worklist-inputs.json`. */
interface WorklistInputs {
  records: Array<{
    path: string;
    collection: string;
    title: string;
    health: number;
    freshness: string;
    draft: boolean;
    structural: boolean;
  }>;
  performance: Record<string, { impressions: number; engagements: number }>;
  published: string[];
  date: string;
}

const FRESHNESS: readonly Freshness[] = ['fresh', 'aging', 'stale', 'critical', 'unknown'];

function toRecord(raw: WorklistInputs['records'][number]): ContentRecord {
  return {
    path: raw.path,
    collection: raw.collection,
    title: raw.title,
    descriptionLen: 0,
    titleLen: 0,
    wordCount: 0,
    headingCount: 0,
    health: raw.health,
    freshness: FRESHNESS.includes(raw.freshness as Freshness) ? (raw.freshness as Freshness) : 'unknown',
    draft: raw.draft,
    generated: false,
    structural: raw.structural,
    readOnly: false,
    isNotebook: false,
    frontmatterPresent: true,
    date: null,
    lastmod: null,
    ageDays: 0,
    brokenLinks: 0,
    issues: [],
  };
}

/** The Python side only ever set `impressions` and `engagements`. */
function toPerfStats(raw: { impressions: number; engagements: number }): PerfStats {
  return {
    impressions: raw.impressions,
    clicks: 0,
    reactions: 0,
    comments: 0,
    shares: 0,
    engagements: raw.engagements,
  };
}

// ---------------------------------------------------------------------------

suite('golden: ledger bytes (json.dump indent=2 sort_keys ensure_ascii)', () => {
  test('pyJsonDump reproduces the Python lane byte for byte', () => {
    // The same object `generate.py` dumps. The `café-métier` URL pins
    // `ensure_ascii` escaping and code-point key ordering at the same time.
    const data = {
      _meta: { generated_by: 'zer0-cms', schema: 1 },
      '/pages/posts/corp/café-métier/': {
        posted_at: '2026-07-30T17:29:20Z',
        source_file: 'pages/_posts/corp/2026-07-30-café-métier.md',
        target: 'jekyll',
        type: 'article',
        urn: 'jekyll:pages/_posts/corp/2026-07-30-café-métier.md',
      },
      '/pages/posts/tech/mcp-for-the-back-office/': {
        posted_at: '2026-07-06T08:00:00Z',
        source_file: 'pages/_posts/tech/2026-07-06-mcp-for-the-back-office.md',
        target: 'jekyll',
        type: 'article',
        urn: 'jekyll:pages/_posts/tech/2026-07-06-mcp-for-the-back-office.md',
      },
    };
    const ours = `${pyJsonDump(data, { indent: 2, sortKeys: true, ensureAscii: true })}\n`;
    assert.equal(ours, golden('ledger.json'));
  });

  test('the golden itself carries the escapes it exists to pin', () => {
    const raw = golden('ledger.json');
    assert.ok(raw.includes('caf\\u00e9-m\\u00e9tier'), 'ensure_ascii=True, not the raw bytes');
    assert.ok(raw.endsWith('\n'), 'json.dump + "\\n"');
    const keys = Object.keys(JSON.parse(raw) as Record<string, unknown>);
    assert.deepEqual(
      keys,
      [...keys].sort(),
      'sort_keys=True — `/` (0x2F) before `_` (0x5F), by code point',
    );
  });
});

suite('golden: catering worklist (catering.render byte-for-byte)', () => {
  test('renderWorklist reproduces the Python lane from its own inputs', () => {
    const inputs = JSON.parse(golden('worklist-inputs.json')) as WorklistInputs;
    const contract: Contract = {
      root: '.',
      dir: path.join('.', '.cms'),
      present: true,
      generatedAt: '',
      records: inputs.records.map(toRecord),
      summary: {},
    };
    const performance: Record<string, PerfStats> = {};
    for (const [key, value] of Object.entries(inputs.performance)) {
      performance[key] = toPerfStats(value);
    }

    const plan = buildCatering(contract, performance, new Set(inputs.published));
    assert.equal(renderWorklist(plan, inputs.date), golden('worklist.md'));
  });

  test('the inputs exercise every lane boundary the renderer has', () => {
    const inputs = JSON.parse(golden('worklist-inputs.json')) as WorklistInputs;
    assert.equal(inputs.records.length, 11);
    assert.equal(Object.keys(inputs.performance).length, 7);

    const healths = inputs.records.map((r) => r.health);
    assert.ok(healths.includes(70), 'health exactly at the publishable floor');
    assert.ok(healths.includes(-1), 'an unscored page');
    assert.ok(inputs.records.some((r) => r.draft), 'a draft, which never distributes');
    assert.ok(inputs.records.some((r) => r.structural), 'a structural page, likewise');
    assert.ok(
      inputs.records.some((r) => r.freshness === 'stale' && inputs.performance[r.path] !== undefined),
      'a stale page with engagements — Lane D',
    );
  });
});

suite('golden: a draft status flip is a one-line diff', () => {
  test('markStatus replaces only the status line of a real queue file', async () => {
    const source = path.join(FIXTURES, 'workspace/.zer0/drafts/sample-article.md');
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'zer0-cms-flip-'));
    try {
      const copy = path.join(dir, 'draft.md');
      fs.copyFileSync(source, copy);

      const before = fs.readFileSync(copy, 'utf8').split('\n');
      await markStatus(copy, 'published');
      const after = fs.readFileSync(copy, 'utf8').split('\n');

      assert.equal(after.length, before.length, 'the line count never moves');
      const changed = before
        .map((line, i) => (line === after[i] ? null : i))
        .filter((i): i is number => i !== null);
      assert.equal(changed.length, 1, `exactly one line changes (got ${changed.length})`);
      assert.equal(after[changed[0] as number], 'status: published');
      assert.equal(
        fs.readFileSync(copy, 'utf8').endsWith('\n'),
        true,
        'exactly one trailing newline, as before',
      );
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});
