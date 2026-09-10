/**
 * The Fleet domain: a lane as the console sees it, and **the gate in front of
 * the two privileged actions** — flipping a lane's `*_ENABLED` switch and
 * dispatching a lane once.
 *
 * This file is to the Fleet console what `governance/approval.ts` is to
 * publishing, and it keeps the same three properties on purpose:
 *
 *   1. **Pure.** Nothing here reads the filesystem or the network. Every input
 *      is passed in, which is what lets the same function run inside a webview
 *      render (advisory), a command (authoritative) and a test.
 *   2. **The order of `FleetBlocker[]` is fixed and tested:**
 *
 *          noWorkspace, dispatchDisabled, noCredential, manifestAbsent,
 *          laneUnknown, laneHasNoSwitch, laneNotDispatchable, guardrailViolation
 *
 *      Cheapest-and-most-fundamental first, so the note under a disabled
 *      button leads with the thing a person has to fix first.
 *   3. **`dispatchDisabled` is the master gate and nothing overrides it.**
 *      Not a `force` flag (there is none), not the manifest, not a repository
 *      variable. It is `zer0Cms.fleet.enabled` AND `zer0Cms.fleet.dispatchAllow`,
 *      and the second is read from the VS Code settings layer alone — a
 *      `zer0.json` cannot arm it, for the same reason a `zer0.json` cannot arm
 *      the MCP publish flag (see `src/config.ts`).
 *
 * `FleetBlocker` is its own type rather than `governance/approval.ts`'s
 * `Blocker` because `kind` is a different closed union; the shape is the same
 * `{ kind, message }`, and the webview's `BlockerView` (`kind: string`) renders
 * both. Declaring a second `Blocker` would make the core barrel ambiguous.
 */

import type { FleetLane, FleetManifest } from '../shared/types';
import { isDispatchable, laneById } from './manifest';

// ---------------------------------------------------------------------------
// A lane, as the console sees it
// ---------------------------------------------------------------------------

/**
 * What the repository variable holds. `unset` is a real answer (the API
 * said 404); `unknown` means nobody asked yet — no credential, or offline —
 * and the console must say so rather than draw a grey pill and hope.
 */
export type FleetSwitchValue = 'true' | 'false' | 'unset' | 'unknown';

export const FLEET_SWITCH_VALUES: readonly FleetSwitchValue[] = ['true', 'false', 'unset', 'unknown'];

/** The newest run of a lane's workflow, as GitHub reports it. */
export interface FleetRun {
  /** `queued`, `in_progress`, `completed`, … */
  status: string;
  /** `success`, `failure`, `cancelled`, … — `null` while not completed. */
  conclusion: string | null;
  url: string;
  /** ISO 8601, verbatim from the API. */
  updatedAt: string;
}

/** A manifest lane plus what the repository currently says about it. */
export interface FleetLaneState {
  lane: FleetLane;
  switchValue: FleetSwitchValue;
  lastRun?: FleetRun;
}

/**
 * The value a repository variable holds → a switch value.
 *
 * Workflows gate on `vars.X_ENABLED == 'true'`, so anything other than the
 * literal string `true` — `false`, `0`, `yes`, an empty string — leaves the
 * lane OFF. Reporting those as `false` is what the workflow itself would do.
 */
export function switchValueOf(raw: string | undefined | null): FleetSwitchValue {
  if (raw === undefined || raw === null) {
    return 'unset';
  }
  return raw.trim() === 'true' ? 'true' : 'false';
}

/**
 * What flipping a switch would write. Derived from the freshly fetched
 * current value — never from the webview, which sends `{lane}` and nothing
 * else. `unknown` has no next value: a toggle that could not read the current
 * state must refuse rather than guess.
 */
export function nextSwitchValue(current: FleetSwitchValue): 'true' | 'false' | null {
  switch (current) {
    case 'true':
      return 'false';
    case 'false':
    case 'unset':
      return 'true';
    case 'unknown':
      return null;
  }
}

/** `true` when the lane is ON: gated and armed, or ungated (always on). */
export function laneIsOn(state: FleetLaneState): boolean {
  return state.lane.switch === null ? true : state.switchValue === 'true';
}

/**
 * Join the manifest with what the repository reported. Pure: the caller
 * fetches (or does not), this arranges. A lane whose switch was not looked up
 * — or which has no switch — is `unknown` / `unset` respectively; a lane with
 * no run on record has no `lastRun` key at all.
 */
export function buildLaneStates(
  manifest: FleetManifest,
  switches: ReadonlyMap<string, FleetSwitchValue> = new Map(),
  runs: ReadonlyMap<string, FleetRun> = new Map(),
): FleetLaneState[] {
  return manifest.lanes.map((lane) => {
    const run = runs.get(lane.id);
    return {
      lane,
      switchValue:
        lane.switch === null ? 'unset' : (switches.get(lane.switch) ?? 'unknown'),
      ...(run === undefined ? {} : { lastRun: run }),
    };
  });
}

// ---------------------------------------------------------------------------
// The gate
// ---------------------------------------------------------------------------

export type FleetBlockerKind =
  | 'noWorkspace'
  | 'dispatchDisabled'
  | 'noCredential'
  | 'manifestAbsent'
  | 'laneUnknown'
  | 'laneHasNoSwitch'
  | 'laneNotDispatchable'
  | 'guardrailViolation'
  // Scaffolding a new lane. Appended after the eight above, never inserted
  // among them: the order is the contract a test pins, and a person reading a
  // refusal should see the same first reason they saw yesterday.
  | 'scaffoldDisabled'
  | 'laneExists'
  | 'workflowFileExists'
  | 'switchNameTaken'
  | 'notExpressible';

export interface FleetBlocker {
  kind: FleetBlockerKind;
  message: string;
}

export type FleetGateMode = 'toggle' | 'dispatch' | 'scaffold';

export interface FleetGateInput {
  workspaceRoot: string;
  /** `zer0Cms.fleet.enabled`, from the merged configuration. */
  enabled: boolean;
  /** `zer0Cms.fleet.dispatchAllow`, from the SETTINGS layer only. */
  dispatchAllow: boolean;
  /** A GitHub session exists for this action. The token itself never comes here. */
  hasCredential: boolean;
  /** The manifest re-read from disk for this action, or why there is none. */
  manifest: FleetManifest | null;
  manifestReason?: string;
  laneId: string;
  /**
   * `zer0Cms.fleet.scaffoldAllow`, from the SETTINGS layer only — the master
   * gate for writing a lane's files, and separate from `dispatchAllow` because
   * writing a workflow into a repository and running one that is already there
   * are different powers.
   */
  scaffoldAllow?: boolean;
  /** What a scaffold would write, for the four checks that need to know. */
  scaffold?: {
    /** The lane id being created. */
    laneId: string;
    /** Workspace-relative path of the workflow file it would write. */
    workflowPath: string;
    /** `true` when that file is already on disk. */
    workflowExists: boolean;
    /** The `*_ENABLED` variable name, and whether another lane already claims it. */
    switchName: string | null;
    switchTaken: boolean;
    /** Empty when the lane is expressible; otherwise why it is not. */
    notExpressibleReasons: readonly string[];
  };
}

function noWorkspace(input: FleetGateInput): FleetBlocker | undefined {
  if (input.workspaceRoot.trim() !== '') {
    return undefined;
  }
  return { kind: 'noWorkspace', message: 'no workspace folder is open' };
}

/**
 * The master gate. Both settings, both named, so "nothing happened when I
 * clicked" names the thing to change. There is no `force`; the manifest
 * cannot set either; and `dispatchAllow` is read from the settings layer
 * alone, so a cloned `zer0.json` cannot arm it.
 */
function dispatchDisabled(input: FleetGateInput): FleetBlocker | undefined {
  if (!input.enabled) {
    return {
      kind: 'dispatchDisabled',
      message: 'the fleet console is disabled (set "zer0Cms.fleet.enabled" to true)',
    };
  }
  if (!input.dispatchAllow) {
    return {
      kind: 'dispatchDisabled',
      message:
        'fleet actions are disabled (set "zer0Cms.fleet.dispatchAllow" to true in your own settings)',
    };
  }
  return undefined;
}

function noCredential(input: FleetGateInput): FleetBlocker | undefined {
  if (input.hasCredential) {
    return undefined;
  }
  return {
    kind: 'noCredential',
    message: 'no GitHub credential (sign in when prompted; the console stores none)',
  };
}

function manifestAbsent(input: FleetGateInput): FleetBlocker | undefined {
  if (input.manifest !== null) {
    return undefined;
  }
  const reason = input.manifestReason?.trim();
  return {
    kind: 'manifestAbsent',
    message: reason ? `no fleet manifest (${reason})` : 'no fleet manifest',
  };
}

function laneUnknown(input: FleetGateInput, lane: FleetLane | undefined): FleetBlocker | undefined {
  if (input.manifest === null || lane !== undefined) {
    return undefined;
  }
  return { kind: 'laneUnknown', message: `lane "${input.laneId}" is not in the manifest` };
}

function laneHasNoSwitch(lane: FleetLane | undefined): FleetBlocker | undefined {
  if (lane === undefined || lane.switch !== null) {
    return undefined;
  }
  return {
    kind: 'laneHasNoSwitch',
    message: `lane "${lane.id}" is ungated (no *_ENABLED switch to toggle)`,
  };
}

function laneNotDispatchable(lane: FleetLane | undefined): FleetBlocker | undefined {
  if (lane === undefined || isDispatchable(lane)) {
    return undefined;
  }
  return {
    kind: 'laneNotDispatchable',
    message:
      lane.implementation === ''
        ? `lane "${lane.id}" names no workflow file`
        : `lane "${lane.id}" has no workflow_dispatch trigger`,
  };
}

/**
 * The console will not arm or dispatch a lane whose own manifest says it
 * merges, or writes straight to the default branch. Those are the two things
 * the fleet doctrine says an agent never does; a manifest admitting to either
 * is a lane for a person to run by hand, with their eyes open, not from a
 * button. A guardrail the manifest left `null` is not a violation — it is an
 * absence, and it is reported as one elsewhere.
 */
function guardrailViolation(lane: FleetLane | undefined): FleetBlocker | undefined {
  if (lane === undefined) {
    return undefined;
  }
  const broken: string[] = [];
  if (lane.guardrails.neverMerges === false) {
    broken.push('never_merges is false');
  }
  if (lane.guardrails.writesDirectlyToDefaultBranch === true) {
    broken.push('writes_directly_to_default_branch is true');
  }
  if (broken.length === 0) {
    return undefined;
  }
  return {
    kind: 'guardrailViolation',
    message: `lane "${lane.id}" declares guardrails the console will not act through (${broken.join(', ')})`,
  };
}

/**
 * Every blocker that applies, in the fixed order. An empty array means the
 * action is allowed — by this gate. The caller still owns the modal.
 */
/**
 * The console's own enable switch, without the dispatch gate behind it.
 *
 * `dispatchDisabled` conflates two questions — is the console on, and may it
 * act — which is right for a toggle or a run and wrong for a scaffold, whose
 * master gate is `scaffoldAllow`. Both report `dispatchDisabled` so the UI has
 * one kind to render for "the console is off".
 */
function consoleDisabled(input: FleetGateInput): FleetBlocker | undefined {
  if (input.enabled) {
    return undefined;
  }
  return {
    kind: 'dispatchDisabled',
    message: 'the fleet console is disabled (set "zer0Cms.fleet.enabled" to true)',
  };
}

/** The scaffold master gate. Settings-only, and nothing overrides it. */
function scaffoldDisabled(input: FleetGateInput): FleetBlocker | undefined {
  if (input.scaffoldAllow === true) {
    return undefined;
  }
  return {
    kind: 'scaffoldDisabled',
    message:
      'writing a lane is off — set `zer0Cms.fleet.scaffoldAllow` in your own settings to allow it',
  };
}

/** A manifest that already declares this lane. Regenerating one is not this command's job. */
function laneExists(input: FleetGateInput, manifest: FleetManifest | null): FleetBlocker | undefined {
  const id = input.scaffold?.laneId;
  if (id === undefined || manifest === null || laneById(manifest, id) === undefined) {
    return undefined;
  }
  return { kind: 'laneExists', message: `the manifest already declares a lane called \`${id}\`` };
}

/** A workflow file already at that path. Overwriting somebody's lane is never the safe default. */
function workflowFileExists(input: FleetGateInput): FleetBlocker | undefined {
  const plan = input.scaffold;
  if (plan === undefined || !plan.workflowExists) {
    return undefined;
  }
  return {
    kind: 'workflowFileExists',
    message: `\`${plan.workflowPath}\` already exists — rename the lane or edit that file directly`,
  };
}

/** Two lanes sharing one `*_ENABLED` variable would arm and disarm each other. */
function switchNameTaken(input: FleetGateInput): FleetBlocker | undefined {
  const plan = input.scaffold;
  if (plan === undefined || !plan.switchTaken || plan.switchName === null) {
    return undefined;
  }
  return {
    kind: 'switchNameTaken',
    message: `another lane already switches on \`${plan.switchName}\`, and two lanes on one variable arm each other`,
  };
}

/** Some lanes cannot be written as a caller of the shared runner, and saying so is the honest answer. */
function notExpressible(input: FleetGateInput): FleetBlocker | undefined {
  const reasons = input.scaffold?.notExpressibleReasons ?? [];
  if (reasons.length === 0) {
    return undefined;
  }
  return {
    kind: 'notExpressible',
    message: `this lane needs a hand-written workflow: ${reasons.join('; ')}`,
  };
}

export function evaluateFleetGates(mode: FleetGateMode, input: FleetGateInput): FleetBlocker[] {
  const lane = input.manifest === null ? undefined : laneById(input.manifest, input.laneId);

  // Scaffolding asks a different question from toggling and dispatching, so it
  // runs a different list rather than the same one with exceptions bolted on.
  // Four of the checks below are actively *wrong* here: writing a lane's files
  // needs no GitHub credential, a repository with no manifest is precisely
  // where a first lane gets written, and the lane cannot already exist — that
  // is what `laneExists` is for, with a message that says so. What both lists
  // share is the workspace and the console's own enable switch.
  if (mode === 'scaffold') {
    const scaffoldChecks: Array<FleetBlocker | undefined> = [
      noWorkspace(input),
      consoleDisabled(input),
      scaffoldDisabled(input),
      laneExists(input, input.manifest),
      workflowFileExists(input),
      switchNameTaken(input),
      notExpressible(input),
    ];
    return scaffoldChecks.filter((b): b is FleetBlocker => b !== undefined);
  }

  const checks: Array<FleetBlocker | undefined> = [
    noWorkspace(input),
    dispatchDisabled(input),
    noCredential(input),
    manifestAbsent(input),
    laneUnknown(input, lane),
    mode === 'toggle' ? laneHasNoSwitch(lane) : undefined,
    mode === 'dispatch' ? laneNotDispatchable(lane) : undefined,
    guardrailViolation(lane),
  ];
  return checks.filter((b): b is FleetBlocker => b !== undefined);
}

/** `true` when `kind` is among the blockers — for the UI and tests. */
export function hasFleetBlocker(blockers: readonly FleetBlocker[], kind: FleetBlockerKind): boolean {
  return blockers.some((b) => b.kind === kind);
}

/** `a; b` — the caller supplies the frame, as with `blockerSummary`. */
export function fleetBlockerSummary(blockers: readonly FleetBlocker[]): string {
  return blockers.map((b) => b.message).join('; ');
}
