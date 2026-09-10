/**
 * One repository's fleet, read entirely from the files on disk — no network, no
 * credential, no GitHub API.
 *
 * This is what lets the Fleet tab show real facts and a real audit grade in a
 * workspace nobody has signed in to: the workflow files and the
 * `fleet.manifest.yml` are already in the folder a person has open, and the
 * engines are pure functions over their text. Decision D11 says network happens
 * only from an explicit user action; this module is the answer to "then what can
 * the console show me before I click anything?" — which turns out to be almost
 * everything except the switch values and the run history.
 *
 * ## Two injections, for two different reasons
 *
 * **The filesystem is injected** because `src/core/` never touches `fs` for
 * workspace content: the shell knows what a workspace root is and what the user
 * has granted, the core does not. `io.listWorkflows()` returns repository-
 * relative paths (`.github/workflows/x.yml`) and `io.readFile(rel)` returns
 * their text.
 *
 * **The engines are injected too**, and that one is a layering rule rather than
 * a preference. This module is re-exported through `src/core/index.ts`, which is
 * the barrel `src/mcp/` imports through, and `dist/mcp-server.js` is built with
 * an empty bare-import allow-list (decision D14). esbuild resolves the whole
 * import graph before it tree-shakes, so a runtime `import … from './engines'`
 * here would fail the MCP build even though the MCP server never calls this
 * function. Taking the four engine entry points as data keeps this module
 * type-only with respect to the package — and makes the dependency legible at
 * every call site, which is the same reasoning behind the injected `fetch` in
 * `github.ts`.
 *
 * A process with no engines therefore cannot inspect. That is the honest
 * outcome: the MCP server's `zer0_fleet_status` reads the local manifest and
 * says the rest is unknown, rather than reporting a grade it computed with half
 * a rulebook.
 */

import type { FleetLane, FleetManifest, ManifestDrift } from '../shared/types';
import { fromEngineLane, manifestDrift, toEngineManifest } from './adapters';
import type {
  EngineFleetManifest,
  Fleet,
  ImportedWorkflow,
  RepoAudit,
  RepoRef,
  WorkflowFacts,
} from './engines';

/**
 * The engine entry points this inspection runs, in the shapes
 * `@bamr87/fleet-engines` declares them. The shell passes the seam's exports
 * straight in: `{ parseWorkflow, extractFacts, buildFleet, attachLanes, auditRepo }`.
 */
export interface FleetEngineFns {
  parseWorkflow(path: string, yamlText: string): ImportedWorkflow;
  extractFacts(path: string, yamlText: string): WorkflowFacts;
  buildFleet(repo: RepoRef, parsed: ImportedWorkflow[]): Fleet;
  attachLanes(fleet: Fleet, manifest: EngineFleetManifest | null): Fleet;
  auditRepo(
    facts: WorkflowFacts[],
    opts?: { workflowStates?: Record<string, string> },
  ): RepoAudit;
}

/** Everything `inspectWorkspaceFleet` needs from outside `src/core/`. */
export interface WorkspaceFleetIo {
  /** Repository-relative paths of `.github/workflows/*.yml`, in any order. */
  listWorkflows(): Promise<string[]>;
  /** The file's text. Rejecting is fine — the file is skipped and named. */
  readFile(rel: string): Promise<string>;
  engines: FleetEngineFns;
}

export interface WorkspaceFleetInspection {
  /** The workspace folder the inspection was run over, echoed for the caller. */
  root: string;
  /** Keyed by the repository-relative workflow path. */
  facts: Record<string, WorkflowFacts>;
  audit: RepoAudit;
  drift: ManifestDrift[];
  /** Workflow files no lane claims — automation nobody has declared. */
  unmatchedWorkflows: string[];
  /** Lane ids whose `implementation` names no file that is here. */
  unmatchedLanes: string[];
  /** Files that would not read, named rather than silently dropped. */
  unreadable: string[];
}

/** `owner/name` → the engines' `RepoRef`; a slug with no slash still yields one. */
function repoRefOf(slug: string): RepoRef {
  const [owner = '', repo = ''] = slug.split('/');
  return repo === '' ? { owner: '', repo: owner } : { owner, repo };
}

/**
 * Inspect the fleet of the repository rooted at `root`.
 *
 * `manifest` is this repository's tolerant parse (`parseFleetManifest`), or
 * `null` for a repository that commits none — which is a normal state, not an
 * error (decision D9), and the one bash-365.com is in: four real AI workflows
 * and nothing declaring them. With no manifest every workflow is unmatched,
 * there is no drift to report, and the audit still runs. That is the most useful
 * screen this console can put in front of somebody who has not adopted a
 * manifest yet.
 *
 * `root` is echoed back and never joined onto anything here: the paths this
 * function speaks are repository-relative, exactly as the engines and the
 * manifest's `implementation` field use them.
 */
export async function inspectWorkspaceFleet(
  root: string,
  manifest: FleetManifest | null,
  io: WorkspaceFleetIo,
): Promise<WorkspaceFleetInspection> {
  const paths = [...(await io.listWorkflows())].sort();
  const facts: Record<string, WorkflowFacts> = {};
  const parsed: ImportedWorkflow[] = [];
  const unreadable: string[] = [];

  for (const rel of paths) {
    let text: string;
    try {
      text = await io.readFile(rel);
    } catch {
      // A workflow we cannot read is reported by name. The engines are total
      // over bad YAML but they cannot be total over a file that is not there.
      unreadable.push(rel);
      continue;
    }
    facts[rel] = io.engines.extractFacts(rel, text);
    parsed.push(io.engines.parseWorkflow(rel, text));
  }

  const engineManifest: EngineFleetManifest | null =
    manifest === null ? null : toEngineManifest(manifest).manifest;
  const fleet = io.engines.attachLanes(
    io.engines.buildFleet(repoRefOf(manifest?.repo ?? ''), parsed),
    engineManifest,
  );

  // `attachLanes` is the matcher: it pins a lane to a workflow by
  // `implementation`, falling back to `id === basename`. Reading the match off
  // its result rather than re-implementing it is what keeps this console and
  // GitFactory agreeing on which lane a file is.
  const ownLanes = new Map<string, FleetLane>(
    (manifest?.lanes ?? []).map((lane) => [lane.id, lane]),
  );
  const matchedLaneIds = new Set<string>();
  const unmatchedWorkflows: string[] = [];
  const drift: ManifestDrift[] = [];

  for (const workflow of fleet.workflows) {
    const attached = workflow.lane;
    if (attached === undefined) {
      unmatchedWorkflows.push(workflow.path);
      continue;
    }
    matchedLaneIds.add(attached.id);
    const workflowFacts = facts[workflow.path];
    if (workflowFacts === undefined) {
      continue;
    }
    // Drift is computed against **this repository's** lane, not the round-tripped
    // engine one: the round trip flattens the tristate (`null` → `true`), and a
    // guardrail the manifest never claimed must not be reported as a broken
    // promise. `fromEngineLane` is the fallback for a lane the engine matched
    // that our own parse somehow does not hold.
    const lane = ownLanes.get(attached.id) ?? fromEngineLane(attached);
    drift.push(...manifestDrift(lane, workflowFacts));
  }

  const unmatchedLanes = (manifest?.lanes ?? [])
    .filter((lane) => !matchedLaneIds.has(lane.id))
    .map((lane) => lane.id);

  return {
    root,
    facts,
    audit: io.engines.auditRepo(Object.values(facts)),
    drift,
    unmatchedWorkflows: unmatchedWorkflows.sort(),
    unmatchedLanes,
    unreadable,
  };
}
