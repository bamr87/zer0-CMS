/**
 * One harness vocabulary, projected two ways (decision D-F).
 *
 * This extension runs an agent in the editor through the Claude Agent SDK; the
 * fleet runs the same roles in CI through the hub's `claude-run` action, which
 * reads `_data/ai.yml` and `.claude/agents/<name>.md`. Until this module they
 * shared no vocabulary at all: the editor did not know the repository's agents,
 * did not read its AI configuration, and defaulted to a model its own CI does
 * not use. "Run this as the grow-lifehacker role" was possible in CI and
 * impossible in the editor, and the two disagreed about the model.
 *
 * `resolveHarnessProfile` is the join, and it is the only place that decides.
 * `toSdkOptions` is the editor projection, `toRunnerInvocation` and
 * `toAiLaneWith` are the CI ones. Two projections of one value cannot drift the
 * way two configurations can — and the differentiator between an editor run and
 * a lane run is deliberately **the human gate**, not a second runner.
 *
 * ### The model precedence mirrors the runner's own
 *
 * `run.sh` resolves `--model` > `AI_MODEL` > `<repo>/_data/ai.yml` > a built-in
 * default. Here that is **settings > `zer0.json` > `_data/ai.yml` > the
 * built-in default**, and the profile records *which layer answered* so a panel
 * can say so rather than showing a bare string. The consequence is the point: a
 * repository that ships an `_data/ai.yml` stops disagreeing with its own CI,
 * because nobody has to remember to set a second value.
 *
 * ### `permissionMode` is clamped, and this is an empirical finding
 *
 * Measured against `@anthropic-ai/claude-agent-sdk` 0.3.220 (2026-09-09), with
 * a one-turn run that asks for a `Write`:
 *
 * | configuration | did `canUseTool` see the `Write`? |
 * |---|---|
 * | `permissionMode: 'default'` | **yes** — and the file was written after the allow |
 * | `permissionMode: 'acceptEdits'` | **no** — the file was written with no callback at all |
 * | project `.claude/settings.json` `permissions.allow: ['Write']` | yes — an allow rule does *not* skip the callback |
 * | project `.claude/settings.json` `permissions.defaultMode: 'acceptEdits'` | yes — the CLI's own trust filter drops an escalating mode from a repo-committed tier |
 *
 * So exactly one thing bypasses decision D10, and it is a value this
 * extension's own setting used to offer. `resolveHarnessProfile` therefore
 * **clamps** any mode that can skip the card down to `default` and reports the
 * clamp through `profileWarnings`, so the transcript says what happened. The
 * manifest enum is narrowed to `default` and `plan` for the same reason; the
 * clamp is here as well because a `zer0.json` arriving with a cloned repository
 * can also name a mode, and a gate that only exists in the settings UI is not a
 * gate.
 */

import type {
  AgentPermissionMode,
  AgentRecord,
  AiConfig,
  HarnessInventory,
  HarnessProfile,
  McpStdioSpec,
  SkillRecord,
  Zer0Config,
} from '../shared/types';
import { findAgent } from './agents';

// ---------------------------------------------------------------------------
// Constants — the vocabulary itself
// ---------------------------------------------------------------------------

/**
 * The model used when no layer answered. Kept here rather than in the agent
 * shell so the core, the manifest default and the shell cannot hold three
 * opinions; `src/agent/agent.ts` re-exports it as `DEFAULT_MODEL`.
 */
export const DEFAULT_HARNESS_MODEL = 'claude-opus-5';

/**
 * What `zer0Cms.agent.model` means when it is left alone: *inherit* — ask the
 * repository. An empty string is the manifest default for exactly this reason.
 */
export const INHERIT_MODEL = '';

/** The MCP server id this extension registers itself under. */
export const MCP_SERVER_NAME = 'zer0-cms';

/**
 * Tools that cannot change the workspace, auto-allowed without a prompt.
 * `TodoWrite` and `NotebookRead` are in the set deliberately: the first writes
 * only to the agent's own scratch list, the second reads.
 */
export const BASE_READ_ONLY_TOOLS: readonly string[] = [
  'Read',
  'Grep',
  'Glob',
  'LS',
  'TodoWrite',
  'NotebookRead',
];

/**
 * The bundled MCP server's tools that cannot change anything — seven of the
 * twelve. The five that are absent all write: `zer0_draft` a queue file,
 * `zer0_publish` content and the ledger, `zer0_worklist` and `zer0_ingest`
 * under `.cms/`, and `zer0_contract` runs the repository's own engine.
 *
 * This is a **list, not an allow-rule**. It is folded into a profile's
 * `readOnlyTools` when the server is attached, so those seven skip the approval
 * card the way `Read` does; it is never passed to the SDK as `allowedTools`,
 * for the reason decision D10 gives.
 */
export const MCP_READ_ONLY_TOOLS: readonly string[] = [
  `mcp__${MCP_SERVER_NAME}__zer0_status`,
  `mcp__${MCP_SERVER_NAME}__zer0_list_content`,
  `mcp__${MCP_SERVER_NAME}__zer0_get_content`,
  `mcp__${MCP_SERVER_NAME}__zer0_preview`,
  `mcp__${MCP_SERVER_NAME}__zer0_portfolio`,
  `mcp__${MCP_SERVER_NAME}__zer0_media`,
  `mcp__${MCP_SERVER_NAME}__zer0_fleet_status`,
  `mcp__${MCP_SERVER_NAME}__zer0_audit`,
];

/**
 * Environment variables an agent subprocess must never inherit.
 *
 * The SDK spawns Claude Code as a child process, and an omitted `env` means it
 * inherits `process.env` wholesale. `ZER0_CMS_MCP_ALLOW_PUBLISH` is the flag
 * that arms the bundled MCP server's publish tool; whatever set it for some
 * other server in this window must not arm an editor agent run by accident.
 * `toSdkOptions` strips these explicitly rather than hoping nobody set them.
 */
export const STRIPPED_ENV: readonly string[] = [
  'ZER0_CMS_MCP_ALLOW_PUBLISH',
  'ZER0_CMS_MCP_ALLOW_SCAFFOLD',
];

/** The two modes that cannot skip the approval card. See the header table. */
export const CARD_SAFE_PERMISSION_MODES: readonly AgentPermissionMode[] = ['default', 'plan'];

/** Instructions appended to the `claude_code` preset system prompt. */
const SYSTEM_BASE = [
  'You are running inside the zer0-CMS VS Code extension, over the user’s content repository.',
  'Content moves through a governed queue: draft → brand guard → human approval → publish → ledger.',
  'Write drafts and edit content; never approve or publish anything yourself, and never change',
  '`governance.publishAllow` or a draft’s `status` field.',
  'Do NOT create a branch, commit, push, or open a pull request — the user reviews every edit in the',
  'approval card and handles git themselves.',
].join(' ');

// ---------------------------------------------------------------------------
// Resolution
// ---------------------------------------------------------------------------

/**
 * Everything the join needs. `inventory` is PR4's full harness read; the three
 * optional lists are the lighter path a window takes before an inventory has
 * been built, so the same function serves both without pretending to have read
 * a manifest it never opened.
 */
export interface HarnessProfileInput {
  cfg: Zer0Config;
  inventory: HarnessInventory | null;
  agents?: readonly AgentRecord[];
  skills?: readonly SkillRecord[];
  aiConfig?: AiConfig | null;
  /** What the person actually set in VS Code settings — `undefined` if nothing. */
  settingsModel: string | undefined;
  agentName: string | null;
  mcpServer: McpStdioSpec | null;
  trusted: boolean;
  loadProjectSettings: boolean;
  extensionVersion: string;
}

/** Whether a permission mode can let a mutating tool skip `canUseTool`. */
export function permissionModeSkipsCard(mode: string): boolean {
  return !CARD_SAFE_PERMISSION_MODES.includes(mode as AgentPermissionMode);
}

function trimmed(value: string | undefined | null): string {
  return typeof value === 'string' ? value.trim() : '';
}

/**
 * The model, and the layer that answered for it.
 *
 * `cfg.agent.model` is already the merged three-layer answer, so it can only
 * speak for `zer0.json` once the settings layer has been asked separately and
 * the built-in default has been excluded — a merged value that equals the
 * manifest default is the default, not a choice somebody made.
 */
export function resolveModel(
  settingsModel: string | undefined,
  cfgModel: string,
  aiConfig: AiConfig | null,
): { model: string; source: HarnessProfile['modelSource'] } {
  const fromSettings = trimmed(settingsModel);
  if (fromSettings.length > 0) {
    return { model: fromSettings, source: 'settings' };
  }
  const fromFile = trimmed(cfgModel);
  if (fromFile.length > 0 && fromFile !== DEFAULT_HARNESS_MODEL) {
    return { model: fromFile, source: 'zer0.json' };
  }
  const fromAiYml = trimmed(aiConfig?.model);
  if (fromAiYml.length > 0) {
    return { model: fromAiYml, source: 'ai.yml' };
  }
  return { model: DEFAULT_HARNESS_MODEL, source: 'default' };
}

/**
 * Resolve one run's harness. Pure: every input is data, and the same inputs
 * always produce the same profile, which is what makes the two projections
 * below comparable rather than merely similar.
 */
export function resolveHarnessProfile(input: HarnessProfileInput): HarnessProfile {
  const agents = input.inventory?.agents ?? input.agents ?? [];
  const skills = input.inventory?.skills ?? input.skills ?? [];
  const aiConfig = input.inventory?.aiConfig ?? input.aiConfig ?? null;

  const { model, source } = resolveModel(input.settingsModel, input.cfg.agent.model, aiConfig);
  const fallback = trimmed(aiConfig?.fallbackModel);
  const agent = findAgent(agents, input.agentName);

  const requested = input.cfg.agent.permissionMode;
  const permissionMode: AgentPermissionMode = permissionModeSkipsCard(requested)
    ? 'default'
    : (requested as AgentPermissionMode);

  const mcpServers: Record<string, McpStdioSpec> =
    input.mcpServer === null ? {} : { [MCP_SERVER_NAME]: input.mcpServer };

  const readOnlyTools =
    input.mcpServer === null
      ? [...BASE_READ_ONLY_TOOLS]
      : [...BASE_READ_ONLY_TOOLS, ...MCP_READ_ONLY_TOOLS];

  return {
    model,
    modelSource: source,
    // A fallback identical to the primary is not a fallback; the fleet's own
    // `_data/ai.yml` often sets both to the same id, and repeating it would put
    // a meaningless flag into every CI projection.
    fallbackModel: fallback.length > 0 && fallback !== model ? fallback : null,
    maxTurns: input.cfg.agent.maxTurns,
    permissionMode,
    agent,
    agents,
    skills,
    systemAppend: buildSystemAppend(agent, input.extensionVersion),
    mcpServers,
    settingSources: input.trusted && input.loadProjectSettings ? ['user', 'project', 'local'] : [],
    strictMcpConfig: true,
    readOnlyTools,
  };
}

function buildSystemAppend(agent: AgentRecord | null, extensionVersion: string): string {
  const parts = [SYSTEM_BASE, `Host: zer0-CMS ${extensionVersion}.`];
  if (agent !== null) {
    const description = agent.description.replace(/\s+/g, ' ').trim();
    parts.push(
      `You are running as the repository's own \`${agent.name}\` role` +
        (description.length > 0 ? `: ${description}` : '') +
        ' Its hard rules apply; the user still approves every mutating tool call.',
    );
  }
  return parts.join(' ');
}

/**
 * What a person needs told about this run, in the transcript, before it starts.
 *
 * `requestedPermissionMode` is the configured value *before* the clamp — pass
 * `cfg.agent.permissionMode`. An empty array is the normal case.
 */
export function profileWarnings(
  profile: HarnessProfile,
  requestedPermissionMode: string,
): string[] {
  const out: string[] = [];
  if (permissionModeSkipsCard(requestedPermissionMode)) {
    out.push(
      `Permission mode "${requestedPermissionMode}" lets a file edit run without the approval ` +
        `card — measured against the SDK, an Edit under that mode never reaches canUseTool at ` +
        `all. This run uses "${profile.permissionMode}" instead, so every mutating tool still ` +
        'asks you first (decision D10).',
    );
  }
  if (profile.settingSources.length > 0) {
    out.push(
      'This run loads the repository’s `.claude/settings.json`, so its hooks and permission ' +
        'rules apply under your own credential. You opted in for this run only.',
    );
  }
  if (profile.agent !== null && !profile.agent.nameMatchesFile) {
    out.push(
      `The agent file ${profile.agent.path} declares the name "${profile.agent.name}", which ` +
        'does not match its filename. CI resolves `--agent` against the filename, so this role ' +
        'may not be the one a lane would run.',
    );
  }
  return out;
}

/** The one-line status a panel shows above the transcript. */
export function describeProfile(profile: HarnessProfile): string {
  const parts = [
    profile.agent === null ? 'no role' : `role ${profile.agent.name}`,
    `${profile.model} (${describeSource(profile.modelSource)})`,
    profile.permissionMode,
    `max ${profile.maxTurns} turns`,
  ];
  const servers = Object.keys(profile.mcpServers);
  parts.push(servers.length === 0 ? 'no MCP server' : `MCP ${servers.join(', ')}`);
  parts.push(
    profile.settingSources.length === 0
      ? 'no settings files'
      : `settings ${profile.settingSources.join('+')}`,
  );
  return parts.join(' · ');
}

function describeSource(source: HarnessProfile['modelSource']): string {
  switch (source) {
    case 'settings':
      return 'from your settings';
    case 'zer0.json':
      return 'from zer0.json';
    case 'ai.yml':
      return 'inherited from the repository';
    default:
      return 'built-in default';
  }
}

// ---------------------------------------------------------------------------
// Projection 1 — the editor run
// ---------------------------------------------------------------------------

/** The SDK options this extension sets. `allowedTools` is absent on purpose. */
export interface SdkOptionsProjection {
  agent?: string;
  model: string;
  fallbackModel?: string;
  maxTurns: number;
  permissionMode: string;
  mcpServers: Record<string, McpStdioSpec>;
  settingSources: HarnessProfile['settingSources'];
  strictMcpConfig: true;
  systemPrompt: { type: 'preset'; preset: 'claude_code'; append: string };
  env: Record<string, string>;
}

/**
 * The editor projection.
 *
 * Three properties are load-bearing:
 *
 *  - **No `allowedTools`, ever** (decision D10). A tool matched by an SDK-side
 *    allow rule never reaches `canUseTool`, and `canUseTool` is the gate. The
 *    field is not in the return type, so it cannot be added by accident.
 *  - **`strictMcpConfig: true`**, so only the servers named here are attached
 *    and a `.mcp.json` arriving with a cloned repository cannot add one.
 *  - **An explicit `env`.** The SDK replaces the child environment wholesale
 *    when this is set, so it starts from the host's and then *deletes* the
 *    flags in `STRIPPED_ENV`: an editor run must not be armed by whatever armed
 *    something else in this window.
 */
export function toSdkOptions(
  profile: HarnessProfile,
  baseEnv: Record<string, string | undefined> = process.env,
): SdkOptionsProjection {
  const env: Record<string, string> = {};
  for (const [key, value] of Object.entries(baseEnv)) {
    if (value !== undefined && !STRIPPED_ENV.includes(key)) {
      env[key] = value;
    }
  }
  return {
    ...(profile.agent === null ? {} : { agent: profile.agent.name }),
    model: profile.model,
    ...(profile.fallbackModel === null ? {} : { fallbackModel: profile.fallbackModel }),
    maxTurns: profile.maxTurns,
    permissionMode: profile.permissionMode,
    mcpServers: profile.mcpServers,
    settingSources: profile.settingSources,
    strictMcpConfig: true,
    systemPrompt: { type: 'preset', preset: 'claude_code', append: profile.systemAppend },
    env,
  };
}

// ---------------------------------------------------------------------------
// Projection 2 — the CI equivalent
// ---------------------------------------------------------------------------

/** The runner shim every non-workflow caller in the fleet invokes. */
export const RUNNER_SHIM = 'scripts/ai/run.sh';

/**
 * The `system` a CI projection carries — deliberately **not** `systemAppend`.
 *
 * This is the one part of a run that describes *where it is running*, and the
 * editor's version says the user reviews every edit in an approval card and
 * that the run must not open a pull request. Both are true here and false in a
 * lane, whose entire job is usually to open one. Copying the editor's sentence
 * into a workflow would be this console writing a field that lies, so the CI
 * projection carries the role's own sentence plus the fleet's universal rule,
 * which is exactly the shape every `system:` input in the fleet already has.
 */
export function ciSystemFor(profile: HarnessProfile): string {
  const role = profile.agent;
  if (role === null) {
    return 'Run as configured for this repository. Never merge.';
  }
  const description = role.description.replace(/\s+/g, ' ').trim();
  const sentence = description.length > 0 ? description : `Act as the ${role.name} role.`;
  return `You are ${role.name}. ${sentence}${/[.!?]$/.test(sentence) ? '' : '.'} Never merge.`;
}

/**
 * The same run as a `scripts/ai/run.sh` invocation — the shim to the hub's
 * `claude-run`, whose flags are `--prompt --agent --tools --mcp --system --out
 * --model --max-turns`.
 *
 * `--model` is emitted **only** when the model is an editor-side override. When
 * it was inherited from `_data/ai.yml` (or is the built-in default) the flag is
 * left off on purpose: the runner reads that same file, and pinning the value
 * here would freeze in a workflow what the site can change in one place.
 *
 * `env` is empty because every value the profile knows has a flag, and the one
 * thing CI additionally needs — the credential — is never ours to name.
 */
export function toRunnerInvocation(
  profile: HarnessProfile,
  prompt: string,
): { argv: string[]; env: Record<string, string> } {
  const argv = [RUNNER_SHIM, '--prompt', prompt];
  if (profile.agent !== null) {
    argv.push('--agent', profile.agent.name);
    if (profile.agent.tools.length > 0) {
      argv.push('--tools', profile.agent.tools.join(','));
    }
  }
  argv.push('--system', ciSystemFor(profile));
  if (profile.modelSource === 'settings' || profile.modelSource === 'zer0.json') {
    argv.push('--model', profile.model);
  }
  argv.push('--max-turns', String(profile.maxTurns));
  return { argv, env: {} };
}

/**
 * The same run as the `with:` block of a caller of the hub's reusable
 * `ai-lane.yml`.
 *
 * Only the inputs the profile actually knows are emitted — `lane`, `switch` and
 * `prompt` are the author's to fill, and inventing them would be this console
 * writing a workflow field it derived rather than read. `model` follows the
 * same rule as `--model` above.
 */
export function toAiLaneWith(profile: HarnessProfile): Record<string, string> {
  const out: Record<string, string> = {};
  if (profile.agent !== null) {
    out['agent'] = profile.agent.name;
    if (profile.agent.tools.length > 0) {
      out['tools'] = profile.agent.tools.join(',');
    }
  }
  out['system'] = ciSystemFor(profile);
  if (profile.modelSource === 'settings' || profile.modelSource === 'zer0.json') {
    out['model'] = profile.model;
  }
  out['max-turns'] = String(profile.maxTurns);
  return out;
}
