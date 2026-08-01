/**
 * The `.cms/` contract — the file bus between the content engine and every
 * surface that reads content.
 *
 * `.cms/` is the machine-readable view of a whole site: one index, many
 * outputs, so there is never a second definition of "a page". This module
 * READS `.cms/index/content-index.json` and `.cms/index/summary.json`, and
 * WRITES `.cms/distribution/` (aggregate performance and catering worklists).
 *
 * Two properties carry the design:
 *
 *   1. **Absence is a normal state** (decision D9). A repository with no
 *      `.cms/` is not an error and never throws — `loadContract` always
 *      resolves an object whose `present` flag says which world you are in,
 *      and `loadContractOrScan` fills the same `ContentRecord` shape from the
 *      filesystem, with `health: -1` and `freshness: 'unknown'`, so the
 *      distributable rule degrades honestly to "not a draft and has a title".
 *
 *   2. **Issues keep their lane.** BASH-CMS's port flattened `issues` to a
 *      list of `kind` strings; the mechanical-vs-substantive lane is the whole
 *      premise of the curation workflow, so the full `CmsIssue` survives here
 *      and `issueKinds()` is the derived helper for callers that only wanted
 *      the names.
 *
 * Everything the engine hands over is coerced field by field. A malformed
 * index produces a wrong-but-well-typed record rather than a `TypeError` three
 * modules away from the bad byte.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { buildIndex, pageToRecord } from '../content/pageIndex';
import { atomicWriteFile } from '../shared/atomic';
import { absPath } from '../shared/config';
import { pyJsonDump } from '../shared/jsonio';
import { utcStamp } from '../shared/timestamp';
import {
  NOOP_LOG,
  UNKNOWN_COUNT,
  type CmsIssue,
  type ContentRecord,
  type Freshness,
  type Lane,
  type LogSink,
  type PerfStats,
  type Severity,
  type Zer0Config,
} from '../shared/types';

// ---------------------------------------------------------------------------
// Layout and thresholds
// ---------------------------------------------------------------------------

/** Conventional name of the contract directory inside a repository. */
export const CMS_DIRNAME = '.cms';

/** Where the engine writes the index it generates. */
export const INDEX_DIRNAME = 'index';

/** Where *this* lane writes: performance aggregates and catering worklists. */
export const DISTRIBUTION_DIRNAME = 'distribution';

/** Health at or above this is worth putting in front of an audience. */
export const PUBLISHABLE_HEALTH = 70;

/** Freshness bands the engine considers current; anything else counts as stale. */
export const FRESH_BANDS: readonly Freshness[] = ['fresh', 'aging'];

/** The metric names the performance file is allowed to carry. */
export const METRICS = ['impressions', 'clicks', 'reactions', 'comments', 'shares'] as const;

const FRESHNESS_VALUES: readonly Freshness[] = ['fresh', 'aging', 'stale', 'critical', 'unknown'];
const SEVERITY_VALUES: readonly Severity[] = ['error', 'warning', 'info'];
const LANE_VALUES: readonly Lane[] = ['mechanical', 'substantive'];

// ---------------------------------------------------------------------------
// Coercion — the boundary where engine JSON becomes typed domain values
// ---------------------------------------------------------------------------

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

/**
 * Read a key by its engine spelling, falling back to the camelCase form.
 * The engine emits snake_case; our own writers emit camelCase. Accepting both
 * costs three lines and removes a whole class of "why is this field zero?".
 */
function pick(raw: Record<string, unknown>, snake: string, camel?: string): unknown {
  const primary = raw[snake];
  if (primary !== undefined) {
    return primary;
  }
  return camel === undefined ? undefined : raw[camel];
}

function asText(value: unknown): string {
  return value === undefined || value === null ? '' : String(value);
}

function asTextOrNull(value: unknown): string | null {
  return value === undefined || value === null ? null : String(value);
}

/** Integers with a defined fallback: `NaN` never escapes this function. */
function asInt(value: unknown, fallback: number): number {
  if (value === undefined || value === null || value === '') {
    return fallback;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.trunc(parsed) : fallback;
}

function asIntOrUndefined(value: unknown): number | undefined {
  if (value === undefined || value === null || value === '') {
    return undefined;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.trunc(parsed) : undefined;
}

function asFloatOrNull(value: unknown): number | null {
  if (value === undefined || value === null || value === '') {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** `null` is meaningful for `draft`: "the engine did not decide", not `false`. */
function asBoolOrNull(value: unknown): boolean | null {
  return value === undefined || value === null ? null : Boolean(value);
}

function asMember<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  const text = asText(value);
  return (allowed as readonly string[]).includes(text) ? (text as T) : fallback;
}

// ---------------------------------------------------------------------------
// Issues
// ---------------------------------------------------------------------------

/**
 * Coerce one engine issue.
 *
 * Two defaults are deliberate. An unrecognised severity becomes `warning`
 * rather than `info`, so a level we have not seen yet is not silently made
 * invisible; an unrecognised lane becomes `substantive`, because "a human
 * should look at this" is the safe answer when we cannot tell whether a fix is
 * mechanical.
 */
function coerceIssue(raw: unknown): CmsIssue | undefined {
  const entry = asRecord(raw);
  if (!entry) {
    return undefined;
  }
  const kind = asText(pick(entry, 'kind')).trim();
  const message = asText(pick(entry, 'message'));
  if (kind === '' && message === '') {
    return undefined;
  }
  return {
    kind: kind === '' ? 'unknown' : kind,
    severity: asMember(pick(entry, 'severity'), SEVERITY_VALUES, 'warning'),
    field: asTextOrNull(pick(entry, 'field')),
    message,
    lane: asMember(pick(entry, 'lane'), LANE_VALUES, 'substantive'),
    suggestion: asTextOrNull(pick(entry, 'suggestion')),
  };
}

function coerceIssues(raw: unknown): CmsIssue[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  const issues: CmsIssue[] = [];
  for (const entry of raw) {
    const issue = coerceIssue(entry);
    if (issue) {
      issues.push(issue);
    }
  }
  return issues;
}

/** The issue *names* on a record — the flattened view older consumers want. */
export function issueKinds(record: ContentRecord): string[] {
  return record.issues.map((issue) => issue.kind);
}

/** Only the issues in one lane. `mechanical` is the safely auto-fixable half. */
export function issuesByLane(record: ContentRecord, lane: Lane): CmsIssue[] {
  return record.issues.filter((issue) => issue.lane === lane);
}

/** Only the issues at or above `severity`, ordered error → warning → info. */
export function issuesBySeverity(record: ContentRecord, severity: Severity): CmsIssue[] {
  const floor = SEVERITY_VALUES.indexOf(severity);
  return record.issues.filter((issue) => SEVERITY_VALUES.indexOf(issue.severity) <= floor);
}

// ---------------------------------------------------------------------------
// Records
// ---------------------------------------------------------------------------

function coerceRecord(raw: Record<string, unknown>): ContentRecord {
  return {
    path: asText(pick(raw, 'path')),
    collection: asText(pick(raw, 'collection')),
    title: asText(pick(raw, 'title')),
    descriptionLen: asInt(pick(raw, 'description_len', 'descriptionLen'), 0),
    titleLen: asInt(pick(raw, 'title_len', 'titleLen'), 0),
    // An index that omits these did not measure them; `health` has always
    // defaulted this way and these two now agree with it.
    wordCount: asInt(pick(raw, 'word_count', 'wordCount'), UNKNOWN_COUNT),
    headingCount: asInt(pick(raw, 'heading_count', 'headingCount'), UNKNOWN_COUNT),
    health: asInt(pick(raw, 'health'), -1),
    freshness: asMember(pick(raw, 'freshness'), FRESHNESS_VALUES, 'unknown'),
    draft: asBoolOrNull(pick(raw, 'draft')),
    generated: Boolean(pick(raw, 'generated')),
    structural: Boolean(pick(raw, 'structural')),
    readOnly: Boolean(pick(raw, 'read_only', 'readOnly')),
    isNotebook: Boolean(pick(raw, 'is_notebook', 'isNotebook')),
    frontmatterPresent: Boolean(pick(raw, 'frontmatter_present', 'frontmatterPresent')),
    date: asTextOrNull(pick(raw, 'date')),
    lastmod: asTextOrNull(pick(raw, 'lastmod')),
    ageDays: asInt(pick(raw, 'age_days', 'ageDays'), 0),
    brokenLinks: asInt(pick(raw, 'broken_links', 'brokenLinks'), 0),
    issues: coerceIssues(pick(raw, 'issues')),
  };
}

/** Filename stem of a record's path — the short handle humans and tools use. */
export function recordSlug(record: Pick<ContentRecord, 'path'>): string {
  return path.basename(record.path).replace(/\.[^.]*$/, '');
}

/**
 * Whether it is honest to put this in front of an audience.
 *
 * Drafts, generated files and structural pages never qualify. A *scored* page
 * must reach `PUBLISHABLE_HEALTH`; an unscored one (`health === -1`) is not
 * punished for the engine's absence — it only has to have a title. So 70 is
 * in, 69 is out, and -1 is in.
 */
export function isDistributable(record: ContentRecord): boolean {
  if (record.draft === true || record.generated || record.structural) {
    return false;
  }
  if (record.health >= 0 && record.health < PUBLISHABLE_HEALTH) {
    return false;
  }
  return record.title !== '';
}

/**
 * Whether a tool may write to this file. A different question from
 * `isDistributable`: that one asks "may we show this to an audience", this one
 * asks "may an agent edit it". Generated output and vendored/read-only files
 * are off limits regardless of how good they score.
 */
export function isEditable(record: ContentRecord): boolean {
  return !record.readOnly && !record.generated && !record.structural && !record.isNotebook;
}

/** Coarse health band, for grouping and for icon selection in the shell. */
export function healthBucket(health: number): 'unknown' | 'poor' | 'fair' | 'good' | 'excellent' {
  if (health < 0) {
    return 'unknown';
  }
  if (health >= 90) {
    return 'excellent';
  }
  if (health >= PUBLISHABLE_HEALTH) {
    return 'good';
  }
  if (health >= 50) {
    return 'fair';
  }
  return 'poor';
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------

export interface CollectionSummary {
  count?: number;
  scored?: number;
  mechanical?: number;
  substantive?: number;
  errors?: number;
  avgHealth?: number | null;
}

/**
 * The engine's own roll-up of the index.
 *
 * Every field is optional on purpose: an absent `.cms/` yields the literal
 * `{}`, and an engine version that has not learned a key yet must not force
 * every reader through a `?? 0` dance for a number it never wrote. Readers get
 * a typed shape; writers of the engine get room to move.
 */
export interface CmsSummary {
  generatedAt?: string;
  totalFiles?: number;
  scoredFiles?: number;
  actionableFiles?: number;
  avgHealth?: number | null;
  avgHealthActionable?: number | null;
  totalMechanicalIssues?: number;
  totalSubstantiveIssues?: number;
  totalErrors?: number;
  readOnlyFiles?: number;
  byCollection?: Record<string, CollectionSummary>;
  freshnessDistribution?: Record<string, number>;
  healthBuckets?: Record<string, number>;
}

type SummaryCountKey =
  | 'totalFiles'
  | 'scoredFiles'
  | 'actionableFiles'
  | 'totalMechanicalIssues'
  | 'totalSubstantiveIssues'
  | 'totalErrors'
  | 'readOnlyFiles';

const SUMMARY_COUNTS: ReadonlyArray<readonly [SummaryCountKey, string]> = [
  ['totalFiles', 'total_files'],
  ['scoredFiles', 'scored_files'],
  ['actionableFiles', 'actionable_files'],
  ['totalMechanicalIssues', 'total_mechanical_issues'],
  ['totalSubstantiveIssues', 'total_substantive_issues'],
  ['totalErrors', 'total_errors'],
  ['readOnlyFiles', 'read_only_files'],
];

function coerceCounters(raw: unknown): Record<string, number> {
  const entry = asRecord(raw);
  if (!entry) {
    return {};
  }
  const out: Record<string, number> = {};
  for (const [key, value] of Object.entries(entry)) {
    out[key] = asInt(value, 0);
  }
  return out;
}

function coerceCollections(raw: unknown): Record<string, CollectionSummary> {
  const entry = asRecord(raw);
  if (!entry) {
    return {};
  }
  const out: Record<string, CollectionSummary> = {};
  for (const [name, value] of Object.entries(entry)) {
    const row = asRecord(value);
    if (!row) {
      continue;
    }
    out[name] = {
      count: asInt(pick(row, 'count'), 0),
      scored: asInt(pick(row, 'scored'), 0),
      mechanical: asInt(pick(row, 'mechanical'), 0),
      substantive: asInt(pick(row, 'substantive'), 0),
      errors: asInt(pick(row, 'errors'), 0),
      avgHealth: asFloatOrNull(pick(row, 'avg_health', 'avgHealth')),
    };
  }
  return out;
}

function coerceSummary(raw: unknown): CmsSummary {
  const entry = asRecord(raw);
  if (!entry) {
    return {};
  }
  const summary: CmsSummary = {};

  const generatedAt = pick(entry, 'generated_at', 'generatedAt');
  if (generatedAt !== undefined && generatedAt !== null) {
    summary.generatedAt = String(generatedAt);
  }
  for (const [key, snake] of SUMMARY_COUNTS) {
    const value = asIntOrUndefined(pick(entry, snake, key));
    if (value !== undefined) {
      summary[key] = value;
    }
  }
  if (pick(entry, 'avg_health', 'avgHealth') !== undefined) {
    summary.avgHealth = asFloatOrNull(pick(entry, 'avg_health', 'avgHealth'));
  }
  if (pick(entry, 'avg_health_actionable', 'avgHealthActionable') !== undefined) {
    summary.avgHealthActionable = asFloatOrNull(
      pick(entry, 'avg_health_actionable', 'avgHealthActionable'),
    );
  }
  if (pick(entry, 'by_collection', 'byCollection') !== undefined) {
    summary.byCollection = coerceCollections(pick(entry, 'by_collection', 'byCollection'));
  }
  if (pick(entry, 'freshness_distribution', 'freshnessDistribution') !== undefined) {
    summary.freshnessDistribution = coerceCounters(
      pick(entry, 'freshness_distribution', 'freshnessDistribution'),
    );
  }
  if (pick(entry, 'health_buckets', 'healthBuckets') !== undefined) {
    summary.healthBuckets = coerceCounters(pick(entry, 'health_buckets', 'healthBuckets'));
  }
  return summary;
}

// ---------------------------------------------------------------------------
// The contract object
// ---------------------------------------------------------------------------

export interface Contract {
  /** Repository root the contract describes. Record paths are relative to it. */
  root: string;
  /**
   * Absolute path of the contract directory. Normally `<root>/.cms`, but
   * `zer0Cms.cms.root` may point somewhere else, so the directory is carried
   * on the object rather than recomputed by every writer.
   */
  dir: string;
  /** `false` means there is no `.cms/index/content-index.json` to read. */
  present: boolean;
  /** The engine's own timestamp for the index; `''` when absent. */
  generatedAt: string;
  records: ContentRecord[];
  summary: CmsSummary;
}

export interface LoadContractOptions {
  /** Absolute (or root-relative) contract directory. Defaults to `<root>/.cms`. */
  dir?: string;
}

export function cmsDir(contract: Contract): string {
  return contract.dir;
}

export function indexDir(contract: Contract): string {
  return path.join(contract.dir, INDEX_DIRNAME);
}

export function distributionDir(contract: Contract): string {
  return path.join(contract.dir, DISTRIBUTION_DIRNAME);
}

/** Never throws: a missing file, a directory in its place, or malformed JSON
 *  all mean "no data here", which is a state this module is built to hold. */
async function readJsonQuietly(filePath: string): Promise<unknown> {
  try {
    return JSON.parse(await fs.readFile(filePath, 'utf8')) as unknown;
  } catch {
    // Deliberately swallowed. `loadContract` reports absence through
    // `present: false`; turning an unreadable index into a rejected promise
    // would make "this repo has no engine" an error at every call site.
    return undefined;
  }
}

/**
 * Read `.cms/` if the repository has one.
 *
 * Always resolves. With no index the result is
 * `{ present: false, generatedAt: '', records: [], summary: {} }` — the same
 * shape, so callers branch on `present` instead of on `undefined`.
 */
export async function loadContract(
  root: string,
  options: LoadContractOptions = {},
): Promise<Contract> {
  const dir = options.dir === undefined ? path.join(root, CMS_DIRNAME) : path.resolve(root, options.dir);
  const contract: Contract = {
    root,
    dir,
    present: false,
    generatedAt: '',
    records: [],
    summary: {},
  };

  contract.summary = coerceSummary(
    await readJsonQuietly(path.join(dir, INDEX_DIRNAME, 'summary.json')),
  );

  const raw = asRecord(await readJsonQuietly(path.join(dir, INDEX_DIRNAME, 'content-index.json')));
  if (!raw) {
    // Keep any summary we did read: a half-written `.cms/` is more useful than
    // none, and `present` still says the index itself is missing.
    return contract;
  }

  contract.present = true;
  contract.generatedAt = asText(pick(raw, 'generated_at', 'generatedAt'));
  const files = pick(raw, 'files', 'records');
  if (Array.isArray(files)) {
    for (const entry of files) {
      const row = asRecord(entry);
      if (row) {
        contract.records.push(coerceRecord(row));
      }
    }
  }
  return contract;
}

/**
 * The contract, or the filesystem standing in for it (decision D9).
 *
 * When `.cms/` is missing, the page index supplies the same `ContentRecord`
 * shape with `health: -1` and `freshness: 'unknown'`. `present` stays `false`
 * — the records are real, the engine's judgement is not.
 */
export async function loadContractOrScan(
  cfg: Zer0Config,
  log: LogSink = NOOP_LOG,
): Promise<Contract> {
  const contract = await loadContract(cfg.workspaceRoot, { dir: absPath(cfg, cfg.cms.root) });
  if (contract.present) {
    return contract;
  }
  try {
    const { pages } = await buildIndex(cfg);
    contract.records = pages.map((page) => pageToRecord(cfg, page));
  } catch (error) {
    // A scan failure degrades to "no records", never to a thrown promise: the
    // dashboard and the MCP server both call this on every refresh, and an
    // unreadable content folder must not take the whole surface down.
    log.warn(`content scan failed: ${error instanceof Error ? error.message : String(error)}`);
  }
  return contract;
}

// ---------------------------------------------------------------------------
// Lookups
// ---------------------------------------------------------------------------

/** Publishable content, best-scored first (health desc, then path asc). */
export function distributable(contract: Contract): ContentRecord[] {
  const ready = contract.records.filter(isDistributable);
  ready.sort((a, b) => {
    const left = a.health >= 0 ? a.health : 0;
    const right = b.health >= 0 ? b.health : 0;
    if (right !== left) {
      return right - left;
    }
    return a.path < b.path ? -1 : a.path > b.path ? 1 : 0;
  });
  return ready;
}

/**
 * Find a record by its exact path or by its filename stem.
 *
 * The stem is tried both as-is and with a `YYYY-MM-DD-` prefix removed,
 * because a Jekyll file is called `2026-07-31-hello.md` and every human who
 * refers to it says "hello". Path matches win over stem matches, and an exact
 * stem wins over a date-stripped one, so an unambiguous reference is never
 * resolved to the wrong file.
 */
export function byPath(contract: Contract, pathOrSlug: string): ContentRecord | undefined {
  const wanted = pathOrSlug.trim();
  if (wanted === '') {
    return undefined;
  }
  const posix = wanted.split(path.sep).join('/');
  return (
    contract.records.find((record) => record.path === posix || record.path === wanted) ??
    contract.records.find((record) => recordSlug(record) === wanted) ??
    contract.records.find((record) => stripDatePrefix(recordSlug(record)) === wanted)
  );
}

function stripDatePrefix(stem: string): string {
  return stem.replace(/^\d{4}-\d{2}-\d{2}-/, '');
}

/** Records grouped by collection, collections in insertion order. */
export function byCollection(contract: Contract): Map<string, ContentRecord[]> {
  const grouped = new Map<string, ContentRecord[]>();
  for (const record of contract.records) {
    const key = record.collection || 'uncategorised';
    const bucket = grouped.get(key);
    if (bucket) {
      bucket.push(record);
    } else {
      grouped.set(key, [record]);
    }
  }
  return grouped;
}

// ---------------------------------------------------------------------------
// Performance — the author's own aggregate numbers
// ---------------------------------------------------------------------------

/**
 * Keep only the known metrics; `engagements` is derived, never read raw.
 *
 * Unknown keys are dropped rather than passed through, which is what makes
 * this file safe to hand to an agent: whatever an upstream export contains,
 * only five counters can survive into the repository.
 */
export function normalisePerformance(raw: Record<string, unknown>): PerfStats {
  const clean = { impressions: 0, clicks: 0, reactions: 0, comments: 0, shares: 0 };
  for (const key of METRICS) {
    clean[key] = asInt(raw[key], 0);
  }
  return { ...clean, engagements: clean.reactions + clean.comments + clean.shares };
}

export function performancePath(contract: Contract): string {
  return path.join(distributionDir(contract), 'performance.json');
}

/** Per-content engagement, keyed by content path. Missing or corrupt → `{}`. */
export async function loadPerformance(contract: Contract): Promise<Record<string, PerfStats>> {
  const data = asRecord(await readJsonQuietly(performancePath(contract)));
  const content = data === undefined ? undefined : asRecord(data.content);
  if (!content) {
    return {};
  }
  const out: Record<string, PerfStats> = {};
  for (const [contentPath, stats] of Object.entries(content)) {
    const row = asRecord(stats);
    if (row) {
      out[contentPath] = normalisePerformance(row);
    }
  }
  return out;
}

export async function writePerformance(
  contract: Contract,
  content: Record<string, PerfStats>,
): Promise<string> {
  const target = performancePath(contract);
  const payload = {
    generated_at: utcStamp(),
    note: "Aggregate statistics for the author's own content. No per-reader data.",
    content,
  };
  await atomicWriteFile(target, `${pyJsonDump(payload, { indent: 2, ensureAscii: true })}\n`);
  return target;
}

// ---------------------------------------------------------------------------
// Worklists
// ---------------------------------------------------------------------------

export function worklistPath(contract: Contract, date: string): string {
  return path.join(distributionDir(contract), 'worklists', `${date}-catering.md`);
}

/** Write `.cms/distribution/worklists/<date>-catering.md`; returns the path. */
export async function writeWorklist(
  contract: Contract,
  date: string,
  body: string,
): Promise<string> {
  const target = worklistPath(contract, date);
  await atomicWriteFile(target, body);
  return target;
}
