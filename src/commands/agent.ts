/**
 * The optional AI layer, and the MCP convenience command.
 *
 * The agent is the one capability in zer0-CMS that is **off by default and
 * lazily loaded**. `@anthropic-ai/claude-agent-sdk` is an
 * `optionalDependencies` entry, marked external in the bundle and imported
 * dynamically, so a workspace that never turns it on never resolves it — no
 * module load, no network, no cost. That is decision D3, and the first line of
 * `agent.start` is what enforces it: with `zer0Cms.agent.enabled` false the
 * command explains and returns, before anything can be imported.
 *
 * ### Why the agent is reached through a host object
 *
 * The agent panel owns a webview, a transcript and an in-flight query. Its
 * lifecycle belongs to it, not to a command handler, so `src/agent/agentPanel.ts`
 * registers itself here with `setAgentHost()` and these four commands become
 * three lines each. The dependency points agent → commands, so the palette
 * still resolves in a window where the agent was never enabled and this module
 * has no import edge into the SDK.
 *
 * If nothing has registered, the commands say so instead of throwing. An agent
 * that is switched off must be *quiet*, not broken.
 *
 * ### Trust is the outer gate, and it is checked here
 *
 * The agent is the fifth execution vector (decision D13): it runs tools that
 * edit files and shell out, inside the user's repository. So `readyHost()`
 * asks `workspaceTrusted()` **before** it asks whether the feature is enabled —
 * an untrusted folder is not a settings problem a person can fix by flipping a
 * switch, and offering "Enable it" there would be the wrong sentence. The check
 * is inside the function rather than only in the `when` clause, and
 * `AgentPanel.start()` asks a second time, because the webview's composer can
 * reach `start()` without passing through a command at all.
 *
 * ### `mcp.writeWorkspaceConfig` writes no secrets
 *
 * It is here because it is the other "wire an AI client up to this repository"
 * action. `configureWorkspaceMcpJson` writes a `.vscode/mcp.json` with no
 * `env` block at all: no token, and specifically no publish opt-in. A file
 * committed to a repository is the last place a publish flag belongs.
 *
 * ### `agent.runAsRole` — the same role CI runs, with a human in front of it
 *
 * The fleet's lanes run as a role: `--agent grow-lifehacker`, resolved against
 * `.claude/agents/grow-lifehacker.md`. This command offers that same list in a
 * QuickPick and starts the SDK with that agent, its model and its tools. The
 * differentiator versus CI is deliberately **the human gate**, not a second
 * runner — the role, the model and the tool list are identical, and every
 * mutating call still goes through the approval card.
 *
 * "Copy the CI equivalent" is the other half of the same idea: it renders the
 * run as either a `scripts/ai/run.sh` invocation or an `ai-lane.yml` `with:`
 * block, so a person who got a run working in the editor can move it into a
 * workflow without re-deriving any of it.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import * as vscode from 'vscode';

import { currentConfig, settingsSnapshot, workspaceRoot, workspaceTrusted } from '../config';
import type { AgentRecord, HarnessProfile, McpStdioSpec, Zer0Config } from '../core';
// Module paths rather than `../core` until WP3.0's harness barrel lines land.
import { readAgents, type HarnessIo } from '../core/harness/agents';
import { readAiConfig } from '../core/harness/aiConfig';
import { resolveHarnessProfile, toAiLaneWith, toRunnerInvocation } from '../core/harness/profile';
import { readSkills } from '../core/harness/skills';
import type { Zer0Shell } from '../extension';
import { configureWorkspaceMcpJson, MCP_SERVER_RELATIVE_PATH } from '../mcpRegistration';
import { notifyInfo, notifyWarning } from '../uiState';
import { register } from './project';

/**
 * What a command needs from the agent layer, and nothing more.
 *
 * Implemented by the agent panel (WP15). Kept deliberately small: the panel
 * owns the transcript, the approval cards and the SDK; the commands own the
 * gate on `agent.enabled` and the palette wiring.
 */
export interface AgentHost {
  /** Reveal the agent view, creating it if needed. */
  open(): void | Promise<void>;
  /**
   * Begin a run. An absent prompt means "ask the user for one"; `options.role`
   * names a `.claude/agents/<name>.md` to run as, and `options.loadProjectSettings`
   * asks for this repository's `.claude/settings.json` — which the host
   * re-confirms modally, because the surface is a courtesy and the function is
   * the gate.
   */
  start(prompt?: string, options?: AgentStartOptions): void | Promise<void>;
  /** Abort the in-flight run. Safe to call when nothing is running. */
  stop(): void;
  /** Whether a query is in flight right now. */
  readonly running: boolean;
}

/** How a run differs from the default one. Both fields are per-run, never sticky. */
export interface AgentStartOptions {
  role?: string;
  loadProjectSettings?: boolean;
}

let agentHost: AgentHost | undefined;

/**
 * Install the agent host. Returns a disposable that removes it again, and only
 * if it is still the installed one — a panel disposed after a replacement
 * registered must not unhook the replacement.
 */
export function setAgentHost(host: AgentHost): vscode.Disposable {
  agentHost = host;
  return new vscode.Disposable(() => {
    if (agentHost === host) {
      agentHost = undefined;
    }
  });
}

/** Whether an agent host is available. Read by the panel/dashboard state builders. */
export function agentHostInstalled(): boolean {
  return agentHost !== undefined;
}

/**
 * The gate every agent command runs first.
 *
 * Three distinct "no"s, with three distinct messages, because they need three
 * different actions from the user: the workspace is not trusted (manage trust),
 * the setting is off (offer to turn it on), or the agent layer is not wired
 * into this window (nothing to offer, say so). Trust is first because it is the
 * outer gate — with it off, the other two are not the reason nothing happens.
 */
async function readyHost(shell: Zer0Shell): Promise<AgentHost | undefined> {
  if (!workspaceTrusted()) {
    const answer = await notifyWarning(
      'the AI agent does not run in an untrusted workspace. It edits files and runs commands ' +
        'inside this repository, which is the decision Workspace Trust exists to make.',
      'Manage trust',
    );
    if (answer === 'Manage trust') {
      await vscode.commands.executeCommand('workbench.trust.manage');
    }
    shell.log.warn('agent command refused: the workspace is not trusted');
    return undefined;
  }
  if (!currentConfig().agent.enabled) {
    const answer = await notifyInfo(
      'the AI agent is disabled. Enable "zer0Cms.agent.enabled" to use it.',
      'Enable it',
    );
    if (answer === 'Enable it') {
      await vscode.workspace
        .getConfiguration('zer0Cms')
        .update('agent.enabled', true, vscode.ConfigurationTarget.Workspace);
      shell.log.info('zer0Cms.agent.enabled set to true for this workspace');
      // Deliberately not auto-starting: turning a capability on and invoking it
      // are separate decisions, and the second one needs a prompt anyway.
    }
    return undefined;
  }
  if (agentHost === undefined) {
    await notifyWarning('the AI agent panel is not available in this window.');
    shell.log.warn('agent command invoked with no agent host registered');
    return undefined;
  }
  return agentHost;
}

// ---------------------------------------------------------------------------
// The harness, read from the open folder
// ---------------------------------------------------------------------------

/**
 * The injected filesystem the pure harness readers take, over a real folder.
 *
 * Both methods answer "nothing" rather than throwing: a repository with no
 * `.claude/` directory is the normal case, not an error, and a reader that
 * threw would turn "this site runs no AI lanes" into a failed command.
 */
export const EMPTY_HARNESS_IO: HarnessIo = {
  list: async () => [],
  read: async () => undefined,
};

export function workspaceHarnessIo(root: string): HarnessIo {
  return {
    async list(rel: string): Promise<string[]> {
      try {
        return await fs.readdir(path.join(root, rel));
      } catch {
        return [];
      }
    },
    async read(rel: string): Promise<string | undefined> {
      try {
        return await fs.readFile(path.join(root, rel), 'utf8');
      } catch {
        return undefined;
      }
    },
  };
}

/**
 * `owner/name` when the checkout says so, else the folder's own name.
 *
 * The fleet's usage ledger keys rows by `GITHUB_REPOSITORY`, so an editor row
 * that carries the same slug joins to a lane's rows; a folder name is the
 * honest fallback when there is no remote to read one from. Nothing here opens
 * a socket — it reads `.git/config`, which is a file.
 */
export async function readRepoSlug(root: string): Promise<string> {
  const fallback = path.basename(root);
  try {
    const config = await fs.readFile(path.join(root, '.git', 'config'), 'utf8');
    const match = /url\s*=\s*\S*?[:/]([^/\s]+\/[^/\s]+?)(?:\.git)?\s*$/m.exec(config);
    return match?.[1] ?? fallback;
  } catch {
    return fallback;
  }
}

/**
 * How to start this extension's own MCP server as a child of an agent run, or
 * `undefined` when the bundle is not there (a source checkout that has not been
 * built yet).
 *
 * The `env` is written out explicitly and carries **only** which project file
 * to read. Neither `ZER0_CMS_MCP_ALLOW_PUBLISH` nor `ZER0_CMS_MCP_ALLOW_EXEC`
 * appears, so the seven read tools plus the audit answer and the five writers
 * refuse — an agent gets the read surface for free and everything else through
 * the card. `toSdkOptions` additionally strips those two names from the
 * inherited environment, because the child would otherwise pick up whatever
 * armed some other server in this window.
 */
export async function agentMcpServer(
  shell: Zer0Shell,
  configFile: string,
): Promise<McpStdioSpec | undefined> {
  const bundle = shell.context.asAbsolutePath(MCP_SERVER_RELATIVE_PATH);
  try {
    await fs.stat(bundle);
  } catch {
    shell.log.verbose(`agent: MCP server not attached — ${bundle} is not built`);
    return undefined;
  }
  return {
    command: process.execPath,
    args: [bundle],
    env: { ZER0_CMS_CONFIG: configFile },
  };
}

/**
 * Resolve the harness for one run: the repository's agents, skills and
 * `_data/ai.yml`, joined with the three configuration layers by the pure
 * `resolveHarnessProfile`. Reads files; opens no socket; decides nothing that
 * `resolveHarnessProfile` could have decided.
 */
export async function resolveProfileFor(
  shell: Zer0Shell,
  root: string | null,
  cfg: Zer0Config,
  options: { role: string | null; loadProjectSettings: boolean; mcpServer: McpStdioSpec | null },
): Promise<HarnessProfile> {
  // A window with no folder open has no repository to inherit from, and must
  // not read one from wherever the editor process happens to be running.
  const io = root === null ? EMPTY_HARNESS_IO : workspaceHarnessIo(root);
  const [agents, skillsRead, aiConfig] = await Promise.all([
    readAgents(io),
    readSkills(io),
    readAiConfig(io, cfg.cms.aiConfigPath),
  ]);
  return resolveHarnessProfile({
    cfg,
    inventory: null,
    agents,
    skills: skillsRead.skills,
    aiConfig,
    settingsModel: settingsSnapshot().agent?.model,
    agentName: options.role,
    mcpServer: options.mcpServer,
    trusted: workspaceTrusted(),
    loadProjectSettings: options.loadProjectSettings,
    extensionVersion: extensionVersionOf(shell),
  });
}

function extensionVersionOf(shell: Zer0Shell): string {
  const raw = shell.context.extension?.packageJSON as { version?: unknown } | undefined;
  return typeof raw?.version === 'string' ? raw.version : '0.0.0';
}

/** Whether this repository ships a `.claude/settings.json` worth offering. */
export async function hasProjectAgentSettings(root: string): Promise<boolean> {
  try {
    await fs.stat(path.join(root, '.claude', 'settings.json'));
    return true;
  } catch {
    return false;
  }
}

export function registerAgentCommands(shell: Zer0Shell): void {
  // --- Open the agent view -------------------------------------------------
  register(shell, 'agent.open', async () => {
    const host = await readyHost(shell);
    if (host !== undefined) {
      await host.open();
    }
  });

  // --- Start a run ---------------------------------------------------------
  register(shell, 'agent.start', async (arg: unknown) => {
    const host = await readyHost(shell);
    if (host === undefined) {
      return;
    }
    if (host.running) {
      await notifyWarning('the agent is already running. Stop it first.');
      return;
    }

    const supplied = typeof arg === 'string' ? arg.trim() : '';
    const prompt =
      supplied !== ''
        ? supplied
        : await vscode.window.showInputBox({
            title: 'zer0-CMS agent',
            prompt: 'What should the agent do? It drafts and edits; publishing stays behind the gate.',
            ignoreFocusOut: true,
          });
    if (prompt === undefined || prompt.trim() === '') {
      return;
    }

    await host.open();
    shell.ui.setAgentRunning(true);
    try {
      await host.start(prompt.trim());
    } finally {
      // The host is the authority on whether a query is still in flight — a
      // `start()` that returns before the run ends must not clear the key that
      // makes `agent.stop` reachable.
      if (!host.running) {
        shell.ui.setAgentRunning(false);
      }
    }
  });

  // --- Run as one of the repository's own fleet roles ------------------------
  register(shell, 'agent.runAsRole', async () => {
    const host = await readyHost(shell);
    if (host === undefined) {
      return;
    }
    if (host.running) {
      await notifyWarning('the agent is already running. Stop it first.');
      return;
    }
    const root = workspaceRoot();
    if (root === undefined) {
      await notifyWarning('open a folder first — a role is one of its own `.claude/agents/` files.');
      return;
    }

    const agents = await readAgents(workspaceHarnessIo(root));
    if (agents.length === 0) {
      await notifyInfo(
        'this repository declares no roles. A role is a `.claude/agents/<name>.md` file — the same ' +
          'one a CI lane names with `--agent`.',
      );
      return;
    }

    const chosen = await vscode.window.showQuickPick(agents.map(roleItem), {
      title: 'Run as a fleet role',
      placeHolder: 'Which of this repository’s roles should the agent perform as?',
      matchOnDescription: true,
      matchOnDetail: true,
    });
    if (chosen === undefined) {
      return;
    }
    const role = chosen.agent;

    const prompt = await vscode.window.showInputBox({
      title: `Run as ${role.name}`,
      prompt: 'What should this role do? It drafts and edits; publishing stays behind the gate.',
      ignoreFocusOut: true,
    });
    if (prompt === undefined || prompt.trim() === '') {
      return;
    }

    const action = await vscode.window.showQuickPick(
      [
        { label: '$(play) Run it here', id: 'run' as const },
        {
          label: '$(law) Run it here, loading this repository’s .claude/settings.json',
          detail: 'Its hooks and permission rules would apply under your credential. Asks again.',
          id: 'run-settings' as const,
        },
        {
          label: '$(terminal) Copy the CI equivalent — scripts/ai/run.sh',
          detail: 'The same role, model and tools as a runner invocation.',
          id: 'copy-runner' as const,
        },
        {
          label: '$(github) Copy the CI equivalent — ai-lane.yml caller',
          detail: 'The `with:` block of a caller of the fleet’s reusable lane.',
          id: 'copy-lane' as const,
        },
      ],
      { title: `Run as ${role.name}`, placeHolder: 'Here, or as the workflow that would do the same thing?' },
    );
    if (action === undefined) {
      return;
    }

    if (action.id === 'run' || action.id === 'run-settings') {
      await host.open();
      await host.start(prompt.trim(), {
        role: role.name,
        loadProjectSettings: action.id === 'run-settings',
      });
      return;
    }

    // The CI projection is deliberately built with **no** MCP server: a lane
    // runs on a checkout, not inside this window, and offering it a server that
    // only exists here would be this console writing a workflow field it made
    // up rather than one it read.
    const profile = await resolveProfileFor(shell, root, currentConfig(), {
      role: role.name,
      loadProjectSettings: false,
      mcpServer: null,
    });
    const text =
      action.id === 'copy-runner'
        ? renderRunnerInvocation(profile, prompt.trim())
        : renderAiLaneCaller(profile, prompt.trim());
    await vscode.env.clipboard.writeText(text);
    shell.log.info(`agent: copied the CI equivalent for role ${role.name}`);
    await notifyInfo(
      `copied the CI equivalent for ${role.name}. The model is ` +
        `${profile.modelSource === 'ai.yml' || profile.modelSource === 'default' ? 'left to the repository’s _data/ai.yml' : `pinned to ${profile.model}`}.`,
    );
  });

  // --- Stop -----------------------------------------------------------------
  register(shell, 'agent.stop', () => {
    if (agentHost === undefined) {
      return;
    }
    agentHost.stop();
    shell.ui.setAgentRunning(false);
    shell.log.info('agent stopped by the user');
  });

  // --- Write .vscode/mcp.json ----------------------------------------------
  register(shell, 'mcp.writeWorkspaceConfig', () => configureWorkspaceMcpJson(shell.context));
}

// ---------------------------------------------------------------------------
// Rendering the CI equivalent
// ---------------------------------------------------------------------------

interface RoleItem extends vscode.QuickPickItem {
  agent: AgentRecord;
}

function roleItem(agent: AgentRecord): RoleItem {
  const oneLine = agent.description.replace(/\s+/g, ' ').trim();
  return {
    agent,
    label: agent.name,
    description: [agent.model ?? '', agent.tools.length > 0 ? `${agent.tools.length} tools` : '']
      .filter((part) => part.length > 0)
      .join(' · '),
    detail: oneLine.length > 160 ? `${oneLine.slice(0, 160)}…` : oneLine,
  };
}

/** POSIX single-quoting: safe for every byte, including newlines and quotes. */
function shellQuote(value: string): string {
  return /^[A-Za-z0-9_./=:-]+$/.test(value) ? value : `'${value.replace(/'/g, `'\\''`)}'`;
}

/** The run as a `scripts/ai/run.sh` invocation, line-continued so it reads. */
export function renderRunnerInvocation(profile: HarnessProfile, prompt: string): string {
  const { argv } = toRunnerInvocation(profile, prompt);
  const head = shellQuote(argv[0] ?? '');
  const rest: string[] = [];
  for (let i = 1; i < argv.length; i += 2) {
    rest.push(`  ${argv[i] ?? ''} ${shellQuote(argv[i + 1] ?? '')}`);
  }
  const note =
    profile.modelSource === 'ai.yml' || profile.modelSource === 'default'
      ? '# No --model: the runner reads the same _data/ai.yml this profile did.\n'
      : `# --model is pinned because it came from ${profile.modelSource}.\n`;
  return `${note}${head} \\\n${rest.join(' \\\n')}\n`;
}

/** The run as a caller of the hub's reusable `ai-lane.yml`. */
export function renderAiLaneCaller(profile: HarnessProfile, prompt: string): string {
  const inputs = { prompt, ...toAiLaneWith(profile) };
  const lines = [
    '# The CI equivalent of this run — a caller of the fleet’s reusable AI lane.',
    '# Fill `lane:` and `switch:`; everything else is this run’s own harness.',
    'jobs:',
    '  lane:',
    '    uses: bamr87/bamr87/.github/workflows/ai-lane.yml@main',
    '    with:',
    '      lane: <lane-id>',
    '      switch: <LANE>_ENABLED',
  ];
  for (const [key, value] of Object.entries(inputs)) {
    lines.push(...yamlInput(key, value));
  }
  lines.push('    secrets: inherit', '');
  return lines.join('\n');
}

/** One `with:` entry — a block scalar when the value has a newline in it. */
function yamlInput(key: string, value: string): string[] {
  if (!value.includes('\n')) {
    return [`      ${key}: ${JSON.stringify(value)}`];
  }
  return [`      ${key}: |-`, ...value.split('\n').map((line) => `        ${line}`)];
}
