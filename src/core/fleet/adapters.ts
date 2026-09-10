/**
 * The boundary between this repository's fleet vocabulary and
 * `@bamr87/fleet-engines`' — and the record of what does not survive the trip.
 *
 * Every import here is an `import type`. TypeScript erases those before esbuild
 * ever sees them, which is what makes this module safe to re-export through
 * `src/core/index.ts` while `./engines.ts` (the value import) never is. If you
 * are tempted to add a runtime import of the package to this file: don't. Take
 * the value as a parameter — that is what `manifestDrift(lane, facts)` does.
 *
 * **The conversion is lossy in one direction and the loss is reported, never
 * swallowed.** This repository models a guardrail as a tristate: `true`, `false`,
 * or `null` meaning "the manifest did not say" — a distinction the Fleet console
 * renders, because "we never checked" and "we checked and it merges" are very
 * different sentences to put next to a Dispatch button. The package's
 * `LaneGuardrails.never_merges` is a plain required boolean whose parser defaults
 * an absent value to `true`. So `toEngineLane` maps `null → true` **and returns a
 * `LaneLoss` saying so**. A caller that ignores the losses gets the package's
 * optimistic default; a caller that reads them can say "the manifest is silent"
 * on screen. Silence is never upgraded to a promise without a paper trail.
 *
 * Three more things the engine lane shape simply cannot hold, each recorded the
 * same way: `writes_directly_to_default_branch` (no field), a `kind` outside the
 * package's closed `LANE_KINDS` (the `fleet/v1` spec's `kind` is free
 * vocabulary), and a `schedule` trigger whose `cron` the manifest omitted (the
 * package's `LaneTrigger` requires the string).
 */

import type {
  DriftKind,
  FleetHarness,
  FleetLane,
  FleetManifest,
  FleetRunRecord,
  ManifestDrift,
  RunnerShape,
} from '../shared/types';
import type {
  EngineFleetLane,
  EngineFleetManifest,
  FactoryRun,
  WorkflowFacts,
} from './engines';

/**
 * One field that changed meaning, or vanished, crossing into the package's
 * shape. `note` is written to be shown to a person, not parsed.
 */
export interface LaneLoss {
  laneId: string;
  field: string;
  note: string;
}

/**
 * The package's closed lane vocabulary, transcribed rather than imported so this
 * module stays type-only. `engines.test.ts` asserts it still equals the
 * package's `LANE_KINDS`, so a widened vocabulary upstream is a failing test
 * rather than a lane silently retyped to `other`.
 */
const ENGINE_KINDS: readonly string[] = [
  'content',
  'triage',
  'review',
  'maintenance',
  'analysis',
  'orchestrator',
  'fanout',
  'mention',
  'other',
];

// ---------------------------------------------------------------------------
// Lanes
// ---------------------------------------------------------------------------

/**
 * This repository's lane in the package's shape, plus everything the shape could
 * not carry.
 */
export function toEngineLane(lane: FleetLane): { lane: EngineFleetLane; losses: LaneLoss[] } {
  const losses: LaneLoss[] = [];

  const kind = ENGINE_KINDS.includes(lane.kind) ? lane.kind : 'other';
  if (kind !== lane.kind) {
    losses.push({
      laneId: lane.id,
      field: 'kind',
      note: `"${lane.kind}" is not one of the package's lane kinds; it becomes "other". The fleet/v1 spec leaves kind free.`,
    });
  }

  const triggers: EngineFleetLane['triggers'] = [];
  for (const trigger of lane.triggers) {
    if (trigger.kind === 'schedule') {
      if (trigger.cron === null) {
        losses.push({
          laneId: lane.id,
          field: 'triggers[].cron',
          note: 'a schedule trigger with no cron becomes an empty cron string; the package has no way to say "scheduled, cron unknown".',
        });
      }
      triggers.push({ kind: 'schedule', cron: trigger.cron ?? '' });
    } else if (trigger.kind === 'event') {
      triggers.push({ kind: 'event', events: [...trigger.events] });
    } else {
      triggers.push({ kind: 'dispatch' });
    }
  }

  const { neverMerges, opensPullRequests, writesDirectlyToDefaultBranch, writablePaths } =
    lane.guardrails;

  if (neverMerges === null) {
    losses.push({
      laneId: lane.id,
      field: 'guardrails.never_merges',
      note: 'the manifest did not say. The package requires a boolean and defaults an absent one to true, so this crosses as true — an assumption, not a promise.',
    });
  }
  if (writesDirectlyToDefaultBranch !== null) {
    losses.push({
      laneId: lane.id,
      field: 'guardrails.writes_directly_to_default_branch',
      note: `the manifest says ${String(writesDirectlyToDefaultBranch)}; the package's guardrail shape has no such field, so the claim is dropped.`,
    });
  }

  const guardrails: EngineFleetLane['guardrails'] = { never_merges: neverMerges ?? true };
  if (opensPullRequests !== null) {
    guardrails.opens_pull_requests = opensPullRequests;
  }
  if (writablePaths.length > 0) {
    guardrails.writable_paths = [...writablePaths];
  }

  return {
    lane: {
      id: lane.id,
      kind: kind as EngineFleetLane['kind'],
      harness: lane.harness,
      implementation: lane.implementation,
      description: lane.description,
      triggers,
      switch: lane.switch,
      uses_tokens: [...lane.usesTokens],
      guardrails,
    },
    losses,
  };
}

/**
 * The package's lane in this repository's shape.
 *
 * `writesDirectlyToDefaultBranch` comes back `null` — not `false` — because the
 * package never carried it, and "we do not know" is the only honest answer. Same
 * reasoning for an absent `opens_pull_requests`.
 */
export function fromEngineLane(lane: EngineFleetLane): FleetLane {
  return {
    id: lane.id,
    kind: lane.kind,
    harness: lane.harness,
    implementation: lane.implementation,
    description: lane.description,
    triggers: lane.triggers.map((trigger) => {
      if (trigger.kind === 'schedule') {
        return { kind: 'schedule' as const, cron: trigger.cron === '' ? null : trigger.cron, events: [] };
      }
      if (trigger.kind === 'event') {
        return { kind: 'event' as const, cron: null, events: [...trigger.events] };
      }
      return { kind: 'dispatch' as const, cron: null, events: [] };
    }),
    switch: lane.switch,
    usesTokens: [...lane.uses_tokens],
    guardrails: {
      neverMerges: lane.guardrails.never_merges,
      opensPullRequests: lane.guardrails.opens_pull_requests ?? null,
      writesDirectlyToDefaultBranch: null,
      writablePaths: lane.guardrails.writable_paths ? [...lane.guardrails.writable_paths] : [],
    },
  };
}

/**
 * A whole manifest in the package's shape.
 *
 * The package's `FleetManifest` carries `spec_version`, `repo`, `provenance`,
 * `summary`, `lanes` and a `skipped` count — and nothing else. The token
 * contract, the metering block, and the agent and skill rosters have no home
 * there, so each is recorded as a manifest-level loss under the pseudo-lane id
 * `''`. `skipped` is `0` because this manifest was read by a reader that
 * reports its refusals as a reason rather than a count.
 */
export function toEngineManifest(m: FleetManifest): {
  manifest: EngineFleetManifest;
  losses: LaneLoss[];
} {
  const losses: LaneLoss[] = [];
  const lanes: EngineFleetLane[] = [];
  for (const lane of m.lanes) {
    const converted = toEngineLane(lane);
    lanes.push(converted.lane);
    losses.push(...converted.losses);
  }
  if (m.tokens.length > 0) {
    losses.push({
      laneId: '',
      field: 'tokens',
      note: `the manifest's token contract (${m.tokens.length} ${m.tokens.length === 1 ? 'entry' : 'entries'}) has no field in the package's manifest shape.`,
    });
  }
  if (Object.keys(m.metering).length > 0) {
    losses.push({
      laneId: '',
      field: 'metering',
      note: "the manifest's metering block has no field in the package's manifest shape.",
    });
  }
  if (m.agents.length > 0 || m.skills.length > 0) {
    losses.push({
      laneId: '',
      field: 'agents/skills',
      note: `the manifest's ${m.agents.length} agents and ${m.skills.length} skills have no field in the package's manifest shape.`,
    });
  }
  return {
    manifest: {
      spec_version: m.specVersion,
      repo: m.repo,
      provenance: m.provenance,
      summary: m.summary,
      lanes,
      skipped: 0,
    },
    losses,
  };
}

// ---------------------------------------------------------------------------
// Runner shape — the engines' AI facts in this repository's vocabulary
// ---------------------------------------------------------------------------

/**
 * How this workflow actually calls a model, in the `RunnerShape` vocabulary
 * `shared/types.ts` declares.
 *
 * The interesting case is the first one. A workflow that delegates to the hub's
 * reusable `ai-lane.yml` contains **no model call of its own**: the engines
 * report `ai.present: false` with an empty `runners` list, because the AI is in
 * the callee. `wtd`'s `adopt.py`, which decides a harness by matching a model-call
 * pattern in the file, sees the same nothing and drops the lane. It is a real
 * lane, it costs real money, and the only evidence in the file is the
 * `uses:` line — so that is what this reads.
 *
 * `none` genuinely means "no evidence in this file". It does not mean "no AI":
 * irony-works' `germinate.yml` calls Claude from a Node engine the facts scanner
 * has no pattern for. Which is why `manifestDrift` refuses to raise a harness
 * drift row on a `none`.
 */
export function runnerShapeOf(facts: WorkflowFacts): RunnerShape {
  if (facts.reusableCalls.some((call) => call.split('@')[0]?.endsWith('/ai-lane.yml') === true)) {
    return 'ai-lane-caller';
  }
  const runners = facts.ai.runners;
  if (runners.includes('claude-run')) {
    return 'claude-run';
  }
  if (runners.includes('claude-code-action')) {
    return 'claude-code-action';
  }
  if (runners.includes('agentic-engine')) {
    return 'agentic-engine';
  }
  if (runners.includes('claude-cli') || runners.includes('run-sh')) {
    return 'claude-cli';
  }
  if (runners.includes('other')) {
    return 'engine';
  }
  return 'none';
}

/**
 * Which `harness:` values in a `fleet/v1` manifest are consistent with an
 * observed runner shape. `wtd fleet adopt` writes `claude-cli` for every
 * command-line flavour — the vendored `run.sh`, the hub's `claude-run` composite,
 * a bare CLI, an agentic engine driver — so all four agree with it, and a lane
 * that delegates to the reusable hub lane is the same family.
 */
function harnessesConsistentWith(shape: RunnerShape): readonly FleetHarness[] {
  switch (shape) {
    case 'claude-code-action':
      return ['claude-code-action'];
    case 'ai-lane-caller':
    case 'claude-run':
    case 'claude-cli':
    case 'agentic-engine':
      return ['claude-cli', 'wtd-fleet'];
    case 'engine':
      return ['engine', 'wtd-fleet'];
    case 'none':
      return [];
  }
}

// ---------------------------------------------------------------------------
// Drift — where the manifest and the workflow file disagree
// ---------------------------------------------------------------------------

function drift(
  laneId: string,
  kind: DriftKind,
  manifestSays: string,
  workflowSays: string,
): ManifestDrift {
  return { laneId, kind, manifestSays, workflowSays };
}

function sortedList(values: readonly string[]): string {
  return values.length === 0 ? '(none)' : [...values].sort().join(', ');
}

/**
 * Every axis on which a lane's committed description disagrees with the workflow
 * file it names. Pure: the caller supplies both sides, and the console shows the
 * rows rather than "fixing" the manifest — this console never writes a manifest
 * field it derived rather than read.
 *
 * A note on `kind`. `DriftKind` (declared in `shared/types.ts`, which this work
 * package does not own) names five axes and none of them is `guardrails`, so a
 * guardrail the workflow contradicts is filed under `implementation`: the
 * manifest's claim about a lane's blast radius is a claim about what its
 * implementation does, and both sides are quoted verbatim so the row reads
 * correctly either way. A sixth `DriftKind` would be the better answer and is
 * worth raising when `shared/types.ts` is next opened.
 */
export function manifestDrift(lane: FleetLane, facts: WorkflowFacts): ManifestDrift[] {
  const rows: ManifestDrift[] = [];

  // — implementation: the path, and what the file is observed to write ——————
  if (lane.implementation !== '' && lane.implementation !== facts.path) {
    rows.push(drift(lane.id, 'implementation', lane.implementation, facts.path));
  }
  if (lane.guardrails.opensPullRequests === false && facts.sinks.includes('pr')) {
    rows.push(
      drift(
        lane.id,
        'implementation',
        'guardrails.opens_pull_requests: false',
        'the workflow opens pull requests (observed sink: pr)',
      ),
    );
  }
  if (lane.guardrails.neverMerges === true && facts.sinks.includes('merge')) {
    rows.push(
      drift(
        lane.id,
        'implementation',
        'guardrails.never_merges: true',
        'the workflow merges (observed sink: merge)',
      ),
    );
  }

  // — switch: the *_ENABLED variable the workflow actually reads ———————————
  const readsSwitches = facts.killSwitches;
  if (lane.switch !== null && !readsSwitches.includes(lane.switch)) {
    rows.push(
      drift(
        lane.id,
        'switch',
        lane.switch,
        readsSwitches.length === 0
          ? 'the workflow reads no repository variable'
          : `the workflow reads ${sortedList(readsSwitches)}`,
      ),
    );
  }
  if (lane.switch === null && readsSwitches.length > 0) {
    rows.push(
      drift(lane.id, 'switch', 'ungated (switch: null)', `the workflow reads ${sortedList(readsSwitches)}`),
    );
  }

  // — triggers: crons and workflow_dispatch —————————————————————————————
  const manifestCrons = lane.triggers
    .filter((t) => t.kind === 'schedule')
    .map((t) => t.cron ?? '(unspecified)');
  if (sortedList(manifestCrons) !== sortedList(facts.crons)) {
    // A cron that is present but commented out is the interesting case, and it
    // is the one lifehacker's `explore` lane is actually in: the manifest still
    // records a daily schedule the workflow has had commented out for weeks.
    // Reporting that as "schedule (none)" would be true and useless.
    const workflowSays =
      facts.crons.length === 0 && facts.dormantCrons.length > 0
        ? `no active schedule (commented out: ${sortedList(facts.dormantCrons)})`
        : `schedule ${sortedList(facts.crons)}`;
    rows.push(drift(lane.id, 'triggers', `schedule ${sortedList(manifestCrons)}`, workflowSays));
  }
  const manifestDispatch = lane.triggers.some((t) => t.kind === 'dispatch');
  const workflowDispatch = facts.triggers.some((t) => t.kind === 'workflow_dispatch');
  if (manifestDispatch !== workflowDispatch) {
    rows.push(
      drift(
        lane.id,
        'triggers',
        manifestDispatch ? 'workflow_dispatch' : 'no workflow_dispatch',
        workflowDispatch ? 'workflow_dispatch' : 'no workflow_dispatch',
      ),
    );
  }

  // — harness: only when the file shows a runner ————————————————————————
  const shape = runnerShapeOf(facts);
  const consistent = harnessesConsistentWith(shape);
  if (consistent.length > 0 && !consistent.includes(lane.harness)) {
    rows.push(drift(lane.id, 'harness', lane.harness, shape));
  }

  // — tokens: the secrets the file names ————————————————————————————————
  if (sortedList(lane.usesTokens) !== sortedList(facts.secretsUsed)) {
    rows.push(drift(lane.id, 'tokens', sortedList(lane.usesTokens), sortedList(facts.secretsUsed)));
  }

  return rows;
}

// ---------------------------------------------------------------------------
// Runs
// ---------------------------------------------------------------------------

/**
 * This console's run records in the shape `computeWorkflowMetrics` folds.
 *
 * The package's `slug` is the `factory--<slug>` name it parses off a GitFactory
 * path; for a lane that GitFactory did not compile there is no such prefix, so
 * the basename without its extension is used — which is exactly what the metrics
 * engine falls back to for a path it has no label for.
 */
const RUN_CONCLUSIONS: readonly string[] = [
  'success',
  'failure',
  'cancelled',
  'timed_out',
  'skipped',
  'action_required',
  'neutral',
  'stale',
  'startup_failure',
];

/** A conclusion the metrics engine understands, or `null` — never a guess. */
function toRunConclusion(value: string | null): FactoryRun['conclusion'] {
  return value !== null && RUN_CONCLUSIONS.includes(value)
    ? (value as FactoryRun['conclusion'])
    : null;
}

export function runsToFactoryRuns(runs: readonly FleetRunRecord[]): FactoryRun[] {
  return runs.map((run) => {
    const base = run.path.split('/').pop() ?? run.path;
    const stem = base.replace(/\.ya?ml$/, '');
    return {
      path: run.path,
      slug: stem.startsWith('factory--') ? stem.slice('factory--'.length) : stem,
      runId: run.runId,
      runNumber: run.runId,
      status: run.status,
      conclusion: toRunConclusion(run.conclusion),
      event: run.event,
      htmlUrl: run.url,
      runStartedAt: run.runStartedAt,
      updatedAt: run.updatedAt,
      createdAt: run.createdAt,
      runAttempt: run.runAttempt,
    };
  });
}
