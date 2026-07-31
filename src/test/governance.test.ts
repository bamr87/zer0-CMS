/**
 * The governed queue: the brand guard, the draft queue, the ledger, the gates,
 * and the read-only preview.
 *
 * Every test that writes does so into a fresh `os.tmpdir()` directory it
 * removes again. The checked-in fixture workspace is read-only here — the
 * `buildPreview` test proves that by snapshotting the whole tree before and
 * after with a throwing `fetch` installed.
 */

import { strict as assert } from 'node:assert';
import * as fs from 'node:fs';
import * as fsp from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import {
  blockerSummary,
  evaluateApproveGates,
  evaluateGates,
  evaluatePublishGates,
  hasBlocker,
} from '../core/governance/approval';
import {
  DRAFT_STATUSES,
  listQueue,
  markStatus,
  readDraft,
  slugOf,
  writeDraft,
} from '../core/governance/drafts';
import {
  BANNED_PATTERNS,
  FILLER,
  FOLD,
  MAX_LEN,
  guardText,
  guardWithWorkspace,
  hasErrors,
  loadWorkspacePatterns,
  workspacePatterns,
} from '../core/governance/guard';
import {
  isPublished,
  loadLedger,
  publishedSourceFiles,
  record,
  shareEntries,
} from '../core/governance/ledger';
import {
  buildPreview,
  canonicalUrl,
  previewRequestFromDraft,
  publishPreview,
  targetFor,
} from '../core/governance/publish';
import {
  isDistributable,
  loadContract,
  normalisePerformance,
  distributable,
  issuesByLane,
  recordSlug,
} from '../core/contract/contract';
import { resolveConfig } from '../core/shared/config';
import type { Zer0Settings } from '../core/shared/config';
import { readJsonc } from '../core/shared/jsonio';
import type { BlockerKind, GateInput } from '../core/governance/approval';
import type { ContentRecord, Zer0Config } from '../core/shared/types';

const WORKSPACE = path.resolve(__dirname, '../../src/test/fixtures/workspace');
const DRAFTS = path.join(WORKSPACE, '.zer0/drafts');

function fixtureConfig(settings: Zer0Settings = {}): Zer0Config {
  const file = readJsonc<unknown>(fs.readFileSync(path.join(WORKSPACE, 'zer0.json'), 'utf8'));
  return resolveConfig(WORKSPACE, file, settings);
}

/** A fresh scratch directory. Every writer in this file goes through it. */
function scratch(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'zer0-cms-test-'));
}

function remove(dir: string): void {
  fs.rmSync(dir, { recursive: true, force: true });
}

/** Every file under `dir`, with its bytes — for a before/after tree snapshot. */
function snapshotTree(dir: string): Map<string, string> {
  const out = new Map<string, string>();
  const walk = (current: string): void => {
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) {
        walk(full);
      } else if (entry.isFile()) {
        out.set(path.relative(dir, full), fs.readFileSync(full, 'utf8'));
      }
    }
  };
  walk(dir);
  return out;
}

function contentRecord(overrides: Partial<ContentRecord> = {}): ContentRecord {
  return {
    path: 'pages/_posts/corp/x.md',
    collection: 'corp',
    title: 'A title',
    descriptionLen: 0,
    titleLen: 0,
    wordCount: 0,
    headingCount: 0,
    health: -1,
    freshness: 'unknown',
    draft: false,
    generated: false,
    structural: false,
    readOnly: false,
    isNotebook: false,
    frontmatterPresent: true,
    date: null,
    lastmod: null,
    ageDays: 0,
    brokenLinks: 0,
    issues: [],
    ...overrides,
  };
}

// ---------------------------------------------------------------------------

suite('governance: the brand guard', () => {
  test('the rule tables are the sizes the Python lane ships', () => {
    assert.equal(BANNED_PATTERNS.length, 13, 'thirteen hard bans, all errors');
    assert.equal(FILLER.length, 9, 'nine filler patterns, all warnings');
    assert.equal(FOLD, 140);
    assert.equal(MAX_LEN, 3000);
    assert.equal(new Set(BANNED_PATTERNS.map((p) => p.name)).size, 13, 'every ban is named once');
  });

  test('a clean string yields exactly one finding: the fold info', () => {
    const findings = guardText('A short, plain sentence that says a real thing and then stops.');
    assert.equal(findings.length, 1);
    assert.equal(findings[0]?.level, 'info');
    assert.match(findings[0]?.message ?? '', /^fold at 140 chars: /);
    assert.equal(hasErrors(findings), false);
  });

  test('all 13 bans fire, each reported under its own name', () => {
    const samples: ReadonlyArray<readonly [string, string]> = [
      ['cutting-edge', 'The cutting edge release lands on Thursday for everyone.'],
      ['next-generation', 'A next-generation approach to the same filing problem.'],
      ['disruptive', 'They describe the pricing model as disruptive, which it is not.'],
      ['revolutionary', 'A revolutionary way to keep the same three spreadsheets.'],
      ["in today's ... world/age/era", "In today's connected world the invoices still need chasing."],
      ['leverage synergies', 'We leverage synergies across the two back-office teams.'],
      ['unlock value', 'The migration will unlock value for the finance team.'],
      ['best-of-breed', 'A best of breed stack assembled from four vendors.'],
      ['world-class', 'A world class support desk answering in under a minute.'],
      ['solutioning', 'Half the meeting was solutioning rather than deciding.'],
      ['ideate', 'The workshop asked us to ideate before lunch.'],
      ['circle back', 'Let us circle back once the numbers are in.'],
      ['low-hanging fruit', 'Start with the low hanging fruit and measure it.'],
    ];
    assert.equal(samples.length, BANNED_PATTERNS.length, 'a sample per ban');

    for (const [name, sample] of samples) {
      const errors = guardText(sample).filter((f) => f.level === 'error');
      assert.equal(
        errors.some((f) => f.message.endsWith(`(${name})`)),
        true,
        `"${sample}" must report the ban named ${name} — got ${JSON.stringify(errors)}`,
      );
    }

    // The smart apostrophe is not optional: real prose from an editor carries
    // U+2019, and a rule matching only U+0027 would wave it through.
    assert.equal(
      guardText('In today’s connected landscape the invoices still need chasing.').some(
        (f) => f.level === 'error' && f.message.includes("in today's"),
      ),
      true,
      'U+2019 must match as well as U+0027',
    );
  });

  test('"leverage synergies" reports twice on purpose; "cutting-edge" reports once', () => {
    const both = guardText('We leverage synergies across the estate to make the numbers work.');
    assert.deepEqual(
      both.map((f) => f.level),
      ['error', 'warning', 'info'],
      'the ban and the `synergy` filler have different names, so both report — upstream behaviour',
    );
    assert.match(both[0]?.message ?? '', /banned phrase "leverage synergies" \(leverage synergies\)/);
    assert.equal(both[1]?.message, 'reads as filler: synergy');

    const once = guardText('Our cutting-edge platform is here for the whole operations group.');
    assert.deepEqual(
      once.map((f) => f.level),
      ['error', 'info'],
      'a filler entry whose name already produced an error is skipped',
    );
  });

  test('one exclamation mark is one warning, and the filler entry does not double it', () => {
    const findings = guardText('This is a fine sentence about the work, and it has energy!');
    assert.deepEqual(findings.map((f) => f.level), ['warning', 'info']);
    assert.equal(findings[0]?.message, 'exclamation mark in commentary (house style: none)');

    const many = guardText('Really!! Truly!!! A sentence that goes on for a while afterwards.');
    assert.equal(
      many.filter((f) => f.message.includes('exclamation')).length,
      1,
      'the dedicated check reports once however many marks there are',
    );
  });

  test('over-length commentary and a weak hook are reported', () => {
    const long = guardText('x'.repeat(MAX_LEN + 1));
    assert.equal(long[0]?.level, 'error');
    assert.equal(long[0]?.message, `commentary is ${MAX_LEN + 1} chars (max ${MAX_LEN})`);
    assert.equal(guardText('x'.repeat(MAX_LEN)).some((f) => f.level === 'error'), false);

    const weak = guardText('Short.\nThen a much longer second line that explains the thing at hand.');
    assert.equal(
      weak.some((f) => f.message === 'weak hook: the first line ends before it says anything'),
      true,
    );
    const strong = guardText(
      'A first line long enough to have actually said something before it ends.\nThen more.',
    );
    assert.equal(strong.some((f) => f.message.startsWith('weak hook')), false);
  });

  test('the workspace patterns file adds rules, and a broken one degrades to none', async () => {
    const cfg = fixtureConfig();
    const extra = await workspacePatterns(cfg);
    assert.deepEqual(extra.map((p) => p.name), ['fixture-ban', 'fixture-ban-stateful']);
    assert.deepEqual(
      extra.map((p) => p.pattern.flags),
      ['i', 'i'],
      'g and y are stripped: a sticky lastIndex would make findings alternate between previews',
    );

    const findings = await guardWithWorkspace(cfg, 'A genuine paradigm shift in how the office runs.');
    assert.equal(findings[0]?.message, 'banned phrase "paradigm shift" (fixture-ban)');

    const missing = fixtureConfig({
      governance: { bannedPatternsFile: 'guard/does-not-exist.json' },
    });
    assert.deepEqual(
      await workspacePatterns(missing),
      [],
      'a broken addition must never brick previewing — the 13 built-in bans still run',
    );
    await assert.rejects(
      loadWorkspacePatterns(path.join(WORKSPACE, 'guard/does-not-exist.json')),
      'the explicit loader still reports why, for the "check my patterns file" command',
    );
  });
});

suite('governance: the draft queue', () => {
  test('listQueue skips a file with zero front-matter keys and sorts by name', async () => {
    const queue = await listQueue(DRAFTS);
    assert.deepEqual(
      queue.map((draft) => path.basename(draft.path)),
      ['approved-note.md', 'sample-article.md'],
      'README.md carries no front matter, so it is prose about the queue, not an item in it',
    );
    assert.deepEqual(queue.map((draft) => draft.status), ['approved', 'pending']);
    assert.deepEqual(queue.map((draft) => draft.type), ['article', 'article']);
    assert.deepEqual([...DRAFT_STATUSES], ['pending', 'approved', 'published']);
  });

  test('a queue folder that does not exist yet is an empty queue, never an error', async () => {
    assert.deepEqual(await listQueue(path.join(WORKSPACE, '.zer0/never-drafted')), []);
  });

  test('writeDraft resolves collisions and always writes status: pending', async () => {
    const dir = path.join(scratch(), 'queue');
    try {
      const first = await writeDraft(dir, { type: 'article', slug: 'note', body: 'One' });
      const second = await writeDraft(dir, {
        type: 'article',
        slug: 'note',
        body: 'Two',
        // Creating a draft and approving one are different acts. An `extras`
        // key must not be able to smuggle the second past a human.
        extras: { status: 'approved', reviewer: 'nobody' },
      });
      const third = await writeDraft(dir, { type: 'article', slug: 'note', body: 'Three' });

      assert.deepEqual(
        [first, second, third].map((p) => path.basename(p)),
        ['note.md', 'note-2.md', 'note-3.md'],
        'the queue is append-only from this direction — a collision never overwrites',
      );
      for (const file of [first, second, third]) {
        const draft = await readDraft(file);
        assert.equal(draft.status, 'pending', `${path.basename(file)} is pending`);
      }
      const smuggled = await readDraft(second);
      assert.equal(smuggled.meta.reviewer, 'nobody', 'other extras are written verbatim');
      assert.equal(fs.readFileSync(second, 'utf8').includes('status: approved'), false);
    } finally {
      remove(path.dirname(dir));
    }
  });

  test('writeDraft emits the fixed key order and quotes what needs quoting', async () => {
    const dir = scratch();
    try {
      const file = await writeDraft(dir, {
        type: 'article',
        slug: 'quoting',
        body: 'Body',
        source: 'pages/_posts/corp/x.md',
        title: 'A title with a "quote" in it',
        description: 'A description',
        link: '/pages/posts/corp/x/',
      });
      const lines = fs.readFileSync(file, 'utf8').split('\n');
      assert.deepEqual(lines.slice(0, 8), [
        '---',
        'type: article',
        'status: pending',
        'source: "pages/_posts/corp/x.md"',
        'title: "A title with a \\"quote\\" in it"',
        'description: "A description"',
        'link: "/pages/posts/corp/x/"',
        '---',
      ]);
      const draft = await readDraft(file);
      assert.equal(draft.meta.title, 'A title with a "quote" in it', 'and it reads back intact');
      assert.equal(slugOf(draft), 'quoting');
    } finally {
      remove(dir);
    }
  });

  test('markStatus inserts a status line when the draft has none', async () => {
    const dir = scratch();
    try {
      const file = path.join(dir, 'no-status.md');
      fs.writeFileSync(file, '---\ntype: article\ntitle: T\n---\n\nBody\n', 'utf8');
      await markStatus(file, 'published');
      assert.equal(
        fs.readFileSync(file, 'utf8'),
        '---\nstatus: published\ntype: article\ntitle: T\n---\n\nBody\n',
        'silently doing nothing would leave the queue claiming the draft is still pending',
      );
    } finally {
      remove(dir);
    }
  });
});

suite('governance: the ledger', () => {
  test('a missing or corrupt ledger reads as an empty one', async () => {
    assert.deepEqual(await loadLedger(path.join(WORKSPACE, '.zer0/no-such-ledger.json')), {});
    const dir = scratch();
    try {
      const file = path.join(dir, 'ledger.json');
      fs.writeFileSync(file, '{ this is not json', 'utf8');
      assert.deepEqual(
        await loadLedger(file),
        {},
        'a corrupt ledger must not take the publish path down; it fails closed on "nothing published"',
      );
    } finally {
      remove(dir);
    }
  });

  test('shareEntries drops `_`-keys and urn-less rows — the only correct enumeration', async () => {
    const ledger = await loadLedger(path.join(WORKSPACE, '.zer0/ledger.json'));
    assert.deepEqual(Object.keys(ledger).length, 3, 'the raw object has _meta and a half-written row');
    assert.deepEqual(
      shareEntries(ledger).map(([url]) => url),
      ['/pages/posts/corp/governed-publishing/'],
    );
    assert.deepEqual(
      [...publishedSourceFiles(ledger)],
      ['pages/_posts/corp/2026-07-08-governed-publishing.md'],
    );
  });

  test('record replaces the entry and writes Python-compatible bytes atomically', async () => {
    const dir = scratch();
    try {
      const file = path.join(dir, 'ledger.json');
      const entry = await record(file, '/pages/posts/corp/café/', 'jekyll:x.md', {
        sourceFile: 'pages/_posts/corp/x.md',
        target: 'jekyll',
      });
      assert.equal(entry.urn, 'jekyll:x.md');
      assert.equal(entry.type, 'article');
      assert.match(entry.posted_at, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/);

      const bytes = fs.readFileSync(file, 'utf8');
      assert.ok(bytes.includes('"/pages/posts/corp/caf\\u00e9/"'), 'ensure_ascii, like the Python lane');
      assert.ok(bytes.endsWith('\n'), 'a trailing newline, like json.dump + "\\n"');
      assert.deepEqual(
        fs.readdirSync(dir),
        ['ledger.json'],
        'the atomic write leaves no .tmp behind',
      );
      assert.equal(await isPublished(file, '/pages/posts/corp/café/'), true);
      assert.equal(await isPublished(file, '/pages/posts/corp/other/'), false);
    } finally {
      remove(dir);
    }
  });
});

suite('governance: the gates (D5)', () => {
  const gateFor = async (): Promise<Awaited<ReturnType<typeof readDraft>>> =>
    readDraft(path.join(DRAFTS, 'approved-note.md'));

  test('a clean draft has no blockers at all', async () => {
    assert.deepEqual(evaluatePublishGates({ cfg: fixtureConfig(), draft: await gateFor() }), []);
  });

  test('every blocker fires in the fixed order when they all apply', async () => {
    const blockers = evaluateGates('publish', {
      cfg: { ...fixtureConfig({ governance: { publishAllow: false } }), workspaceRoot: '' },
      draft: { ...(await gateFor()), status: 'rejected' },
      guard: [{ level: 'error', message: 'banned phrase "x" (y)' }],
      ledgerEntry: { urn: 'urn:1', posted_at: '2026-07-01T00:00:00Z' },
      violations: [
        {
          path: ['title'],
          field: { name: 'title', type: 'string', title: 'Title' },
          message: 'Title is required.',
        },
      ],
      previewError: 'boom',
    });
    assert.deepEqual(
      blockers.map((b) => b.kind),
      [
        'noWorkspace',
        'publishDisabled',
        'guardError',
        'alreadyPublished',
        'statusNotAccepted',
        'requiredFieldMissing',
        'previewFailed',
      ],
      'the order is fixed so the rendered note reads the same way every time',
    );
    assert.equal(
      blockerSummary(blockers.slice(0, 2)),
      'no workspace folder is open; publishing is disabled ' +
        '(set "zer0Cms.governance.publishAllow" to true)',
    );
  });

  /**
   * Each blocker on its own: one cause in, one blocker out, nothing else.
   *
   * A blocker that only ever fires alongside the others is a blocker nobody
   * has actually tested — so each row supplies exactly one reason to refuse
   * and asserts the gate names that one and stops.
   */
  const isolated: ReadonlyArray<{
    kind: BlockerKind;
    input: () => Promise<GateInput>;
    message: RegExp;
  }> = [
    {
      kind: 'noWorkspace',
      input: async () => ({ cfg: { ...fixtureConfig(), workspaceRoot: '' }, draft: await gateFor() }),
      message: /no workspace folder is open/,
    },
    {
      kind: 'publishDisabled',
      input: async () => ({
        cfg: fixtureConfig({ governance: { publishAllow: false } }),
        draft: await gateFor(),
      }),
      message: /publishing is disabled/,
    },
    {
      kind: 'guardError',
      input: async () => ({
        cfg: fixtureConfig(),
        draft: await gateFor(),
        // A warning alongside the error must not produce a second blocker.
        guard: [
          { level: 'error', message: 'banned phrase "x" (y)' },
          { level: 'warning', message: 'reads as filler: synergy' },
        ],
      }),
      message: /^brand guard: /,
    },
    {
      kind: 'alreadyPublished',
      input: async () => ({
        cfg: fixtureConfig(),
        draft: await gateFor(),
        ledgerEntry: { urn: 'urn:9', posted_at: '2026-07-01T00:00:00Z' },
      }),
      message: /already published as urn:9 on 2026-07-01T00:00:00Z/,
    },
    {
      kind: 'statusNotAccepted',
      input: async () => ({
        cfg: fixtureConfig(),
        draft: { ...(await gateFor()), status: 'rejected' },
      }),
      message: /draft status is "rejected" \(accepted: pending, approved\)/,
    },
    {
      kind: 'requiredFieldMissing',
      input: async () => ({
        cfg: fixtureConfig(),
        draft: await gateFor(),
        violations: [
          {
            path: ['title'],
            field: { name: 'title', type: 'string', title: 'Title' },
            message: 'Title is required.',
          },
        ],
      }),
      message: /1 required field missing: Title/,
    },
    {
      kind: 'previewFailed',
      input: async () => ({
        cfg: fixtureConfig(),
        draft: await gateFor(),
        previewError: 'a text update needs message',
      }),
      message: /^preview failed: a text update needs message/,
    },
  ];

  for (const { kind, input, message } of isolated) {
    test(`${kind} fires on its own`, async () => {
      const blockers = evaluatePublishGates(await input());
      assert.deepEqual(
        blockers.map((b) => b.kind),
        [kind],
        `only ${kind} — got ${JSON.stringify(blockers)}`,
      );
      assert.match(blockers[0]?.message ?? '', message);
      assert.equal(hasBlocker(blockers, kind), true);
    });
  }

  test('governance.enabled: false blocks publishing with its own message', async () => {
    const blockers = evaluatePublishGates({
      cfg: fixtureConfig({ governance: { enabled: false, publishAllow: true } }),
      draft: await gateFor(),
    });
    assert.deepEqual(blockers.map((b) => b.kind), ['publishDisabled']);
    assert.match(blockers[0]?.message ?? '', /governance is disabled/);
  });

  test('approve accepts only `pending`, whatever publish accepts', async () => {
    const cfg = fixtureConfig();
    const approved = await gateFor();
    assert.deepEqual(evaluateApproveGates({ cfg, draft: approved }).map((b) => b.message), [
      'draft is already approved',
    ]);
    assert.deepEqual(
      evaluatePublishGates({ cfg, draft: approved }),
      [],
      'the same draft is publishable — `approved` is in governance.acceptStatuses',
    );
    const pending = await readDraft(path.join(DRAFTS, 'sample-article.md'));
    assert.deepEqual(evaluateApproveGates({ cfg, draft: pending }), []);
  });
});

suite('governance: the contract (D9)', () => {
  test('the fixture contract loads, and an absent one is the same shape', async () => {
    const contract = await loadContract(WORKSPACE);
    assert.equal(contract.present, true);
    assert.equal(contract.records.length, 6);
    assert.equal(contract.generatedAt, '2026-07-30T06:00:00Z');
    assert.equal(contract.summary.totalFiles, 6);
    assert.equal(contract.summary.avgHealth, 81.33);

    const absent = await loadContract(path.join(WORKSPACE, 'assets'));
    assert.equal(absent.present, false);
    assert.deepEqual(absent.records, []);
    assert.deepEqual(absent.summary, {}, 'the literal empty summary the acceptance criterion names');
  });

  test('isDistributable: 70 is in, 69 is out, -1 is in', () => {
    assert.equal(isDistributable(contentRecord({ health: 70 })), true);
    assert.equal(isDistributable(contentRecord({ health: 69 })), false);
    assert.equal(isDistributable(contentRecord({ health: -1 })), true, 'unscored is not punished');
    assert.equal(isDistributable(contentRecord({ health: 95, draft: true })), false);
    assert.equal(isDistributable(contentRecord({ health: 95, generated: true })), false);
    assert.equal(isDistributable(contentRecord({ health: 95, structural: true })), false);
    assert.equal(isDistributable(contentRecord({ health: 95, title: '' })), false);
  });

  test('the fixture’s distributable set is health-ordered and excludes the draft and the index', async () => {
    const contract = await loadContract(WORKSPACE);
    assert.deepEqual(
      distributable(contract).map((r) => [recordSlug(r), r.health]),
      [
        ['2026-07-06-mcp-for-the-back-office', 95],
        ['2026-07-08-governed-publishing', 93],
        ['2026-07-20-toml-dialect', 88],
        ['2026-07-12-house-style', 82],
      ],
    );
    const wip = contract.records.find((r) => r.draft === true);
    assert.ok(wip !== undefined);
    assert.deepEqual(issuesByLane(wip, 'mechanical').map((i) => i.kind), ['broken-link']);
    assert.deepEqual(issuesByLane(wip, 'substantive').map((i) => i.kind), ['thin-content']);
  });

  test('normalisePerformance keeps the five metrics, derives engagements, drops the rest', () => {
    assert.deepEqual(
      normalisePerformance({ impressions: '12', clicks: 3, reactions: 1, comments: 2, shares: 4, bogus: 9 }),
      { impressions: 12, clicks: 3, reactions: 1, comments: 2, shares: 4, engagements: 7 },
    );
    assert.deepEqual(normalisePerformance({}), {
      impressions: 0,
      clicks: 0,
      reactions: 0,
      comments: 0,
      shares: 0,
      engagements: 0,
    });
  });
});

suite('governance: preview is read-only', () => {
  test('canonicalUrl is site-relative and a front-matter permalink wins verbatim', () => {
    const cfg = fixtureConfig();
    assert.equal(
      canonicalUrl(cfg, 'pages/_posts/corp/2026-07-31-hello.md'),
      '/pages/posts/corp/hello/',
      'the extension, the date prefix and the collection underscore all come off',
    );
    assert.equal(
      canonicalUrl(cfg, 'pages/_posts/corp/2026-07-31-hello.md', { permalink: '/somewhere/else/' }),
      '/somewhere/else/',
    );
  });

  test('buildPreview writes nothing and calls nothing out', async () => {
    const cfg = fixtureConfig();
    const draft = await readDraft(path.join(DRAFTS, 'sample-article.md'));

    const before = snapshotTree(WORKSPACE);
    const realFetch = globalThis.fetch;
    let calls = 0;
    Object.defineProperty(globalThis, 'fetch', {
      configurable: true,
      writable: true,
      value: () => {
        calls += 1;
        throw new Error('buildPreview must not reach the network');
      },
    });

    try {
      const preview = await buildPreview(cfg, previewRequestFromDraft(draft));
      assert.equal(preview.kind, 'article');
      assert.equal(preview.url, '/pages/posts/corp/governed-publishing/');
      assert.equal(preview.sourceFile, '.zer0/drafts/sample-article.md');
      assert.equal(preview.page?.relPath, 'pages/_posts/corp/2026-07-08-governed-publishing.md');
      assert.ok(preview.plan !== undefined, 'the plan is what `send` would write');
      assert.equal(preview.plan.title, 'Governed publishing without a platform');
      assert.ok(preview.artifact !== undefined, 'the artifact comes from the configured target');
      assert.deepEqual(preview.guard.map((f) => f.level), ['info'], 'the commentary is clean');
    } finally {
      Object.defineProperty(globalThis, 'fetch', {
        configurable: true,
        writable: true,
        value: realFetch,
      });
    }

    assert.equal(calls, 0, 'nothing even attempted a fetch');
    const after = snapshotTree(WORKSPACE);
    assert.deepEqual(
      [...after.keys()].sort(),
      [...before.keys()].sort(),
      'no file was created or removed',
    );
    for (const [file, bytes] of before) {
      assert.equal(after.get(file), bytes, `${file} is byte-identical`);
    }
  });

  test('publishPreview refuses while publishing is disabled, and skips a ledgered URL', async () => {
    const disabled = fixtureConfig({ governance: { publishAllow: false } });
    const fresh = await readDraft(path.join(DRAFTS, 'approved-note.md'));
    const blocked = await publishPreview(
      disabled,
      await buildPreview(disabled, previewRequestFromDraft(fresh)),
      targetFor(disabled),
      { draft: fresh },
    );
    assert.equal(blocked.urn, undefined, 'nothing went out');
    assert.deepEqual(blocked.blocked?.length, 1);
    assert.match(blocked.blocked?.[0] ?? '', /publishing is disabled/);

    // The same URL is already in the fixture ledger, so even with the gate open
    // the answer is "skip", not a second copy.
    const allowed = fixtureConfig();
    const ledgered = await readDraft(path.join(DRAFTS, 'sample-article.md'));
    const outcome = await publishPreview(
      allowed,
      await buildPreview(allowed, previewRequestFromDraft(ledgered)),
      targetFor(allowed),
      { draft: ledgered },
    );
    assert.equal(outcome.urn, undefined);
    assert.match(outcome.skipped ?? '', /already published as /);
    assert.equal(
      await fsp
        .readdir(path.join(WORKSPACE, 'pages/_posts/corp'))
        .then((names) => names.length),
      3,
      'the corp folder still holds exactly its three fixture files',
    );
  });
});
