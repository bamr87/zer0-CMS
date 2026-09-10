/**
 * Open pull requests, as the console reads them: what came back from the list
 * endpoint, which stage of the fleet's own review pipeline each one is in, and
 * which lane opened it.
 *
 * ## The stage rules are transcribed, not invented
 *
 * `prStage` maps the fleet's real label vocabulary onto a stage, and every rule
 * below is a line in a workflow that is running in production today:
 *
 *   * `bamr87/lifehacker.dev` `.github/workflows/auto-merge.yml:77-82` — the
 *     candidate query. Open pull requests **not** labelled `needs-human`, and
 *     labelled one of `auto:content`, `source/triage-bot`, `source/ai-usage-bot`;
 *     the last two are the "flavours" it then holds to a generated-data-only bar
 *     (`:96-104`).
 *   * `bamr87/it-journey` `.github/workflows/content-auto-merge.yml:135-148` —
 *     the policy router, in its own order: not open → nothing; `draft` → nothing;
 *     `needs-human` → leave for a reviewer; then `quest-walkthrough` + `automated`,
 *     then `auto:issue` (same-repo head only), then `auto:content`.
 *
 * The two agree on the shape and differ only in vocabulary, so the union is the
 * rule set here. Changing one of those workflows should change the fixtures in
 * `src/test/fleet.test.ts` and then this file, in that order.
 *
 * ## What is deliberately absent
 *
 * **`mergeable` is not computed.** GitHub's list endpoint omits it, and asking
 * per pull request is one call each against a console that makes four per
 * repository per refresh. `FleetPull` therefore carries no merge state at all,
 * and the console renders it as unknown. A grey cell that says "unknown" is
 * honest; a green one that guessed is not.
 *
 * Nothing here writes a label, and nothing here decides whether a pull request
 * *should* merge — `prStage` reports where the fleet's own workflows have put
 * it. The verbs that would change that answer are refused by
 * `fleetPlanHasNoMergeVerbs` in `./github.ts`.
 */

import type { FleetLane, FleetPull, PrStage } from '../shared/types';
import { workflowFileOf } from './manifest';

// ---------------------------------------------------------------------------
// The label vocabulary, as data
// ---------------------------------------------------------------------------

/** The escalation label. Both workflows check it before anything else they act on. */
export const PR_HOLD_LABEL = 'needs-human';

/**
 * Labels that put a pull request on an armed auto-merge policy.
 *
 * `auto:issue` is on the list even though it-journey additionally requires a
 * same-repo head: the head check is a separate fact (`FleetPull.sameRepoHead`)
 * and `prStage` reports it through the `repoLocal` mapping rather than by
 * silently downgrading a stage the operator can see the reason for.
 */
export const PR_AUTOMERGE_LABELS: readonly string[] = ['auto:content', 'auto:issue'];

/**
 * Bot labels whose pull requests carry generated data only. auto-merge.yml
 * treats these as their own flavour with a tighter bar than content, so the
 * console gives them their own stage rather than calling them content.
 */
export const PR_DATA_LABELS: readonly string[] = ['source/triage-bot', 'source/ai-usage-bot'];

/**
 * The pair it-journey's quest-report policy requires together
 * (`content-auto-merge.yml:142`). Either one alone is not a policy match.
 */
export const PR_QUEST_LABELS: readonly string[] = ['quest-walkthrough', 'automated'];

/** The prefix the fleet's lanes label their own pull requests with. */
export const PR_SOURCE_PREFIX = 'source/';

/**
 * Labels that only say "a bot opened this", with no policy attached.
 * `automated` is half of it-journey's quest-report pair; on its own it means
 * the pull request is in the automated pipeline and nothing will merge it.
 */
export const PR_BOT_MARKERS: readonly string[] = ['automated'];

// ---------------------------------------------------------------------------
// Coercion
// ---------------------------------------------------------------------------

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function asText(value: unknown): string {
  return value === undefined || value === null ? '' : String(value);
}

/** `labels: [{name}]` → the names, dropping anything that is not one. */
function labelNames(raw: unknown): string[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  const names: string[] = [];
  for (const entry of raw) {
    const name = typeof entry === 'string' ? entry : asText(asRecord(entry)?.name);
    if (name !== '') {
      names.push(name);
    }
  }
  return names;
}

/**
 * One pull request from the list endpoint, coerced field by field.
 *
 * A record with no number is dropped: every action the console could ever offer
 * on a pull request names it by number, and a row that cannot be named is a row
 * that cannot be acted on.
 */
export function coercePull(raw: unknown): FleetPull | undefined {
  const pull = asRecord(raw);
  if (pull === undefined) {
    return undefined;
  }
  const number = Number(pull.number);
  if (!Number.isFinite(number) || number <= 0) {
    return undefined;
  }
  const head = asRecord(pull.head);
  const base = asRecord(pull.base);
  const headRepo = asText(asRecord(head?.repo)?.full_name);
  const baseRepo = asText(asRecord(base?.repo)?.full_name);
  return {
    number,
    title: asText(pull.title),
    headRef: asText(head?.ref),
    labels: labelNames(pull.labels),
    draft: pull.draft === true,
    authorLogin: asText(asRecord(pull.user)?.login),
    url: asText(pull.html_url),
    updatedAt: asText(pull.updated_at),
    // A fork's head is a different blast radius from a branch on the repository,
    // and it-journey's `auto:issue` policy turns on exactly this fact
    // (`content-auto-merge.yml:129,144`). An unreadable base is not a licence to
    // call a fork a branch, so an empty repository name is never a match.
    sameRepoHead: headRepo !== '' && headRepo === baseRepo,
  };
}

// ---------------------------------------------------------------------------
// The stage
// ---------------------------------------------------------------------------

/**
 * Where a pull request sits in the fleet's own review pipeline.
 *
 * The order below is the order the two auto-merge workflows check in, and it is
 * load-bearing:
 *
 *   1. **`draft`** — `content-auto-merge.yml:138`. The API's own flag, and no
 *      label can repaint it.
 *   2. **`needs-human`** — `auto-merge.yml:80`, `content-auto-merge.yml:140`.
 *      An escalation, and no label and no `repoLocal` mapping can repaint it
 *      either. A configuration file that could paint a held pull request green
 *      would be the fleet equivalent of a `zer0.json` arming a write.
 *   3. **`repoLocal`** — a repository's own label vocabulary, consulted before
 *      the shared one so a site can name its stages without patching this file.
 *      The first label with a mapping wins, in the order the pull request
 *      carries them.
 *   4. **`data-refresh`** — `source/triage-bot` / `source/ai-usage-bot`
 *      (`auto-merge.yml:81-82`), the flavours held to a generated-data-only bar.
 *   5. **`auto-mergeable`** — `auto:content` / `auto:issue`, or
 *      `quest-walkthrough` **and** `automated` together.
 *   6. **`in-review`** — any other `source/<bot>` label, or a bare `automated`:
 *      a lane opened it, and no policy will merge it, so a person will.
 *   7. **`unknown`** — nothing said. Usually a human's pull request, and the
 *      console says so rather than guessing a stage for it.
 *
 * Note what a stage is *not*: it is not a prediction that something will merge.
 * Every policy above is additionally gated on a repository variable
 * (`AUTO_MERGE_ENABLED`, `CONTENT_AUTOMERGE_ENABLED`, …) that this function is
 * not given — `mergePolicyOf` in `./policy.ts` reports those separately, and
 * the console shows the two side by side.
 */
export function prStage(
  labels: readonly string[],
  draft: boolean,
  repoLocal?: Readonly<Record<string, PrStage>>,
): PrStage {
  if (draft) {
    return 'draft';
  }
  const has = (name: string): boolean => labels.includes(name);
  if (has(PR_HOLD_LABEL)) {
    return 'needs-human';
  }
  if (repoLocal !== undefined) {
    for (const label of labels) {
      const mapped = Object.prototype.hasOwnProperty.call(repoLocal, label)
        ? repoLocal[label]
        : undefined;
      if (mapped !== undefined) {
        return mapped;
      }
    }
  }
  if (PR_DATA_LABELS.some(has)) {
    return 'data-refresh';
  }
  if (PR_AUTOMERGE_LABELS.some(has) || PR_QUEST_LABELS.every(has)) {
    return 'auto-mergeable';
  }
  if (labels.some((label) => label.startsWith(PR_SOURCE_PREFIX)) || PR_BOT_MARKERS.some(has)) {
    return 'in-review';
  }
  return 'unknown';
}

// ---------------------------------------------------------------------------
// Attribution
// ---------------------------------------------------------------------------

/** `source/triage-bot` → `triage-bot`; anything else → `undefined`. */
function sourceLaneHint(label: string): string | undefined {
  return label.startsWith(PR_SOURCE_PREFIX) ? label.slice(PR_SOURCE_PREFIX.length) : undefined;
}

/** `germinate/20260909-0641` → `germinate`; a branch with no prefix → `undefined`. */
function branchLaneHint(headRef: string): string | undefined {
  const slash = headRef.indexOf('/');
  return slash > 0 ? headRef.slice(0, slash) : undefined;
}

/**
 * The names a lane answers to: its id and its workflow file's stem.
 * `attachLanes` in the engines matches a workflow to a lane the same two ways,
 * which is what keeps this console and GitFactory agreeing on which lane a
 * thing belongs to.
 */
function laneKeys(lane: FleetLane): string[] {
  const file = workflowFileOf(lane);
  const stem = file.replace(/\.ya?ml$/i, '');
  return stem === '' || stem === lane.id ? [lane.id] : [lane.id, stem];
}

/**
 * Join open pull requests to the lanes that opened them.
 *
 * Two rules, in order, and both exact rather than fuzzy:
 *
 *   1. a `source/<bot>` label, with a trailing `-bot` stripped — the fleet
 *      writes `source/content-scout` for the `content-scout` lane and
 *      `source/triage-bot` for the `triage` one;
 *   2. failing that, the head branch's first segment — the lanes create
 *      `triage/<stamp>`, `wire/<stamp>`, `ai-usage/<stamp>` branches.
 *
 * A hint matches a lane by its id or by its workflow file's stem, and nothing
 * else. Approximate matching is how a console tells a confident lie about who
 * wrote something, so **whatever cannot be attributed stays visible in
 * `unattributed`** rather than being dropped or guessed onto a plausible lane.
 * On a real fleet that list is not empty — lifehacker's `source/site-explorer`
 * label and its `explorer/` branches belong to a lane called `explore` — and
 * seeing it is the point: an unattributed row is either a lane the manifest has
 * not declared or a naming drift somebody should fix.
 *
 * The map holds an entry only for a lane that actually has pull requests, and
 * every pull request appears exactly once across the map and the list.
 */
export function attributePulls(
  pulls: readonly FleetPull[],
  lanes: readonly FleetLane[],
): { byLane: ReadonlyMap<string, FleetPull[]>; unattributed: FleetPull[] } {
  const byKey = new Map<string, string>();
  for (const lane of lanes) {
    for (const key of laneKeys(lane)) {
      const lower = key.toLowerCase();
      if (!byKey.has(lower)) {
        byKey.set(lower, lane.id);
      }
    }
  }

  const resolve = (hint: string | undefined): string | undefined => {
    if (hint === undefined || hint === '') {
      return undefined;
    }
    const lower = hint.toLowerCase();
    return byKey.get(lower) ?? byKey.get(lower.replace(/-bot$/, ''));
  };

  const byLane = new Map<string, FleetPull[]>();
  const unattributed: FleetPull[] = [];
  for (const pull of pulls) {
    let laneId: string | undefined;
    for (const label of pull.labels) {
      laneId = resolve(sourceLaneHint(label));
      if (laneId !== undefined) {
        break;
      }
    }
    laneId ??= resolve(branchLaneHint(pull.headRef));
    if (laneId === undefined) {
      unattributed.push(pull);
      continue;
    }
    const existing = byLane.get(laneId);
    if (existing === undefined) {
      byLane.set(laneId, [pull]);
    } else {
      existing.push(pull);
    }
  }
  return { byLane, unattributed };
}
