/**
 * The bits of UI that are not a view: context keys, the status bar item, and
 * the handful of notification helpers every command uses.
 *
 * **Eight context keys, and every one of them gates something in
 * `package.json`.** Upstream shipped fourteen, five of which were dead — one
 * of them (`frontMatterCanInit`) gating the *initialize* command that a fresh
 * workspace needs, which is why that command was unreachable. The rule here is
 * simple: if a key is not named by a `when` clause in the manifest, it does not
 * exist. Grep for the key before adding one.
 *
 * `setContext` is asynchronous and comparatively expensive, so every key is
 * mirrored in memory and only written when the value actually changes. A
 * keystroke-driven caller (the active-editor listener) can therefore call
 * `applyEditor()` on every change without flooding the command bus.
 */

import * as vscode from 'vscode';

import {
  folderForFile,
  isSupported,
  splitFrontMatter,
  type Zer0Config,
} from './core';
import { describeError, log } from './logger';
import type { Snapshot } from './store';

/**
 * Every context key the manifest's `when` clauses can name.
 *
 * | key | gates |
 * |---|---|
 * | `zer0Cms:enabled` | the `Initialize project` welcome view, the dashboard button, `ctrl+alt+n` |
 * | `zer0Cms:file:isValid` | slug/last-modified/insert-image/content-type commands and the editor title button |
 * | `zer0Cms:dashboard:open` | hides the editor-title dashboard button while it is open |
 * | `zer0Cms:governance:enabled` | the Drafts and Published views, approve/publish in the palette |
 * | `zer0Cms:contract:present` | the Distribution view |
 * | `zer0Cms:agent:enabled` | `agent.start` in the palette |
 * | `zer0Cms:agent:running` | `agent.stop` in the palette |
 * | `zer0Cms:folder:registered` | register vs unregister in the explorer context menu |
 */
export const CONTEXT_KEYS = {
  enabled: 'zer0Cms:enabled',
  fileIsValid: 'zer0Cms:file:isValid',
  dashboardOpen: 'zer0Cms:dashboard:open',
  governanceEnabled: 'zer0Cms:governance:enabled',
  contractPresent: 'zer0Cms:contract:present',
  agentEnabled: 'zer0Cms:agent:enabled',
  agentRunning: 'zer0Cms:agent:running',
  folderRegistered: 'zer0Cms:folder:registered',
} as const;

export type ContextKey = (typeof CONTEXT_KEYS)[keyof typeof CONTEXT_KEYS];

/** All eight, for the "activation sets every key" test. */
export const ALL_CONTEXT_KEYS: readonly ContextKey[] = Object.values(CONTEXT_KEYS);

// ---------------------------------------------------------------------------
// Notifications
// ---------------------------------------------------------------------------

/** Everything a user sees from us is prefixed, so the source is never in doubt. */
const PREFIX = 'zer0-CMS: ';

export function notifyInfo(message: string, ...actions: string[]): Thenable<string | undefined> {
  return vscode.window.showInformationMessage(`${PREFIX}${message}`, ...actions);
}

export function notifyWarning(message: string, ...actions: string[]): Thenable<string | undefined> {
  return vscode.window.showWarningMessage(`${PREFIX}${message}`, ...actions);
}

export function notifyError(message: string, ...actions: string[]): Thenable<string | undefined> {
  log.error(message);
  return vscode.window.showErrorMessage(`${PREFIX}${message}`, ...actions);
}

/** Report a caught value. Returns nothing so a `catch` can be a one-liner. */
export function reportError(error: unknown, context?: string): void {
  const message = describeError(error);
  void notifyError(context === undefined ? message : `${context} — ${message}`);
}

/**
 * A modal yes/no. Modal on purpose: this is the dialog in front of every
 * privileged action, and a dismissible toast is not consent.
 *
 * Returns `true` only when the user pressed `confirmLabel` itself.
 */
export async function confirm(
  message: string,
  confirmLabel: string,
  detail?: string,
): Promise<boolean> {
  const options: vscode.MessageOptions =
    detail === undefined ? { modal: true } : { modal: true, detail };
  const answer = await vscode.window.showWarningMessage(message, options, confirmLabel);
  return answer === confirmLabel;
}

// ---------------------------------------------------------------------------
// The state object
// ---------------------------------------------------------------------------

/**
 * Whether the active editor is a file this extension can edit: a supported
 * extension *and* either a registered content folder or a front-matter block.
 *
 * The second half of that test is what makes the panel useful in a repository
 * whose folders are not registered yet — a markdown file with front matter is
 * self-evidently content, whatever the config says.
 */
export function isEditableDocument(cfg: Zer0Config, document: vscode.TextDocument): boolean {
  if (document.uri.scheme !== 'file' || !isSupported(cfg, document.uri.fsPath)) {
    return false;
  }
  if (folderForFile(cfg.contentFolders, document.uri.fsPath) !== undefined) {
    return true;
  }
  return splitFrontMatter(document.getText()).block !== null;
}

export class UiState implements vscode.Disposable {
  private readonly known = new Map<string, boolean>();
  private readonly statusBar: vscode.StatusBarItem;

  constructor() {
    // Right-aligned with a low priority, like every other "which tool owns this
    // window" badge. The command matches the badge's meaning: click it, get the
    // dashboard.
    this.statusBar = vscode.window.createStatusBarItem(
      'zer0Cms.status',
      vscode.StatusBarAlignment.Right,
      -100,
    );
    this.statusBar.name = 'zer0-CMS';
    this.statusBar.command = 'zer0Cms.dashboard';
    this.statusBar.text = '$(book) zer0-CMS';
    this.statusBar.tooltip = 'zer0-CMS — open the dashboard';
  }

  /** Set one key, skipping the round trip when it already holds that value. */
  set(key: ContextKey, value: boolean): void {
    if (this.known.get(key) === value) {
      return;
    }
    this.known.set(key, value);
    void vscode.commands.executeCommand('setContext', key, value).then(undefined, (error: unknown) => {
      // A failed setContext leaves the mirror lying about the real state.
      this.known.delete(key);
      log.warn(`setContext ${key} failed: ${describeError(error)}`);
    });
  }

  /** The value last written, or `undefined` if the key was never set. */
  get(key: ContextKey): boolean | undefined {
    return this.known.get(key);
  }

  /**
   * Write all eight keys from what is knowable without touching the disk.
   * Called once during activation so no `when` clause is ever evaluated
   * against an unset key, and again whenever the configuration changes.
   */
  applyConfig(cfg: Zer0Config, projectConfigPresent: boolean): void {
    this.set(CONTEXT_KEYS.enabled, projectConfigPresent && cfg.workspaceRoot !== '');
    this.set(CONTEXT_KEYS.governanceEnabled, cfg.governance.enabled);
    this.set(CONTEXT_KEYS.agentEnabled, cfg.agent.enabled);
    // These four have no answer yet at activation; an explicit `false` is a
    // better starting point than an unset key, which reads as `false` anyway
    // but cannot be distinguished from "we forgot".
    for (const key of [
      CONTEXT_KEYS.fileIsValid,
      CONTEXT_KEYS.dashboardOpen,
      CONTEXT_KEYS.contractPresent,
      CONTEXT_KEYS.agentRunning,
      CONTEXT_KEYS.folderRegistered,
    ] as const) {
      if (this.known.get(key) === undefined) {
        this.set(key, false);
      }
    }
  }

  /** Keys and status-bar text that only a built snapshot can answer. */
  applySnapshot(snapshot: Snapshot): void {
    this.set(CONTEXT_KEYS.contractPresent, snapshot.contract.present);
    this.set(CONTEXT_KEYS.governanceEnabled, snapshot.cfg.governance.enabled);
    this.set(CONTEXT_KEYS.agentEnabled, snapshot.cfg.agent.enabled);
    this.updateStatusBar(snapshot);
  }

  /** `zer0Cms:file:isValid` for the editor that just became active. */
  applyEditor(cfg: Zer0Config, editor: vscode.TextEditor | undefined): void {
    this.set(
      CONTEXT_KEYS.fileIsValid,
      editor !== undefined && isEditableDocument(cfg, editor.document),
    );
  }

  setDashboardOpen(open: boolean): void {
    this.set(CONTEXT_KEYS.dashboardOpen, open);
  }

  setAgentRunning(running: boolean): void {
    this.set(CONTEXT_KEYS.agentRunning, running);
  }

  /**
   * Set by the explorer context menu before it renders, so the same slot can
   * show `Register content folder` or `Unregister content folder`.
   */
  setFolderRegistered(registered: boolean): void {
    this.set(CONTEXT_KEYS.folderRegistered, registered);
  }

  // -------------------------------------------------------------------------
  // Status bar
  // -------------------------------------------------------------------------

  /**
   * One item, and it reports the only number worth a permanent pixel: how much
   * is waiting on a human. Upstream had three items, two of which never
   * changed after activation.
   */
  private updateStatusBar(snapshot: Snapshot): void {
    if (snapshot.cfg.workspaceRoot === '') {
      this.statusBar.hide();
      return;
    }
    const pending = snapshot.drafts.filter((draft) => draft.status === 'pending').length;
    this.statusBar.text = pending > 0 ? `$(book) zer0-CMS $(circle-filled) ${pending}` : '$(book) zer0-CMS';
    const lines = [
      `${snapshot.pages.length} page(s) indexed`,
      `${snapshot.drafts.length} draft(s), ${pending} pending review`,
      snapshot.contract.present ? 'CMS contract present' : 'no .cms/ contract (scanning the workspace)',
      snapshot.cfg.governance.publishAllow ? 'publishing ENABLED' : 'publishing disabled',
    ];
    this.statusBar.tooltip = new vscode.MarkdownString(
      `**zer0-CMS**\n\n${lines.map((line) => `- ${line}`).join('\n')}\n\nClick to open the dashboard.`,
    );
    this.statusBar.show();
  }

  dispose(): void {
    this.statusBar.dispose();
  }
}
