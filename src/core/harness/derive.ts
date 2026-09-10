/**
 * `wtd fleet adopt`, in TypeScript — a port of `bamr87/wtd`'s
 * `wtd/fleet/adopt.py` used **only to agree**, never to overwrite.
 *
 * Every committed `fleet.manifest.yml` in this fleet is `provenance: derived`:
 * a Python script read the workflow files and wrote the manifest. That means the
 * manifest is a *cache* of a derivation, and a cache can go stale. This module
 * recomputes the derivation from the same bytes so the console can answer one
 * question the fleet cannot answer today: **does the manifest still describe the
 * workflows?**
 *
 * ## The rule that makes this safe
 *
 * A disagreement between this derivation and a committed manifest is a **drift
 * row**, not a correction. The manifest carries things inference cannot know —
 * a hand-written summary, `writable_paths`, `state_paths`, per-lane metering,
 * a deliberate exception — and `adopt.py` itself says so ("a committed manifest
 * always wins over inference"). Nothing in this console writes a derived lane
 * over a committed one; `joins.ts` reports the difference and stops.
 *
 * ## Bug-for-bug, on purpose — with one deliberate divergence
 *
 * Parity is the whole value, so the port reproduces `adopt.py`'s quirks:
 *
 *  - **Crons are scanned from raw text**, comments included. That is why
 *    lifehacker's manifest says the `explore` lane runs at `23 6 * * *` when
 *    that cron has been commented out for months. `scanWorkflow` records it as
 *    a `dormantCron`; this function records it as a live schedule, because that
 *    is what the manifest on disk was generated from.
 *  - **`harness` collapses four runner shapes into `claude-cli`.** The hub
 *    composite, a bare `claude -p`, and `scripts/ai/run.sh` all land there,
 *    because `fleet/v1`'s vocabulary has no name for the composite.
 *  - **The switch is picked by name similarity** — the first switch whose
 *    squashed name starts with the first eight squashed characters of the
 *    filename stem, else the first switch mentioned anywhere in the file,
 *    comments included.
 *  - **Guardrails are read from command lines only**, through the textscan
 *    port, so a prompt that forbids merging is not read as merging.
 *
 * The one divergence: **`adopt.py`'s harness patterns miss an `ai-lane.yml@`
 * caller.** None of its four regexes matches
 * `uses: bamr87/bamr87/.github/workflows/ai-lane.yml@main`, so the lane gets
 * `Harness.NONE` and is **dropped from the manifest entirely** — a lane that
 * runs an agent every Monday, invisible to the fleet's own inventory. This port
 * recognises the shape and derives the lane, and `harness.test.ts` pins the
 * disagreement rather than hiding it. It is the one place where "used only to
 * agree" would mean agreeing with a gap.
 */

import type { FleetGuardrails, FleetHarness, FleetLane, FleetTrigger } from '../shared/types';
import {
  commandLines,
  readEvents,
  readWorkflowName,
  workflowBasename,
  workflowStem,
} from './workflows';

/**
 * `adopt.py:_HARNESS_PATTERNS`, in order, plus the `ai-lane.yml@` shape upstream
 * misses. First match wins.
 */
const HARNESS_PATTERNS: ReadonlyArray<{ harness: FleetHarness; pattern: RegExp }> = [
  { harness: 'claude-code-action', pattern: /anthropics\/claude-code-action/ },
  { harness: 'wtd-fleet', pattern: /\bwtd\s+fleet\b/ },
  {
    harness: 'claude-cli',
    pattern:
      /(?<!\w)claude\s+-p\b|@anthropic-ai\/claude-code|claude_args|actions\/claude-run\b|[\w.-]+\/[\w.-]+\/[^\s'"]*claude-run@|scripts\/ai\/run\.sh|[\w.-]+\/[\w.-]+\/\.github\/workflows\/ai-lane\.ya?ml@/,
  },
  { harness: 'engine', pattern: /germinate\.mjs|gate\.mjs|agentic_validate\.py|dash-gen/ },
];

/** The pattern `adopt.py` would have needed. Kept separate so the gap is testable. */
export const AI_LANE_CALLER_PATTERN = /[\w.-]+\/[\w.-]+\/\.github\/workflows\/ai-lane\.ya?ml@/;

/** `true` when upstream's own patterns would return `none` for this text. */
export function upstreamWouldDropLane(text: string): boolean {
  const upstream = HARNESS_PATTERNS.map(({ harness, pattern }) => ({
    harness,
    pattern:
      harness === 'claude-cli'
        ? // `adopt.py`'s claude-cli pattern, without our ai-lane addition.
          /(?<!\w)claude\s+-p\b|@anthropic-ai\/claude-code|claude_args|actions\/claude-run\b|[\w.-]+\/[\w.-]+\/[^\s'"]*claude-run@|scripts\/ai\/run\.sh/
        : pattern,
  }));
  return !upstream.some(({ pattern }) => pattern.test(text));
}

/** `adopt.py:detect_harness`. `none` when the file calls no model. */
export function detectHarness(text: string): FleetHarness {
  for (const { harness, pattern } of HARNESS_PATTERNS) {
    if (pattern.test(text)) {
      return harness;
    }
  }
  return 'none';
}

/** `adopt.py:_KIND_HINTS`, in order. The vocabulary is FLEET-SPEC's, not ours. */
const KIND_HINTS: ReadonlyArray<{ kind: string; pattern: RegExp }> = [
  { kind: 'orchestrator', pattern: /fleet-?loop|orchestrat|dispatcher/i },
  { kind: 'review', pattern: /review|pr-gate|gatekeep/i },
  { kind: 'triage', pattern: /triage|issue-pipeline|issue-factory|remediat/i },
  { kind: 'fanout', pattern: /fanout|standardiz|propagat|seed/i },
  {
    kind: 'maintenance',
    pattern: /auto-?fix|auto-?update|doctor|pulse|reconcile|drift|watch|expiry/i,
  },
  {
    kind: 'content',
    pattern: /content|scout|wire|epic|germinate|grow|garden|lineage|write|blog/i,
  },
  { kind: 'analysis', pattern: /analytic|usage|explore|metric|report|audit/i },
];

/**
 * `adopt.py:_MENTION_RE`. A mention handler is gated on a human typing
 * `@claude`; it is not an autonomous loop and FLEET-SPEC forbids auditing it as
 * one. The *gating expression* is matched, not the bare string, because a
 * fan-out workflow legitimately carries `@claude` as payload.
 */
const MENTION = /contains\s*\(\s*github\.event[^)]*@claude/i;

/** `adopt.py:detect_kind`. The body decides mention; the name decides the rest. */
export function detectKind(filename: string, workflowName: string, text: string): string {
  if (MENTION.test(text) || /^claude\.ya?ml$/i.test(filename)) {
    return 'mention';
  }
  const hay = `${filename} ${workflowName}`;
  for (const { kind, pattern } of KIND_HINTS) {
    if (pattern.test(hay)) {
      return kind;
    }
  }
  return 'other';
}

const MERGE_PATTERNS =
  /gh pr merge|pulls\/\S+\/merge|--auto\s+--merge|merge_pull_request|enable_pr_auto_merge/;
const PR_PATTERNS = /gh pr create|create-pull-request|pulls\b|open_pr/;
const PUSH_MAIN = /git push[^\n]*\b(origin\s+)?(main|master)\b/;

/** The GitHub events `adopt.py` recognises. Anything else under `on:` is dropped. */
const EVENT_KEYS = new Set([
  'push',
  'pull_request',
  'pull_request_target',
  'issues',
  'issue_comment',
  'workflow_run',
  'workflow_call',
  'release',
  'repository_dispatch',
  'pull_request_review',
  'pull_request_review_comment',
  'discussion',
]);

/** `adopt.py:_CRON_RE` — quoted crons, from the raw text, comments included. */
function rawCrons(text: string): string[] {
  const out: string[] = [];
  const pattern = /cron:\s*['"]([^'"]+)['"]/g;
  let match = pattern.exec(text);
  while (match !== null) {
    const value = (match[1] ?? '').trim();
    if (value !== '') {
      out.push(value);
    }
    match = pattern.exec(text);
  }
  return out;
}

/**
 * `adopt.py:_triggers`.
 *
 * Upstream reads the `on:` block through PyYAML — where the key is the YAML 1.1
 * boolean `True`, which is why its `_on_block` looks for `True` first — and
 * falls back to scanning the raw text for `^\s*<event>:` only when the file will
 * not parse at all. This port reads the `on:` block as a **region of lines**
 * (`onBlock`), which is the same answer for every well-formed workflow and does
 * not need a YAML parser to get there.
 *
 * Upstream's *fallback* is the one thing not reproduced, and deliberately: a
 * whole-file `^\s*<event>:` scan matches `issues: write` under `permissions:`,
 * and taking it as the common denominator gave four lifehacker lanes a phantom
 * `event issues` trigger — four drift rows against a manifest that was right.
 * Since PyYAML parses every workflow in this fleet, the fallback never ran
 * upstream either; copying it would have been copying dead code and its bug.
 *
 * Crons, on the other hand, are scanned from raw text exactly as upstream does
 * — **comments included** — because that is what generated the manifests on
 * disk. `scanWorkflow` tells the truth about a parked cron; this reproduces the
 * fiction so parity is measurable.
 */
function deriveTriggers(text: string): FleetTrigger[] {
  const triggers: FleetTrigger[] = [];
  for (const cron of rawCrons(text)) {
    triggers.push({ kind: 'schedule', cron, events: [] });
  }
  const declared = readEvents(text);
  const events = declared.filter((event) => EVENT_KEYS.has(event));
  if (events.length > 0) {
    triggers.push({ kind: 'event', cron: null, events: [...events].sort() });
  }
  if (declared.includes('workflow_dispatch')) {
    triggers.push({ kind: 'dispatch', cron: null, events: [] });
  }
  return triggers;
}

/**
 * `adopt.py:_guardrails`. Read from command lines only, so a prompt that says
 * "Never merge" is not read as merging and a `grep -nE 'gh pr merge'` audit step
 * is not read as merging either. Upstream never sets `writable_paths`, so the
 * derived value is `[]` — which the manifest omits and this repository's reader
 * therefore reads back as `[]` too.
 */
function deriveGuardrails(text: string): FleetGuardrails {
  const lines = commandLines(text);
  const executes = (pattern: RegExp): boolean => lines.some((line) => pattern.test(line));
  return {
    neverMerges: !executes(MERGE_PATTERNS),
    opensPullRequests: executes(PR_PATTERNS),
    writesDirectlyToDefaultBranch: executes(PUSH_MAIN),
    writablePaths: [],
  };
}

/** The command lines that made a lane look like it merges. `adopt.py:merge_evidence`. */
export function mergeEvidence(text: string, limit = 3): string[] {
  return commandLines(text)
    .filter((line) => MERGE_PATTERNS.test(line))
    .map((line) => line.trim().slice(0, 160))
    .slice(0, limit);
}

const SWITCH_RE = /\b([A-Z][A-Z0-9_]*_ENABLED)\b/g;
const SECRET_RE = /secrets\.([A-Z][A-Z0-9_]*)/g;

/**
 * `adopt.py:_pick_switch`. The gate is the switch the file is *named* for when
 * one matches, else the first mentioned — where "matches" means the switch's
 * squashed lowercase name starts with the first eight squashed characters of the
 * stem. Eight characters is upstream's number, and it is why `content-scout.yml`
 * picks `CONTENT_SCOUT_ENABLED` over `CONTENT_FACTORY_ENABLED` when both appear.
 */
export function pickSwitch(switches: readonly string[], stem: string): string | null {
  if (switches.length === 0) {
    return null;
  }
  const stemKey = stem.toLowerCase().replace(/[^a-z0-9]+/g, '');
  const prefix = stemKey.slice(0, 8);
  if (prefix !== '') {
    for (const name of switches) {
      if (name.toLowerCase().replace(/[^a-z0-9]+/g, '').startsWith(prefix)) {
        return name;
      }
    }
  }
  return switches[0] ?? null;
}

function sortedMatches(text: string, pattern: RegExp): string[] {
  const found = new Set<string>();
  pattern.lastIndex = 0;
  let match = pattern.exec(text);
  while (match !== null) {
    if (match[1] !== undefined) {
      found.add(match[1]);
    }
    match = pattern.exec(text);
  }
  return [...found].sort();
}

/**
 * Derive one lane from one workflow file, in memory.
 *
 * Unlike `adopt.py:lane_from_text`, which returns `None` for a workflow that
 * calls no model, this always returns a lane — with `harness: 'none'`. The
 * caller filters. Two reasons: a `FleetLane` is a well-typed value a drift
 * report can show either way, and "upstream would have dropped this" is itself
 * a fact worth reporting (`upstreamWouldDropLane`) rather than a `null` a caller
 * has to guess the meaning of.
 */
export function deriveLaneFromWorkflow(filePath: string, text: string): FleetLane {
  const filename = workflowBasename(filePath);
  const stem = workflowStem(filePath);
  const workflowName = readWorkflowName(text, filePath);
  const switches = sortedMatches(text, SWITCH_RE);
  return {
    id: stem,
    kind: detectKind(filename, workflowName, text),
    harness: detectHarness(text),
    implementation: `.github/workflows/${filename}`,
    description: workflowName,
    triggers: deriveTriggers(text),
    switch: pickSwitch(switches, stem),
    usesTokens: sortedMatches(text, SECRET_RE),
    guardrails: deriveGuardrails(text),
  };
}

/** The fields a derived lane can legitimately be compared against a committed one on. */
export const LANE_PARITY_FIELDS: readonly string[] = [
  'kind',
  'harness',
  'implementation',
  'description',
  'triggers',
  'switch',
  'uses_tokens',
  'guardrails',
];
