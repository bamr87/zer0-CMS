/**
 * The harness commands: read this repository's whole AI machinery, preview what
 * generating a lane would write, and — behind the strictest gate in this
 * directory — write it.
 *
 * **`doScaffoldLane` is the single authoritative gate for the one privileged
 * action here** (decision D5), and it is the strictest of the four pairs in this
 * directory because it writes a *workflow* into a repository: a file that, once
 * its variable exists, spends tokens on a schedule with nobody watching. The
 * dashboard's Workflows tab posts `{type:'command', id:'lane.scaffold',
 * args:{spec:'<lane id>'}}` — a lane id and nothing else. Not the rendered
 * files, not the plan it drew a moment ago, not "the person already read the
 * diff". The host then does all of this, in this order, before a byte lands:
 *
 *   1. **Re-read the configuration.** `currentConfig()` is uncached, and the
 *      master gate `zer0Cms.fleet.scaffoldAllow` is read from the settings
 *      layer alone through `settingsFleetScaffoldAllow()` — a `zer0.json` that
 *      arrived with a clone cannot arm a repository to write its own next
 *      workflow, which is `settingsFleetDispatchAllow`'s reasoning pointed at
 *      the working tree instead of at GitHub. That reader also re-asks
 *      Workspace Trust, so an untrusted folder refuses here without this file
 *      needing a fifth trust check (decision D13).
 *   2. **Re-read the harness inventory and the manifest from disk.** Not the
 *      dashboard's snapshot, not the last preview, not anything a message
 *      carried. The lane's *description* is the one thing a person typed, and
 *      it is re-read from the whitelisted UI state the host itself persisted —
 *      never from the message either.
 *   3. **Plan, once.** `planScaffold` is the single pure computation behind the
 *      palette command, the MCP preview and the modal, so "the modal showed me
 *      something else" is impossible rather than unlikely. `selfAudit` is
 *      passed here and only here: the extension host is the one place allowed
 *      to import the engines seam.
 *   4. **Re-run `evaluateFleetGates('scaffold', …)`** over `scaffoldGateFacts`,
 *      and refuse in the blockers' own words, in the gate's own order.
 *   5. **Ask, modally**, listing every file it would write with its byte count,
 *      the manifest line it would add — and, separately and last, the
 *      `*_ENABLED` variable it is **not** creating.
 *   6. **Write**, exclusively (`wx`), only under the open folder, never over an
 *      existing file, and never at a `factory--*.yml` path.
 *
 * ### The switch is a note, never an action
 *
 * Writing a file somebody then reads, commits and reviews is one power. Arming
 * a lane to run on a schedule is another. This command holds only the first,
 * and the modal says so in as many words: the lane it writes is inert until a
 * person creates its repository variable themselves, somewhere this console
 * cannot reach from the same gesture. Bundling the two is exactly how a
 * generated loop starts running before anyone has read it.
 *
 * ### Two questions, two gates
 *
 * `evaluateFleetGates('scaffold', …)` answers "may this console write here" —
 * the master switch, an id already taken, a file already there, a variable
 * already claimed, a lane the generators refuse. `preflightLaneSpec` (folded
 * into `plan.audit` alongside the engines' rulebook) answers "is this a lane
 * worth writing" — a missing kill switch, a cron on the hour, a token presence
 * chain. Both have to pass, and the second is enforced here rather than in the
 * gate because the gate's blocker order is a pinned contract: a house rule
 * arriving as a sixth scaffold blocker would renumber a list other surfaces
 * render. An `error`-severity finding refuses the write and says which.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import * as vscode from 'vscode';

import {
  DEFAULT_INVENTORY_OPTIONS,
  TEMPLATE_FILES,
  absPath,
  classifyExpressibility,
  describeHarnessInventory,
  detectPlatform,
  evaluateFleetGates,
  fleetBlockerSummary,
  insideWorkspace,
  parseKitVersion,
  planScaffold,
  readHarnessInventory,
  scaffoldGateFacts,
  toRunnerInvocation,
  workflowPathFor,
  type FleetBlocker,
  type FleetGateInput,
  type HarnessInventory,
  type HarnessIo,
  type HarnessProfile,
  type LaneKindVerb,
  type LaneSetup,
  type LaneSpec,
  type PlatformIo,
  type PlatformProfile,
  type ResolvedPlatform,
  type ScaffoldPlan,
  type Zer0Config,
} from '../core';
import { selfAudit } from '../core/harness/selfAudit';
import { currentConfig, settingsFleetScaffoldAllow, workspaceFolder } from '../config';
import type { Zer0Shell } from '../extension';
import { describeError } from '../logger';
import { confirm, notifyError, notifyInfo, notifyWarning } from '../uiState';
import type { HarnessState, LanePassportView, SettingItem, WorkflowsState } from '../webview/shared/protocol';
import { workspaceHarnessIo } from './agent';
import { register } from './project';

/** The workspace-state key the dashboard boots its route from. */
const ROUTE_STATE_KEY = 'zer0Cms:Dashboard:Route';

/**
 * The three functions the dashboard host is handed.
 *
 * It gets the functions rather than the command ids, for the reason
 * `AuditActions` and `FleetActions` do: a surface that wants a lane written has
 * to hold the whole gate, and there is no way to hold a partial one.
 */
export interface HarnessActions {
  /** Read the active site's whole harness from disk. `null` with no folder open. */
  inventory(): Promise<HarnessInventory | null>;
  /** What writing the staged lane would do. Writes nothing. */
  preview(specId: string): Promise<LanePreviewReply>;
  /** Write the staged lane's files, gated and confirmed. `true` if bytes landed. */
  scaffold(specId: string): Promise<boolean>;
}

/**
 * The `lanePreview` request's reply: exactly `WorkflowsState['plan']`, or a
 * refusal in words.
 *
 * Shaped as the slice the webview already knows how to draw, so the host
 * handler is a pass-through and the tab never learns a second vocabulary for
 * the same answer. `switchToCreateLater` travels beside it because it is the
 * one sentence the screen has to be able to put next to the write button, and
 * it is the plan's answer rather than the form's.
 */
export interface LanePreviewReply {
  plan: NonNullable<WorkflowsState['plan']> | null;
  switchToCreateLater: string | null;
  refused: string | null;
}

// ---------------------------------------------------------------------------
// The staged lane description — fourteen keys, all named by the host
// ---------------------------------------------------------------------------

/**
 * The fields a person fills in to describe a lane.
 *
 * They are *the host's* keys: `WorkflowsState.form` offers them, the dashboard
 * host whitelists exactly these in `UI_STATE_KEYS`, and the webview can only
 * ever hand back one it was offered — the Settings route's contract, applied to
 * a form whose values are a draft rather than a setting. Everything else in a
 * `LaneSpec` is derived (see `laneSpecFrom`), because a form with forty rows is
 * a form nobody fills in and half of a lane spec is a consequence of the other
 * half.
 */
export const LANE_FIELDS = [
  'id',
  'kind',
  'verb',
  'description',
  'agent',
  'skill',
  'switch',
  'cron',
  'prompt',
  'tools',
  'resultFile',
  'dispatchBypassesSwitch',
  'timeoutMinutes',
  'model',
] as const;

export type LaneField = (typeof LANE_FIELDS)[number];

/** The protocol key for one field: what the webview posts and the host offers. */
export function laneFieldKey(field: LaneField): string {
  return `Lane:${field}`;
}

/**
 * The staged form's whitelist, in the shape `dashboardPanel.ts`'s
 * `UI_STATE_KEYS` holds: protocol key → workspace-state id.
 *
 * Exported so the host merges one table rather than maintaining a second copy
 * of fourteen names. A key absent from the host's whitelist is a write the host
 * drops with a warning, which is the correct failure — but it is also a form
 * row that silently never saves, so the two lists must come from here.
 */
export const LANE_UI_STATE_KEYS: Readonly<Record<string, string>> = Object.fromEntries(
  LANE_FIELDS.map((field) => [laneFieldKey(field), `zer0Cms:Dashboard:Lane:${field}`]),
);

/** The runner's own tool names, offered as a `multichoice` rather than typed. */
export const LANE_TOOL_CHOICES: readonly string[] = [
  'Bash',
  'Read',
  'Write',
  'Edit',
  'Grep',
  'Glob',
  'WebFetch',
  'WebSearch',
];

/** The seven verbs `LaneKindVerb` allows, as the form's choice list. */
export const LANE_VERBS: readonly LaneKindVerb[] = [
  'create',
  'improve',
  'review',
  'scout',
  'triage',
  'fix',
  'audit',
];

/**
 * The interpreter versions a generated lane asks the runner to set up.
 *
 * Runner facts, not platform facts — which is why they are here and not in a
 * platform profile: the profile says what command serves the site, this says
 * which `setup-*` version the hub's lane should install to be able to run it.
 */
const SETUP_VERSIONS = { ruby: '3.3', node: '20', python: '3.12' } as const;

/** Every field's default, before anything is staged. */
const LANE_DEFAULTS: Readonly<Record<LaneField, string>> = {
  id: '',
  kind: 'content',
  verb: 'create',
  description: '',
  agent: '',
  skill: '',
  switch: '',
  cron: '',
  prompt: '',
  tools: 'Bash, Read, Write, Edit, Grep, Glob',
  resultFile: 'pr-result.txt',
  dispatchBypassesSwitch: 'true',
  timeoutMinutes: '20',
  model: '',
};

/** What each row says about itself, in the form. */
const LANE_LABELS: Readonly<Record<LaneField, { label: string; description: string }>> = {
  id: {
    label: 'Lane id',
    description:
      'Becomes .github/workflows/<id>.yml, the concurrency group and the metering role. Lowercase letters, digits, ".", "_" and "-".',
  },
  kind: {
    label: 'Kind',
    description: 'The manifest\'s own vocabulary — content, maintenance, quality, ops.',
  },
  verb: { label: 'Verb', description: 'What the lane does, in one word.' },
  description: {
    label: 'Description',
    description:
      'One sentence, written for whoever reads the workflow file in a year. It becomes the file\'s opening comment and the manifest entry.',
  },
  agent: {
    label: 'Agent',
    description:
      'The role the runner resolves as .claude/agents/<name>.md. Left blank, the lane id is used.',
  },
  skill: {
    label: 'Skill',
    description:
      'Optional. A stub is written at .claude/skills/<name>/SKILL.md for the routine the agent follows.',
  },
  switch: {
    label: 'Kill switch',
    description:
      'The *_ENABLED repository variable this lane idles behind. Left blank, it is derived from the id. This command never creates the variable.',
  },
  cron: {
    label: 'Schedule (cron)',
    description:
      'Five fields, and never minute :00 — a fleet scheduled on the hour queues behind the rest of GitHub. Required: the preflight refuses a lane with no trigger at all, because nothing but a manual dispatch would ever run it.',
  },
  prompt: {
    label: 'Prompt',
    description:
      'What the agent is told to do. Name the result file in it, or the assertion that makes a crashed run show red fires on every successful one too.',
  },
  tools: { label: 'Tools', description: 'Least privilege: give the lane only what it needs.' },
  resultFile: {
    label: 'Result file',
    description: 'The lane fails when this file is empty — that is how a crashed agent shows red.',
  },
  dispatchBypassesSwitch: {
    label: 'A manual run bypasses the switch',
    description:
      'The shared lane always lets workflow_dispatch through. Turning this off means the gate has to be written out by hand.',
  },
  timeoutMinutes: {
    label: 'Timeout (minutes)',
    description: 'A lane with no timeout is a lane that can bill for six hours.',
  },
  model: {
    label: 'Model',
    description: 'Blank inherits whatever the runner and the repository already agree on.',
  },
};

/** `content-review` → `CONTENT_REVIEW_ENABLED`. The fleet's own naming, exactly. */
export function defaultSwitchFor(laneId: string): string {
  const stem = laneId
    .trim()
    .replace(/[^A-Za-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .toUpperCase();
  return stem === '' ? '' : `${stem}_ENABLED`;
}

/**
 * Which runtime the lane has to set up, read out of the platform profile's own
 * serve/build command rather than switched on the platform id.
 *
 * `bundle exec jekyll serve` needs Ruby; `mkdocs serve` needs Python; `npm run
 * dev` needs Node. Reading the tool name keeps the one platform-specific fact
 * where decision D12 put it — in the profile — instead of growing a second
 * table here that would disagree with it the first time a profile changed.
 */
export function laneSetupFor(profile: PlatformProfile): LaneSetup {
  const argv = [...(profile.commands.serve ?? []), ...(profile.commands.build ?? [])];
  const tool = argv.find((word) => /^(bundle|gem|ruby|mkdocs|pip|python3?|npm|npx|node|yarn|pnpm)$/.test(word));
  switch (tool) {
    case 'bundle':
    case 'gem':
    case 'ruby':
      return { ruby: SETUP_VERSIONS.ruby, node: null, python: null };
    case 'mkdocs':
    case 'pip':
    case 'python':
    case 'python3':
      return { ruby: null, node: null, python: SETUP_VERSIONS.python };
    case 'npm':
    case 'npx':
    case 'node':
    case 'yarn':
    case 'pnpm':
      return { ruby: null, node: SETUP_VERSIONS.node, python: null };
    default:
      // A profile that declares no commands (the generic fallback, and Wiki.js
      // with git storage) gets no `setup-*` input at all, which is right: the
      // hub's lane installs nothing it was not asked to.
      return { ruby: null, node: null, python: null };
  }
}

/** The staged value of one field, or its default. Read from workspace state. */
function stagedField(shell: Zer0Shell, field: LaneField): string {
  const id = LANE_UI_STATE_KEYS[laneFieldKey(field)];
  const value = id === undefined ? undefined : shell.context.workspaceState.get<unknown>(id);
  return typeof value === 'string' && value.trim() !== '' ? value.trim() : LANE_DEFAULTS[field];
}

/** The form the host offers, with the staged values already in it. */
export function laneFormItems(shell: Zer0Shell): SettingItem[] {
  return LANE_FIELDS.map((field): SettingItem => {
    const raw = stagedField(shell, field);
    const copy = LANE_LABELS[field];
    const base = { key: laneFieldKey(field), label: copy.label, description: copy.description };
    switch (field) {
      case 'verb':
        return { ...base, kind: 'choice', value: raw, choices: [...LANE_VERBS] };
      case 'tools':
        return { ...base, kind: 'multichoice', value: raw, choices: [...LANE_TOOL_CHOICES] };
      case 'resultFile':
        return { ...base, kind: 'path', value: raw };
      case 'dispatchBypassesSwitch':
        return { ...base, kind: 'boolean', value: raw === 'true' };
      case 'timeoutMinutes':
        return { ...base, kind: 'number', value: Number(raw) };
      default:
        return { ...base, kind: 'string', value: raw };
    }
  });
}

function asVerb(value: string): LaneKindVerb {
  return (LANE_VERBS as readonly string[]).includes(value) ? (value as LaneKindVerb) : 'create';
}

function asTools(value: string): string[] {
  const tools = value
    .split(',')
    .map((part) => part.trim())
    .filter((part) => part !== '');
  return tools.length === 0 ? ['Read'] : tools;
}

/**
 * The staged description, plus everything a lane needs that follows from it.
 *
 * Derived rather than asked: the project name (the manifest's repository, else
 * the folder), the platform (detected once, decision D12), the runtime setup
 * (from the profile's own commands), the manifest's `permissions` pair, and the
 * system prompt. `matrix`, `crossRepoCheckout`, `prHeadCheckout` and
 * `modelPasses` are fixed at the values that keep a generated lane expressible
 * — a person who needs any of them needs a hand-written workflow, and
 * `classifyExpressibility` says so in words rather than this form pretending to
 * offer them.
 */
export function laneSpecFrom(
  shell: Zer0Shell,
  cfg: Zer0Config,
  profile: PlatformProfile,
  inventory: HarnessInventory | null,
  kitVersion: string,
): LaneSpec {
  const id = stagedField(shell, 'id');
  const agent = stagedField(shell, 'agent') || id;
  const skill = stagedField(shell, 'skill');
  const description = stagedField(shell, 'description');
  const switchName = stagedField(shell, 'switch') || defaultSwitchFor(id);
  const cron = stagedField(shell, 'cron');
  const model = stagedField(shell, 'model');
  const projectName =
    inventory?.manifest.manifest?.repo ??
    (cfg.workspaceRoot === '' ? 'this repository' : path.basename(cfg.workspaceRoot));
  const timeout = Number(stagedField(shell, 'timeoutMinutes'));

  return {
    id,
    kind: stagedField(shell, 'kind'),
    verb: asVerb(stagedField(shell, 'verb')),
    description,
    agent,
    skill: skill === '' ? null : skill,
    projectName,
    platform: profile.id,
    switch: switchName === '' ? null : switchName,
    dispatchBypassesSwitch: stagedField(shell, 'dispatchBypassesSwitch') === 'true',
    cron: cron === '' ? null : cron,
    events: [],
    prompt: stagedField(shell, 'prompt'),
    system:
      description === ''
        ? `You are the ${agent} agent for ${projectName}. Do exactly one unit of work, open one pull request, and never merge.`
        : `You are the ${agent} agent for ${projectName}. ${description}`,
    tools: asTools(stagedField(shell, 'tools')),
    mcp: null,
    model: model === '' ? null : model,
    maxTurns: null,
    setup: laneSetupFor(profile),
    preRun: null,
    postRun: null,
    resultFile: stagedField(shell, 'resultFile'),
    artifactPath: null,
    timeoutMinutes: Number.isFinite(timeout) && timeout > 0 ? Math.trunc(timeout) : 20,
    cancelInProgress: false,
    continueOnError: false,
    permissions: { contents: 'write', 'pull-requests': 'write' },
    matrix: null,
    crossRepoCheckout: false,
    prHeadCheckout: false,
    modelPasses: 1,
    labels: [],
    branchPattern: null,
    kitVersion,
  };
}

// ---------------------------------------------------------------------------
// Reading the harness, and the templates the generators render from
// ---------------------------------------------------------------------------

/**
 * Platform detection reads marker files under the root — the same two methods
 * `src/commands/audit.ts` hands it, over `node:fs` because the harness reader
 * beside it is `node:fs` too and one folder should not be read two ways.
 */
function platformIo(root: string): PlatformIo {
  return {
    exists: async (rel) => {
      try {
        await fs.access(path.resolve(root, rel));
        return true;
      } catch {
        // Missing or unreadable: either way this marker is not evidence.
        return false;
      }
    },
    read: async (rel) => {
      try {
        return await fs.readFile(path.resolve(root, rel), 'utf8');
      } catch {
        return undefined;
      }
    },
  };
}

/** The active site's folder, its configuration and an I/O over its root. */
interface HarnessContext {
  cfg: Zer0Config;
  io: HarnessIo;
  platform: ResolvedPlatform;
  profile: PlatformProfile;
}

/**
 * Everything the two read paths share, resolved fresh.
 *
 * The platform is **detected**, not taken from the store's snapshot: this file
 * is the one that decides what a generated lane sets up, and a profile carried
 * in a snapshot is a profile somebody else read at some other time.
 */
async function harnessContext(): Promise<HarnessContext | undefined> {
  const folder = workspaceFolder();
  const cfg = currentConfig(folder);
  if (cfg.workspaceRoot === '') {
    return undefined;
  }
  const platform = await detectPlatform(cfg.workspaceRoot, platformIo(cfg.workspaceRoot), cfg.platform);
  return {
    cfg,
    io: workspaceHarnessIo(cfg.workspaceRoot),
    platform,
    profile: platform.profile,
  };
}

/** Everything on disk, joined. Reads files; opens no socket; writes nothing. */
export async function readInventory(shell: Zer0Shell): Promise<HarnessInventory | null> {
  const ctx = await harnessContext();
  if (ctx === undefined) {
    return null;
  }
  const inventory = await readHarnessInventory(ctx.cfg.workspaceRoot, ctx.io, {
    ...DEFAULT_INVENTORY_OPTIONS,
    manifestPath: ctx.cfg.fleet.manifestPath,
    aiConfigPath: ctx.cfg.cms.aiConfigPath,
  });
  shell.log.verbose(`harness: ${ctx.cfg.workspaceRoot} — ${describeHarnessInventory(inventory)}`);
  return inventory;
}

/** The vendored caller template, the agent template and the kit version. */
interface Templates {
  template: string;
  agentTemplate: string;
  kitVersion: string;
}

/**
 * The three shipped files under `media/templates/`, read from the extension's
 * own install directory.
 *
 * They are shipped rather than fetched, and read rather than inlined, for the
 * same reason the stamp is read from the VERSION file: a refreshed template and
 * a stale constant would disagree in the one place a person looks to find out
 * what generated a workflow.
 */
async function templates(shell: Zer0Shell): Promise<Templates | { refused: string }> {
  try {
    const [template, agentTemplate, version] = await Promise.all([
      fs.readFile(shell.context.asAbsolutePath(TEMPLATE_FILES.aiLane), 'utf8'),
      fs.readFile(shell.context.asAbsolutePath(TEMPLATE_FILES.agent), 'utf8'),
      fs.readFile(shell.context.asAbsolutePath(TEMPLATE_FILES.version), 'utf8'),
    ]);
    const kitVersion = parseKitVersion(version);
    if (kitVersion === null) {
      return { refused: `${TEMPLATE_FILES.version} declares no version` };
    }
    return { template, agentTemplate, kitVersion };
  } catch (error) {
    return {
      refused: `the lane templates are not installed (${describeError(error)}) — ${TEMPLATE_FILES.aiLane} ships with the extension`,
    };
  }
}

// ---------------------------------------------------------------------------
// The plan — one computation, three callers
// ---------------------------------------------------------------------------

/** Everything a plan needs, all of it read fresh from disk for this action. */
interface PlanContext {
  cfg: Zer0Config;
  spec: LaneSpec;
  plan: ScaffoldPlan;
  manifestText: string | undefined;
  manifestRel: string;
  inventory: HarnessInventory;
  scaffoldAllow: boolean;
}

/**
 * Re-read everything and plan. `withAudit` is `false` only for a preview that
 * a person did not ask to write anything from; the modal's plan always carries
 * the engines' verdict on the files it is about to show.
 */
async function collectPlan(
  shell: Zer0Shell,
  specId: string,
): Promise<PlanContext | { refused: string }> {
  // 1 — the configuration, uncached, and the master gate from the settings
  //     layer alone (which re-asks Workspace Trust for us).
  const ctx = await harnessContext();
  if (ctx === undefined) {
    return { refused: 'no workspace folder is open' };
  }
  const { cfg, io } = ctx;
  const scaffoldAllow = settingsFleetScaffoldAllow(workspaceFolder()) === true;

  const files = await templates(shell);
  if ('refused' in files) {
    return files;
  }

  // 2 — the inventory and the manifest, from disk, for this action.
  const manifestRel = cfg.fleet.manifestPath;
  const [inventory, manifestText] = await Promise.all([
    readHarnessInventory(cfg.workspaceRoot, io, {
      ...DEFAULT_INVENTORY_OPTIONS,
      manifestPath: manifestRel,
      aiConfigPath: cfg.cms.aiConfigPath,
    }),
    io.read(manifestRel),
  ]);

  const spec = laneSpecFrom(shell, cfg, ctx.profile, inventory, files.kitVersion);
  if (spec.id === '') {
    return { refused: 'describe the lane first — it has no id yet' };
  }
  // The message named a lane; the host derived one from its own persisted
  // state. When they disagree the person edited the form after clicking, and
  // acting on either answer would be acting on something nobody asked for.
  if (specId !== spec.id) {
    return {
      refused: `the staged form now describes "${spec.id}", not "${specId}" — preview it again before writing`,
    };
  }

  // 3 — one plan. `selfAudit` is injected here and nowhere the MCP bundle can
  //     reach: the engines seam is admitted to `dist/extension.js` alone.
  const plan = await planScaffold(spec, {
    template: files.template,
    agentTemplate: files.agentTemplate,
    manifestText,
    manifestRel,
    existing: (rel) => io.read(rel),
    audit: selfAudit,
  });

  return { cfg, spec, plan, manifestText, manifestRel, inventory, scaffoldAllow };
}

/** The gate's input, built from the plan so nothing is re-derived by hand. */
function scaffoldGateInput(ctx: PlanContext): FleetGateInput {
  return {
    workspaceRoot: ctx.cfg.workspaceRoot,
    enabled: ctx.cfg.fleet.enabled,
    // Irrelevant in scaffold mode — writing a file needs no dispatch gate and
    // no credential — but `FleetGateInput` is one shape for three modes.
    dispatchAllow: false,
    hasCredential: false,
    manifest: ctx.inventory.manifest.manifest,
    ...(ctx.inventory.manifest.reason === undefined
      ? {}
      : { manifestReason: ctx.inventory.manifest.reason }),
    laneId: ctx.spec.id,
    scaffoldAllow: ctx.scaffoldAllow,
    scaffold: scaffoldGateFacts(ctx.spec, ctx.plan, ctx.manifestText),
  };
}

/** The blockers, in the gate's own order, for the advisory slice and the gate. */
export function scaffoldBlockersFor(ctx: PlanContext): FleetBlocker[] {
  return evaluateFleetGates('scaffold', scaffoldGateInput(ctx));
}

/**
 * A one-file diff, rendered the way `diffView` colours it: `#` is a header,
 * `+` an added line, `-` a removed one.
 *
 * A file that does not exist yet is *all* addition, and saying so beats showing
 * a hunk with no context: the whole point of this preview is that a person
 * reads every line a generator wrote before it lands.
 */
export function laneDiff(rel: string, before: string | undefined, after: string): string {
  const head = before === undefined ? `# new file: ${rel}` : `# ${rel} (already exists)`;
  if (before === undefined) {
    return [head, ...after.replace(/\n$/, '').split('\n').map((line) => `+${line}`)].join('\n');
  }
  const oldLines = before.replace(/\n$/, '').split('\n');
  const newLines = after.replace(/\n$/, '').split('\n');
  let prefix = 0;
  while (prefix < oldLines.length && prefix < newLines.length && oldLines[prefix] === newLines[prefix]) {
    prefix += 1;
  }
  let suffix = 0;
  while (
    suffix < oldLines.length - prefix &&
    suffix < newLines.length - prefix &&
    oldLines[oldLines.length - 1 - suffix] === newLines[newLines.length - 1 - suffix]
  ) {
    suffix += 1;
  }
  return [
    head,
    `# ${prefix} unchanged line(s) above, ${suffix} below`,
    ...oldLines.slice(prefix, oldLines.length - suffix).map((line) => `-${line}`),
    ...newLines.slice(prefix, newLines.length - suffix).map((line) => `+${line}`),
  ].join('\n');
}

/** The plan as the Workflows tab draws it: shape, reasons, diffs, findings. */
export function planView(ctx: PlanContext): NonNullable<WorkflowsState['plan']> {
  const files = ctx.plan.files.map((file) => ({
    rel: file.rel,
    exists: file.exists,
    diff: laneDiff(file.rel, file.exists ? '' : undefined, file.contents),
  }));
  if (ctx.plan.manifest !== null) {
    files.push({
      rel: ctx.plan.manifest.rel,
      exists: true,
      diff: laneDiff(ctx.plan.manifest.rel, ctx.plan.manifest.before, ctx.plan.manifest.after),
    });
  }
  return {
    shape: ctx.plan.shape,
    reasons: ctx.plan.reasons,
    files,
    audit: ctx.plan.audit.map((finding) => ({
      rule: finding.rule,
      severity: finding.severity,
      message: finding.path === null ? finding.message : `${finding.path}: ${finding.message}`,
    })),
  };
}

/** A one-line summary of a plan, for the output channel. */
export function describeScaffoldPlan(plan: ScaffoldPlan): string {
  const errors = plan.audit.filter((f) => f.severity === 'error' || f.severity === 'fail').length;
  return (
    `${plan.shape} · ${plan.files.length} file(s) (${plan.files.map((f) => f.rel).join(', ') || 'none'}) · ` +
    `${errors} blocking finding(s)` +
    (plan.switchToCreateLater === null ? '' : ` · switch ${plan.switchToCreateLater} NOT created`)
  );
}

/**
 * The `lanePreview` request: what a scaffold would write, and nothing else.
 *
 * It goes through the same `planScaffold` the write does, which is what makes
 * "the preview showed me something else" impossible rather than unlikely. It
 * writes nothing, and it decides nothing — `doScaffoldLane` re-derives all of
 * this from scratch.
 */
export async function lanePreview(shell: Zer0Shell, specId: string): Promise<LanePreviewReply> {
  const ctx = await collectPlan(shell, specId);
  if ('refused' in ctx) {
    return { plan: null, switchToCreateLater: null, refused: ctx.refused };
  }
  shell.log.verbose(`lane preview: ${ctx.spec.id} — ${describeScaffoldPlan(ctx.plan)}`);
  return {
    plan: planView(ctx),
    switchToCreateLater: ctx.plan.switchToCreateLater,
    refused: null,
  };
}

// ---------------------------------------------------------------------------
// The gate
// ---------------------------------------------------------------------------

async function refuse(shell: Zer0Shell, message: string): Promise<false> {
  shell.log.warn(`lane scaffold: ${message}`);
  await notifyError(`Write lane blocked: ${message}.`);
  return false;
}

/** Findings a lane should not be written over. `error` and `fail` both count. */
function blockingFindings(plan: ScaffoldPlan): string[] {
  return plan.audit
    .filter((finding) => finding.severity === 'error' || finding.severity === 'fail')
    .map((finding) => `${finding.rule}: ${finding.message}`);
}

/**
 * Write one lane's files into the open folder, or say in words why it will not.
 *
 * The ordering in this file's header is the whole design; the two things worth
 * repeating at the write itself are these. Every path is checked to resolve
 * **inside** the workspace root, whichever layer supplied it, because a
 * workflow path is a string and `../` is a string too. And every file is
 * written with the exclusive `wx` flag, so a file that appeared between the plan
 * and the write costs a refusal rather than somebody's lane.
 */
export async function doScaffoldLane(shell: Zer0Shell, specId: string): Promise<boolean> {
  const ctx = await collectPlan(shell, specId);
  if ('refused' in ctx) {
    return refuse(shell, ctx.refused);
  }
  const { cfg, spec, plan } = ctx;

  // 4 — the gate, in its own order, in its own words.
  const blockers = scaffoldBlockersFor(ctx);
  if (blockers.length > 0) {
    return refuse(shell, fleetBlockerSummary(blockers));
  }

  // 4b — the house rules. The gate says whether this console may write here;
  //      the preflight and the engines' rulebook say whether this is a lane
  //      worth writing. A missing kill switch lands here, and it is the one
  //      finding this command exists to refuse.
  const fatal = blockingFindings(plan);
  if (fatal.length > 0) {
    return refuse(shell, `the lane does not pass its own audit — ${fatal.join('; ')}`);
  }

  if (plan.files.length === 0) {
    return refuse(shell, 'the plan would write nothing');
  }

  // 4c — every path, resolved and checked. `exists` is the plan's advisory;
  //      the `wx` flag below is the decision.
  for (const file of plan.files) {
    if (/(^|\/)factory--/.test(file.rel)) {
      return refuse(
        shell,
        `${file.rel} is GitFactory's compiled output — this console does not own the compiler's files`,
      );
    }
    if (!insideWorkspace(cfg.workspaceRoot, path.resolve(cfg.workspaceRoot, file.rel))) {
      return refuse(shell, `${file.rel} resolves outside ${cfg.workspaceRoot}`);
    }
    if (file.exists) {
      return refuse(shell, `${file.rel} already exists — rename the lane or edit that file directly`);
    }
  }

  // 5 — the human, modally: every file, then the manifest line, then — last
  //     and on its own — the variable this action is NOT creating.
  const lines: string[] = [
    `Repository: ${ctx.inventory.manifest.manifest?.repo ?? spec.projectName}`,
    `Lane: ${spec.id} (${spec.kind}, ${spec.verb}) — shape ${plan.shape}`,
    `Agent: ${spec.agent}${spec.skill === null ? '' : ` · skill ${spec.skill}`}`,
    `Trigger: ${spec.cron === null ? 'workflow_dispatch only' : `cron "${spec.cron}" plus workflow_dispatch`}`,
    '',
    `Files to write (${plan.files.length}), none of which exists:`,
    ...plan.files.map((file) => `  ${file.rel} (${file.contents.length} bytes)`),
  ];
  if (plan.manifest !== null) {
    lines.push('', `Manifest: appends the lane to ${plan.manifest.rel}, before its \`tokens:\` block.`);
  } else {
    lines.push('', `Manifest: ${ctx.manifestRel} is not there, so no lane entry is appended.`);
  }
  const warnings = plan.audit.filter((finding) => finding.severity === 'warning');
  if (warnings.length > 0) {
    lines.push('', `Warnings (${warnings.length}):`, ...warnings.map((w) => `  ${w.rule}: ${w.message}`));
  }
  lines.push(
    '',
    plan.switchToCreateLater === null
      ? // Unreachable while the preflight's missing-switch finding is an error:
        // step 4b refuses before this. Cheap insurance if that ever changes.
        'NOT created: this lane declares no kill switch at all, so nothing would be able to stop it.'
      : `NOT created: the repository variable ${plan.switchToCreateLater}. This writes files only. ` +
          `The lane stays inert until you create that variable yourself — writing a file somebody reviews ` +
          `and arming a loop to run are different powers, and this console holds only the first.`,
    'Nothing is committed, pushed or merged. Read the files, then commit them yourself.',
  );

  const ok = await confirm(
    `Write ${plan.files.length} file(s) for lane "${spec.id}"?`,
    'Write the files',
    lines.join('\n'),
  );
  if (!ok) {
    shell.log.verbose(`lane scaffold declined for ${spec.id}`);
    return false;
  }

  // 6 — the write. Exclusive, one file at a time, and the manifest last so a
  //     failure never leaves a manifest declaring a lane whose file is absent.
  const written: string[] = [];
  for (const file of plan.files) {
    const abs = path.resolve(cfg.workspaceRoot, file.rel);
    try {
      await fs.mkdir(path.dirname(abs), { recursive: true });
      await fs.writeFile(abs, file.contents, { encoding: 'utf8', flag: 'wx' });
    } catch (error) {
      return refuse(
        shell,
        `${file.rel} could not be written (${describeError(error)}) — ${written.length} file(s) already landed: ${written.join(', ') || 'none'}`,
      );
    }
    written.push(file.rel);
  }

  if (plan.manifest !== null) {
    const manifestAbs = absPath(cfg, plan.manifest.rel);
    try {
      // The manifest is the one file this action rewrites rather than creates,
      // so its bytes are re-read and compared with the ones the plan was built
      // from. A manifest that moved under us is a refusal, not a merge.
      const current = await fs.readFile(manifestAbs, 'utf8');
      if (current !== plan.manifest.before) {
        return refuse(
          shell,
          `${plan.manifest.rel} changed while you were reading the plan — the ${written.length} lane file(s) were written; re-run to append the manifest entry`,
        );
      }
      await fs.writeFile(manifestAbs, plan.manifest.after, 'utf8');
      written.push(plan.manifest.rel);
    } catch (error) {
      return refuse(
        shell,
        `${plan.manifest.rel} could not be updated (${describeError(error)}) — the lane files were written`,
      );
    }
  }

  shell.log.info(`lane scaffold: wrote ${written.join(', ')} for lane ${spec.id} (${plan.shape})`);
  const answer = await notifyInfo(
    `Wrote ${written.length} file(s) for "${spec.id}". ` +
      (plan.switchToCreateLater === null
        ? 'The lane is inert.'
        : `The lane is inert until ${plan.switchToCreateLater} exists as a repository variable — this console did not create it.`),
    'Open the workflow',
  );
  if (answer === 'Open the workflow') {
    // Found by path rather than taken as `files[0]`: which file the planner
    // happens to push first is not something this file should depend on.
    const workflow = plan.files.find((file) => file.rel.startsWith('.github/workflows/'));
    if (workflow !== undefined) {
      await vscode.window.showTextDocument(
        vscode.Uri.file(path.resolve(cfg.workspaceRoot, workflow.rel)),
      );
    }
  }
  return true;
}

// ---------------------------------------------------------------------------
// The two view slices
// ---------------------------------------------------------------------------

/**
 * `HarnessInventory` → `HarnessState`.
 *
 * It lives beside the command rather than in the dashboard host because two
 * things in it are derivations rather than copies — the profile's runner line,
 * which is the *same* projection `agent.runAsRole`'s "Copy the CI equivalent"
 * offers, and the ledger's one honest number — and a second copy of either
 * would be a second answer to the same question.
 *
 * Tokens reach the screen as names, here as everywhere: the manifest names
 * them, the console shows names, and no surface in this extension reads a
 * secret's value.
 */
export function harnessStateFrom(
  inventory: HarnessInventory,
  profile: HarnessProfile | null,
): HarnessState {
  return {
    readAt: inventory.readAt,
    agents: inventory.agents.map((agent) => ({
      name: agent.name,
      path: agent.path,
      description: agent.description,
      tools: agent.tools,
      model: agent.model,
      dialect: agent.dialect,
    })),
    skills: [...inventory.skills],
    workflows: inventory.workflows.map((workflow) => ({
      path: workflow.path,
      name: workflow.name,
      runnerShape: workflow.runnerShape,
      switches: workflow.switches,
      crons: workflow.crons,
      dispatchBypassesSwitch: workflow.dispatchBypassesSwitch,
    })),
    joins: [...inventory.joins],
    findings: inventory.findings.map((finding) => ({
      kind: finding.kind,
      severity: finding.severity,
      path: finding.path,
      message: finding.message,
    })),
    ledger:
      inventory.ledger === null
        ? null
        : {
            path: inventory.ledger.path,
            last7dUsd: inventory.ledger.last7dUsd,
            unit: inventory.ledger.unit,
          },
    profile:
      profile === null
        ? null
        : {
            model: profile.model,
            modelSource: profile.modelSource,
            agent: profile.agent?.name ?? null,
            mcpServers: Object.keys(profile.mcpServers),
            settingSources: [...profile.settingSources],
            runnerLine: toRunnerInvocation(profile, '<the prompt>').argv.join(' '),
          },
  };
}

/**
 * One lane's passport, read out of the manifest and the workflow that
 * implements it — plus whether the generators could express it again.
 *
 * Read-only by decision D-I. The expressibility column is not an offer to
 * regenerate anything; it is the honest answer to "could this console have
 * written this?", and for the bespoke lanes in this fleet the reasons are the
 * useful half. lifehacker's content-review lane is the example worth keeping in
 * mind: approximating it would silently drop the loop-breaker guard that
 * repository had to add after an infinite-retrigger bug.
 */
export function lanePassportsFrom(inventory: HarnessInventory, kitVersion: string): LanePassportView[] {
  const manifest = inventory.manifest.manifest;
  if (manifest === null) {
    return [];
  }
  const byPath = new Map(inventory.workflows.map((workflow) => [workflow.path, workflow]));
  return manifest.lanes.map((lane): LanePassportView => {
    const workflow = lane.implementation === '' ? undefined : byPath.get(lane.implementation);
    const spec: LaneSpec = {
      ...blankSpec(kitVersion),
      id: lane.id,
      kind: lane.kind,
      description: lane.description,
      agent: workflow?.agentRefs[0] ?? lane.id,
      switch: lane.switch,
      dispatchBypassesSwitch: workflow?.dispatchBypassesSwitch ?? true,
      cron: workflow?.crons[0] ?? null,
      events: workflow?.events ?? [],
      resultFile: workflow?.resultFile ?? '',
      matrix:
        workflow?.matrix === 'dynamic'
          ? { dynamic: true }
          : workflow?.matrix === 'static'
            ? { static: ['(as the workflow declares)'] }
            : null,
    };
    const { shape, reasons } = classifyExpressibility(spec);
    return {
      id: lane.id,
      workflowPath: lane.implementation === '' ? null : lane.implementation,
      runnerShape: workflow?.runnerShape ?? 'none',
      switch: lane.switch,
      dispatchBypassesSwitch: workflow?.dispatchBypassesSwitch ?? null,
      cron: workflow?.crons[0] ?? null,
      tokens: lane.usesTokens,
      resultFile: workflow?.resultFile ?? null,
      expressibility: shape,
      expressibilityReasons: reasons,
      // No network at activation, and none from opening a tab (D11).
      runs: null,
    };
  });
}

/** A spec with every optional answered, for classifying an existing lane. */
function blankSpec(kitVersion: string): LaneSpec {
  return {
    id: '',
    kind: '',
    verb: 'create',
    description: '',
    agent: '',
    skill: null,
    projectName: '',
    platform: 'generic',
    switch: null,
    dispatchBypassesSwitch: true,
    cron: null,
    events: [],
    prompt: '',
    system: '',
    tools: [],
    mcp: null,
    model: null,
    maxTurns: null,
    setup: { ruby: null, node: null, python: null },
    preRun: null,
    postRun: null,
    resultFile: '',
    artifactPath: null,
    timeoutMinutes: 20,
    cancelInProgress: false,
    continueOnError: false,
    permissions: {},
    matrix: null,
    crossRepoCheckout: false,
    prHeadCheckout: false,
    modelPasses: 1,
    labels: [],
    branchPattern: null,
    kitVersion,
  };
}

/**
 * The blockers a disabled Write button carries — the gate's own evaluation, run
 * against what is on disk right now.
 *
 * Advisory, and it says so: `doScaffoldLane` re-reads everything and runs the
 * same gate again, and an exclusive (`wx`) write is what actually decides
 * whether a file was already there. What this buys is a button that is greyed
 * out for the right reason before anybody clicks it. `spec.id === ''` is the
 * "nothing described yet" state, and it is a blocker with a sentence rather
 * than an enabled button that would refuse a moment later.
 */
async function advisoryScaffoldBlockers(
  ctx: HarnessContext,
  inventory: HarnessInventory,
  spec: LaneSpec,
  scaffoldAllow: boolean,
): Promise<FleetBlocker[]> {
  if (spec.id === '') {
    return [{ kind: 'laneUnknown', message: 'describe the lane first — it has no id yet' }];
  }
  const workflowPath = workflowPathFor(spec);
  const manifest = inventory.manifest.manifest;
  const { shape, reasons } = classifyExpressibility(spec);
  return evaluateFleetGates('scaffold', {
    workspaceRoot: ctx.cfg.workspaceRoot,
    enabled: ctx.cfg.fleet.enabled,
    dispatchAllow: false,
    hasCredential: false,
    manifest,
    ...(inventory.manifest.reason === undefined
      ? {}
      : { manifestReason: inventory.manifest.reason }),
    laneId: spec.id,
    scaffoldAllow,
    scaffold: {
      laneId: spec.id,
      workflowPath,
      workflowExists: (await ctx.io.read(workflowPath)) !== undefined,
      switchName: spec.switch,
      switchTaken:
        spec.switch !== null &&
        manifest !== null &&
        manifest.lanes.some((lane) => lane.id !== spec.id && lane.switch === spec.switch),
      notExpressibleReasons: shape === 'bespoke' ? reasons : [],
    },
  });
}

/**
 * The Workflows slice: the lane catalogue, the staged form, and the advisory
 * blockers in the gate's own order.
 *
 * `plan` is deliberately `null`. Rendering a plan into every snapshot would
 * mean planning a lane nobody asked about on every watcher-driven rebuild; the
 * tab asks for one with the `lanePreview` request when a person presses
 * Preview, exactly as the Audit tab asks for a fix preview.
 */
export async function workflowsStateFrom(shell: Zer0Shell): Promise<WorkflowsState | null> {
  const ctx = await harnessContext();
  if (ctx === undefined) {
    return null;
  }
  const files = await templates(shell);
  const kitVersion = 'refused' in files ? '' : files.kitVersion;
  const inventory = await readHarnessInventory(ctx.cfg.workspaceRoot, ctx.io, {
    ...DEFAULT_INVENTORY_OPTIONS,
    manifestPath: ctx.cfg.fleet.manifestPath,
    aiConfigPath: ctx.cfg.cms.aiConfigPath,
  });
  const folder = workspaceFolder();
  const scaffoldAllow = settingsFleetScaffoldAllow(folder) === true;
  const spec = laneSpecFrom(shell, ctx.cfg, ctx.profile, inventory, kitVersion);
  const blockers = await advisoryScaffoldBlockers(ctx, inventory, spec, scaffoldAllow);

  return {
    lanes: lanePassportsFrom(inventory, kitVersion),
    form: laneFormItems(shell),
    kitVersion,
    scaffoldAllow,
    scaffoldBlockers: blockers.map((blocker) => ({ kind: blocker.kind, message: blocker.message })),
    plan: null,
  };
}

// ---------------------------------------------------------------------------
// Arguments — a spec id, and nothing else
// ---------------------------------------------------------------------------

/** `{spec}` from a webview, a bare string from the palette, or nothing. */
export function specIdFrom(arg: unknown): string | undefined {
  if (typeof arg === 'string') {
    return arg.trim() === '' ? undefined : arg.trim();
  }
  if (typeof arg === 'object' && arg !== null) {
    const value = (arg as { spec?: unknown }).spec;
    if (typeof value === 'string' && value.trim() !== '') {
      return value.trim();
    }
  }
  return undefined;
}

// ---------------------------------------------------------------------------
// Registration
// ---------------------------------------------------------------------------

/** Reveal one of the two tabs, exactly as `fleet.open` does. */
async function openRoute(shell: Zer0Shell, route: 'harness' | 'workflows'): Promise<void> {
  await shell.context.workspaceState.update(ROUTE_STATE_KEY, route);
  await vscode.commands.executeCommand('zer0Cms.dashboard');
}

export function registerHarnessCommands(shell: Zer0Shell): HarnessActions {
  const actions: HarnessActions = {
    inventory: () => readInventory(shell),
    preview: (specId) => lanePreview(shell, specId),
    scaffold: (specId) => doScaffoldLane(shell, specId),
  };

  // --- Open the Harness tab (and say what it found) ------------------------
  register(shell, 'harness.open', async () => {
    const inventory = await readInventory(shell);
    if (inventory === null) {
      await notifyWarning('open a folder before reading its harness.');
      return;
    }
    shell.log.info(`harness: ${describeHarnessInventory(inventory)}`);
    await openRoute(shell, 'harness');
  });

  // --- Open the lane catalogue --------------------------------------------
  register(shell, 'workflows.open', async () => {
    await openRoute(shell, 'workflows');
  });

  // --- Write a lane -------------------------------------------------------
  // The palette has no form in front of it, so it names the lane the staged
  // description currently describes and lets the gate refuse if that is empty.
  register(shell, 'lane.scaffold', async (arg: unknown) => {
    const specId = specIdFrom(arg) ?? stagedField(shell, 'id');
    if (specId === '') {
      await notifyWarning(
        'no lane is described yet — open the Workflows tab and fill in the lane form first.',
      );
      return;
    }
    await doScaffoldLane(shell, specId);
  });

  return actions;
}

