/**
 * The Fleet console's commands: read this repository's lanes, flip a lane's
 * `*_ENABLED` switch, dispatch a lane once.
 *
 * **`doToggleSwitch` and `doDispatchLane` are the single authoritative gate**
 * for the two privileged fleet actions, exactly as `doApprove`/`doPublish`
 * are for publishing (decision D5). The dashboard's Fleet tab posts
 * `{type:'command', id:'fleet.toggleSwitch', args:{lane}}` — a lane id and
 * nothing else — and the host routes it into the *same* function the command
 * palette calls. Every privileged action here does the same four things, in
 * this order, before a byte leaves the machine:
 *
 *   1. **Re-read the configuration.** `currentConfig()` is uncached, and the
 *      master gate `zer0Cms.fleet.dispatchAllow` is read from the settings
 *      layer alone through `settingsFleetDispatchAllow()` — a `zer0.json`
 *      cannot arm it (see `src/config.ts` for the reasoning, which is the MCP
 *      publish flag's).
 *   2. **Re-read `fleet.manifest.yml` from disk.** Not the store snapshot, not
 *      the webview's copy, not the last live read.
 *   3. **Re-run `evaluateFleetGates()`.** The webview rendered an advisory
 *      version to grey out a button; this evaluation is the decision.
 *   4. **Ask, modally**, naming the repository, the lane, the variable and the
 *      value about to be written. For a toggle that value is derived host-side
 *      from the variable *as fetched a moment ago* — the webview never sends
 *      it, so a forged message cannot choose what gets written.
 *
 * ### Decision D11 — network only from an explicit user action
 *
 * `src/extension.ts` promises no network, no telemetry and no authentication
 * on activation, and this module keeps that promise while adding the first
 * network surface the extension has. The relaxation is exactly this: a GitHub
 * session is obtained **lazily, inside the action** (`getSession` with
 * `createIfNone` only when a person asked), every request goes through the
 * `fetch` injected into `githubFleetClient` (Node 20's global, handed in so a
 * test can intercept it and so `src/core` never touches the network on its
 * own), and nothing runs at activation. The extension stores no token: the
 * client asks VS Code for the session per request and the value goes into one
 * header. A passive read — opening the Fleet tab — never prompts for sign-in;
 * it renders the manifest with `switchValue: 'unknown'` and says so.
 *
 * What this file deliberately does **not** have: a `force` flag, a way to
 * write a switch value the current value did not derive, a way to dispatch on
 * any ref but the default branch, or a multi-repo roster. Those are slice 2.
 */

import * as path from 'node:path';
import * as vscode from 'vscode';

import {
  absPath,
  describeGuardrails,
  describeTriggers,
  evaluateFleetGates,
  fleetBlockerSummary,
  githubFleetClient,
  isDispatchable,
  laneById,
  nextSwitchValue,
  readFleetManifest,
  switchValueOf,
  workflowFileOf,
  type FleetBlocker,
  type FleetClient,
  type FleetGateInput,
  type FleetGateMode,
  type FleetLane,
  type FleetManifest,
  type FleetRun,
  type FleetSwitchValue,
  type ParsedFleetManifest,
  type Zer0Config,
} from '../core';
import { currentConfig, settingsFleetDispatchAllow } from '../config';
import type { Zer0Shell } from '../extension';
import { describeError } from '../logger';
import { confirm, notifyError, notifyInfo, notifyWarning } from '../uiState';
import { register } from './project';

/** The scopes the console asks for. `workflow` is what a dispatch needs. */
export const GITHUB_SCOPES: readonly string[] = ['repo', 'workflow'];

/** The workspace-state key the dashboard boots its route from. */
const ROUTE_STATE_KEY = 'zer0Cms:Dashboard:Route';

/**
 * The last live read of the repository: switch values and newest runs, keyed
 * by variable name and lane id. Held in memory for the dashboard to render
 * between refreshes; never written anywhere, never consulted by a gate.
 */
export interface FleetLive {
  /** ISO stamp of the read. */
  fetchedAt: string;
  repo: string;
  switches: Map<string, FleetSwitchValue>;
  runs: Map<string, FleetRun>;
  /** A partial failure — some lanes could not be read — explained for the screen. */
  note?: string;
}

/**
 * What the dashboard host is handed. It gets the functions, not the command
 * ids, so that holding the gate is visible in the type system.
 */
export interface FleetActions {
  /** The last live read, if any. Synchronous; no I/O. */
  live(): FleetLive | undefined;
  /**
   * Re-read the repository. `interactive` may prompt to sign in; a passive
   * refresh (opening the tab) never does, and leaves `live()` alone when
   * there is no session.
   */
  refresh(interactive: boolean): Promise<void>;
  /** Flip a lane's switch, gated and confirmed. Resolves `true` if it happened. */
  toggleSwitch(laneId: string): Promise<boolean>;
  /** Queue one run of a lane, gated and confirmed. Resolves `true` if it happened. */
  dispatchLane(laneId: string): Promise<boolean>;
}

// ---------------------------------------------------------------------------
// The lane id a message names — and nothing else
// ---------------------------------------------------------------------------

/** `{lane}` from a webview, a bare string from the palette, or nothing. */
export function laneIdFrom(arg: unknown): string | undefined {
  if (typeof arg === 'string') {
    return arg.trim() === '' ? undefined : arg.trim();
  }
  if (typeof arg === 'object' && arg !== null) {
    const lane = (arg as { lane?: unknown }).lane;
    if (typeof lane === 'string' && lane.trim() !== '') {
      return lane.trim();
    }
  }
  return undefined;
}

// ---------------------------------------------------------------------------
// Credential — obtained inside the action, never stored (D11)
// ---------------------------------------------------------------------------

async function session(
  shell: Zer0Shell,
  createIfNone: boolean,
): Promise<vscode.AuthenticationSession | undefined> {
  try {
    return await vscode.authentication.getSession('github', [...GITHUB_SCOPES], {
      createIfNone,
      silent: !createIfNone,
    });
  } catch (error) {
    // The user dismissed the sign-in, or no GitHub auth provider is installed.
    // Either way the honest answer is "no credential", not an exception.
    shell.log.verbose(`fleet: github session unavailable (${describeError(error)})`);
    return undefined;
  }
}

/** A client whose token is asked of VS Code per request. Nothing is kept. */
function clientFor(shell: Zer0Shell, manifest: FleetManifest): FleetClient {
  return githubFleetClient({
    repo: manifest.repo,
    fetchImpl: fetch,
    token: async () => {
      const found = await session(shell, false);
      if (found === undefined) {
        throw new Error('the GitHub session went away; sign in again');
      }
      return found.accessToken;
    },
  });
}

// ---------------------------------------------------------------------------
// Gate context — everything `evaluateFleetGates` needs, all of it read fresh
// ---------------------------------------------------------------------------

interface GateContext {
  cfg: Zer0Config;
  parsed: ParsedFleetManifest;
  dispatchAllow: boolean;
}

async function collectGateContext(): Promise<GateContext> {
  const cfg = currentConfig();
  const parsed = await readFleetManifest(absPath(cfg, cfg.fleet.manifestPath));
  return { cfg, parsed, dispatchAllow: settingsFleetDispatchAllow() === true };
}

function gateInput(ctx: GateContext, laneId: string, hasCredential: boolean): FleetGateInput {
  return {
    workspaceRoot: ctx.cfg.workspaceRoot,
    enabled: ctx.cfg.fleet.enabled,
    dispatchAllow: ctx.dispatchAllow,
    hasCredential,
    manifest: ctx.parsed.manifest,
    ...(ctx.parsed.reason === undefined ? {} : { manifestReason: ctx.parsed.reason }),
    laneId,
  };
}

async function reportBlockers(
  shell: Zer0Shell,
  action: string,
  laneId: string,
  blockers: readonly FleetBlocker[],
): Promise<void> {
  const summary = fleetBlockerSummary(blockers);
  shell.log.warn(`fleet: ${action} blocked for lane "${laneId}": ${summary}`);
  await notifyError(`${action} blocked: ${summary}.`);
}

/**
 * The shared front half of both privileged actions.
 *
 * Gates are evaluated before a credential is asked for, with `hasCredential`
 * assumed, so a workspace whose master gate is off is told that rather than
 * shown a sign-in prompt. Then the session is obtained — interactively, since
 * a person just asked for a privileged act — and the gate runs again with the
 * real answer. The order of the blockers is the same either way.
 */
async function gatedLane(
  shell: Zer0Shell,
  mode: FleetGateMode,
  action: string,
  laneId: string,
): Promise<{ ctx: GateContext; manifest: FleetManifest; lane: FleetLane; client: FleetClient } | undefined> {
  const ctx = await collectGateContext();
  const early = evaluateFleetGates(mode, gateInput(ctx, laneId, true));
  if (early.length > 0) {
    await reportBlockers(shell, action, laneId, early);
    return undefined;
  }

  const found = await session(shell, true);
  const blockers = evaluateFleetGates(mode, gateInput(ctx, laneId, found !== undefined));
  if (blockers.length > 0) {
    await reportBlockers(shell, action, laneId, blockers);
    return undefined;
  }

  const manifest = ctx.parsed.manifest;
  const lane = manifest === null ? undefined : laneById(manifest, laneId);
  if (manifest === null || lane === undefined) {
    // Unreachable while `manifestAbsent` and `laneUnknown` are in the gate
    // order; cheap insurance if that ever changes.
    await notifyError(`${action} blocked: lane "${laneId}" could not be resolved.`);
    return undefined;
  }
  return { ctx, manifest, lane, client: clientFor(shell, manifest) };
}

// ---------------------------------------------------------------------------
// The gate
// ---------------------------------------------------------------------------

/**
 * Flip a lane's `*_ENABLED` repository variable.
 *
 * The new value is `nextSwitchValue(current)` where `current` is the variable
 * as GitHub reports it *now* — not as the dashboard last drew it, and never as
 * a webview message claims it. A read that fails leaves `current` unknown,
 * and unknown has no next value, so the toggle refuses rather than guesses.
 */
export async function doToggleSwitch(shell: Zer0Shell, laneId: string, live: LiveCache): Promise<boolean> {
  const gated = await gatedLane(shell, 'toggle', 'Toggle switch', laneId);
  if (gated === undefined) {
    return false;
  }
  const { manifest, lane, client } = gated;
  const variable = lane.switch;
  if (variable === null) {
    // Unreachable while `laneHasNoSwitch` is in the gate order.
    await notifyError(`Toggle switch blocked: lane "${lane.id}" has no switch.`);
    return false;
  }

  let current: FleetSwitchValue;
  try {
    current = switchValueOf(await client.getVariable(variable));
  } catch (error) {
    await notifyError(`Toggle switch blocked: could not read ${variable} (${describeError(error)}).`);
    return false;
  }
  const next = nextSwitchValue(current);
  if (next === null) {
    await notifyError(`Toggle switch blocked: the current value of ${variable} is unknown.`);
    return false;
  }

  const detail = [
    `Repository: ${manifest.repo}`,
    `Lane: ${lane.id} (${lane.kind}, ${lane.harness})`,
    `Workflow: ${lane.implementation || '(none)'}`,
    `Variable: ${variable}`,
    `Current value: ${current === 'unset' ? '(unset — the lane is off)' : current}`,
    `New value: ${next}`,
    `Triggers: ${describeTriggers(lane.triggers)}`,
    `Guardrails: ${describeGuardrails(lane.guardrails)}`,
    next === 'true'
      ? 'ON means the lane runs on its schedule and events, spending its tokens, until switched off.'
      : 'OFF means scheduled and event runs skip. workflow_dispatch still bypasses the switch.',
  ].join('\n');

  const ok = await confirm(
    `Set ${variable} to "${next}" on ${manifest.repo}?`,
    next === 'true' ? 'Switch on' : 'Switch off',
    detail,
  );
  if (!ok) {
    return false;
  }

  try {
    await client.setVariable(variable, next);
  } catch (error) {
    await notifyError(`Toggle switch failed: ${describeError(error)}.`);
    return false;
  }
  live.recordSwitch(manifest.repo, variable, next);
  shell.log.info(`fleet: ${manifest.repo} ${variable}=${next} (lane ${lane.id})`);
  await notifyInfo(`${variable} is now "${next}" on ${manifest.repo}.`);
  return true;
}

/**
 * Queue one `workflow_dispatch` for a lane, on the repository's default
 * branch. A dispatch bypasses the lane's switch by design — that is what
 * `workflow_dispatch` is for — which is why it is gated and confirmed on its
 * own rather than inheriting the toggle's answer.
 */
export async function doDispatchLane(shell: Zer0Shell, laneId: string, live: LiveCache): Promise<boolean> {
  const gated = await gatedLane(shell, 'dispatch', 'Dispatch lane', laneId);
  if (gated === undefined) {
    return false;
  }
  const { manifest, lane, client } = gated;
  const file = workflowFileOf(lane);

  let branch: string;
  try {
    branch = await client.defaultBranch();
  } catch (error) {
    await notifyError(`Dispatch lane blocked: could not read the default branch (${describeError(error)}).`);
    return false;
  }

  const switchLine =
    lane.switch === null
      ? 'Switch: none — this lane is ungated.'
      : `Switch: ${lane.switch} (a dispatch runs regardless of its value).`;
  const detail = [
    `Repository: ${manifest.repo}`,
    `Lane: ${lane.id} (${lane.kind}, ${lane.harness})`,
    `Workflow: ${lane.implementation} on ${branch}`,
    switchLine,
    `Tokens: ${lane.usesTokens.length === 0 ? '(none declared)' : lane.usesTokens.join(', ')}`,
    `Guardrails: ${describeGuardrails(lane.guardrails)}`,
    'This queues exactly one run. It does not merge anything; the lane opens a pull request for a person to review, or it does nothing.',
  ].join('\n');

  const ok = await confirm(`Dispatch "${lane.id}" on ${manifest.repo}@${branch}?`, 'Dispatch', detail);
  if (!ok) {
    return false;
  }

  try {
    await client.dispatch(file, branch);
  } catch (error) {
    await notifyError(`Dispatch lane failed: ${describeError(error)}.`);
    return false;
  }
  live.recordDispatch(manifest.repo, lane.id);
  shell.log.info(`fleet: dispatched ${manifest.repo} ${file} on ${branch} (lane ${lane.id})`);
  await notifyInfo(`Dispatched "${lane.id}" on ${manifest.repo}@${branch}. Refresh the Fleet tab to see the run.`);
  return true;
}

// ---------------------------------------------------------------------------
// The live read
// ---------------------------------------------------------------------------

/** The in-memory live state and the two ways an action updates it. */
class LiveCache {
  private value: FleetLive | undefined;

  current(): FleetLive | undefined {
    return this.value;
  }

  replace(next: FleetLive | undefined): void {
    this.value = next;
  }

  /** A write just succeeded: the screen may show it without a round trip. */
  recordSwitch(repo: string, variable: string, value: FleetSwitchValue): void {
    const live = this.value ?? this.blank(repo);
    if (live.repo !== repo) {
      return;
    }
    live.switches.set(variable, value);
    this.value = live;
  }

  /** A dispatch was queued; the newest run is now stale until the next read. */
  recordDispatch(repo: string, laneId: string): void {
    const live = this.value;
    if (live === undefined || live.repo !== repo) {
      return;
    }
    live.runs.set(laneId, { status: 'queued', conclusion: null, url: '', updatedAt: new Date().toISOString() });
  }

  private blank(repo: string): FleetLive {
    return { fetchedAt: new Date().toISOString(), repo, switches: new Map(), runs: new Map() };
  }
}

/**
 * Read every gated lane's switch and every lane's newest run. Failures are
 * per lane: one 403 on a variable does not blank the whole table, it becomes
 * `unknown` for that lane and a note for the screen.
 */
async function readLive(shell: Zer0Shell, manifest: FleetManifest): Promise<FleetLive> {
  const client = clientFor(shell, manifest);
  const switches = new Map<string, FleetSwitchValue>();
  const runs = new Map<string, FleetRun>();
  const failures: string[] = [];

  for (const lane of manifest.lanes) {
    if (lane.switch !== null) {
      try {
        switches.set(lane.switch, switchValueOf(await client.getVariable(lane.switch)));
      } catch (error) {
        failures.push(`${lane.switch}: ${describeError(error)}`);
      }
    }
    const file = workflowFileOf(lane);
    if (file !== '') {
      try {
        const run = await client.latestRun(file);
        if (run !== undefined) {
          runs.set(lane.id, run);
        }
      } catch (error) {
        failures.push(`${file}: ${describeError(error)}`);
      }
    }
  }

  return {
    fetchedAt: new Date().toISOString(),
    repo: manifest.repo,
    switches,
    runs,
    ...(failures.length === 0 ? {} : { note: `some reads failed — ${failures.join('; ')}` }),
  };
}

async function doRefresh(shell: Zer0Shell, live: LiveCache, interactive: boolean): Promise<void> {
  const cfg = currentConfig();
  if (cfg.workspaceRoot === '' || !cfg.fleet.enabled) {
    if (interactive) {
      await notifyWarning('the fleet console is disabled (set "zer0Cms.fleet.enabled" to true).');
    }
    return;
  }
  const parsed = await readFleetManifest(absPath(cfg, cfg.fleet.manifestPath));
  if (parsed.manifest === null) {
    if (interactive) {
      await notifyWarning(`no fleet manifest (${parsed.reason}).`);
    }
    return;
  }
  const found = await session(shell, interactive);
  if (found === undefined) {
    if (interactive) {
      await notifyWarning('no GitHub credential — the Fleet tab shows the manifest only.');
    }
    return;
  }
  try {
    const next = await readLive(shell, parsed.manifest);
    live.replace(next);
    const gated = parsed.manifest.lanes.filter((lane) => lane.switch !== null).length;
    shell.log.info(`fleet: read ${parsed.manifest.repo} — ${next.switches.size}/${gated} switches, ${next.runs.size} runs`);
    if (next.note !== undefined) {
      shell.log.warn(`fleet: ${next.note}`);
    }
  } catch (error) {
    shell.log.warn(`fleet: refresh failed (${describeError(error)})`);
    if (interactive) {
      await notifyError(`fleet refresh failed: ${describeError(error)}.`);
    }
  }
}

// ---------------------------------------------------------------------------
// Picking a lane from the palette
// ---------------------------------------------------------------------------

async function pickLane(filter: (lane: FleetLane) => boolean, placeHolder: string): Promise<string | undefined> {
  const cfg = currentConfig();
  const parsed = await readFleetManifest(absPath(cfg, cfg.fleet.manifestPath));
  if (parsed.manifest === null) {
    await notifyWarning(`no fleet manifest (${parsed.reason}).`);
    return undefined;
  }
  const lanes = parsed.manifest.lanes.filter(filter);
  if (lanes.length === 0) {
    await notifyInfo('no lane in the manifest qualifies.');
    return undefined;
  }
  const picked = await vscode.window.showQuickPick(
    lanes.map((lane) => ({
      label: lane.id,
      description: `${lane.kind} · ${lane.harness} · ${lane.switch ?? 'ungated'}`,
      detail: `${path.posix.basename(lane.implementation) || '(no workflow)'} — ${describeTriggers(lane.triggers)}`,
      laneId: lane.id,
    })),
    { placeHolder, ignoreFocusOut: true },
  );
  return picked?.laneId;
}

// ---------------------------------------------------------------------------
// Registration
// ---------------------------------------------------------------------------

export function registerFleetCommands(shell: Zer0Shell): FleetActions {
  const live = new LiveCache();

  const actions: FleetActions = {
    live: () => live.current(),
    refresh: (interactive) => doRefresh(shell, live, interactive),
    toggleSwitch: (laneId) => doToggleSwitch(shell, laneId, live),
    dispatchLane: (laneId) => doDispatchLane(shell, laneId, live),
  };

  // --- Open the Fleet tab -------------------------------------------------
  // The dashboard boots from the persisted route; an already-open panel is
  // revealed rather than re-routed, which is `DashboardPanel.open()`'s own rule.
  register(shell, 'fleet.open', async () => {
    await shell.context.workspaceState.update(ROUTE_STATE_KEY, 'fleet');
    await vscode.commands.executeCommand('zer0Cms.dashboard');
  });

  // --- Refresh -------------------------------------------------------------
  register(shell, 'fleet.refresh', async () => {
    await doRefresh(shell, live, true);
    const now = live.current();
    if (now !== undefined) {
      await notifyInfo(`fleet: ${now.repo} read at ${now.fetchedAt}.`);
    }
  });

  // --- Toggle a switch -----------------------------------------------------
  register(shell, 'fleet.toggleSwitch', async (arg: unknown) => {
    const laneId =
      laneIdFrom(arg) ?? (await pickLane((lane) => lane.switch !== null, 'Which lane’s switch?'));
    if (laneId !== undefined) {
      await doToggleSwitch(shell, laneId, live);
    }
  });

  // --- Dispatch a lane -----------------------------------------------------
  register(shell, 'fleet.dispatchLane', async (arg: unknown) => {
    const laneId = laneIdFrom(arg) ?? (await pickLane(isDispatchable, 'Which lane to dispatch once?'));
    if (laneId !== undefined) {
      await doDispatchLane(shell, laneId, live);
    }
  });

  return actions;
}
