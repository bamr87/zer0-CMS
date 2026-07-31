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
 */

import { randomBytes } from 'node:crypto';

import * as vscode from 'vscode';

import { currentConfig, workspaceRoot } from '../config';
import { utcStamp } from '../core';
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
import { CmsAgent, type AgentReporter, type AgentRole, type ApprovalRequest } from './agent';

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
  private readonly disposables: vscode.Disposable[] = [];

  private transcript: TranscriptEntry[] = [];
  private approval: ApprovalCard | null = null;
  private status = 'idle';
  private notice: string | null = null;

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
   */
  async start(prompt: string): Promise<void> {
    const text = prompt.trim();
    this.open();

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

    // Read fresh, here, on every start: this is the authoritative copy of the
    // enabled flag, the model and the turn limit (D5).
    const cfg = currentConfig();
    this.notice = null;
    this.appendEntry('user', text);
    this.agent = new CmsAgent(root, this, cfg.agent);
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
    const model = cfg.model.trim().length > 0 ? cfg.model.trim() : 'claude-opus-5';
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
 * The `<style>` block is agent-specific layout only. It names `--z-*` tokens
 * exclusively, never a VS Code theme variable: `media/tokens.css` stays the one
 * file in the repository that knows those names.
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
<style nonce="${token}">
  body { display: flex; }
  #z-agent { display: flex; flex-direction: column; width: 100%; height: 100vh; }
  #z-agent > .z-section { flex: 0 0 auto; }
  #z-agent > .z-section[data-section="transcript"] { flex: 1 1 auto; min-height: 0; overflow-y: auto; }
  .z-agent__bar { display: flex; align-items: center; gap: var(--z-sp-2);
    padding: var(--z-sp-2) var(--z-gutter); border-bottom: 1px solid var(--z-border); }
  .z-agent__bar h1 { font-size: 1rem; font-weight: 600; color: var(--z-fg-header); }
  .z-agent__spacer { flex: 1 1 auto; }
  .z-agent__status { display: inline-flex; align-items: center; gap: var(--z-sp-1);
    padding: 0 var(--z-sp-2); border-radius: var(--z-radius-round);
    background: var(--z-bg-badge); color: var(--z-fg-badge); font-size: 0.85rem; }
  .z-agent__status.is-running { background: var(--z-accent); }
  .z-agent__notice { padding: var(--z-sp-2) var(--z-gutter); color: var(--z-fg-warning);
    background: var(--z-warn-bg); border-bottom: 1px solid var(--z-border); }
  .z-agent__log { display: flex; flex-direction: column; gap: var(--z-sp-2);
    padding: var(--z-gutter) var(--z-gutter-lg); }
  .z-agent__line { display: grid; grid-template-columns: 5.5rem 1fr; gap: var(--z-sp-2);
    border-left: 2px solid transparent; padding-left: var(--z-sp-2); }
  .z-agent__gutter { color: var(--z-fg-muted); font-size: 0.85rem; font-variant-numeric: tabular-nums; }
  .z-agent__role { display: block; text-transform: uppercase; letter-spacing: 0.04em; }
  .z-agent__text { margin: 0; white-space: pre-wrap; word-break: break-word; font-family: inherit; }
  .z-agent__line--user { border-left-color: var(--z-accent); }
  .z-agent__line--assistant { border-left-color: var(--z-border-active); }
  .z-agent__line--tool .z-agent__text { font-family: var(--z-mono); font-size: var(--z-mono-size); color: var(--z-fg-description); }
  .z-agent__line--system .z-agent__text { color: var(--z-fg-muted); font-style: italic; }
  .z-agent__line--result { border-left-color: var(--z-ok); }
  .z-agent__line--error { border-left-color: var(--z-error-border); }
  .z-agent__line--error .z-agent__text { color: var(--z-fg-error); }
  .z-agent__card { margin: 0 var(--z-gutter-lg) var(--z-gutter);
    border: 1px solid var(--z-warn-border); border-radius: var(--z-radius); overflow: hidden; }
  .z-agent__card__head { display: flex; align-items: baseline; gap: var(--z-sp-2);
    padding: var(--z-sp-2) var(--z-sp-3); background: var(--z-warn-bg); }
  .z-agent__card__tool { font-weight: 600; }
  .z-agent__card__summary { color: var(--z-fg-description); font-family: var(--z-mono);
    font-size: var(--z-mono-size); overflow-wrap: anywhere; }
  .z-agent__diff { max-height: 40vh; overflow: auto; margin: 0; padding: var(--z-sp-2) var(--z-sp-3);
    font-family: var(--z-mono); font-size: var(--z-mono-size); background: var(--z-bg-input); }
  .z-agent__diff span { display: block; white-space: pre-wrap; word-break: break-word; }
  .z-agent__diff .is-add { color: var(--z-ok); }
  .z-agent__diff .is-del { color: var(--z-fg-error); }
  .z-agent__diff .is-meta { color: var(--z-fg-muted); }
  .z-agent__card__actions { display: flex; justify-content: flex-end; gap: var(--z-sp-2);
    padding: var(--z-sp-2) var(--z-sp-3); border-top: 1px solid var(--z-border); }
  .z-agent__composer { display: flex; flex-direction: column; gap: var(--z-sp-2);
    padding: var(--z-sp-3) var(--z-gutter-lg); border-top: 1px solid var(--z-border); }
  .z-agent__composer textarea { width: 100%; resize: vertical; min-height: 4.5rem;
    padding: var(--z-sp-2); color: var(--z-input-fg); background: var(--z-bg-input);
    border: 1px solid var(--z-input-border); border-radius: var(--z-radius);
    font-family: inherit; font-size: inherit; }
  .z-agent__composer__row { display: flex; align-items: center; gap: var(--z-sp-2); }
  .z-agent__hint { color: var(--z-fg-muted); font-size: 0.85rem; }
</style>
</head>
<body>
<div id="z-agent"></div>
<script nonce="${token}" src="${script.toString()}"></script>
</body>
</html>`;
}
