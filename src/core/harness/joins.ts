/**
 * The joins — and, more usefully, where the seven files that describe one lane
 * disagree.
 *
 * An agent file, a skill, a workflow, a manifest lane, a repository variable, a
 * token and a line in a spend ledger are seven artefacts describing **one**
 * thing. Nothing in the fleet joins them: `lint_agents.rb` checks one edge,
 * `audit.rb` checks another against a hard-coded table of one repository's
 * filenames, and a person holds the rest in their head. This module reads the
 * records the other files in this package produce and writes the join down.
 *
 * ## The six edges
 *
 * | edge | how it is joined | what a break means |
 * |---|---|---|
 * | lane ↔ workflow | `implementation`, falling back to `id` ↔ filename stem | a lane nothing runs, or automation nobody declared |
 * | workflow ↔ agent | the `agent:` input / `--agent` flag ↔ `.claude/agents/<name>.md` | the role runs with no system prompt |
 * | agent ↔ skill | prose (`Use the <x> skill`, `**<x> skill**`, `<x> subagent`) | the procedure the role was told to follow is not there |
 * | lane ↔ switch | the manifest's `switch` ↔ a `vars.<NAME>` the workflow reads | the kill switch does not gate the thing it names |
 * | lane ↔ tokens | `uses_tokens` ↔ `secrets.<NAME>` in the file | a declared credential nothing consumes, or the reverse |
 * | lane ↔ spend | a ledger row's `workflow` (the `name:`) or `agent` | the lane's cost is unattributable |
 *
 * The lane↔workflow rule is deliberately the same one `@bamr87/fleet-engines`'
 * `laneForPath` uses (`implementation === path`, else `id === basename stem`),
 * so this console and GitFactory agree about which lane a file is. It is written
 * here rather than imported because this module must stay engines-free for the
 * MCP bundle (decision D14) — one rule, two implementations, and a test that
 * pins the rule so they cannot drift into two answers.
 *
 * ## The rule about rules
 *
 * **A finding that fires on a healthy repository is a wrong rule, not a
 * discovery.** Every rule below is therefore guarded by what the repository
 * actually claims: `dangling-skill` only fires where a `.claude/skills/`
 * directory exists, `unmetered-model-call` only where the repository meters at
 * all, and `workflow-without-lane` only for workflows that really do call a
 * model. A repository that has adopted none of this is not failing — it simply
 * has not adopted it (decision D9), and the honest report is a short one.
 */

import type {
  AgentRecord,
  FleetLane,
  FleetManifest,
  HarnessFinding,
  HarnessFindingKind,
  HarnessJoin,
  LedgerSummary,
  Severity,
  SkillRecord,
  WorkflowRecord,
} from '../shared/types';
import { deriveLaneFromWorkflow } from './derive';
import { stripYamlComments, workflowStem } from './workflows';

/** Everything the join reads. All records; no I/O, no clock, no engines. */
export interface HarnessJoinInput {
  manifest: FleetManifest | null;
  workflows: readonly WorkflowRecord[];
  agents: readonly AgentRecord[];
  skills: readonly SkillRecord[];
  ledger: LedgerSummary | null;
  /** Present when the repository has a `.claude/skills/` directory at all. */
  hasSkillsDir: boolean;
  /** The workflow text, keyed by path — only needed to re-derive a lane for drift. */
  sources?: Readonly<Record<string, string>> | undefined;
}

export interface HarnessJoinResult {
  joins: HarnessJoin[];
  findings: HarnessFinding[];
}

/**
 * `laneForPath`, written down. A lane claims a workflow when its
 * `implementation` is that path, or — for a manifest that names no path — when
 * its id equals the filename stem.
 */
export function laneForWorkflow(
  lanes: readonly FleetLane[],
  workflowPath: string,
): FleetLane | null {
  const normalized = workflowPath.replace(/\\/g, '/');
  const stem = workflowStem(normalized);
  return (
    lanes.find((lane) => lane.implementation === normalized) ??
    lanes.find((lane) => lane.implementation === '' && lane.id === stem) ??
    null
  );
}

function finding(
  kind: HarnessFindingKind,
  severity: Severity,
  path: string | null,
  message: string,
): HarnessFinding {
  return { kind, severity, path, message };
}

/** The documented presence-vs-validity trap: `||` picks the first non-empty operand. */
const TOKEN_CHAIN = /secrets\.[A-Z][A-Z0-9_]*\s*\|\|\s*(?:secrets\.[A-Z][A-Z0-9_]*|github\.token)/;

/** A step that folds a run's usage into the ledger. */
const METERING_STEP = /usage_report\.rb|usage\.rb|usage-ledger\.mjs|usage_ledger\.rb/;

/**
 * Join the records and report the breaks.
 *
 * One row per workflow: the workflow is the artefact that actually runs, so it
 * is the anchor. A lane with no workflow cannot have a row — it is a finding,
 * which is the more useful shape for the thing it describes.
 */
export function joinHarness(input: HarnessJoinInput): HarnessJoinResult {
  const lanes = input.manifest?.lanes ?? [];
  const agentNames = new Set(input.agents.map((agent) => agent.name));
  const agentByName = new Map(input.agents.map((agent) => [agent.name, agent]));
  const skillNames = new Set(input.skills.map((skill) => skill.name));
  const joins: HarnessJoin[] = [];
  const findings: HarnessFinding[] = [];
  const claimed = new Set<string>();

  for (const workflow of input.workflows) {
    const lane = laneForWorkflow(lanes, workflow.path);
    if (lane !== null) {
      claimed.add(lane.id);
    }
    const agentName = workflow.agentRefs[0] ?? null;
    const agent = agentName === null ? null : (agentByName.get(agentName) ?? null);
    const skill =
      workflow.skillRefs.find((name) => skillNames.has(name)) ??
      workflow.skillRefs[0] ??
      agent?.skillRefs[0] ??
      null;
    const tokens = lane !== null && lane.usesTokens.length > 0 ? lane.usesTokens : workflow.secrets;

    joins.push({
      laneId: lane?.id ?? null,
      workflowPath: workflow.path,
      agent: agentName,
      skill,
      switch: lane?.switch ?? workflow.switches[0] ?? null,
      tokens,
      costUsd: costFor(input.ledger, workflow, agentName),
    });

    findings.push(...workflowFindings(input, workflow, lane, agentNames, skillNames));
  }

  for (const lane of lanes) {
    if (claimed.has(lane.id)) {
      continue;
    }
    findings.push(
      finding(
        'lane-without-workflow',
        'warning',
        lane.implementation === '' ? null : lane.implementation,
        `the manifest declares the lane "${lane.id}" but ${
          lane.implementation === ''
            ? 'names no workflow file'
            : `no workflow file ${lane.implementation} was read`
        } — a lane nothing runs.`,
      ),
    );
  }

  return { joins, findings: sortFindings(findings) };
}

function costFor(
  ledger: LedgerSummary | null,
  workflow: WorkflowRecord,
  agentName: string | null,
): number | null {
  if (ledger === null) {
    return null;
  }
  // The ledger's `workflow` key is the workflow's `name:`, not its filename
  // stem — the rows say "pipeline" and "Factory: Issue Factory 1".
  const byWorkflow = ledger.byWorkflow[workflow.name];
  if (byWorkflow !== undefined) {
    return byWorkflow.costUsd;
  }
  const byRole = agentName === null ? undefined : ledger.byRole[agentName];
  return byRole?.costUsd ?? null;
}

function workflowFindings(
  input: HarnessJoinInput,
  workflow: WorkflowRecord,
  lane: FleetLane | null,
  agentNames: ReadonlySet<string>,
  skillNames: ReadonlySet<string>,
): HarnessFinding[] {
  const out: HarnessFinding[] = [];

  // --- workflow ↔ agent ----------------------------------------------------
  for (const name of workflow.agentRefs) {
    if (!agentNames.has(name)) {
      out.push(
        finding(
          'dangling-agent',
          'error',
          workflow.path,
          `names the agent "${name}", and .claude/agents/${name}.md is not there — the role would run with no system prompt.`,
        ),
      );
    }
  }

  // --- workflow ↔ skill ----------------------------------------------------
  // Only where the repository keeps skills at all: a house that writes its
  // procedures into the prompt has not broken a link it never made.
  if (input.hasSkillsDir) {
    for (const name of workflow.skillRefs) {
      if (!skillNames.has(name)) {
        out.push(
          finding(
            'dangling-skill',
            'warning',
            workflow.path,
            `its prompt says to use the "${name}" skill, and .claude/skills/${name}/SKILL.md is not there.`,
          ),
        );
      }
    }
  }

  // --- lane ↔ workflow -----------------------------------------------------
  if (lane === null && workflow.runnerShape !== 'none') {
    const declared = input.manifest !== null;
    out.push(
      finding(
        'workflow-without-lane',
        declared ? 'warning' : 'info',
        workflow.path,
        declared
          ? `calls a model (${workflow.runnerShape}) and no manifest lane claims it — automation nobody declared.`
          : `calls a model (${workflow.runnerShape}) and this repository commits no fleet.manifest.yml, so nothing declares it.`,
      ),
    );
  }

  // --- lane ↔ switch -------------------------------------------------------
  if (lane !== null && lane.switch !== null && !workflow.switches.includes(lane.switch)) {
    const host = workflow.switchHost;
    out.push(
      finding(
        'switch-hosted-elsewhere',
        'info',
        workflow.path,
        host === null
          ? `the manifest gates "${lane.id}" on ${lane.switch}, and this workflow never reads vars.${lane.switch} — the switch does not gate the file it names.`
          : `the manifest gates "${lane.id}" on ${lane.switch}, which is enforced on ${host} rather than here — flipping it changes what dispatches this lane, not this lane.`,
      ),
    );
  }

  // --- lane ↔ tokens -------------------------------------------------------
  // Comment-stripped, because a comment *about* the trap is not the trap.
  // lifehacker's `content-scout.yml` documents the idiom it was migrated off in
  // a header comment, and its own `lint_tokens.rb` skips comment lines for
  // exactly that reason. Reading the raw text instead reported a repaired
  // workflow as broken — the thirteenth finding against a list of twelve.
  if (TOKEN_CHAIN.test(stripYamlComments(input.sources?.[workflow.path] ?? ''))) {
    out.push(
      finding(
        'token-presence-chain',
        'warning',
        workflow.path,
        'uses `secrets.X || …` for a token. `||` in an Actions expression returns the first NON-EMPTY operand, not the first working one, so an expired PAT wins and the fallback is unreachable — probe the token instead (bamr87/bamr87#53).',
      ),
    );
  }

  // --- metering ------------------------------------------------------------
  // Only where the repository meters at all. A repository with no ledger is not
  // failing to meter a lane; it has not adopted metering.
  if (
    input.ledger !== null &&
    workflow.runnerShape !== 'none' &&
    workflow.runnerShape !== 'claude-run' &&
    workflow.runnerShape !== 'ai-lane-caller' &&
    !METERING_STEP.test(stripYamlComments(input.sources?.[workflow.path] ?? ''))
  ) {
    out.push(
      finding(
        'unmetered-model-call',
        'warning',
        workflow.path,
        `runs a model as ${workflow.runnerShape} — outside the hub runner, which meters on its own — and carries no usage-report step, so its spend never reaches the ledger.`,
      ),
    );
  }

  return out;
}

/**
 * Every place a derived lane disagrees with the committed one.
 *
 * Reported as `manifest-drift` findings rather than applied: the committed
 * manifest carries what inference cannot know, and every one of these files was
 * generated by `wtd fleet adopt` and then edited by hand on purpose. A
 * disagreement means "the manifest was true when it was written"; whether it
 * still should be is a person's call.
 */
export function manifestDriftFindings(
  manifest: FleetManifest | null,
  workflows: readonly WorkflowRecord[],
  sources: Readonly<Record<string, string>>,
): HarnessFinding[] {
  if (manifest === null) {
    return [];
  }
  const out: HarnessFinding[] = [];
  for (const workflow of workflows) {
    const lane = laneForWorkflow(manifest.lanes, workflow.path);
    const text = sources[workflow.path];
    if (lane === null || text === undefined) {
      continue;
    }
    const derived = deriveLaneFromWorkflow(workflow.path, text);
    for (const row of compareLanes(lane, derived)) {
      out.push(
        finding(
          'manifest-drift',
          'warning',
          workflow.path,
          `lane "${lane.id}" ${row.field}: the manifest says ${row.manifestSays}, the workflow says ${row.workflowSays}.`,
        ),
      );
    }
  }
  return out;
}

/** One field's disagreement, in the shape a drift table renders. */
export interface LaneFieldDrift {
  field: string;
  manifestSays: string;
  workflowSays: string;
}

/**
 * Compare a committed lane with a derived one on the fields inference can speak
 * to.
 *
 * `description` is excluded: it is the workflow's `name:`, which people rewrite
 * without changing behaviour, and a drift table full of prose renames buries the
 * rows that matter. A guardrail the manifest never claimed (`null`) is not
 * compared at all — `null` means "the manifest did not say", and reporting a
 * silence as a disagreement is exactly the mistake `FleetGuardrails`' tristate
 * exists to prevent.
 */
export function compareLanes(committed: FleetLane, derived: FleetLane): LaneFieldDrift[] {
  const out: LaneFieldDrift[] = [];
  const add = (field: string, a: string, b: string): void => {
    if (a !== b) {
      out.push({ field, manifestSays: a, workflowSays: b });
    }
  };
  add('kind', committed.kind, derived.kind);
  add('harness', committed.harness, derived.harness);
  add('switch', committed.switch ?? '(ungated)', derived.switch ?? '(ungated)');
  add('uses_tokens', committed.usesTokens.join(', '), derived.usesTokens.join(', '));
  add('triggers', triggerLine(committed), triggerLine(derived));

  const guards: Array<[string, boolean | null, boolean | null]> = [
    ['never_merges', committed.guardrails.neverMerges, derived.guardrails.neverMerges],
    [
      'opens_pull_requests',
      committed.guardrails.opensPullRequests,
      derived.guardrails.opensPullRequests,
    ],
    [
      'writes_directly_to_default_branch',
      committed.guardrails.writesDirectlyToDefaultBranch,
      derived.guardrails.writesDirectlyToDefaultBranch,
    ],
  ];
  for (const [field, said, found] of guards) {
    if (said !== null && found !== null && said !== found) {
      out.push({ field, manifestSays: String(said), workflowSays: String(found) });
    }
  }
  return out;
}

function triggerLine(lane: FleetLane): string {
  return lane.triggers
    .map((trigger) => {
      if (trigger.kind === 'schedule') {
        return `schedule ${trigger.cron ?? ''}`.trim();
      }
      if (trigger.kind === 'event') {
        return `event ${trigger.events.join('+')}`;
      }
      return 'dispatch';
    })
    .sort()
    .join(' · ');
}

/** An agent whose front-matter `name` disagrees with its filename. */
export function agentNameFindings(agents: readonly AgentRecord[]): HarnessFinding[] {
  return agents
    .filter((agent) => !agent.nameMatchesFile)
    .map((agent) =>
      finding(
        'agent-name-mismatch',
        'error',
        agent.path,
        `declares name "${agent.name}" and lives at a different filename — Claude Code resolves --agent against the FILENAME, so this role would silently no-op.`,
      ),
    );
}

/**
 * A skill nothing anywhere names — a procedure written for a role that never
 * asks for it.
 *
 * The reference test is deliberately the *loosest* one available: the parsed
 * `skillRefs` of every workflow and agent, plus a plain substring scan of every
 * workflow's raw text. That is on purpose. `readWorkflowSkillRefs` only follows
 * three prose spellings and deliberately ignores a slash-command mention
 * (`/test-lifehacker`), because a slash command cannot be told apart from a
 * path — and a strict reader here would report a dozen live skills as orphans.
 * Missing an orphan costs nothing; inventing one costs a maintainer an
 * afternoon.
 *
 * Reported under `dangling-skill` at `info`, because the finding vocabulary has
 * no `orphan-skill` kind. The message says which direction the break runs.
 */
export function orphanSkillFindings(
  skills: readonly SkillRecord[],
  workflows: readonly WorkflowRecord[],
  agents: readonly AgentRecord[],
  sources: Readonly<Record<string, string>>,
): HarnessFinding[] {
  const referenced = new Set<string>();
  for (const workflow of workflows) {
    for (const name of workflow.skillRefs) {
      referenced.add(name);
    }
  }
  for (const agent of agents) {
    for (const name of agent.skillRefs) {
      referenced.add(name);
    }
  }
  const haystack = Object.values(sources).join('\n');
  return skills
    .filter((skill) => !referenced.has(skill.name) && !haystack.includes(skill.name))
    .map((skill) =>
      finding(
        'dangling-skill',
        'info',
        skill.path,
        `nothing names the "${skill.name}" skill — no workflow prompt, no agent file, no workflow text. It is reachable only by a person typing its trigger.`,
      ),
    );
}

const SEVERITY_ORDER: Record<Severity, number> = { error: 0, warning: 1, info: 2 };

/** Errors first, then by kind and path, so two runs report in the same order. */
export function sortFindings(findings: readonly HarnessFinding[]): HarnessFinding[] {
  return [...findings].sort(
    (a, b) =>
      SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] ||
      a.kind.localeCompare(b.kind) ||
      (a.path ?? '').localeCompare(b.path ?? '') ||
      a.message.localeCompare(b.message),
  );
}
