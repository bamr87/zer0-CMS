/**
 * The Fleet console's commands: read a repository's lanes, flip a lane's
 * `*_ENABLED` switch, dispatch a lane once — and, in slice 2, act on what the
 * lane's workflow actually did: re-run its newest failure, cancel what is still
 * going, and register its workflow file enabled or disabled.
 *
 * **The five privileged verbs here are the single authoritative gate** for
 * everything the Fleet and Monitor tabs offer, exactly as `doApprove`/
 * `doPublish` are for publishing (decision D5). The dashboard posts
 * `{type:'command', id:'fleet.<verb>', args:{repo, lane}}` — a repository slug
 * and a lane id, and nothing else — and the host routes it into the *same*
 * function the command palette calls. Every privileged action does the same
 * four things, in this order, before a byte leaves the machine:
 *
 *   1. **Re-read the configuration.** `currentConfig()` is uncached, and the
 *      master gate `zer0Cms.fleet.dispatchAllow` is read from the settings
 *      layer alone through `settingsFleetDispatchAllow()` — a `zer0.json`
 *      cannot arm it (see `src/config.ts` for the reasoning, which is the MCP
 *      publish flag's). It is read **for the target repository's own folder**,
 *      because the setting is `resource`-scoped: arming one site arms one site.
 *   2. **Re-read `fleet.manifest.yml` from disk.** Not the store snapshot, not
 *      the webview's copy, not the last live read. This is also why the three
 *      new verbs act only on a repository this window has a checkout of: a
 *      repository with no folder open has no manifest on disk to re-read, and a
 *      gate that cannot re-read is not a gate.
 *   3. **Re-run `evaluateFleetGates()`** for that verb's own mode. The webview
 *      rendered an advisory version to grey out a button; this evaluation is
 *      the decision.
 *   4. **Ask, modally**, naming the repository, the lane, and exactly what is
 *      about to happen. For a toggle the value about to be written is derived
 *      host-side from the variable *as fetched a moment ago*; for a re-run or a
 *      cancel the run id comes from **what the last Refresh read**, host-side,
 *      never from a message. A forged message can choose which lane, and
 *      nothing else.
 *
 * ### What the three new verbs actually do, said in the modal
 *
 * Operators mis-model all three, so each modal says the mechanism in words:
 *
 *   * **Re-running queues a NEW attempt.** The original attempt stays on the
 *     record with its logs; nothing is overwritten and nothing is deleted.
 *   * **Cancelling stops what is in flight** and leaves the run recorded as
 *     `cancelled`. A cancelled run is not a failed one and it is not a
 *     vanished one.
 *   * **Disabling registers the workflow `disabled_manually` and does not
 *     touch the file.** Not one byte of `.github/workflows/` changes, which is
 *     why this is not an edit — and why a person who wants the lane *gone*
 *     still has to delete the file and commit that.
 *
 * ### Decision D11 — network only from an explicit user action
 *
 * `src/extension.ts` promises no network, no telemetry and no authentication on
 * activation, and this module keeps that promise while owning the extension's
 * only network surface. The relaxation is exactly this: a GitHub session is
 * obtained **lazily, inside the action** (`getSession` with `createIfNone` only
 * when a person asked), every request goes through the `fetch` injected into
 * `githubFleetClient` (Node's global, handed in so a test can intercept it and
 * so `src/core` never touches the network on its own), and nothing runs at
 * activation — no timer, no watcher, no poll. The extension stores no token:
 * the client asks VS Code for the session per request and the value goes into
 * one header. A passive read — opening the Fleet tab — never prompts for
 * sign-in; it renders the manifest with `switchValue: 'unknown'` and says so.
 *
 * **One Refresh is four calls, per repository, never per lane.** `readLive`
 * asks for every variable, every registered workflow, one bounded page of
 * recent runs and one bounded page of open pull requests, and then joins those
 * four answers to the manifest's lanes locally. Slice 1 asked per lane and cost
 * 2N calls; on lifehacker's seventeen lanes that was thirty-four requests for
 * one screen. Cost and the audit grade are read from the **checkout on disk**,
 * so they add no calls at all — and a repository with no checkout reports them
 * as unknown rather than spending a request per workflow file to guess.
 *
 * ### What this file still deliberately does not have
 *
 * No `force` flag. No way to write a switch value the current value did not
 * derive. No way to dispatch on any ref but the default branch. And no merge,
 * approve, close or label verb: `fleetPlanHasNoMergeVerbs` refuses those at the
 * level of URLs, and nothing here routes around it.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import * as vscode from 'vscode';

import {
  FLEET_MANIFEST_FILE,
  MERGE_POLICY_SWITCHES,
  absPath,
  attributePulls,
  buildLaneStates,
  costByLane,
  describeGuardrails,
  describeMergePolicy,
  describeTriggers,
  engineClientOver,
  evaluateFleetGates,
  fleetBlockerSummary,
  gitFactoryLink,
  githubFleetClient,
  inspectWorkspaceFleet,
  isDispatchable,
  laneById,
  mergeFleetRoster,
  mergePolicyOf,
  nextSwitchValue,
  parseFleetManifest,
  parseProjectsRegistry,
  parseRosterSetting,
  parseUsageSummary,
  prStage,
  readFleetManifest,
  rosterSlugOf,
  switchValueOf,
  workflowFileOf,
  type AuditFindingView,
  type FleetBlocker,
  type FleetClient,
  type FleetGateInput,
  type FleetGateMode,
  type FleetLane,
  type FleetManifest,
  type FleetPull,
  type FleetRosterEntry,
  type FleetRun,
  type FleetRunRecord,
  type FleetSwitchValue,
  type FleetWorkflowState,
  type LaneCost,
  type ManifestDrift,
  type MergePolicy,
  type ParsedFleetManifest,
  type WorkspaceFleetIo,
  type Zer0Config,
} from '../core';
import {
  attachLanes,
  auditRepo,
  buildFleet,
  extractFacts,
  gradeFor,
  parseWorkflow,
  readHub,
  type AuditFinding,
  type HubSnapshot,
  type RepoAudit,
} from '../core/fleet/engines';
import {
  currentConfig,
  settingsFleetDispatchAllow,
  settingsFleetRoster,
  workspaceFolder,
} from '../config';
import type { Zer0Shell } from '../extension';
import { describeError } from '../logger';
import { confirm, notifyError, notifyInfo, notifyWarning } from '../uiState';
import type {
  FleetPullView,
  FleetRunView,
  MonitorRepoView,
  MonitorState,
} from '../webview/shared/protocol';
import { register } from './project';

/** The scopes the console asks for. `workflow` is what a dispatch needs. */
export const GITHUB_SCOPES: readonly string[] = ['repo', 'workflow'];

/** The workspace-state key the dashboard boots its route from. */
const ROUTE_STATE_KEY = 'zer0Cms:Dashboard:Route';

/**
 * The ledger the fleet's own `ai-usage` lane commits. Read from the checkout,
 * never over the network: cost is a committed file, and a console that spent a
 * request on it would be paying for a number the working tree already has.
 */
const USAGE_SUMMARY_PATH = '_data/ai_usage/summary.yml';

/** The hub's project registry — the join key every dash surface already uses. */
const HUB_REGISTRY_PATH = '_data/projects.yml';

/**
 * The scoring weights `auditRepo` documents for its own 0–100 score
 * (`fail 10, warn 3, info 1`, clamped).
 *
 * The package grades a *repository*; the Monitor draws a *lane* per row, and
 * `gradeFor` — the thresholds, which are the part worth not re-deciding — is
 * the package's. Only the arithmetic is transcribed, and it is transcribed here
 * rather than spread through the projection so that the day the package offers
 * a per-workflow grade there is exactly one call site to delete.
 */
const AUDIT_WEIGHTS: Readonly<Record<string, number>> = { fail: 10, warn: 3, info: 1 };

// ---------------------------------------------------------------------------
// The live read, per repository
// ---------------------------------------------------------------------------

/**
 * What one Refresh of one repository read.
 *
 * Held in memory for the dashboard to render between refreshes; never written
 * anywhere, never consulted by a gate as *authority* — the three run verbs read
 * `runs`/`workflows` here to name a run id host-side, and then the gate decides
 * with that name in hand.
 *
 * Every field distinguishes "unknown" from "none", because on this screen the
 * two are different answers and a console that conflates them lies quietly:
 *
 *   * `switchesReadable: false` means `listVariables()` answered 403/404 —
 *     nobody could ask. The map is then empty and every gated lane renders
 *     `unknown`. When the list *was* readable, every gated lane's variable is
 *     pre-seeded `unset`, so an empty repository renders "off" rather than
 *     "unknown", which is what the workflow's `!= 'true'` gate would do.
 *   * `pulls: null` means the list could not be read; `[]` means there are none.
 *   * an absent `cost` entry means nobody measured that lane, and it is
 *     deliberately not a `LaneCost` full of zeroes.
 *   * `grade: null` means no checkout was read, not "grade D".
 */
export interface FleetLive {
  /** ISO stamp of the read. */
  fetchedAt: string;
  repo: string;
  /** The checkout this read joined its local facts from, when there is one. */
  localRoot: string | null;
  /** The manifest as it stood at the read, so the Monitor can draw a row without disk. */
  manifest: FleetManifest;
  switches: Map<string, FleetSwitchValue>;
  /** `false` when the variable list came back 403/404 — nobody could ask. */
  switchesReadable: boolean;
  /** The newest run per lane id. */
  runs: Map<string, FleetRun>;
  /** Every run the one bounded page carried, per lane id, newest first. */
  runsByLane: Map<string, FleetRunRecord[]>;
  /** The registered workflow per lane id — the thing enable/disable acts on. */
  workflows: Map<string, FleetWorkflowState>;
  /** Open pull requests; `null` when the list could not be read. */
  pulls: FleetPull[] | null;
  pullsByLane: Map<string, FleetPull[]>;
  /** Pull requests no lane claims. Visible on purpose — see `attributePulls`. */
  unattributedPulls: FleetPull[];
  mergePolicy: MergePolicy;
  /** Per-lane cost from the repository's own committed ledger. Absent = unmeasured. */
  cost: Map<string, LaneCost>;
  /** All-time API-equivalent dollars for the whole repository, or `null`. */
  costTotalUsd: number | null;
  /** The engines' letter for this repository's workflows, or `null` when unread. */
  grade: string | null;
  /** The rulebook's findings, per lane id. */
  audit: Map<string, AuditFindingView[]>;
  /** Per-lane letter, from `gradeFor` over that lane's own findings. */
  laneGrades: Map<string, string>;
  /** Where the manifest and the workflow files disagree. */
  drift: ManifestDrift[];
  /** A partial failure — some reads did not land — explained for the screen. */
  note?: string;
}

/**
 * What the dashboard host is handed. It gets the functions, not the command
 * ids, so that holding the gate is visible in the type system.
 */
export interface FleetActions {
  /**
   * The last live read. With no argument, the most recent one — which is what
   * the Fleet tab's "read at" line is about; with a repository slug, that
   * repository's, whether or not it was the last one read.
   */
  live(repo?: string): FleetLive | undefined;
  /**
   * Re-read a repository. `interactive` may prompt to sign in; a passive
   * refresh (opening the tab) never does, and leaves `live()` alone when
   * there is no session. With no `repo` this is the active site.
   */
  refresh(interactive: boolean, repo?: string): Promise<void>;
  /** Flip a lane's switch, gated and confirmed. Resolves `true` if it happened. */
  toggleSwitch(laneId: string): Promise<boolean>;
  /** Queue one run of a lane, gated and confirmed. Resolves `true` if it happened. */
  dispatchLane(laneId: string): Promise<boolean>;
  /** Queue the newest failed run again, as a new attempt. Gated and confirmed. */
  rerunLastFailure(target: FleetTargetRef): Promise<boolean>;
  /** Ask the newest in-flight run to stop. Gated and confirmed. */
  cancelNewest(target: FleetTargetRef): Promise<boolean>;
  /** Register the lane's workflow enabled or disabled. Gated and confirmed. */
  toggleWorkflowFile(target: FleetTargetRef): Promise<boolean>;
  /** The roster × its lanes, for the Monitor tab. Reads manifests from disk only. */
  monitor(): Promise<MonitorState>;
  /** Build the GitFactory link and hand it to the browser. Opens no socket here. */
  openInGitFactory(): Promise<void>;
  /** Read the hub's registry and scorecard. An explicit action, never ambient. */
  importHubRoster(): Promise<void>;
}

// ---------------------------------------------------------------------------
// The target a message names — and nothing else
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

/**
 * Which repository, and which lane. Both are *targets* — names the host then
 * resolves against a roster it built itself, from folders this window has open
 * and settings this person wrote. Neither is a value the action uses directly:
 * the repository selects whose manifest to re-read from disk, and the lane
 * selects a row inside it.
 */
export interface FleetTargetRef {
  /** `owner/name`, or absent for "the site the person is looking at". */
  repo?: string;
  lane: string;
}

/** `{repo, lane}` from a webview, a bare lane id from the palette, or nothing. */
export function fleetTargetFrom(arg: unknown): FleetTargetRef | undefined {
  const lane = laneIdFrom(arg);
  if (lane === undefined) {
    return undefined;
  }
  if (typeof arg === 'object' && arg !== null) {
    const repo = (arg as { repo?: unknown }).repo;
    if (typeof repo === 'string' && repo.trim() !== '') {
      return { repo: repo.trim(), lane };
    }
  }
  return { lane };
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
function clientFor(shell: Zer0Shell, repo: string): FleetClient {
  return githubFleetClient({
    repo,
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
// The roster — where the list of repositories comes from
// ---------------------------------------------------------------------------

/**
 * A roster entry with the folder that owns it, when this window has one.
 *
 * The folder is what makes the entry actionable: it scopes `currentConfig()`
 * and the `resource`-scoped `dispatchAllow`, and it is where the manifest is
 * re-read from before a gate runs.
 */
interface RosterSite {
  entry: FleetRosterEntry;
  folder: vscode.WorkspaceFolder | undefined;
}

/**
 * The repositories this console is operating, from three places at once.
 *
 * **Workspace** — every open folder that carries a readable manifest. The slug
 * is the manifest's own `repo:`, because that is the field the fleet joins on;
 * a folder whose manifest is absent or refused is not on the roster at all,
 * which is why "twelve folders, nine manifests" is nine rows and not twelve.
 *
 * **Settings** — `zer0Cms.fleet.roster`, read through `settingsFleetRoster()`
 * from the VS Code settings layer alone. A `zer0.json` arriving with a cloned
 * repository cannot add a repository to the roster, for the same reason it
 * cannot arm a dispatch. Entries that are not `owner/name` are reported rather
 * than swallowed: a typo in a settings array is otherwise invisible.
 *
 * **Hub** — only what an explicit `fleet.importHubRoster` read into memory.
 * Nothing here opens a socket; `hubEntries` is whatever a person's own action
 * put there, and it is empty until they take it.
 *
 * `mergeFleetRoster` decides which record survives a slug that arrives twice:
 * `workspace` > `settings` > `hub`, because a checkout on disk is readable now,
 * offline, at whatever commit is checked out.
 */
async function buildRoster(
  shell: Zer0Shell,
  hubEntries: readonly FleetRosterEntry[],
): Promise<RosterSite[]> {
  const workspace: FleetRosterEntry[] = [];
  const folders = new Map<string, vscode.WorkspaceFolder>();

  for (const site of shell.sites.all()) {
    const cfg = currentConfig(site.folder);
    if (cfg.workspaceRoot === '') {
      continue;
    }
    const parsed = await readFleetManifest(absPath(cfg, cfg.fleet.manifestPath));
    const slug = parsed.manifest === null ? undefined : rosterSlugOf(parsed.manifest.repo);
    if (slug === undefined) {
      continue;
    }
    workspace.push({
      slug,
      source: 'workspace',
      localRoot: cfg.workspaceRoot,
      manifestPath: cfg.fleet.manifestPath,
      branch: null,
    });
    folders.set(slug.toLowerCase(), site.folder);
  }

  const setting = parseRosterSetting(settingsFleetRoster(workspaceFolder()));
  if (setting.rejected.length > 0) {
    shell.log.warn(
      `fleet: "zer0Cms.fleet.roster" ignored ${setting.rejected.length} entry that is not owner/name: ${setting.rejected.join(', ')}`,
    );
  }

  return mergeFleetRoster(workspace, setting.entries, hubEntries).map((entry) => ({
    entry,
    folder: folders.get(entry.slug.toLowerCase()),
  }));
}

// ---------------------------------------------------------------------------
// Gate context — everything `evaluateFleetGates` needs, all of it read fresh
// ---------------------------------------------------------------------------

interface GateContext {
  cfg: Zer0Config;
  parsed: ParsedFleetManifest;
  dispatchAllow: boolean;
  /** `owner/name` for the modal and the gate's `repo` field. */
  repo: string;
}

/**
 * Everything the fleet gate depends on, for one repository.
 *
 * `fleet.manifest.yml` is a property of one repository, and so is the master
 * gate: `zer0Cms.fleet.dispatchAllow` is `resource`-scoped, so a person can arm
 * dispatch for the one repository they operate and leave the other eleven
 * folders in the window disarmed. Reading it unscoped would have made a single
 * `true` anywhere arm every site at once — which is the opposite of what a
 * per-resource setting is for.
 *
 * With no `repo` this is the **active site**, which is what the palette and the
 * Fleet tab mean. With one, it is that repository's own folder — and a slug
 * this window has no folder for resolves to `undefined`, because step 2 of the
 * gate is "re-read the manifest from disk" and there is no disk to read.
 */
async function collectGateContext(
  shell: Zer0Shell,
  repo?: string,
): Promise<GateContext | undefined> {
  let folder = workspaceFolder();
  if (repo !== undefined) {
    const roster = await buildRoster(shell, []);
    const wanted = repo.trim().toLowerCase();
    const match = roster.find((site) => site.entry.slug.toLowerCase() === wanted);
    if (match?.folder === undefined) {
      return undefined;
    }
    folder = match.folder;
  }
  const cfg = currentConfig(folder);
  const parsed = await readFleetManifest(absPath(cfg, cfg.fleet.manifestPath));
  return {
    cfg,
    parsed,
    dispatchAllow: settingsFleetDispatchAllow(folder) === true,
    repo: parsed.manifest?.repo ?? repo ?? '',
  };
}

function gateInput(
  ctx: GateContext,
  laneId: string,
  hasCredential: boolean,
  live?: FleetGateInput['live'],
): FleetGateInput {
  return {
    workspaceRoot: ctx.cfg.workspaceRoot,
    enabled: ctx.cfg.fleet.enabled,
    dispatchAllow: ctx.dispatchAllow,
    hasCredential,
    manifest: ctx.parsed.manifest,
    ...(ctx.parsed.reason === undefined ? {} : { manifestReason: ctx.parsed.reason }),
    laneId,
    ...(ctx.repo === '' ? {} : { repo: ctx.repo }),
    ...(live === undefined ? {} : { live }),
  };
}

async function reportBlockers(
  shell: Zer0Shell,
  action: string,
  laneId: string,
  blockers: readonly FleetBlocker[],
  suffix = '',
): Promise<void> {
  const summary = fleetBlockerSummary(blockers);
  shell.log.warn(`fleet: ${action} blocked for lane "${laneId}": ${summary}${suffix}`);
  await notifyError(`${action} blocked: ${summary}${suffix}.`);
}

/**
 * The shared front half of every privileged action.
 *
 * Gates are evaluated before a credential is asked for, with `hasCredential`
 * assumed, so a workspace whose master gate is off is told that rather than
 * shown a sign-in prompt. Then the session is obtained — interactively, since
 * a person just asked for a privileged act — and the gate runs again with the
 * real answer. The order of the blockers is the same either way.
 *
 * `liveFacts` is what the last Refresh read for this lane, or `undefined` when
 * nobody has refreshed. That is a different answer from "there is nothing to
 * re-run", and the refusal says which: an absent live read appends a sentence
 * naming Refresh, so a person is not left staring at "no failed run" for a lane
 * whose failures the console has simply never looked at.
 */
async function gatedLane(
  shell: Zer0Shell,
  mode: FleetGateMode,
  action: string,
  target: FleetTargetRef,
  live: LiveCache,
): Promise<
  | {
      ctx: GateContext;
      manifest: FleetManifest;
      lane: FleetLane;
      client: FleetClient;
      read: FleetLive | undefined;
    }
  | undefined
> {
  const laneId = target.lane;
  const ctx = await collectGateContext(shell, target.repo);
  if (ctx === undefined) {
    await notifyError(
      `${action} blocked: "${target.repo ?? ''}" is not a repository this window has open, and the manifest can only be re-read from a checkout.`,
    );
    return undefined;
  }

  const read = ctx.repo === '' ? undefined : live.current(ctx.repo);
  const facts = liveFactsFor(read, laneId);
  const unread =
    read === undefined && (mode === 'rerun' || mode === 'cancel' || mode === 'toggleWorkflow')
      ? ` — nothing has been read from ${ctx.repo === '' ? 'this repository' : ctx.repo} yet, so press Refresh first`
      : '';

  const early = evaluateFleetGates(mode, gateInput(ctx, laneId, true, facts));
  if (early.length > 0) {
    await reportBlockers(shell, action, laneId, early, unread);
    return undefined;
  }

  const found = await session(shell, true);
  const blockers = evaluateFleetGates(mode, gateInput(ctx, laneId, found !== undefined, facts));
  if (blockers.length > 0) {
    await reportBlockers(shell, action, laneId, blockers, unread);
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
  return { ctx, manifest, lane, client: clientFor(shell, manifest.repo), read };
}

/**
 * What one Refresh read about one lane, in the shape the gate takes it.
 *
 * `undefined` when there is no read at all — the gate then sees no `live` key,
 * which is the case its three new checks are written to distinguish.
 */
function liveFactsFor(read: FleetLive | undefined, laneId: string): FleetGateInput['live'] {
  if (read === undefined) {
    return undefined;
  }
  const workflow = read.workflows.get(laneId);
  return {
    runs: read.runsByLane.get(laneId) ?? [],
    ...(workflow === undefined ? {} : { workflow }),
  };
}

// ---------------------------------------------------------------------------
// The two configuration verbs
// ---------------------------------------------------------------------------

/**
 * Flip a lane's `*_ENABLED` repository variable.
 *
 * The new value is `nextSwitchValue(current)` where `current` is the variable
 * as GitHub reports it *now* — not as the dashboard last drew it, and never as
 * a webview message claims it. A read that fails leaves `current` unknown,
 * and unknown has no next value, so the toggle refuses rather than guesses.
 */
export async function doToggleSwitch(
  shell: Zer0Shell,
  target: FleetTargetRef,
  live: LiveCache,
): Promise<boolean> {
  const gated = await gatedLane(shell, 'toggle', 'Toggle switch', target, live);
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
export async function doDispatchLane(
  shell: Zer0Shell,
  target: FleetTargetRef,
  live: LiveCache,
): Promise<boolean> {
  const gated = await gatedLane(shell, 'dispatch', 'Dispatch lane', target, live);
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
// The three run verbs
// ---------------------------------------------------------------------------

/** `2026-09-10T06:41:00Z · push · attempt 2` — a run named the way a person reads one. */
function describeRun(run: FleetRunRecord): string {
  const outcome = run.conclusion === null ? run.status : `${run.status} · ${run.conclusion}`;
  return `#${run.runId} — ${outcome}, ${run.event}, attempt ${run.runAttempt}, updated ${run.updatedAt}`;
}

/** The newest failed run of a lane, from the one bounded page a Refresh read. */
function newestFailure(runs: readonly FleetRunRecord[]): FleetRunRecord | undefined {
  return runs.find(
    (run) => run.status === 'completed' && run.conclusion !== null && run.conclusion !== 'success',
  );
}

/** The newest run of a lane that has not completed. */
function newestInFlight(runs: readonly FleetRunRecord[]): FleetRunRecord | undefined {
  return runs.find((run) => run.status !== 'completed');
}

/**
 * Queue a lane's newest failed run again, as a new attempt.
 *
 * **The run id is not in the message.** It comes from `runsByLane` — the one
 * bounded page of recent runs the last Refresh read, joined to this lane
 * host-side. A webview that wanted to re-run something else would have to
 * change what Refresh read, which is a different program.
 */
export async function doRerunLastFailure(
  shell: Zer0Shell,
  target: FleetTargetRef,
  live: LiveCache,
): Promise<boolean> {
  const gated = await gatedLane(shell, 'rerun', 'Re-run', target, live);
  if (gated === undefined) {
    return false;
  }
  const { manifest, lane, client, read } = gated;
  const run = newestFailure(read?.runsByLane.get(lane.id) ?? []);
  if (run === undefined) {
    // Unreachable while `noRetryableRun` is in the gate order for this mode.
    await notifyError(`Re-run blocked: lane "${lane.id}" has no failed run on record.`);
    return false;
  }

  const detail = [
    `Repository: ${manifest.repo}`,
    `Lane: ${lane.id} (${lane.kind}, ${lane.harness})`,
    `Workflow: ${lane.implementation || '(none)'}`,
    `Run: ${describeRun(run)}`,
    `Read at: ${read?.fetchedAt ?? '(unknown)'} — Refresh again if that is stale.`,
    '',
    'Re-running queues a NEW attempt of this run. The original attempt stays on the record with its logs; nothing is overwritten and nothing is deleted.',
    'It re-runs the workflow as it was for that run. It does not merge anything, and it does not change the lane\'s switch.',
  ].join('\n');

  const ok = await confirm(`Re-run run #${run.runId} of "${lane.id}" on ${manifest.repo}?`, 'Re-run', detail);
  if (!ok) {
    return false;
  }

  try {
    await client.rerunRun(run.runId);
  } catch (error) {
    await notifyError(`Re-run failed: ${describeError(error)}.`);
    return false;
  }
  live.recordPending(manifest.repo, lane.id, 'queued');
  shell.log.info(`fleet: re-ran ${manifest.repo} run #${run.runId} (lane ${lane.id})`);
  await notifyInfo(`Queued a new attempt of run #${run.runId} on ${manifest.repo}. Refresh to see it.`);
  return true;
}

/**
 * Ask a lane's newest in-flight run to stop.
 *
 * Like the re-run, the run id is host-side: the newest run in the page Refresh
 * read whose status is not `completed`.
 */
export async function doCancelNewest(
  shell: Zer0Shell,
  target: FleetTargetRef,
  live: LiveCache,
): Promise<boolean> {
  const gated = await gatedLane(shell, 'cancel', 'Cancel', target, live);
  if (gated === undefined) {
    return false;
  }
  const { manifest, lane, client, read } = gated;
  const run = newestInFlight(read?.runsByLane.get(lane.id) ?? []);
  if (run === undefined) {
    // Unreachable while `noRunInProgress` is in the gate order for this mode.
    await notifyError(`Cancel blocked: lane "${lane.id}" has nothing running.`);
    return false;
  }

  const detail = [
    `Repository: ${manifest.repo}`,
    `Lane: ${lane.id} (${lane.kind}, ${lane.harness})`,
    `Workflow: ${lane.implementation || '(none)'}`,
    `Run: ${describeRun(run)}`,
    `Read at: ${read?.fetchedAt ?? '(unknown)'} — the run may have finished since.`,
    '',
    'Cancelling stops what is in flight. The run stays on the record, concluded "cancelled" — it is not removed, and a cancelled run is not a failed one.',
    'Work the run had already done (a pushed branch, an opened pull request) stays done. Cancelling stops the rest of it.',
  ].join('\n');

  const ok = await confirm(
    `Cancel run #${run.runId} of "${lane.id}" on ${manifest.repo}?`,
    'Cancel the run',
    detail,
  );
  if (!ok) {
    return false;
  }

  try {
    await client.cancelRun(run.runId);
  } catch (error) {
    await notifyError(`Cancel failed: ${describeError(error)}.`);
    return false;
  }
  live.recordPending(manifest.repo, lane.id, 'completed');
  shell.log.info(`fleet: cancelled ${manifest.repo} run #${run.runId} (lane ${lane.id})`);
  await notifyInfo(`Asked run #${run.runId} on ${manifest.repo} to stop. Refresh to see the conclusion.`);
  return true;
}

/**
 * Register a lane's workflow `active` or `disabled_manually`.
 *
 * **This is not an edit.** GitHub keeps an enablement flag beside the workflow
 * it registered; setting it changes no file, and the workflow path this acts on
 * comes from `listWorkflows()` — what GitHub says it has — rather than from the
 * manifest's `implementation`, so a file that has never run (and is therefore
 * unregistered) is refused by `workflowUnknown` instead of 404ing.
 *
 * The direction is derived from the state that same Refresh read: `active`
 * becomes disabled, anything else becomes active. A webview cannot choose it.
 */
export async function doToggleWorkflowFile(
  shell: Zer0Shell,
  target: FleetTargetRef,
  live: LiveCache,
): Promise<boolean> {
  const gated = await gatedLane(shell, 'toggleWorkflow', 'Enable/disable workflow', target, live);
  if (gated === undefined) {
    return false;
  }
  const { manifest, lane, client, read } = gated;
  const workflow = read?.workflows.get(lane.id);
  if (workflow === undefined) {
    // Unreachable while `workflowUnknown` is in the gate order for this mode.
    await notifyError(`Enable/disable workflow blocked: GitHub has no registered workflow for "${lane.id}".`);
    return false;
  }

  const enable = workflow.state !== 'active';
  const verb = enable ? 'Enable' : 'Disable';
  const detail = [
    `Repository: ${manifest.repo}`,
    `Lane: ${lane.id} (${lane.kind}, ${lane.harness})`,
    `Workflow: ${workflow.path} ("${workflow.name}")`,
    `Registered state: ${workflow.state}`,
    `New state: ${enable ? 'active' : 'disabled_manually'}`,
    `Switch: ${lane.switch ?? 'none — this lane is ungated'}`,
    `Read at: ${read?.fetchedAt ?? '(unknown)'}`,
    '',
    enable
      ? 'Enabling registers the workflow active again with GitHub. The file was never changed, so this restores exactly what is committed — schedules, events and all.'
      : 'Disabling registers the workflow disabled_manually with GitHub. It does NOT touch the file: not one byte of .github/workflows/ changes, which is why this is not an edit — and why a person who wants the lane gone still has to delete the file and commit that.',
    lane.switch === null
      ? 'This lane has no *_ENABLED variable, so this flag is the only thing holding it.'
      : `This is a different control from ${lane.switch}: the variable is read inside the workflow, this stops GitHub from starting it at all.`,
  ].join('\n');

  const ok = await confirm(
    `${verb} "${workflow.path}" on ${manifest.repo}?`,
    `${verb} workflow`,
    detail,
  );
  if (!ok) {
    return false;
  }

  try {
    // The numeric id, not `workflow.path`: GitHub addresses a workflow by its
    // id or by its **file name**, never by its repository-relative path, and
    // the id is the one of those two that cannot be ambiguous.
    await client.setWorkflowEnabled(String(workflow.id), enable);
  } catch (error) {
    await notifyError(`${verb} workflow failed: ${describeError(error)}.`);
    return false;
  }
  live.recordWorkflowState(manifest.repo, lane.id, enable ? 'active' : 'disabled_manually');
  shell.log.info(`fleet: ${enable ? 'enabled' : 'disabled'} ${manifest.repo} ${workflow.path} (lane ${lane.id})`);
  await notifyInfo(
    `${workflow.path} is now ${enable ? 'active' : 'disabled_manually'} on ${manifest.repo}. The file is unchanged.`,
  );
  return true;
}

// ---------------------------------------------------------------------------
// The live cache
// ---------------------------------------------------------------------------

/** What an explicit hub read put in memory. Empty until somebody asks for one. */
interface HubImport {
  slug: string;
  readAt: string;
  entries: FleetRosterEntry[];
  note: string | null;
  snapshot: HubSnapshot | null;
}

/**
 * The in-memory live state, one entry per repository, and the four ways an
 * action updates it.
 *
 * Keyed case-insensitively on the slug because GitHub is: `bamr87/It-Journey`
 * and `bamr87/it-journey` are one repository, and two entries would make two of
 * every row on the Monitor.
 */
class LiveCache {
  private readonly byRepo = new Map<string, FleetLive>();
  private newest: string | undefined;
  private hub: HubImport | undefined;

  /** The newest read, or a named repository's. Synchronous; no I/O. */
  current(repo?: string): FleetLive | undefined {
    if (repo === undefined) {
      return this.newest === undefined ? undefined : this.byRepo.get(this.newest);
    }
    return this.byRepo.get(repo.trim().toLowerCase());
  }

  replace(next: FleetLive): void {
    const key = next.repo.trim().toLowerCase();
    this.byRepo.set(key, next);
    this.newest = key;
  }

  hubImport(): HubImport | undefined {
    return this.hub;
  }

  setHub(next: HubImport): void {
    this.hub = next;
  }

  /** A write just succeeded: the screen may show it without a round trip. */
  recordSwitch(repo: string, variable: string, value: FleetSwitchValue): void {
    const live = this.byRepo.get(repo.trim().toLowerCase());
    if (live === undefined) {
      return;
    }
    live.switches.set(variable, value);
    live.mergePolicy = mergePolicyOf(live.switches);
  }

  /** A dispatch was queued; the newest run is now stale until the next read. */
  recordDispatch(repo: string, laneId: string): void {
    this.recordPending(repo, laneId, 'queued');
  }

  /**
   * A run verb landed. The screen shows the new status immediately and the
   * conclusion stays `null`, because the console does not know one — it asked
   * for something to happen and has not looked since.
   */
  recordPending(repo: string, laneId: string, status: string): void {
    const live = this.byRepo.get(repo.trim().toLowerCase());
    if (live === undefined) {
      return;
    }
    live.runs.set(laneId, { status, conclusion: null, url: '', updatedAt: new Date().toISOString() });
  }

  /** An enable/disable landed; the registered state is known without a re-read. */
  recordWorkflowState(repo: string, laneId: string, state: string): void {
    const live = this.byRepo.get(repo.trim().toLowerCase());
    const workflow = live?.workflows.get(laneId);
    if (live === undefined || workflow === undefined) {
      return;
    }
    live.workflows.set(laneId, { ...workflow, state });
  }
}

// ---------------------------------------------------------------------------
// Reading a repository — four calls, never per lane
// ---------------------------------------------------------------------------

/** The engines, injected as data the way `inspectWorkspaceFleet` asks for them. */
function workspaceFleetIo(root: string): WorkspaceFleetIo {
  return {
    async listWorkflows(): Promise<string[]> {
      try {
        const names = await fs.readdir(path.join(root, '.github', 'workflows'));
        return names
          .filter((name) => /\.ya?ml$/i.test(name))
          .map((name) => `.github/workflows/${name}`);
      } catch {
        // No `.github/workflows/` is a normal state — a site that runs no lanes.
        return [];
      }
    },
    readFile: (rel: string) => fs.readFile(path.join(root, rel), 'utf8'),
    engines: { parseWorkflow, extractFacts, buildFleet, attachLanes, auditRepo },
  };
}

/** `AuditFinding` → the wire shape, which carries no package type (decision D14). */
function auditView(finding: AuditFinding): AuditFindingView {
  return {
    rule: finding.ruleId,
    severity: finding.severity,
    message: finding.message,
    path: finding.path,
  };
}

/**
 * One lane's own letter, from its own findings.
 *
 * `gradeFor` — the thresholds — is the package's; only `auditRepo`'s documented
 * weighting is transcribed (see `AUDIT_WEIGHTS`). A lane with no findings at
 * all still grades `S`, which is the same answer the repository-level rulebook
 * would give a spotless workflow.
 */
function laneGrade(findings: readonly AuditFinding[]): string {
  let score = 100;
  for (const finding of findings) {
    score -= AUDIT_WEIGHTS[finding.severity] ?? 0;
  }
  return gradeFor(Math.max(0, Math.min(100, score)), [...findings]);
}

/** The facts a checkout gives for free: cost, the audit grade, drift. */
interface LocalFacts {
  cost: Map<string, LaneCost>;
  costTotalUsd: number | null;
  grade: string | null;
  audit: Map<string, AuditFindingView[]>;
  laneGrades: Map<string, string>;
  drift: ManifestDrift[];
  notes: string[];
}

/**
 * Every local column, unknown.
 *
 * A function rather than a shared constant: these are the values a repository
 * with no checkout gets, they end up inside a cached `FleetLive`, and one
 * shared empty `Map` handed to twelve rows is a bug waiting for the first line
 * of code that writes to it.
 */
function noLocalFacts(): LocalFacts {
  return {
    cost: new Map(),
    costTotalUsd: null,
    grade: null,
    audit: new Map(),
    laneGrades: new Map(),
    drift: [],
    notes: [],
  };
}

/**
 * Everything a checkout answers without a socket.
 *
 * The audit rulebook, the drift rows and the cost ledger are all functions of
 * files that are already in the folder a person has open, so reading them here
 * costs nothing and keeps a Refresh at four requests. A repository with no
 * checkout gets `noLocalFacts()` — every one of those columns `null` or absent,
 * which is what the Monitor renders as unknown. It is deliberately *not* a
 * per-workflow contents read: that would be one request per file, on a screen
 * whose whole budget is four.
 */
async function readLocalFacts(
  root: string,
  manifest: FleetManifest,
  workflows: readonly FleetWorkflowState[],
  workflowByLane: ReadonlyMap<string, FleetWorkflowState>,
): Promise<LocalFacts> {
  const notes: string[] = [];
  const facts: LocalFacts = { ...noLocalFacts(), notes };

  // --- the engines, over the workflow files on disk --------------------------
  try {
    const inspection = await inspectWorkspaceFleet(root, manifest, workspaceFleetIo(root));
    const states: Record<string, string> = {};
    for (const workflow of workflows) {
      states[workflow.path] = workflow.state;
    }
    const audit: RepoAudit =
      Object.keys(states).length === 0
        ? inspection.audit
        : auditRepo(Object.values(inspection.facts), { workflowStates: states });
    facts.grade = audit.grade;
    facts.drift = inspection.drift;

    const byPath = new Map<string, AuditFinding[]>();
    for (const finding of audit.findings) {
      if (finding.path === null) {
        continue;
      }
      const existing = byPath.get(finding.path);
      if (existing === undefined) {
        byPath.set(finding.path, [finding]);
      } else {
        existing.push(finding);
      }
    }
    for (const lane of manifest.lanes) {
      const lanePath = workflowByLane.get(lane.id)?.path ?? lane.implementation;
      const found = lanePath === '' ? undefined : byPath.get(lanePath);
      if (found === undefined) {
        continue;
      }
      facts.audit.set(lane.id, found.map(auditView));
      facts.laneGrades.set(lane.id, laneGrade(found));
    }
  } catch (error) {
    notes.push(`the audit could not be run over the checkout (${describeError(error)})`);
  }

  // --- the committed ledger --------------------------------------------------
  try {
    const text = await fs.readFile(path.join(root, USAGE_SUMMARY_PATH), 'utf8');
    const summary = parseUsageSummary(text);
    if (summary !== null) {
      const names = new Map<string, string>();
      for (const workflow of workflows) {
        names.set(workflow.path, workflow.name);
        names.set(workflow.path.slice(workflow.path.lastIndexOf('/') + 1), workflow.name);
      }
      facts.cost = new Map(costByLane(summary, manifest, names));
      facts.costTotalUsd = summary.allTimeUsd;
    }
  } catch {
    // No ledger is the normal state for a repository that has never metered a
    // run. Absent cost is `null`, never `0` — see `core/fleet/cost.ts`.
  }

  return facts;
}

/**
 * Read one repository: **four calls, and never one per lane.**
 *
 *   1. every Actions variable — one page, which answers every lane's switch
 *      *and* the three merge-policy variables in the same reply;
 *   2. every registered workflow with its state;
 *   3. one bounded page of the newest runs across every workflow;
 *   4. one bounded page of the open pull requests.
 *
 * Then the four answers are joined to the manifest's lanes locally. Slice 1
 * asked per lane and cost 2N requests; lifehacker's seventeen lanes made that
 * thirty-four for one screen, and it-journey's fifteen made thirty.
 *
 * **Each call fails on its own.** A 403 on the variables leaves every switch
 * `unknown` and names the failure in the note; it does not blank the runs, and
 * it does not take the tab down. `listVariables()`'s `null` is the tristate
 * that makes that possible: `[]` means the repository has no variables and
 * every switch is genuinely unset, `null` means nobody could ask.
 */
async function readLive(
  client: FleetClient,
  slug: string,
  manifest: FleetManifest,
  localRoot: string | null,
): Promise<FleetLive> {
  const failures: string[] = [];
  if (manifest.repo !== '' && manifest.repo.toLowerCase() !== slug.toLowerCase()) {
    // The roster row is what was read; the manifest is what that repository
    // committed. A fork legitimately carries its upstream's slug, so this is a
    // note rather than a refusal — but the row must stay labelled with the
    // repository the four calls actually went to.
    failures.push(`the manifest in ${slug} declares repo: ${manifest.repo}`);
  }

  const variables = await client
    .listVariables()
    .catch((error: unknown) => {
      failures.push(`variables: ${describeError(error)}`);
      return null;
    });
  const workflowList = await client.listWorkflows().catch((error: unknown) => {
    failures.push(`workflows: ${describeError(error)}`);
    return [] as FleetWorkflowState[];
  });
  const recent = await client.recentRuns().catch((error: unknown) => {
    failures.push(`runs: ${describeError(error)}`);
    return [] as FleetRunRecord[];
  });
  const pullList = await client.openPulls().catch((error: unknown) => {
    failures.push(`pulls: ${describeError(error)}`);
    return null;
  });

  // --- switches --------------------------------------------------------------
  const switches = new Map<string, FleetSwitchValue>();
  const switchesReadable = variables !== null;
  if (variables !== null) {
    // Seed every name the screen asks about with `unset`, then overwrite from
    // the reply. Without the seed an empty repository would render `unknown`
    // for a variable that is genuinely not set, which is the one confusion the
    // whole tristate exists to prevent.
    for (const lane of manifest.lanes) {
      if (lane.switch !== null) {
        switches.set(lane.switch, 'unset');
      }
    }
    for (const name of MERGE_POLICY_SWITCHES) {
      switches.set(name, 'unset');
    }
    for (const variable of variables) {
      switches.set(variable.name, switchValueOf(variable.value));
    }
  }

  // --- workflows, by lane ----------------------------------------------------
  const byPath = new Map<string, FleetWorkflowState>();
  const byFile = new Map<string, FleetWorkflowState>();
  for (const workflow of workflowList) {
    byPath.set(workflow.path, workflow);
    byFile.set(workflow.path.slice(workflow.path.lastIndexOf('/') + 1), workflow);
  }
  const workflows = new Map<string, FleetWorkflowState>();
  for (const lane of manifest.lanes) {
    const file = workflowFileOf(lane);
    const found =
      (lane.implementation === '' ? undefined : byPath.get(lane.implementation)) ??
      (file === '' ? undefined : byFile.get(file));
    if (found !== undefined) {
      workflows.set(lane.id, found);
    }
  }

  // --- runs, by lane ---------------------------------------------------------
  const runsByLane = new Map<string, FleetRunRecord[]>();
  const runs = new Map<string, FleetRun>();
  for (const lane of manifest.lanes) {
    const file = workflowFileOf(lane);
    const wanted = workflows.get(lane.id)?.path ?? lane.implementation;
    const mine = recent.filter(
      (run) =>
        (wanted !== '' && run.path === wanted) ||
        (file !== '' && run.path.slice(run.path.lastIndexOf('/') + 1) === file),
    );
    if (mine.length === 0) {
      continue;
    }
    runsByLane.set(lane.id, mine);
    const newest = mine[0];
    if (newest !== undefined) {
      runs.set(lane.id, {
        status: newest.status,
        conclusion: newest.conclusion,
        url: newest.url,
        updatedAt: newest.updatedAt,
      });
    }
  }

  // --- pull requests, by lane ------------------------------------------------
  const attributed = attributePulls(pullList ?? [], manifest.lanes);
  const pullsByLane = new Map<string, FleetPull[]>(attributed.byLane);

  // --- what the checkout answers for free ------------------------------------
  const local =
    localRoot === null || localRoot === ''
      ? noLocalFacts()
      : await readLocalFacts(localRoot, manifest, workflowList, workflows);
  failures.push(...local.notes);

  return {
    fetchedAt: new Date().toISOString(),
    repo: slug,
    localRoot: localRoot === '' ? null : localRoot,
    manifest,
    switches,
    switchesReadable,
    runs,
    runsByLane,
    workflows,
    pulls: pullList,
    pullsByLane,
    unattributedPulls: attributed.unattributed,
    mergePolicy: mergePolicyOf(switches),
    cost: local.cost,
    costTotalUsd: local.costTotalUsd,
    grade: local.grade,
    audit: local.audit,
    laneGrades: local.laneGrades,
    drift: local.drift,
    ...(failures.length === 0 ? {} : { note: `some reads failed — ${failures.join('; ')}` }),
  };
}

/**
 * Refresh one repository — the active site, or a named roster entry.
 *
 * A read that fails **degrades to a note** rather than taking the tab down: the
 * cache keeps whatever it had, the log says what happened, and an interactive
 * caller is told. That is the same posture as `readLive`'s per-call catches,
 * one level up.
 */
async function doRefresh(
  shell: Zer0Shell,
  live: LiveCache,
  interactive: boolean,
  repo?: string,
): Promise<void> {
  if (repo !== undefined) {
    const roster = await buildRoster(shell, live.hubImport()?.entries ?? []);
    const wanted = repo.trim().toLowerCase();
    const site = roster.find((entry) => entry.entry.slug.toLowerCase() === wanted);
    if (site === undefined) {
      if (interactive) {
        await notifyWarning(`"${repo}" is not on this window's fleet roster.`);
      }
      return;
    }
    if (site.folder === undefined) {
      await refreshRemote(shell, live, interactive, site.entry);
      return;
    }
  }

  const ctx = await collectGateContext(shell, repo);
  if (ctx === undefined) {
    if (interactive) {
      await notifyWarning(`"${repo ?? ''}" is not a repository this window has open.`);
    }
    return;
  }
  if (ctx.cfg.workspaceRoot === '' || !ctx.cfg.fleet.enabled) {
    if (interactive) {
      await notifyWarning('the fleet console is disabled (set "zer0Cms.fleet.enabled" to true).');
    }
    return;
  }
  const manifest = ctx.parsed.manifest;
  if (manifest === null) {
    if (interactive) {
      await notifyWarning(`no fleet manifest (${ctx.parsed.reason}).`);
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
    const next = await readLive(
      clientFor(shell, manifest.repo),
      manifest.repo,
      manifest,
      ctx.cfg.workspaceRoot,
    );
    live.replace(next);
    const gated = manifest.lanes.filter((lane) => lane.switch !== null).length;
    shell.log.info(
      `fleet: read ${manifest.repo} in 4 calls — ${next.switchesReadable ? `${gated} switches` : 'switches unreadable'}, ` +
        `${next.runs.size} lanes with a run, ${next.pulls === null ? 'pulls unreadable' : `${next.pulls.length} open pulls`}`,
    );
    // The one sentence an operator wants before they look at the queue: is
    // anything going to merge these without a person? The vocabulary lives in
    // `core/fleet/policy.ts` so the log and the screen cannot drift apart.
    shell.log.info(`fleet: ${manifest.repo} ${describeMergePolicy(next.mergePolicy)}`);
    if (next.note !== undefined) {
      shell.log.warn(`fleet: ${next.note}`);
    }
  } catch (error) {
    shell.log.warn(`fleet: refresh of ${manifest.repo} failed (${describeError(error)})`);
    if (interactive) {
      await notifyError(`fleet refresh failed: ${describeError(error)}.`);
    }
  }
}

/**
 * Refresh a roster entry this window has **no checkout of**.
 *
 * One extra call before the usual four: the manifest is read with the declared
 * contents call, whose own `returns` sentence names a manifest as one of the
 * three things it is for. So a settings- or hub-named repository costs five
 * requests and comes back with real lane rows, real switches, real runs and a
 * real pull queue.
 *
 * What it cannot come back with is the audit grade, the drift rows or the cost:
 * all three are functions of files in a checkout — the workflow YAML and the
 * committed ledger — and fetching those would be one request per workflow file
 * on a screen whose budget is four. They stay `null`, the Monitor renders them
 * as unknown, and the row says why.
 *
 * No privileged verb is offered on such a row, and that is not an oversight:
 * step 2 of every gate is "re-read the manifest from disk", and a repository
 * with no folder open has no disk to re-read. Reading is safe; acting on a
 * manifest nobody can re-read is not.
 */
async function refreshRemote(
  shell: Zer0Shell,
  live: LiveCache,
  interactive: boolean,
  entry: FleetRosterEntry,
): Promise<void> {
  const found = await session(shell, interactive);
  if (found === undefined) {
    if (interactive) {
      await notifyWarning(`no GitHub credential — ${entry.slug} was not read.`);
    }
    return;
  }
  const client = clientFor(shell, entry.slug);
  try {
    const file = await client.readFile(entry.manifestPath);
    const parsed = file === null ? undefined : parseFleetManifest(file.content);
    const manifest = parsed?.manifest ?? null;
    if (manifest === null) {
      if (interactive) {
        await notifyWarning(
          `${entry.slug} has no readable ${entry.manifestPath} on its default branch (${parsed?.reason ?? 'not found'}).`,
        );
      }
      return;
    }
    const next = await readLive(client, entry.slug, manifest, null);
    // The one field a remote read can never fill honestly, said once here so
    // the screen does not have to infer it from three separate nulls.
    next.note = [
      next.note,
      'no checkout in this window, so the audit grade, the drift rows and the cost are unread',
    ]
      .filter((line): line is string => line !== undefined && line !== '')
      .join('; ');
    live.replace(next);
    shell.log.info(
      `fleet: read ${entry.slug} in 5 calls (manifest + 4) — ${manifest.lanes.length} lanes, no checkout`,
    );
  } catch (error) {
    shell.log.warn(`fleet: refresh of ${entry.slug} failed (${describeError(error)})`);
    if (interactive) {
      await notifyError(`fleet refresh of ${entry.slug} failed: ${describeError(error)}.`);
    }
  }
}

// ---------------------------------------------------------------------------
// The hub — read only when a person asks
// ---------------------------------------------------------------------------

/**
 * Read the hub's project registry and its harness scorecard.
 *
 * **This is the only thing in the console that reaches a repository nobody
 * named.** It is therefore a command a person invokes, never something a tab
 * open does: `_data/projects.yml` is one contents read, and the engines'
 * `readHub` is a handful more over the hub's committed signals. Both go through
 * the same declared plan as everything else — `readHub` is handed the
 * `engineClientOver` adapter, whose ten refused members throw before any fetch.
 */
async function doReadHub(shell: Zer0Shell, live: LiveCache): Promise<void> {
  const cfg = currentConfig(workspaceFolder());
  const slug = rosterSlugOf(cfg.fleet.hub);
  if (slug === undefined) {
    await notifyWarning(`"zer0Cms.fleet.hub" is not an owner/name repository (${cfg.fleet.hub}).`);
    return;
  }
  const found = await session(shell, true);
  if (found === undefined) {
    await notifyWarning('no GitHub credential — the hub was not read.');
    return;
  }

  const client = clientFor(shell, slug);
  const notes: string[] = [];
  let entries: FleetRosterEntry[] = [];
  try {
    const file = await client.readFile(HUB_REGISTRY_PATH);
    entries = file === null ? [] : parseProjectsRegistry(file.content);
    if (file === null) {
      notes.push(`${slug} has no ${HUB_REGISTRY_PATH}`);
    }
  } catch (error) {
    notes.push(`the registry could not be read (${describeError(error)})`);
  }

  let snapshot: HubSnapshot | null = null;
  try {
    const [owner = '', repo = ''] = slug.split('/');
    snapshot = await readHub(engineClientOver(client, slug), { owner, repo });
  } catch (error) {
    notes.push(`the harness scorecard could not be read (${describeError(error)})`);
  }

  live.setHub({
    slug,
    readAt: new Date().toISOString(),
    entries,
    note: notes.length === 0 ? null : notes.join('; '),
    snapshot,
  });
  shell.log.info(`fleet: read the hub ${slug} — ${entries.length} registry entries`);
  await notifyInfo(
    `Imported ${entries.length} repositor${entries.length === 1 ? 'y' : 'ies'} from ${slug}. They are read-only rows until a folder is open for one.`,
  );
}

// ---------------------------------------------------------------------------
// The Monitor projection
// ---------------------------------------------------------------------------

function runView(run: FleetRun | undefined): FleetRunView | null {
  return run === undefined
    ? null
    : { status: run.status, conclusion: run.conclusion, url: run.url, updatedAt: run.updatedAt };
}

/** The pull strip, in the shape both tabs draw. */
export function pullViews(
  pulls: readonly FleetPull[] | null,
  byLane: ReadonlyMap<string, readonly FleetPull[]>,
): FleetPullView[] | null {
  if (pulls === null) {
    return null;
  }
  const laneOf = new Map<number, string>();
  for (const [laneId, list] of byLane) {
    for (const pull of list) {
      laneOf.set(pull.number, laneId);
    }
  }
  return pulls.map((pull) => ({
    number: pull.number,
    title: pull.title,
    stage: prStage(pull.labels, pull.draft),
    url: pull.url,
    laneId: laneOf.get(pull.number) ?? null,
  }));
}

/** `MERGE_POLICY_SWITCHES` → the wire's plain record. Never a writer. */
export function mergePolicyView(policy: MergePolicy): Record<string, string> {
  const out: Record<string, string> = {};
  for (const name of MERGE_POLICY_SWITCHES) {
    out[name] = policy.switches[name];
  }
  return out;
}

/**
 * The roster as a matrix: every repository, every lane, and honestly-unknown
 * everywhere nobody has looked.
 *
 * Two absences are different and both are drawn as such. A repository with a
 * checkout but no refresh has **real lane rows** — the manifest is on disk, so
 * the console knows the lanes exist — and every live column `unknown`. A
 * repository with no checkout and no refresh has no lane rows at all, because
 * nothing has read its manifest; its note says so. Neither renders a `0`.
 *
 * Reads manifests from disk and the live cache. No network, ever: the Monitor
 * tab opening must not spend a request, and a person who wants numbers presses
 * Refresh on the row they care about.
 */
async function monitorStateFrom(shell: Zer0Shell, live: LiveCache): Promise<MonitorState> {
  const cfg = currentConfig(workspaceFolder());
  const hub = live.hubImport();
  const roster = await buildRoster(shell, hub?.entries ?? []);
  const rows: MonitorRepoView[] = [];

  for (const site of roster) {
    const read = live.current(site.entry.slug);
    let manifest: FleetManifest | null = read?.manifest ?? null;
    let reason: string | undefined;

    if (site.entry.localRoot !== null) {
      const parsed = await readFleetManifest(
        path.join(site.entry.localRoot, site.entry.manifestPath),
      );
      manifest = parsed.manifest ?? manifest;
      reason = parsed.reason;
    }

    const states = manifest === null ? [] : buildLaneStates(manifest, read?.switches, read?.runs);
    const note =
      read?.note ??
      (read !== undefined
        ? null
        : site.entry.localRoot === null
          ? 'No checkout in this window and no read yet — nothing about this repository is known here.'
          : reason !== undefined
            ? `The manifest could not be read (${reason}).`
            : 'Not read yet — the lanes come from the checkout; every live column is unknown until Refresh.');

    rows.push({
      slug: site.entry.slug,
      source: site.entry.source,
      localRoot: site.entry.localRoot,
      fetchedAt: read?.fetchedAt ?? null,
      note,
      grade: read?.grade ?? null,
      mergePolicy: read === undefined ? null : mergePolicyView(read.mergePolicy),
      cost:
        read?.costTotalUsd === undefined || read.costTotalUsd === null
          ? null
          : { costUsd: read.costTotalUsd, window: 'all_time', note: 'API-equivalent' },
      lanes: states.map((state) => ({
        id: state.lane.id,
        // A lane with no `*_ENABLED` variable is not "unset", which reads as
        // off; it is ungated, which means nothing is holding it. The Fleet tab
        // has the variable name to draw that distinction with and this row does
        // not, so the distinction goes on the wire as its own word.
        switchValue: state.lane.switch === null ? 'ungated' : state.switchValue,
        lastRun: runView(state.lastRun),
        // `null` is "nobody read the pull requests"; a number — zero included —
        // is a measurement. The Monitor renders the first as unknown.
        openPulls: read?.pulls === undefined || read.pulls === null
          ? null
          : (read.pullsByLane.get(state.lane.id)?.length ?? 0),
        cost: read?.cost.get(state.lane.id)?.costUsd ?? null,
        grade: read?.laneGrades.get(state.lane.id) ?? null,
      })),
      pulls: read === undefined ? null : pullViews(read.pulls, read.pullsByLane),
    });
  }

  const snapshot = hub?.snapshot ?? null;
  return {
    roster: rows,
    hub: {
      slug: hub?.slug ?? cfg.fleet.hub,
      readAt: hub?.readAt ?? null,
      note:
        hub?.note ??
        (hub === undefined
          ? 'The hub has not been read. "Import hub roster" reads its registry and its harness scorecard, once, when you ask.'
          : null),
      scorecard:
        snapshot === null
          ? null
          : Object.entries(snapshot.recomputed.scorecard).map(([key, metric]) => ({
              key,
              // A metric with no value is "not measured", and it says so rather
              // than printing a zero the hub never computed.
              value: metric.value === null ? 'unknown' : String(metric.value),
              status: metric.value === null ? 'unknown' : (metric.status ?? 'unknown'),
            })),
    },
    gitfactoryUrl: cfg.fleet.gitfactoryUrl,
  };
}

// ---------------------------------------------------------------------------
// The hand-off
// ---------------------------------------------------------------------------

/**
 * Open this roster in GitFactory.
 *
 * **Building a URL opens no socket; the browser does.** `gitFactoryLink` is
 * pure and its output is asserted *parseable by* gitorio's own `parseDeepLink`
 * — the reader is the contract, and byte-equality with that app's writer is
 * not, because this console carries a `hub=` the writer has no reason to emit.
 * Handing the URL to `openExternal` is where the person's machine takes over,
 * and this extension has nothing further to do with it.
 */
async function doOpenInGitFactory(shell: Zer0Shell, live: LiveCache): Promise<void> {
  const cfg = currentConfig(workspaceFolder());
  const roster = await buildRoster(shell, live.hubImport()?.entries ?? []);
  const url = gitFactoryLink(
    cfg.fleet.gitfactoryUrl,
    cfg.fleet.hub,
    roster.map((site) => site.entry.slug),
    'fleet',
  );
  shell.log.info(`fleet: handing ${roster.length} repositories to GitFactory — ${url}`);
  await vscode.env.openExternal(vscode.Uri.parse(url));
}

// ---------------------------------------------------------------------------
// Picking a lane from the palette
// ---------------------------------------------------------------------------

async function pickLane(filter: (lane: FleetLane) => boolean, placeHolder: string): Promise<string | undefined> {
  const cfg = currentConfig(workspaceFolder());
  const parsed = await readFleetManifest(absPath(cfg, cfg.fleet.manifestPath));
  if (parsed.manifest === null) {
    await notifyWarning(`no fleet manifest (${parsed.reason ?? FLEET_MANIFEST_FILE}).`);
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

/** Every lane, for the three verbs whose eligibility only the gate can answer. */
function anyLane(): boolean {
  return true;
}

// ---------------------------------------------------------------------------
// Registration
// ---------------------------------------------------------------------------

export function registerFleetCommands(shell: Zer0Shell): FleetActions {
  const live = new LiveCache();

  const actions: FleetActions = {
    live: (repo) => live.current(repo),
    refresh: (interactive, repo) => doRefresh(shell, live, interactive, repo),
    toggleSwitch: (laneId) => doToggleSwitch(shell, { lane: laneId }, live),
    dispatchLane: (laneId) => doDispatchLane(shell, { lane: laneId }, live),
    rerunLastFailure: (target) => doRerunLastFailure(shell, target, live),
    cancelNewest: (target) => doCancelNewest(shell, target, live),
    toggleWorkflowFile: (target) => doToggleWorkflowFile(shell, target, live),
    monitor: () => monitorStateFrom(shell, live),
    openInGitFactory: () => doOpenInGitFactory(shell, live),
    importHubRoster: () => doReadHub(shell, live),
  };

  // --- Open the Fleet tab -------------------------------------------------
  // The dashboard boots from the persisted route; an already-open panel is
  // revealed rather than re-routed, which is `DashboardPanel.open()`'s own rule.
  register(shell, 'fleet.open', async () => {
    await shell.context.workspaceState.update(ROUTE_STATE_KEY, 'fleet');
    await vscode.commands.executeCommand('zer0Cms.dashboard');
  });

  // --- Open the Monitor tab -----------------------------------------------
  register(shell, 'monitor.open', async () => {
    await shell.context.workspaceState.update(ROUTE_STATE_KEY, 'monitor');
    await vscode.commands.executeCommand('zer0Cms.dashboard');
  });

  // --- Refresh -------------------------------------------------------------
  // With a `{repo}` target this reads that roster row; with none, the active
  // site. Nothing fans out: a click reads ONE repository — four calls, or five
  // when the row has no checkout and its manifest has to be read too. The
  // fleet's own workspace holds nine manifests, so a button that quietly read
  // them all would make thirty-six requests, which is exactly the ambient
  // traffic decision D11 exists to forbid.
  register(shell, 'fleet.refresh', async (arg: unknown) => {
    const target = repoArgFrom(arg);
    await doRefresh(shell, live, true, target);
    const now = live.current(target);
    if (now !== undefined) {
      await notifyInfo(`fleet: ${now.repo} read at ${now.fetchedAt}.`);
    }
  });

  // --- Toggle a switch -----------------------------------------------------
  register(shell, 'fleet.toggleSwitch', async (arg: unknown) => {
    const target =
      fleetTargetFrom(arg) ??
      laneFromPick(await pickLane((lane) => lane.switch !== null, 'Which lane’s switch?'));
    if (target !== undefined) {
      await doToggleSwitch(shell, target, live);
    }
  });

  // --- Dispatch a lane -----------------------------------------------------
  register(shell, 'fleet.dispatchLane', async (arg: unknown) => {
    const target = fleetTargetFrom(arg) ?? laneFromPick(await pickLane(isDispatchable, 'Which lane to dispatch once?'));
    if (target !== undefined) {
      await doDispatchLane(shell, target, live);
    }
  });

  // --- Re-run the newest failure ------------------------------------------
  register(shell, 'fleet.rerunLastFailure', async (arg: unknown) => {
    const target = fleetTargetFrom(arg) ?? laneFromPick(await pickLane(anyLane, 'Re-run which lane’s newest failure?'));
    if (target !== undefined) {
      await doRerunLastFailure(shell, target, live);
    }
  });

  // --- Cancel what is running ---------------------------------------------
  register(shell, 'fleet.cancelNewest', async (arg: unknown) => {
    const target = fleetTargetFrom(arg) ?? laneFromPick(await pickLane(anyLane, 'Cancel which lane’s newest run?'));
    if (target !== undefined) {
      await doCancelNewest(shell, target, live);
    }
  });

  // --- Enable or disable the workflow file ---------------------------------
  register(shell, 'fleet.toggleWorkflowFile', async (arg: unknown) => {
    const target =
      fleetTargetFrom(arg) ?? laneFromPick(await pickLane(anyLane, 'Enable or disable which lane’s workflow?'));
    if (target !== undefined) {
      await doToggleWorkflowFile(shell, target, live);
    }
  });

  // --- Hand the roster to GitFactory ---------------------------------------
  register(shell, 'fleet.openInGitFactory', async () => {
    await doOpenInGitFactory(shell, live);
  });

  // --- Import the hub's registry -------------------------------------------
  register(shell, 'fleet.importHubRoster', async () => {
    await doReadHub(shell, live);
  });

  return actions;
}

/** `{repo}` on its own — the Monitor's per-row Refresh, which names no lane. */
function repoArgFrom(arg: unknown): string | undefined {
  if (typeof arg === 'object' && arg !== null) {
    const repo = (arg as { repo?: unknown }).repo;
    if (typeof repo === 'string' && repo.trim() !== '') {
      return repo.trim();
    }
  }
  return undefined;
}

/** A quick-pick answer → a target for the active site, or nothing. */
function laneFromPick(laneId: string | undefined): FleetTargetRef | undefined {
  return laneId === undefined ? undefined : { lane: laneId };
}
