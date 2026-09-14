/**
 * `_data/ai_usage/{ledger.jsonl,summary.yml}` — what a repository's automation
 * has actually spent.
 *
 * Metering is the seventh file in a lane's join, and the only one that exists in
 * exactly one repository: lifehacker.dev writes a JSONL record per model call
 * (`scripts/ai/usage.rb`), folds them into a committed ledger, and rolls that up
 * into `summary.yml`. Everybody else has thirty-day artifacts or nothing. So the
 * honest answer for most of the fleet is `null`, and this module returns `null`
 * — never a zero.
 *
 * That distinction is the reason this file exists rather than a `reduce` at the
 * call site. A `0` adds up: a scorecard that showed "spend: $0.00" for a
 * repository with no ledger would be reporting an absence as an achievement, and
 * a fleet total that summed those zeros would be quietly wrong. Decision D9's
 * rule for a missing `.cms/` is the same rule here: report less, never invent.
 *
 * ## The join keys, and the one that surprises
 *
 * A ledger row carries `agent` and `workflow`. `agent` joins to
 * `.claude/agents/<name>.md`. `workflow` joins to the workflow's **`name:`** —
 * not its filename stem: the rows say `pipeline` and `Factory: Issue Factory 1`,
 * which are `name:` values. `joins.ts` matches on the name for that reason, and
 * a lane whose workflow was renamed loses its own history, which is a fact about
 * the ledger rather than a defect in the reader.
 *
 * ## Which numbers come from where
 *
 * `byRole` and `byWorkflow` are computed from the ledger rows — per-row is the
 * finest grain available and it is always there when a ledger is. The three
 * window totals come from `summary.yml`, because those windows are relative to
 * the moment the rollup was generated (`generated_at`), and recomputing "the
 * last seven days" against *now* would silently answer a different question than
 * the site's own published page. When there is no summary, `allTimeUsd` is
 * summed from the rows and the two windows stay `null`.
 *
 * `unit` is stated rather than assumed: these are API-equivalent dollars — what
 * the tokens would have billed at list prices — and a subscription OAuth run has
 * no marginal cost at all. A dashboard that forgets that lies quietly.
 */

import { parseYamlSubset, type FmValue } from '../content/frontmatter';
import type { LedgerSummary } from '../shared/types';
import type { HarnessIo } from './agents';

/** Where the fleet's one metered repository keeps its ledger. */
export const LEDGER_PATH = '_data/ai_usage/ledger.jsonl';

/** Its committed rollup, rendered by Liquid on the site's own usage page. */
export const LEDGER_SUMMARY_PATH = '_data/ai_usage/summary.yml';

interface Bucket {
  calls: number;
  costUsd: number;
}

function bump(into: Record<string, Bucket>, key: string, costUsd: number | null): void {
  const bucket = into[key] ?? { calls: 0, costUsd: 0 };
  bucket.calls += 1;
  if (costUsd !== null) {
    bucket.costUsd += costUsd;
  }
  into[key] = bucket;
}

/** A finite number, or `null`. A ledger row's cost may legitimately be absent. */
function finite(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function text(value: unknown): string {
  return value === undefined || value === null ? '' : String(value).trim();
}

/** Round to cents-and-then-some, so a float sum does not print 0.6396584999999. */
function round(value: number): number {
  return Math.round(value * 1e6) / 1e6;
}

interface LedgerRow {
  agent: string;
  workflow: string;
  costUsd: number | null;
}

/**
 * One JSONL line. A row this reader cannot parse is skipped rather than thrown:
 * the file is append-only, written by two different scripts and occasionally a
 * third, and one truncated line at the end of it must not cost the whole ledger.
 */
function parseRow(line: string): LedgerRow | null {
  const trimmed = line.trim();
  if (trimmed === '' || !trimmed.startsWith('{')) {
    return null;
  }
  let raw: unknown;
  try {
    raw = JSON.parse(trimmed);
  } catch {
    return null;
  }
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
    return null;
  }
  const record = raw as Record<string, unknown>;
  return {
    agent: text(record['agent']),
    workflow: text(record['workflow']),
    costUsd: finite(record['cost_usd']),
  };
}

/** `summary.yml`'s three window totals, or `null` for each it does not carry. */
function windowsOf(summaryText: string | undefined): {
  last7dUsd: number | null;
  last30dUsd: number | null;
  allTimeUsd: number | null;
} {
  if (summaryText === undefined) {
    return { last7dUsd: null, last30dUsd: null, allTimeUsd: null };
  }
  const data = parseYamlSubset(summaryText);
  return {
    last7dUsd: costIn(data['last_7d']),
    last30dUsd: costIn(data['last_30d']),
    allTimeUsd: costIn(data['all_time']),
  };
}

function costIn(value: FmValue | undefined): number | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return null;
  }
  return finite((value as Record<string, FmValue>)['cost_usd']);
}

/** `summary.yml`'s `by_workflow:` / `by_role:` lists, when there are no rows to count. */
function bucketsFromSummary(
  summaryText: string | undefined,
  key: 'by_workflow' | 'by_role',
  nameKey: 'workflow' | 'role',
): Record<string, Bucket> {
  const out: Record<string, Bucket> = {};
  if (summaryText === undefined) {
    return out;
  }
  const rows = parseYamlSubset(summaryText)[key];
  if (!Array.isArray(rows)) {
    return out;
  }
  for (const row of rows) {
    if (typeof row !== 'object' || row === null || Array.isArray(row)) {
      continue;
    }
    const entry = row as Record<string, FmValue>;
    const name = text(entry[nameKey]);
    if (name === '') {
      continue;
    }
    out[name] = {
      calls: finite(entry['calls']) ?? 0,
      costUsd: round(finite(entry['cost_usd']) ?? 0),
    };
  }
  return out;
}

/**
 * Parse a ledger and its rollup into one summary. `null` when neither file is
 * there — which is the state of five of the six repositories in this fleet, and
 * a normal one.
 */
export function parseLedger(
  ledgerPath: string,
  ledgerText: string | undefined,
  summaryText?: string | undefined,
): LedgerSummary | null {
  if (ledgerText === undefined && summaryText === undefined) {
    return null;
  }
  const byRole: Record<string, Bucket> = {};
  const byWorkflow: Record<string, Bucket> = {};
  let records = 0;
  let summed = 0;
  let sawCost = false;

  for (const line of (ledgerText ?? '').split('\n')) {
    const row = parseRow(line);
    if (row === null) {
      continue;
    }
    records += 1;
    if (row.agent !== '') {
      bump(byRole, row.agent, row.costUsd);
    }
    if (row.workflow !== '') {
      bump(byWorkflow, row.workflow, row.costUsd);
    }
    if (row.costUsd !== null) {
      summed += row.costUsd;
      sawCost = true;
    }
  }

  for (const bucket of [...Object.values(byRole), ...Object.values(byWorkflow)]) {
    bucket.costUsd = round(bucket.costUsd);
  }

  const windows = windowsOf(summaryText);
  return {
    path: ledgerPath,
    records,
    byRole: records === 0 ? bucketsFromSummary(summaryText, 'by_role', 'role') : byRole,
    byWorkflow:
      records === 0 ? bucketsFromSummary(summaryText, 'by_workflow', 'workflow') : byWorkflow,
    last7dUsd: windows.last7dUsd,
    last30dUsd: windows.last30dUsd,
    // The rollup is authoritative for all-time when it exists; otherwise the
    // rows are summed. `null` when neither said, never `0`.
    allTimeUsd: windows.allTimeUsd ?? (sawCost ? round(summed) : null),
    unit: 'api-equivalent-usd',
  };
}

/** Read a repository's ledger, or `null` when it does not meter (decision D9). */
export async function readLedger(
  io: HarnessIo,
  ledgerPath: string = LEDGER_PATH,
  summaryPath: string = LEDGER_SUMMARY_PATH,
): Promise<LedgerSummary | null> {
  const [ledgerText, summaryText] = await Promise.all([
    io.read(ledgerPath),
    io.read(summaryPath),
  ]);
  return parseLedger(ledgerPath, ledgerText, summaryText);
}
