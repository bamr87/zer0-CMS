/**
 * What the fleet costs, read from the ledger each repository already commits.
 *
 * The source is `_data/ai_usage/summary.yml` — the rollup
 * `scripts/ai/usage_ledger.rb` recomputes from `_data/ai_usage/ledger.jsonl`
 * and the `ai-usage` lane commits. The console reads that file through one
 * declared contents call; it computes no cost of its own, and it never reaches
 * a billing API.
 *
 * Three honesty rules govern every number this module produces.
 *
 * **Absent is `null`, never `0`.** "This cost nothing" and "nobody measured" are
 * different answers, and a zero in a cost column reads as the first. So
 * `UsageSummary`'s window totals are `null` when the file did not carry them,
 * and `costByLane` returns **no entry at all** for a lane it could not join —
 * an absent key the caller renders as unknown, rather than a `LaneCost` with
 * zeroes in it.
 *
 * **The window is `all_time`, and it says so in the data.** The rollup's
 * `by_workflow` block is a total over the whole ledger; only the top-level
 * figures carry `last_7d` / `last_30d`, and they are not broken out per
 * workflow. A per-lane number labelled "this week" that is really "since the
 * beginning" is worse than no number, so `LaneCost.window` is a field rather
 * than a comment.
 *
 * **The dollars are API-equivalent.** The ledger's own header says it: the
 * figures are what the tokens would bill at list prices, and a subscription
 * OAuth run has zero marginal cost. `LaneCost.note` carries that label so it
 * cannot be lost between here and the screen.
 */

import { parseYamlSubset } from '../content/frontmatter';
import type { FleetManifest, LaneCost, UsageSummary } from '../shared/types';
import { workflowFileOf } from './manifest';

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function asText(value: unknown): string {
  return value === undefined || value === null ? '' : String(value);
}

/** A number, or `null` when the key was absent or unreadable. Never a silent zero. */
function asNumberOrNull(value: unknown): number | null {
  if (value === undefined || value === null || value === '') {
    return null;
  }
  const n = typeof value === 'number' ? value : Number(String(value));
  return Number.isFinite(n) ? n : null;
}

function asCount(value: unknown): number {
  return asNumberOrNull(value) ?? 0;
}

/** `all_time: { cost_usd }` → the dollars, or `null` when the block is not there. */
function windowCost(summary: Record<string, unknown>, key: string): number | null {
  return asNumberOrNull(asRecord(summary[key])?.cost_usd);
}

/**
 * The ledger counts model **calls**; `UsageSummary` names the field `runs`.
 *
 * One lane run makes several calls, so the two are not the same number. A
 * future ledger that emits `runs:` is read as such; today's emits `calls:` and
 * that is what lands in the field. The console labels the column "calls" for
 * exactly this reason — the shape is the hub's, the honesty is ours.
 */
function runCount(entry: Record<string, unknown>): number {
  return asCount(entry.runs ?? entry.calls);
}

/**
 * Read `_data/ai_usage/summary.yml`.
 *
 * `null` when the text is not a mapping or carries none of the rollup's keys —
 * a repository that has never run the ledger has no usage file, which is a
 * normal state and not an error. A file that is present but says nothing about
 * cost is the same answer as no file at all.
 */
export function parseUsageSummary(text: string): UsageSummary | null {
  const raw = parseYamlSubset(text);
  const known = ['by_workflow', 'by_role', 'all_time', 'last_30d', 'last_7d'];
  if (!known.some((key) => key in raw)) {
    return null;
  }

  const byWorkflow: UsageSummary['byWorkflow'] = [];
  for (const entry of Array.isArray(raw.by_workflow) ? raw.by_workflow : []) {
    const row = asRecord(entry);
    const workflow = asText(row?.workflow);
    if (row === undefined || workflow === '') {
      continue;
    }
    byWorkflow.push({ workflow, runs: runCount(row), costUsd: asCount(row.cost_usd) });
  }

  const byRole: UsageSummary['byRole'] = [];
  for (const entry of Array.isArray(raw.by_role) ? raw.by_role : []) {
    const row = asRecord(entry);
    const role = asText(row?.role);
    if (row === undefined || role === '') {
      continue;
    }
    byRole.push({ role, runs: runCount(row), costUsd: asCount(row.cost_usd) });
  }

  return {
    byWorkflow,
    byRole,
    last7dUsd: windowCost(raw, 'last_7d'),
    last30dUsd: windowCost(raw, 'last_30d'),
    allTimeUsd: windowCost(raw, 'all_time'),
  };
}

/**
 * Join the ledger to the manifest's lanes.
 *
 * The ledger keys its rollup by the **workflow name** — `${{ github.workflow }}`,
 * the `name:` at the top of the file — while a lane names a **path**. Bridging
 * the two needs the repository's own workflow list, which is what
 * `workflowNames` is: `.github/workflows/pipeline.yml` → `pipeline`, straight
 * from `FleetClient.listWorkflows()`. The bare file name is accepted as a key
 * too, so a caller that already has a filename-keyed map works; the full path
 * wins when both are present.
 *
 * A lane with no workflow, no name for its workflow, or no ledger row for that
 * name is **absent from the result**. That is the "nobody measured" answer, and
 * it is deliberately not a `LaneCost` full of zeroes: the caller renders an
 * absent key as unknown.
 *
 * Pure — no I/O, no clock, and the inputs are never mutated.
 */
export function costByLane(
  summary: UsageSummary,
  manifest: FleetManifest,
  workflowNames: ReadonlyMap<string, string>,
): ReadonlyMap<string, LaneCost> {
  const ledger = new Map<string, UsageSummary['byWorkflow'][number]>();
  for (const row of summary.byWorkflow) {
    if (!ledger.has(row.workflow)) {
      ledger.set(row.workflow, row);
    }
  }

  const costs = new Map<string, LaneCost>();
  for (const lane of manifest.lanes) {
    const file = workflowFileOf(lane);
    const workflowName =
      (lane.implementation === '' ? undefined : workflowNames.get(lane.implementation)) ??
      (file === '' ? undefined : workflowNames.get(file));
    if (workflowName === undefined) {
      continue;
    }
    const row = ledger.get(workflowName);
    if (row === undefined) {
      continue;
    }
    costs.set(lane.id, {
      laneId: lane.id,
      workflowName,
      runs: row.runs,
      costUsd: row.costUsd,
      window: 'all_time',
      note: 'API-equivalent',
    });
  }
  return costs;
}
