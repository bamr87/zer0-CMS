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
 * ### `mcp.writeWorkspaceConfig` writes no secrets
 *
 * It is here because it is the other "wire an AI client up to this repository"
 * action. `configureWorkspaceMcpJson` writes a `.vscode/mcp.json` with no
 * `env` block at all: no token, and specifically no publish opt-in. A file
 * committed to a repository is the last place a publish flag belongs.
 */

import * as vscode from 'vscode';

import { currentConfig } from '../config';
import type { Zer0Shell } from '../extension';
import { configureWorkspaceMcpJson } from '../mcpRegistration';
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
  /** Begin a run. An absent prompt means "ask the user for one". */
  start(prompt?: string): void | Promise<void>;
  /** Abort the in-flight run. Safe to call when nothing is running. */
  stop(): void;
  /** Whether a query is in flight right now. */
  readonly running: boolean;
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
 * Two distinct "no"s, with two distinct messages, because they need two
 * different actions from the user: the setting is off (offer to turn it on),
 * or the agent layer is not wired into this window (nothing to offer, say so).
 */
async function readyHost(shell: Zer0Shell): Promise<AgentHost | undefined> {
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
