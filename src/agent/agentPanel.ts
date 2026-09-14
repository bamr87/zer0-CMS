/**
 * `AgentPanel` — the `AgentReporter` implementation, as a webview panel.
 *
 * One singleton `WebviewPanel` holding a transcript, a status line, an approval
 * card and a composer. It owns three things and nothing else:
 *
 *  - **The view model.** Everything the webview draws arrives as one full
 *    `AgentState` snapshot (decision D4). The panel never sends a patch, so the
 *    front end holds no derived state it could disagree with.
 *  - **The approval round trip.** `requestApproval()` parks a promise, shows the
 *    card, and resolves when the webview replies `agent.approve`/`agent.deny`
 *    with the matching id. A mismatched id is dropped; a closed panel or a
 *    stopped run resolves every pending request as a denial, which is what
 *    unwinds the SDK's `canUseTool` await instead of leaking it.
 *  - **The intent whitelist.** Inbound `command` messages are looked up in a
 *    `Record<CommandId, Handler>`; an id with no handler is logged and dropped.
 *    That is decision D5's enforcement point for this surface: the webview can
 *    say "start", it cannot say "start with the agent disabled" — the enabled
 *    flag, the model and the turn limit are re-read from configuration here, on
 *    every start, and a fresh `CmsAgent` is built from them.
 *
 * The panel deliberately does **not** live in `src/panel/` or `src/dashboard/`:
 * it is the only surface that may be entirely absent from a session, and
 * keeping it beside `agent.ts` keeps the whole optional capability in one
 * directory that can be read — or removed — as a unit.
 *
 * ### The constructor is what makes the four commands work
 *
 * `setAgentHost(this)` runs in the constructor, not in `open()`. Until this was
 * here, nothing in `src/` ever installed a host and all four `zer0Cms.agent.*`
 * commands ended at "the AI agent panel is not available in this window" —
 * documented wiring that did not exist. The registration lives in `registered`
 * rather than `disposables` on purpose: `disposables` is emptied by
 * `teardown()` when the *webview* closes, and a closed webview must not
 * uninstall the host that `agent.open` uses to bring it back.
 *
 * ### Two surfaces reach `start()`, so `start()` holds the gate
 *
 * `zer0Cms.agent.start` goes through `readyHost()` in `src/commands/agent.ts`,
 * which checks Workspace Trust. The composer in this panel does not — it posts
 * `agent.send` straight into the handler table. So `start()` asks again
 * (decision D13). Same rule as everywhere else in this repository: the surface
 * is a courtesy, the function is the gate.
 */

import { randomBytes } from 'node:crypto';

import * as vscode from 'vscode';

import {
  agentMcpServer,
  hasProjectAgentSettings,
  readRepoSlug,
  resolveProfileFor,
  setAgentHost,
  type AgentStartOptions,
} from '../commands/agent';
import { configFileName, currentConfig, workspaceRoot, workspaceTrusted } from '../config';
import { utcStamp, type HarnessProfile } from '../core';
// Module path rather than `../core` until WP3.0's harness barrel lines land.
import { defaultUsageLedgerPath } from '../core/harness/metering';
import type { Zer0Shell } from '../extension';
import { describeError, log } from '../logger';
import type {
  AgentState,
  ApprovalCard,
  CommandId,
  TranscriptEntry,
  TranscriptRole,
  ViewMsg,
} from '../webview/shared/protocol';
import {
  CmsAgent,
  DEFAULT_MODEL,
  type AgentReporter,
  type AgentRole,
  type ApprovalRequest,
} from './agent';

/** Older lines are dropped rather than posted forever to a live webview. */
const TRANSCRIPT_LIMIT = 400;

type Handler = (args: unknown) => void;

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : undefined;
}

function readString(args: unknown, key: string): string | undefined {
  const value = asRecord(args)?.[key];
  return typeof value === 'string' ? value : undefined;
}

export class AgentPanel implements AgentReporter, vscode.Disposable {
  static readonly viewType = 'zer0Cms.agentPanel';

  private panel: vscode.WebviewPanel | undefined;
  private agent: CmsAgent | undefined;
  /** Lives as long as the current *webview*; `teardown()` empties it. */
  private readonly disposables: vscode.Disposable[] = [];
  /** Lives as long as this *object*; only `dispose()` empties it. */
  private readonly registered: vscode.Disposable[] = [];

  private transcript: TranscriptEntry[] = [];
  private approval: ApprovalCard | null = null;
  private status = 'idle';
  private notice: string | null = null;

  /**
   * The harness as last resolved — the model, the role and the layer that
   * answered. Refreshed when the panel opens and again before every run, never
   * cached across one: `_data/ai.yml` is a file in the repository the person is
   * editing, and a status line that quotes a stale copy of it is worse than one
   * that admits it does not know yet.
   */
  private profile: HarnessProfile | undefined;

  /** Pending `requestApproval` promises, keyed by card id. */
  private readonly pending = new Map<string, (approved: boolean) => void>();

  private readonly handlers: Partial<Record<CommandId, Handler>>;

  constructor(private readonly shell: Zer0Shell) {
    this.handlers = {
      'agent.send': (args) => {
        void this.start(readString(args, 'prompt') ?? '');
      },
      'agent.start': (args) => {
        void this.start(readString(args, 'prompt') ?? '');
      },
      'agent.stop': () => {
        this.stop();
      },
      'agent.approve': (args) => {
        this.settle(readString(args, 'id'), true);
      },
      'agent.deny': (args) => {
        this.settle(readString(args, 'id'), false);
      },
      showOutput: () => {
        log.show();
      },
    };

    // The wiring the four `zer0Cms.agent.*` commands look for. `setAgentHost`
    // returns a disposable that unhooks only if this host is still the
    // installed one, so a second panel replacing this one and then closing
    // cannot unhook the replacement.
    this.registered.push(setAgentHost(this));
  }

  // -------------------------------------------------------------------------
  // Lifecycle
  // -------------------------------------------------------------------------

  get running(): boolean {
    return this.agent?.running === true;
  }

  /** Show the panel, creating it on first use. */
  open(): void {
    if (this.panel) {
      this.panel.reveal(this.panel.viewColumn ?? vscode.ViewColumn.Active, true);
      return;
    }

    const extensionUri = this.shell.context.extensionUri;
    const panel = vscode.window.createWebviewPanel(
      AgentPanel.viewType,
      'zer0-CMS agent',
      { viewColumn: vscode.ViewColumn.Active, preserveFocus: false },
      {
        enableScripts: true,
        // The transcript is expensive to rebuild and an approval may be
        // pending, so the page must survive being hidden behind another tab.
        retainContextWhenHidden: true,
        localResourceRoots: [
          vscode.Uri.joinPath(extensionUri, 'media'),
          vscode.Uri.joinPath(extensionUri, 'dist'),
        ],
      },
    );
    this.panel = panel;
    panel.webview.html = agentHtml(panel.webview, extensionUri);

    // Resolving the harness reads a handful of files (the repository's agents,
    // its skills, its `_data/ai.yml`). It happens when a person opens this
    // panel — never at activation, and never on a timer.
    void this.refreshProfile(null, false);

    this.disposables.push(
      panel.webview.onDidReceiveMessage((message: unknown) => {
        this.receive(message);
      }),
      panel.onDidDispose(() => {
        this.teardown();
      }),
    );
    this.post();
  }

  /**
   * Start a run. Configuration is read fresh here — not cached at construction
   * — so toggling `zer0Cms.agent.enabled` or changing the model takes effect on
   * the next run without a reload, and the webview cannot supply either value.
   *
   * `options.role` and `options.loadProjectSettings` are the two things a *run*
   * may differ by, and both are re-checked here: the composer in this panel
   * reaches `start()` without passing through a command at all, so the second
   * one is asked again, modally, before any settings file is read.
   */
  async start(prompt: string, options: AgentStartOptions = {}): Promise<void> {
    const text = prompt.trim();
    this.open();

    // The gate, re-asked here because the composer reaches this method without
    // passing through `readyHost()` (D13). The panel still opens: the notice is
    // the whole point, and a blank window would explain nothing.
    if (!workspaceTrusted()) {
      this.notice =
        'This workspace is not trusted, so the agent will not run. It edits files and runs ' +
        'commands inside this repository — trust the folder to enable it.';
      this.post();
      return;
    }

    if (this.running) {
      this.notice = 'A run is already in progress.';
      this.post();
      return;
    }

    if (text.length === 0) {
      this.notice = 'Type something for the agent to do.';
      this.post();
      return;
    }

    // The agent's `cwd` is the user's content repository. Without one there is
    // nothing for it to read, and defaulting to some other directory would
    // point a file-writing tool somewhere nobody asked for.
    const root = workspaceRoot();
    if (root === undefined) {
      this.notice = 'Open a folder first — the agent works inside your content repository.';
      this.post();
      return;
    }

    // The repository's `.claude/settings.json` can name hooks, and a hook is a
    // command line that runs under this person's own credential. So the opt-in
    // is asked for again here, modally, naming what it means — and a workspace
    // that is not trusted never reaches this line at all.
    let loadProjectSettings = false;
    if (options.loadProjectSettings === true && (await hasProjectAgentSettings(root))) {
      const answer = await vscode.window.showWarningMessage(
        'Load this repository’s .claude/settings.json for this run?',
        {
          modal: true,
          detail:
            'Its hooks and permission rules would apply to a run using your own credential. ' +
            'A hook is a command line the repository supplies. This applies to this run only.',
        },
        'Load it for this run',
      );
      loadProjectSettings = answer === 'Load it for this run';
      if (!loadProjectSettings) {
        // Not a transcript line: `run()` clears the transcript a moment later,
        // and the run's own opening status line already ends with "no settings
        // files", which says the same thing where it will still be visible.
        log.info('agent: the per-run settings-file opt-in was declined');
      }
    }

    // Read fresh, here, on every start: this is the authoritative copy of the
    // enabled flag, the model and the turn limit (D5). The harness is resolved
    // the same way — from the repository's own agents and `_data/ai.yml`, not
    // from a value the webview supplied.
    const cfg = currentConfig();
    const profile = await this.refreshProfile(options.role ?? null, loadProjectSettings);
    this.notice = null;
    this.appendEntry('user', text);
    this.agent = new CmsAgent(root, this, cfg.agent, {
      profile,
      repo: await readRepoSlug(root),
      usageLedgerPath: defaultUsageLedgerPath(this.shell.context.globalStorageUri.fsPath),
    });
    this.shell.ui.setAgentRunning(true);
    try {
      await this.agent.run(text);
    } catch (error) {
      // `run()` handles its own failures; anything reaching here is a defect in
      // this file, and a silent one would look like a run that never started.
      this.append('error', `The agent run failed to complete: ${describeError(error)}`);
    } finally {
      this.shell.ui.setAgentRunning(false);
      this.post();
    }
  }

  /**
   * Resolve the harness for the active site and remember it for the status
   * line. The MCP server is attached here and nowhere else: `strictMcpConfig`
   * means the servers this profile names are the only ones a run gets, so a
   * `.mcp.json` arriving with a cloned repository cannot add one.
   */
  private async refreshProfile(
    role: string | null,
    loadProjectSettings: boolean,
  ): Promise<HarnessProfile> {
    const root = workspaceRoot();
    const cfg = currentConfig();
    const mcpServer = (await agentMcpServer(this.shell, configFileName())) ?? null;
    const profile = await resolveProfileFor(this.shell, root ?? null, cfg, {
      role,
      loadProjectSettings: root === undefined ? false : loadProjectSettings,
      mcpServer,
    });
    this.profile = profile;
    this.post();
    return profile;
  }

  /** Abort the current run and deny anything it was waiting on. */
  stop(): void {
    if (!this.agent?.running) {
      return;
    }
    this.agent.stop();
    // The SDK is blocked on our approval promise, not on the abort signal, so a
    // pending card has to be resolved or the run never unwinds.
    this.denyAllPending();
    this.post();
  }

  dispose(): void {
    this.teardown();
    // After `teardown()`, which only empties the webview-scoped list. The host
    // registration outlives every panel this object opens and closes, and is
    // removed exactly once, here.
    for (const disposable of this.registered.splice(0)) {
      disposable.dispose();
    }
    this.panel?.dispose();
    this.panel = undefined;
  }

  private teardown(): void {
    this.agent?.stop();
    this.denyAllPending();
    for (const disposable of this.disposables.splice(0)) {
      disposable.dispose();
    }
    this.panel = undefined;
    this.shell.ui.setAgentRunning(false);
  }

  // -------------------------------------------------------------------------
  // AgentReporter
  // -------------------------------------------------------------------------

  append(role: AgentRole, text: string): void {
    this.appendEntry(role, text);
    this.post();
  }

  clearTranscript(): void {
    // The user's own prompt is the first line of the run and is added before
    // `run()` starts, so it is kept: clearing it would leave a transcript whose
    // first entry is the model replying to nothing.
    const last = this.transcript[this.transcript.length - 1];
    this.transcript = last && last.role === 'user' ? [last] : [];
    this.approval = null;
    this.post();
  }

  setStatus(text: string, running: boolean): void {
    this.status = text;
    this.shell.ui.setAgentRunning(running);
    this.post();
  }

  /**
   * Show an approval card and wait. The promise is resolved by the webview, by
   * `stop()`, or by the panel being closed — never by a timeout: the SDK holds
   * the tool call open indefinitely and a timer would silently deny a decision
   * the user was still making.
   */
  requestApproval(request: ApprovalRequest): Promise<boolean> {
    this.open();
    this.approval = {
      id: request.id,
      tool: request.tool,
      summary: request.summary,
      detail: request.detail,
    };
    this.post();
    return new Promise<boolean>((resolve) => {
      this.pending.set(request.id, resolve);
    });
  }

  // -------------------------------------------------------------------------
  // Approvals
  // -------------------------------------------------------------------------

  private settle(id: string | undefined, approved: boolean): void {
    if (id === undefined) {
      log.warn('agent: approval reply carried no id');
      return;
    }
    const resolve = this.pending.get(id);
    if (!resolve) {
      // A reply for a card that has already been answered — a double click, or
      // a stale page. Dropping it is correct; the first answer stands.
      log.verbose(`agent: no pending approval for ${id}`);
      return;
    }
    this.pending.delete(id);
    if (this.approval?.id === id) {
      this.approval = null;
    }
    resolve(approved);
    this.post();
  }

  private denyAllPending(): void {
    for (const resolve of this.pending.values()) {
      resolve(false);
    }
    this.pending.clear();
    this.approval = null;
  }

  // -------------------------------------------------------------------------
  // Messaging
  // -------------------------------------------------------------------------

  private receive(message: unknown): void {
    const msg = asRecord(message) as ViewMsg | undefined;
    if (!msg || typeof msg.type !== 'string') {
      return;
    }
    switch (msg.type) {
      case 'ready':
        this.post();
        return;
      case 'log':
        log[msg.level](`agent webview: ${msg.message}`);
        return;
      case 'command': {
        const handler = this.handlers[msg.id];
        if (!handler) {
          log.warn(`agent webview: dropped unknown command "${msg.id}"`);
          return;
        }
        handler(msg.args);
        return;
      }
      default:
        // The panel has no fields, no taxonomy and no host-computed requests,
        // so the other three webview→host shapes cannot apply to it.
        log.verbose(`agent webview: ignored message "${msg.type}"`);
        return;
    }
  }

  private appendEntry(role: TranscriptRole, text: string): void {
    this.transcript.push({ role, text, at: utcStamp() });
    if (this.transcript.length > TRANSCRIPT_LIMIT) {
      this.transcript = this.transcript.slice(-TRANSCRIPT_LIMIT);
    }
  }

  private post(): void {
    const panel = this.panel;
    if (!panel) {
      return;
    }
    void panel.webview.postMessage({ type: 'state', state: this.state() });
  }

  private state(): AgentState {
    const cfg = currentConfig().agent;
    const available = this.agent?.available ?? true;
    // The resolved profile is the authority. Only before the first resolve does
    // this fall back to the configured value — and to `DEFAULT_MODEL` only when
    // nothing configured one, which after the "inherit" default means "nothing
    // has told us yet", not "this is what will run".
    const model = this.profile?.model ?? (cfg.model.trim() || DEFAULT_MODEL);
    return {
      kind: 'agent',
      enabled: cfg.enabled,
      available,
      running: this.running,
      status: this.status,
      model,
      transcript: this.transcript,
      approval: this.approval,
      notice: this.notice ?? defaultNotice(cfg.enabled, available),
    };
  }
}

/** The line above the composer when the agent cannot actually be used. */
function defaultNotice(enabled: boolean, available: boolean): string | null {
  if (!enabled) {
    return 'The AI agent is off. Turn on "zer0Cms.agent.enabled" to use it.';
  }
  if (!available) {
    return 'The Claude Agent SDK is not installed. Run `npm install` in the extension root and reload the window.';
  }
  return null;
}

// ---------------------------------------------------------------------------
// The page shell
// ---------------------------------------------------------------------------

/** 128 cryptographic bits, regenerated for every page. */
function nonce(): string {
  return randomBytes(16).toString('base64');
}

/**
 * The static shell. **No agent output, draft text or file name is templated in
 * here** — the page ships empty and every character of content arrives over
 * `postMessage` and is written with `textContent`, which is what makes the
 * `default-src 'none'` policy below load-bearing rather than decorative.
 *
 * **There is no `<style>` block.** There used to be about forty rules inlined
 * here, which meant the agent panel's styling was the one part of this
 * extension's appearance that lived in a TypeScript string literal: invisible
 * to the styling test, unreachable from `media/dashboard.css`, and re-parsed on
 * every page render. Those rules now live in `media/base.css` beside the widget
 * kernel, and this file links it. The class names it expects are the
 * `z-agent__*` family the front end builds in `src/webview/agent/main.ts` —
 * `bar`, `spacer`, `status` (with `is-running`), `notice`, `log`, `line` (with
 * the six `--user/--assistant/--tool/--system/--result/--error` modifiers),
 * `gutter`, `role`, `text`, `card` (with `card__head`, `card__tool`,
 * `card__summary`, `card__actions`), `diff` (with `is-add`, `is-del`,
 * `is-meta`), `composer` (with `composer__row`) and `hint`, plus the
 * `#z-agent` column itself. Every one of them names `--z-*` tokens only:
 * `media/tokens.css` stays the single file in the repository that knows a VS
 * Code theme variable's name.
 */
function agentHtml(webview: vscode.Webview, extensionUri: vscode.Uri): string {
  const token = nonce();
  const asset = (...parts: string[]): vscode.Uri =>
    webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, ...parts));
  const codicons = asset('dist', 'media', 'codicon.css');
  const tokens = asset('media', 'tokens.css');
  const base = asset('media', 'base.css');
  const panel = asset('media', 'panel.css');
  const script = asset('dist', 'agent.js');

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'nonce-${token}'; script-src 'nonce-${token}'; font-src ${webview.cspSource}; img-src ${webview.cspSource} data:;">
<title>zer0-CMS agent</title>
<link nonce="${token}" rel="stylesheet" href="${codicons.toString()}">
<link nonce="${token}" rel="stylesheet" href="${tokens.toString()}">
<link nonce="${token}" rel="stylesheet" href="${base.toString()}">
<link nonce="${token}" rel="stylesheet" href="${panel.toString()}">
</head>
<body>
<div id="z-agent"></div>
<script nonce="${token}" src="${script.toString()}"></script>
</body>
</html>`;
}
