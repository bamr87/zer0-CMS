/**
 * Portfolio — the track record publishing accumulates into.
 *
 * Catering answers "what should I write next." This answers the question that
 * decides whether anybody keeps asking it: *has any of this added up to
 * anything?* One post is a post. Forty posts tied to real work is a record, and
 * it is the thing an editor, a client, or a hiring manager actually looks at.
 *
 * Everything is computed from the ledger, with the contract supplying each
 * entry's collection. That has two consequences worth stating:
 *
 * - It works with no audience data at all. Cadence and streak are properties of
 *   *when you published*, not of how it performed, so a portfolio is meaningful
 *   from the first entry — unlike Lanes B–D, which stay empty until statistics
 *   exist.
 * - The topic axis is the author's own collections, the same axis catering
 *   groups by. No clustering, no inferred interests, nothing derived about
 *   anybody. A portfolio is a fact about the author's output.
 *
 * Pure, like `buildCatering`: the caller loads the ledger and the contract.
 */

import { byPath, type Contract } from '../contract/contract';
import { shareEntries, type Ledger } from '../governance/ledger';

/** How many topics `renderPortfolio` lists before it stops. */
export const TOPIC_LIMIT = 5;

export interface Portfolio {
  /** Published artifacts in the ledger. */
  count: number;
  /** Artifact type (`article`, `update`, …) → how many. */
  byType: Record<string, number>;
  /** Collection → how many, the same axis catering groups by. */
  byCollection: Record<string, number>;
  /** `YYYY-MM` → how many, the basis for cadence and streak. */
  byMonth: Record<string, number>;
  /** Distinct months with at least one post. */
  monthsActive: number;
  /** Posts per active month, to one decimal. Zero when nothing is published. */
  cadence: number;
  /** Consecutive months ending at the most recent one that has a post. */
  streak: number;
  /** `posted_at` of the newest entry, or `''`. */
  latest: string;
}

/** `YYYY-MM` from a timestamp, or `''` if it is not one. */
function monthOf(postedAt: unknown): string {
  if (typeof postedAt !== 'string' || postedAt.length < 7) {
    return '';
  }
  const month = postedAt.slice(0, 7);
  return /^\d{4}-\d{2}$/.test(month) ? month : '';
}

/** The month before `YYYY-MM`, rolling the year at January. */
function previousMonth(month: string): string {
  const year = Number(month.slice(0, 4));
  const index = Number(month.slice(5, 7));
  return index === 1
    ? `${String(year - 1).padStart(4, '0')}-12`
    : `${String(year).padStart(4, '0')}-${String(index - 1).padStart(2, '0')}`;
}

/**
 * Consecutive months with at least one post, counted back from the newest.
 *
 * Anchored to the newest month *in the data*, not to today. A portfolio that
 * reported a broken streak because the reader opened it in a quiet week would
 * be measuring the calendar, not the work; "three months running, most recently
 * in June" is a fact that stays true in July.
 */
export function streakOf(byMonth: Record<string, number>): number {
  const months = Object.keys(byMonth).sort().reverse();
  if (months.length === 0) {
    return 0;
  }
  let streak = 0;
  let cursor = months[0];
  for (const month of months) {
    if (month !== cursor) {
      break;
    }
    streak += 1;
    cursor = previousMonth(cursor);
  }
  return streak;
}

function bump(counts: Record<string, number>, key: string): void {
  counts[key] = (counts[key] ?? 0) + 1;
}

/** Build the track record from the ledger, with collections from the contract. */
export function buildPortfolio(ledger: Ledger, contract?: Contract): Portfolio {
  const portfolio: Portfolio = {
    count: 0,
    byType: {},
    byCollection: {},
    byMonth: {},
    monthsActive: 0,
    cadence: 0,
    streak: 0,
    latest: '',
  };

  for (const [, entry] of shareEntries(ledger)) {
    portfolio.count += 1;
    bump(portfolio.byType, entry.type || 'unknown');

    const month = monthOf(entry.posted_at);
    if (month) {
      bump(portfolio.byMonth, month);
    }

    // Without a contract there is no collection for a path, so the axis
    // collapses to one bucket rather than being silently wrong.
    const record = contract && entry.source_file ? byPath(contract, entry.source_file) : undefined;
    bump(portfolio.byCollection, record?.collection || 'uncategorised');

    const postedAt = typeof entry.posted_at === 'string' ? entry.posted_at : '';
    if (postedAt > portfolio.latest) {
      portfolio.latest = postedAt;
    }
  }

  portfolio.monthsActive = Object.keys(portfolio.byMonth).length;
  portfolio.cadence = portfolio.monthsActive
    ? Math.round((portfolio.count / portfolio.monthsActive) * 10) / 10
    : 0;
  portfolio.streak = streakOf(portfolio.byMonth);
  return portfolio;
}

/** Counts as `name n` pairs, most frequent first, ties broken by name. */
function describeCounts(counts: Record<string, number>, limit = Infinity): string {
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, limit)
    .map(([name, n]) => `${name} ${n}`)
    .join(', ');
}

/**
 * The track record as text.
 *
 * The empty state is a sentence rather than a zero, because "0 posts" reads as
 * a measurement of the author and "the record starts at one" reads as the next
 * action — and at that moment the next action is the useful thing to say.
 */
export function renderPortfolio(portfolio: Portfolio): string {
  if (portfolio.count === 0) {
    return [
      'portfolio: nothing published yet.',
      '  Approve a draft and publish it — the record starts at one.',
    ].join('\n');
  }

  const lines = [
    `portfolio: ${portfolio.count} post(s) across ${portfolio.monthsActive} month(s)`,
    `  cadence:  ${portfolio.cadence} per active month`,
    `  streak:   ${portfolio.streak} consecutive month(s)`,
  ];
  const types = describeCounts(portfolio.byType);
  if (types) {
    lines.push(`  kinds:    ${types}`);
  }
  const collections = describeCounts(portfolio.byCollection, TOPIC_LIMIT);
  if (collections) {
    lines.push(`  topics:   ${collections}`);
  }
  if (portfolio.latest) {
    lines.push(`  latest:   ${portfolio.latest}`);
  }
  return lines.join('\n');
}
