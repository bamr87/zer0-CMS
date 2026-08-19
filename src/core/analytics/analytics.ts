/**
 * Analytics — how the author's own content performed, and nothing else.
 *
 * `catering/` can already turn engagement into a worklist, and `contract/` can
 * already store it. What was missing is the step between: nothing turned
 * statistics *from a platform* into the `performance.json` those two agree on.
 * Without it the loop stayed open — a worklist could be rendered, but only from
 * a file somebody typed by hand.
 *
 * This module closes it, and does exactly two things.
 *
 * **`readPlan` declares the read surface.** Every call the analytics lane would
 * ever make, as data rather than prose, so it can be printed, tested, and shown
 * to a reviewer *before* a credential exists. `analytics.readSurface.test`
 * asserts the list contains nothing that returns another person's data, which
 * turns the privacy boundary into a build failure rather than a promise.
 *
 * **`ingestPerformance` performs the join.** Statistics arrive keyed by the
 * platform's post id; catering needs them keyed by content path. The ledger is
 * the only thing that knows which post came from which page, so it is the join
 * table — and the join is a pure function of two plain objects, which is why it
 * needs no network and no fixtures to test.
 *
 * ## The boundary, stated once
 *
 * Everything here is the author's own **aggregate** numbers: impressions,
 * clicks, reactions, comments, shares. Nothing identifies who engaged. There is
 * no per-reader record, no attempt to resolve a reaction to a profile, and no
 * join against any other dataset about a person. `catering/` consumes only what
 * this module produces, so that boundary holds for the whole feedback loop by
 * construction rather than by discipline.
 *
 * ## What is deliberately absent
 *
 * There is no `fetch`. Fetching statistics needs a live credential and a
 * platform client, both of which belong in a publish target, not in the pure
 * layer. A stub returning invented numbers would be worse than nothing: it
 * would poison the worklist that decides what somebody writes next, and it
 * would do so silently. `ingestPerformance` therefore takes the statistics as
 * an argument and lets the caller say where they came from.
 */

import { normalisePerformance } from '../contract/contract';
import { shareEntries, type Ledger } from '../governance/ledger';
import type { PerfStats } from '../shared/types';

// ---------------------------------------------------------------------------
// The read surface
// ---------------------------------------------------------------------------

/** One call the analytics lane would make, described rather than made. */
export interface ReadCall {
  /** Why the call exists, in the author's terms. */
  what: string;
  /** The endpoint, concrete enough for a reviewer to check against the docs. */
  endpoint: string;
  /** The permission it needs. */
  scope: string;
  /** What comes back — always the author's own content. */
  returns: string;
}

/** Which identity published the content whose statistics are being read. */
export type AuthorKind = 'member' | 'organization';

/**
 * Reads for content published by an individual, to their own profile.
 *
 * Both entries say "own" in `returns` on purpose: `readSurfaceIsOwnContentOnly`
 * asserts it, so adding a call that reaches somebody else's data fails the test
 * rather than shipping.
 */
export const MEMBER_READS: readonly ReadCall[] = [
  {
    what: 'confirm a post published',
    endpoint: 'GET /rest/posts/{urn}',
    scope: 'member read, own content',
    returns: "the member's own post, as created",
  },
  {
    what: "aggregate statistics for the member's own posts",
    endpoint: 'GET /rest/posts (own) + statistics',
    scope: 'member read, own content',
    returns: "impressions, clicks, reactions, comments, shares for the member's own posts",
  },
];

/** Reads for content published to a page the author administers. */
export const ORGANIZATION_READS: readonly ReadCall[] = [
  {
    what: 'confirm a post published',
    endpoint: 'GET /rest/posts/{urn}',
    scope: 'r_organization_social',
    returns: "the page's own post, as created",
  },
  {
    what: "aggregate statistics for the page's own posts",
    endpoint: 'GET /rest/organizationalEntityShareStatistics',
    scope: 'r_organization_social',
    returns: "impressions, clicks, reactions, comments, shares for the page's own posts",
  },
  {
    what: 'page follower and visitor trend',
    endpoint: 'GET /rest/organizationPageStatistics',
    scope: 'r_organization_social',
    returns: "aggregate counts over time for the author's own page",
  },
];

/** The complete read surface for one author kind. Short on purpose. */
export function readPlan(authorKind: AuthorKind): readonly ReadCall[] {
  return authorKind === 'organization' ? ORGANIZATION_READS : MEMBER_READS;
}

/**
 * Whether every call in a plan returns only the author's own content.
 *
 * The check is the word "own" in `returns`, which reads like a weak test until
 * you consider what it is defending against: not a typo, but somebody adding a
 * follower-list or connections call and not noticing that it changes what the
 * product is. Writing `returns` forces that author to describe the data in a
 * sentence, and a sentence that cannot honestly contain "own" fails here.
 */
export function readSurfaceIsOwnContentOnly(plan: readonly ReadCall[]): boolean {
  return plan.every((call) => /\bown\b/.test(call.returns));
}

/** The read surface as text, for a terminal, a log, or an application form. */
export function describeReadPlan(authorKind: AuthorKind): string {
  const lines = ['Reads this lane would make, and nothing else:', ''];
  for (const call of readPlan(authorKind)) {
    lines.push(`  ${call.endpoint}`);
    lines.push(`    to        ${call.what}`);
    lines.push(`    scope     ${call.scope}`);
    lines.push(`    returns   ${call.returns}`);
    lines.push('');
  }
  lines.push('No profiles, connections, followers, or feeds. No per-reader');
  lines.push('records of who engaged — aggregate counts only.');
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// The join: platform post id → content path
// ---------------------------------------------------------------------------

/**
 * Ledger keys that may carry a platform's id for a published artifact.
 *
 * `urn` is this lane's own field. The others exist because the Python lane and
 * earlier versions wrote their own names — `Ledger` entries are deliberately
 * `Partial<LedgerEntry> & Record<string, unknown>` so those survive a rewrite,
 * and an ingest that only understood `urn` would silently match nothing against
 * a ledger written by the other lane.
 */
export const POST_ID_KEYS = ['urn', 'linkedin_urn', 'post_urn', 'share_urn'] as const;

/**
 * Platform post id → the content path that produced it.
 *
 * Every id key on an entry is indexed, not just the first: one artifact can be
 * known by both `urn` and `linkedin_urn`, and statistics may arrive keyed by
 * either. Entries with no `source_file` are skipped — there is no page to
 * attribute them to, and inventing one is how a worklist ends up ranking a
 * topic that nobody wrote.
 */
export function postIdIndex(ledger: Ledger): Map<string, string> {
  const index = new Map<string, string>();
  for (const [url, entry] of shareEntries(ledger)) {
    const sourceFile = entry.source_file;
    if (!sourceFile) {
      continue;
    }
    // `shareEntries` narrows to `LedgerEntry`, which is the modelled subset;
    // the unmodelled id keys survive on the ledger's own row, so read them
    // there rather than widening the narrowed value back out with a cast.
    const raw = ledger[url] ?? {};
    for (const key of POST_ID_KEYS) {
      const id = raw[key];
      if (typeof id === 'string' && id !== '') {
        index.set(id, sourceFile);
      }
    }
  }
  return index;
}

export interface IngestResult {
  /** Content path → aggregate statistics, ready for `writePerformance`. */
  performance: Record<string, PerfStats>;
  /** Post ids that matched a ledger entry and were applied. */
  matched: string[];
  /**
   * Post ids with no ledger entry. Not an error: a post made by hand, outside
   * this lane, has no row here. Surfaced so the caller can say so rather than
   * reporting a silent partial success.
   */
  unmatched: string[];
}

/**
 * Join statistics onto content paths through the ledger.
 *
 * Pure: it takes the ledger and the statistics and returns a new object. The
 * caller loads the ledger, decides where the statistics came from, and writes
 * the result — the same shape as `buildCatering`, and for the same reason.
 *
 * `existing` is merged under the new values so a partial refresh — statistics
 * for last week's three posts — updates those three and leaves the rest alone,
 * rather than deleting the history that Lane D depends on.
 */
export function ingestPerformance(
  ledger: Ledger,
  statsByPostId: Record<string, unknown>,
  existing: Record<string, PerfStats> = {},
): IngestResult {
  const index = postIdIndex(ledger);
  const performance: Record<string, PerfStats> = { ...existing };
  const matched: string[] = [];
  const unmatched: string[] = [];

  for (const [postId, raw] of Object.entries(statsByPostId)) {
    const contentPath = index.get(postId);
    if (contentPath === undefined) {
      unmatched.push(postId);
      continue;
    }
    if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) {
      unmatched.push(postId);
      continue;
    }
    performance[contentPath] = normalisePerformance(raw as Record<string, unknown>);
    matched.push(postId);
  }

  return { performance, matched, unmatched };
}

/**
 * Unwrap the statistics object from a file that may wrap it in `posts`.
 *
 * Exports from a platform console usually arrive as `{"posts": {...}}`; a
 * hand-written fixture is usually the bare map. Accepting both costs three
 * lines and removes the most likely reason an ingest reports zero matches.
 */
export function unwrapStats(raw: unknown): Record<string, unknown> {
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) {
    return {};
  }
  const record = raw as Record<string, unknown>;
  const posts = record.posts;
  if (posts !== null && typeof posts === 'object' && !Array.isArray(posts)) {
    return posts as Record<string, unknown>;
  }
  return record;
}
