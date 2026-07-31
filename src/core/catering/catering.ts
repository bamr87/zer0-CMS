/**
 * Catering — deciding what to write next from how the audience responded.
 *
 * Joins three files that already exist — the content index (`.cms/`), the
 * publish ledger, and per-content engagement — and answers four questions:
 *
 *   Lane A  what strong content was never distributed
 *   Lane B  which topics earned attention
 *   Lane C  which topics consistently did not
 *   Lane D  what performed and has since gone stale
 *
 * Every ranking comes from the author's OWN aggregate numbers. Nothing here
 * looks at who engaged, and no per-reader data enters this module — which is
 * why the whole thing is a pure function of three JSON files.
 *
 * The arithmetic is Python-compatible on purpose: `roundHalfEven` is Python's
 * `round()`, and the median is Python's `signals[len(signals) // 2]` on a
 * *descending* list. Both are pinned by the golden worklist test, so the
 * TypeScript and Python lanes produce the same bytes for the same inputs.
 */

import {
  FRESH_BANDS,
  byPath,
  distributable,
  type Contract,
} from '../contract/contract';
import { publishedSourceFiles, type Ledger } from '../governance/ledger';
import type { ContentRecord, PerfStats } from '../shared/types';

/** Below this many observations a per-topic average is noise, not a signal. */
export const MIN_OBSERVATIONS = 2;

/** How many rows each lane may contribute to a worklist. */
export const LANE_LIMITS = { undistributed: 15, proven: 6, quiet: 6, refresh: 10 } as const;

export interface TopicSignal {
  topic: string;
  posts: number;
  impressions: number;
  engagements: number;
}

export interface CateringPlan {
  undistributed: ContentRecord[];
  proven: TopicSignal[];
  quiet: TopicSignal[];
  refresh: ContentRecord[];
  /** How many pieces of content have any statistics at all. */
  observations: number;
}

/**
 * Python-parity banker's rounding (round-half-to-even) — the semantics of
 * Python's built-in `round()` and of `{:.2%}` formatting. JavaScript's
 * `Math.round` rounds half *up*, which diverges on exactly the values a
 * percentage table is full of.
 */
export function roundHalfEven(x: number, digits: number): number {
  const scale = Math.pow(10, digits);
  const scaled = x * scale;
  const floor = Math.floor(scaled);
  const diff = scaled - floor;
  const eps = 1e-9;
  if (Math.abs(diff - 0.5) < eps) {
    return (floor % 2 === 0 ? floor : floor + 1) / scale;
  }
  return Math.round(scaled) / scale;
}

/** Engagements per impression — the only rate comparable across topics. */
export function rateOf(signal: TopicSignal): number {
  return signal.impressions ? roundHalfEven(signal.engagements / signal.impressions, 4) : 0.0;
}

/** Enough posts, and somebody saw them. Below this a rate is an anecdote. */
export function isConfident(signal: TopicSignal): boolean {
  return signal.posts >= MIN_OBSERVATIONS && signal.impressions > 0;
}

/** Whether any audience data exists yet. Lane B stays empty rather than guess. */
export function hasEvidence(plan: CateringPlan): boolean {
  return plan.observations > 0;
}

/** Group engagement by the collection each piece of content belongs to. */
function topicSignals(
  performance: Record<string, PerfStats>,
  contract: Contract,
): TopicSignal[] {
  const grouped = new Map<string, TopicSignal>();
  for (const [contentPath, stats] of Object.entries(performance)) {
    if (stats === null || typeof stats !== 'object') {
      continue;
    }
    const record = byPath(contract, contentPath);
    const topic = record?.collection || 'uncategorised';
    let signal = grouped.get(topic);
    if (!signal) {
      signal = { topic, posts: 0, impressions: 0, engagements: 0 };
      grouped.set(topic, signal);
    }
    signal.posts += 1;
    signal.impressions += toCount(stats.impressions);
    signal.engagements += toCount(stats.engagements);
  }
  return [...grouped.values()];
}

function toCount(value: unknown): number {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? Math.trunc(parsed) : 0;
}

/**
 * Build the four lanes.
 *
 * The median is deliberately Python's `signals[len(signals) // 2]` applied to
 * a list sorted by rate *descending* — for an even-length list that is the
 * lower-middle element, not the mean of the two middles, and for an odd-length
 * one it is the true middle. It is a pseudo-median and the asymmetry is
 * intentional: `>= median` goes to "proven", so a tie lands in the optimistic
 * lane. Do not "fix" it without regenerating the golden worklist.
 */
export function buildCatering(
  contract: Contract,
  performance: Record<string, PerfStats>,
  publishedPaths: ReadonlySet<string>,
): CateringPlan {
  const plan: CateringPlan = {
    undistributed: [],
    proven: [],
    quiet: [],
    refresh: [],
    observations: Object.keys(performance).length,
  };

  // Lane A — strong content nobody has seen. Ranked by health, best first.
  plan.undistributed = distributable(contract)
    .filter((record) => !publishedPaths.has(record.path))
    .slice(0, LANE_LIMITS.undistributed);

  // Lanes B and C — topics that landed, and topics that did not.
  const signals = topicSignals(performance, contract).filter(isConfident);
  signals.sort((a, b) => rateOf(b) - rateOf(a));
  const middle = signals[Math.floor(signals.length / 2)];
  if (middle !== undefined) {
    const median = rateOf(middle);
    plan.proven = signals.filter((s) => rateOf(s) >= median).slice(0, LANE_LIMITS.proven);
    plan.quiet = signals.filter((s) => rateOf(s) < median).slice(0, LANE_LIMITS.quiet);
  }

  // Lane D — content that earned attention and has since gone stale.
  const refresh: ContentRecord[] = [];
  for (const [contentPath, stats] of Object.entries(performance)) {
    const record = byPath(contract, contentPath);
    if (
      record &&
      !FRESH_BANDS.includes(record.freshness) &&
      toCount(stats?.engagements) > 0
    ) {
      refresh.push(record);
    }
  }
  plan.refresh = refresh.slice(0, LANE_LIMITS.refresh);

  return plan;
}

/** Total rows across all four lanes — the "is there anything to do" number. */
export function planSize(plan: CateringPlan): number {
  return (
    plan.undistributed.length + plan.proven.length + plan.quiet.length + plan.refresh.length
  );
}

// ---------------------------------------------------------------------------
// Ledger adapters
// ---------------------------------------------------------------------------

/**
 * Content paths that have already been distributed.
 *
 * The ledger is keyed by canonical URL and carries `source_file`; catering
 * joins on content paths. `ledger.publishedSourceFiles` does exactly this
 * work — the name is kept because the catering lane reads as four questions
 * about *paths*, and re-stating the join at the boundary is cheaper than
 * making every reader remember which key the ledger happens to use.
 */
export function publishedPathsFromLedger(ledger: Ledger): Set<string> {
  return publishedSourceFiles(ledger);
}
