/**
 * Lane generation — which shape a described lane fits, and the whole of what
 * writing it would do, computed with nothing written.
 *
 * A person should be able to say "review every content pull request", "draft one
 * post a day", "audit the docs weekly" and get the files that make it real: a
 * workflow, an agent role, a skill stub, a manifest entry. Not a wizard that
 * hides what it wrote — a plan they read, a diff they see, and files they commit
 * themselves.
 *
 * **Three shapes, and `bespoke` is an answer, not a failure.**
 *
 *  1. `ai-lane-caller` — a caller of the hub's reusable `ai-lane.yml`. The gate,
 *     the bot guard, the concurrency, the PAT probe and the result assertion all
 *     live upstream; the caller is thirty lines of `with:`.
 *  2. `gate+claude-run` — the gate written out by hand plus the hub's
 *     `claude-run` composite. What a per-item matrix needs, because the reusable
 *     lane's own answer to fan-out is "call it once per item", and five
 *     near-identical caller jobs is a worse file than one matrix.
 *  3. `bespoke` — this console should not generate it at all. A lane that checks
 *     out another repository, or the pull request's head, or computes its matrix
 *     in a planning job, or makes several model passes in one job, is a workflow
 *     somebody writes and reviews. Generating an approximation of it would be
 *     worse than saying so.
 *
 * **The reasons matter more than the verdict.** "needs a dynamic matrix" is
 * something a person can act on — split the planner out, or write the file by
 * hand. A bare "unsupported" is not. So `classifyExpressibility` returns the
 * reasons in both directions: why it is bespoke, and why the second shape was
 * chosen over the first.
 *
 * **`planScaffold` writes nothing.** It reports each file, its contents, and
 * whether something is already there; the manifest before and after; the switch
 * that would have to be created *later*; and the findings of an audit run over
 * what would be written. Creating a repository variable is a different power
 * from writing a file, and bundling the two is how a person ends up arming
 * something they only meant to draft — so the switch is a note, never an action.
 *
 * Engines-free, `fs`-free, `vscode`-free. The self-audit crosses that line and
 * therefore lives in its own file (`selfAudit.ts`), which is deliberately not
 * barrel-exported and is injected here as `ctx.audit`.
 */

import type { FleetGateInput } from '../fleet/fleet';
import type {
  AuditFindingView,
  Expressibility,
  HarnessFinding,
  LaneSpec,
  ScaffoldFile,
  ScaffoldPlan,
} from '../shared/types';

import { appendLaneToManifest, switchesIn } from './manifestWrite';
import { preflightLaneSpec, FACTORY_OWNED } from './preflight';
import {
  agentPathFor,
  renderAgentFile,
  renderAiLaneCaller,
  renderGateAndClaudeRun,
  renderManifestLane,
  renderSkillStub,
  skillPathFor,
  workflowPathFor,
} from './render';

/** Where the manifest sits unless `zer0Cms.fleet.manifestPath` says otherwise. */
export const DEFAULT_MANIFEST_REL = 'fleet.manifest.yml';

// ---------------------------------------------------------------------------
// The kit version, read from the vendored VERSION file
// ---------------------------------------------------------------------------

/**
 * `version: 0.1.0` out of `media/templates/ai-runner.VERSION`.
 *
 * The stamp on every generated file says which kit produced it, and that string
 * has to come from the vendored file rather than a constant in this source —
 * otherwise a refreshed template and a stale stamp would disagree, silently, in
 * the one place a person looks to find out what generated a workflow.
 */
export function parseKitVersion(versionFileText: string): string | null {
  const match = /^version:\s*(.+?)\s*$/m.exec(versionFileText);
  const value = match?.[1];
  return value === undefined || value === '' ? null : value;
}

// ---------------------------------------------------------------------------
// Expressibility
// ---------------------------------------------------------------------------

/**
 * The six things the kit's own header says it cannot express, plus the one this
 * console adds about files it does not own.
 *
 * The first five are read straight off the spec. The last two are read out of
 * the pre/post-run hooks, because that is where they show up in the real fleet:
 * a hook that downloads an artifact is a multi-job pipeline wearing a lane's
 * clothes, and a hook that runs `claude -p` itself is a bare-CLI lane whose
 * model call the runner would never meter.
 */
function bespokeReasons(spec: LaneSpec): string[] {
  const reasons: string[] = [];
  const hooks = `${spec.preRun ?? ''}\n${spec.postRun ?? ''}`;

  if (spec.matrix !== null && 'dynamic' in spec.matrix) {
    reasons.push(
      'the matrix is computed at run time: the shared lane has no fan-out input, so a planning job has to compute the items and call the lane once per item',
    );
  }
  if (spec.crossRepoCheckout) {
    reasons.push(
      "it checks out another repository: the shared lane's checkout takes no `repository` input, and cross-repo work needs a token decision a generator should not make for you",
    );
  }
  if (spec.prHeadCheckout) {
    reasons.push(
      "it checks out the pull request's head: the shared lane's checkout takes no `ref` or `token`, and pushing to a fork's branch is a permission question, not a parameter",
    );
  }
  if (spec.modelPasses > 1) {
    reasons.push(
      `it makes ${spec.modelPasses} model passes in one job: the shared lane runs exactly one agent step`,
    );
  }
  if (/download-artifact/.test(hooks)) {
    reasons.push(
      "it consumes another job's artifact: that is a multi-job pipeline with a hand-off, and the shared lane is one job",
    );
  }
  if (/\bclaude\s+-p\b|--output-format\b/.test(hooks)) {
    reasons.push(
      'a hook calls the CLI itself and reads its stdout: that is a bare-CLI lane, and the model call inside a hook is one the runner never meters',
    );
  }
  if (FACTORY_OWNED.test(spec.id)) {
    reasons.push(
      "`factory--*` workflows are GitFactory's compiled output — this console operates lanes in the editor, it does not own the compiler's files",
    );
  }
  return reasons;
}

/**
 * Which renderer can express this lane without losing anything, and why.
 *
 * `reasons` is populated for every answer: for `bespoke` it lists what the
 * shared lane cannot do, and for `gate+claude-run` it says what pushed the lane
 * off the simplest shape. Only a plain caller comes back with none, because
 * there is nothing to explain.
 */
export function classifyExpressibility(spec: LaneSpec): {
  shape: Expressibility;
  reasons: string[];
} {
  const blockers = bespokeReasons(spec);
  if (blockers.length > 0) {
    return { shape: 'bespoke', reasons: blockers };
  }

  const reasons: string[] = [];
  if (spec.matrix !== null && 'static' in spec.matrix && spec.matrix.static.length > 0) {
    reasons.push(
      `it fans out over ${spec.matrix.static.length} items: the shared lane would be that many near-identical caller jobs, so the gate is written out once with a matrix behind it`,
    );
  }
  if (!spec.dispatchBypassesSwitch) {
    reasons.push(
      'the switch must hold even for a manual run: the shared lane always lets `workflow_dispatch` bypass it, so the gate has to be written out',
    );
  }
  return reasons.length > 0 ? { shape: 'gate+claude-run', reasons } : { shape: 'ai-lane-caller', reasons };
}

// ---------------------------------------------------------------------------
// The plan
// ---------------------------------------------------------------------------

/** What `planScaffold` needs to answer without touching a filesystem itself. */
export interface ScaffoldContext {
  /** `media/templates/ai-lane.template.yml`, as text. */
  template: string;
  /** `media/templates/agent.template.md`, as text. */
  agentTemplate: string;
  /** The workspace's `fleet.manifest.yml`, or `undefined` when it has none. */
  manifestText: string | undefined;
  /** Where that manifest lives, workspace-relative. */
  manifestRel?: string;
  /** The current contents of a workspace-relative path, or `undefined`. */
  existing(rel: string): Promise<string | undefined>;
  /**
   * The engines-backed audit, injected because it may not be imported from a
   * module the MCP bundle reaches. Pass `selfAudit`; omit it in the MCP server,
   * where `plan.audit` then carries the preflight findings alone.
   */
  audit?(plan: ScaffoldPlan): AuditFindingView[];
}

/**
 * The single pure planning step behind the editor command, the MCP preview and
 * the modal. Three callers, one computation — which is what makes "the modal
 * showed me something else" impossible rather than unlikely.
 */
export async function planScaffold(spec: LaneSpec, ctx: ScaffoldContext): Promise<ScaffoldPlan> {
  const { shape, reasons } = classifyExpressibility(spec);
  const manifestRel = ctx.manifestRel ?? DEFAULT_MANIFEST_REL;
  const preflight = preflightLaneSpec(spec);

  // Bespoke means "this console should not generate it", so it does not — and
  // it says why rather than rendering an approximation nobody asked for.
  if (shape === 'bespoke') {
    return {
      shape,
      reasons,
      files: [],
      manifest: null,
      switchToCreateLater: null,
      audit: preflight.map(asAuditView),
    };
  }

  const files: ScaffoldFile[] = [];
  const workflowRel = workflowPathFor(spec);
  files.push(
    await scaffoldFile(
      ctx,
      workflowRel,
      shape === 'ai-lane-caller'
        ? renderAiLaneCaller(spec, ctx.template)
        : renderGateAndClaudeRun(spec),
    ),
  );
  files.push(await scaffoldFile(ctx, agentPathFor(spec), renderAgentFile(spec, ctx.agentTemplate)));
  const skillRel = skillPathFor(spec);
  if (skillRel !== null) {
    files.push(await scaffoldFile(ctx, skillRel, renderSkillStub(spec)));
  }

  const manifest = planManifest(spec, ctx.manifestText, manifestRel);

  const plan: ScaffoldPlan = {
    shape,
    reasons,
    files,
    manifest: manifest.entry,
    // A note, never an action. Creating a repository variable is a different
    // power from writing a file, and the two are never bundled into one gesture.
    switchToCreateLater: spec.switch === null || spec.switch === '' ? null : spec.switch,
    audit: [...preflight.map(asAuditView), ...manifest.findings],
  };

  return { ...plan, audit: [...plan.audit, ...(ctx.audit?.(plan) ?? [])] };
}

/** One file's contents, plus whether writing it would overwrite something. */
async function scaffoldFile(
  ctx: ScaffoldContext,
  rel: string,
  contents: string,
): Promise<ScaffoldFile> {
  const current = await ctx.existing(rel);
  return { rel, contents, exists: current !== undefined };
}

/**
 * The manifest before and after — or an honest finding about why there is no
 * after. A repository with no manifest is exactly where a first lane gets
 * written, so that is not an error; it is a sentence saying the lane's files
 * were planned and its manifest entry was not.
 */
function planManifest(
  spec: LaneSpec,
  manifestText: string | undefined,
  manifestRel: string,
): { entry: ScaffoldPlan['manifest']; findings: AuditFindingView[] } {
  const laneYaml = renderManifestLane(spec);
  if (manifestText === undefined) {
    return {
      entry: null,
      findings: [
        {
          rule: 'manifest-absent',
          severity: 'info',
          path: manifestRel,
          message: `this repository has no \`${manifestRel}\`, so the lane's entry cannot be appended to one. The workflow, the agent and the skill are still the whole of the lane; declare it in a manifest when the repository grows one.`,
        },
      ],
    };
  }

  const appended = appendLaneToManifest(manifestText, laneYaml);
  if ('refused' in appended) {
    return {
      entry: null,
      findings: [
        {
          rule: 'manifest-refused',
          severity: 'error',
          path: manifestRel,
          message: appended.refused,
        },
      ],
    };
  }
  return {
    entry: { rel: manifestRel, before: manifestText, after: appended.text },
    findings: [],
  };
}

/** A preflight finding, in the one shape the modal and the webview render. */
function asAuditView(finding: HarnessFinding): AuditFindingView {
  return {
    rule: `preflight:${finding.kind}`,
    severity: finding.severity,
    message: finding.message,
    path: finding.path,
  };
}

// ---------------------------------------------------------------------------
// What the gate needs to know
// ---------------------------------------------------------------------------

/**
 * The five facts `evaluateFleetGates('scaffold', …)` checks, derived from a plan
 * so the command layer does not have to re-derive them and get one wrong.
 *
 * Note what is *not* here: `notExpressibleReasons` is empty for a
 * `gate+claude-run` lane. Its `reasons` explain a choice, not a refusal, and
 * feeding them to the gate would block a lane this console can express
 * perfectly well.
 */
export function scaffoldGateFacts(
  spec: LaneSpec,
  plan: ScaffoldPlan,
  manifestText: string | undefined,
): NonNullable<FleetGateInput['scaffold']> {
  const workflowRel = workflowPathFor(spec);
  const workflow = plan.files.find((file) => file.rel === workflowRel);
  const takenBy =
    spec.switch === null || manifestText === undefined
      ? []
      : switchesIn(manifestText).filter((name) => name === spec.switch);

  return {
    laneId: spec.id,
    workflowPath: workflowRel,
    workflowExists: workflow?.exists ?? false,
    switchName: spec.switch,
    switchTaken: takenBy.length > 0,
    notExpressibleReasons: plan.shape === 'bespoke' ? plan.reasons : [],
  };
}
