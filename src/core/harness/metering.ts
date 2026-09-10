/**
 * What an editor agent run cost, written where the fleet's ledger can read it.
 *
 * The fleet meters every CI model call through `scripts/ai/usage.rb`, which
 * appends one JSON object per line to `$AI_USAGE_DIR/records.jsonl` and later
 * folds those into `_data/ai_usage/ledger.jsonl`. This module writes the same
 * record shape for a run started in the editor, so one reader can add up both:
 * the field names are the fleet's (`cost_usd`, `cost_source`, `num_turns`,
 * `session_id`, `tokens.cache_read`), not ones invented here.
 *
 * Two deliberate differences, both visible in the record itself rather than
 * hidden in a convention:
 *
 *  - `source` is `zer0-cms-agent` and `auth` is `sdk` — values the CI writer's
 *    own vocabulary does not use, so a row from this console is identifiable at
 *    a glance and can never be mistaken for a lane's.
 *  - The default path is **outside the checkout** (the extension's global
 *    storage). An editor run is not the repository's business unless somebody
 *    says it is; committing a personal token ledger into a content repo is a
 *    decision, and one nobody made by installing an extension.
 *
 * Keys are sorted on the way out. The CI writer's Ruby emits insertion order,
 * which is fine for an append-only file nobody diffs; a file this console may
 * write from two windows benefits from being byte-stable, and a sorted line is
 * still exactly the same JSON object to every reader.
 */

import { createHash } from 'node:crypto';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { pyJsonDump } from '../shared/jsonio';
import type { UsageRecord } from '../shared/types';

/** The ledger's filename, matching the fleet's `records.jsonl`. */
export const USAGE_FILE = 'records.jsonl';

/** The directory the ledger lives in, under the extension's global storage. */
export const USAGE_DIR = 'ai-usage';

/** Where an editor run's meter writes when nobody chose somewhere else. */
export function defaultUsageLedgerPath(globalStorageDir: string): string {
  return path.join(globalStorageDir, USAGE_DIR, USAGE_FILE);
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : undefined;
}

function num(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function str(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

/**
 * A stable id for one record, the way `usage.rb` computes one: a truncated
 * SHA-256 over the fields that identify the call. Re-recording the same result
 * yields the same id, so a double-append is detectable rather than silent.
 */
export function usageRecordId(parts: readonly string[]): string {
  return createHash('sha256').update(parts.join('|')).digest('hex').slice(0, 16);
}

/**
 * Project the SDK's `result` message onto the fleet's record shape.
 *
 * Every field is read defensively: the SDK's message shape has changed across
 * versions, and a meter that throws on an unfamiliar payload would take the run
 * down with it. An absent number is `0`; an absent cost is `null` — never a
 * zero, because a zero adds up and a `null` does not.
 */
export function usageRecordFrom(
  result: unknown,
  ctx: {
    agent: string | null;
    model: string;
    repo: string;
    workspaceRoot: string;
    startedAt: number;
    now?: number;
  },
): UsageRecord {
  const message = asRecord(result) ?? {};
  const usage = asRecord(message['usage']) ?? {};
  const now = ctx.now ?? Date.now();
  const ts = new Date(now).toISOString();
  const sessionId = str(message['session_id']);
  const reported = message['total_cost_usd'];
  const hasCost = typeof reported === 'number' && Number.isFinite(reported);
  const durationRaw = message['duration_ms'];
  const duration =
    typeof durationRaw === 'number' && Number.isFinite(durationRaw)
      ? durationRaw
      : Math.max(0, now - ctx.startedAt);

  return {
    id: usageRecordId([ctx.repo, ctx.workspaceRoot, sessionId, ts, ctx.model]),
    ts,
    source: 'zer0-cms-agent',
    status: message['is_error'] === true ? 'error' : 'success',
    agent: ctx.agent,
    model: str(message['model']) || ctx.model,
    auth: 'sdk',
    tokens: {
      input: num(usage['input_tokens']),
      output: num(usage['output_tokens']),
      cache_read: num(usage['cache_read_input_tokens']),
      cache_creation: num(usage['cache_creation_input_tokens']),
    },
    cost_usd: hasCost ? (reported as number) : null,
    // `null` under `estimated` is the honest pair for "the SDK reported no cost
    // and this console carries no pricing table", which is not the same claim
    // as a reported zero.
    cost_source: hasCost ? 'reported' : 'estimated',
    duration_ms: duration,
    num_turns: num(message['num_turns']),
    session_id: sessionId,
    repo: ctx.repo,
    workspaceRoot: ctx.workspaceRoot,
  };
}

/** One JSONL line: sorted keys, compact, newline-terminated. */
export function serializeUsageRecord(record: UsageRecord): string {
  return `${pyJsonDump(record, { sortKeys: true })}\n`;
}

/**
 * Append one record. Creates the directory on first use, and appends rather
 * than rewrites so two windows metering at once interleave lines instead of
 * losing one.
 */
export async function appendUsageRecord(filePath: string, record: UsageRecord): Promise<void> {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.appendFile(filePath, serializeUsageRecord(record), 'utf8');
}
