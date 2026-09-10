/**
 * The bits of UI that are not a view: context keys, the status bar item, and
 * the handful of notification helpers every command uses.
 *
 * **Eleven context keys, and every one of them gates something in
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

import { workspaceTrusted } from './config';
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
 * | `zer0Cms:fleet:enabled` | the four `fleet.*` commands in the palette |
 * | `zer0Cms:workspace:trusted` | every menu entry that would start a process |
 * | `zer0Cms:sites:multi` | the Sites view, and `site.pick` in the palette |
 *
 * The tenth is a **courtesy, not a gate** (decision D13). It hides the engine,
 * normalizer and agent entries in an untrusted folder so nobody clicks a thing
 * that is going to refuse — but the refusal lives inside the function, which
 * re-asks `workspaceTrusted()` rather than reading this mirror. A context key
 * is only as fresh as the last time somebody remembered to set it; a gate that
 * trusts one is a gate with a stale answer in it.
 *
 * The eleventh is the multi-root switch. It is `true` only when more than one
 * folder is open, which is what keeps a one-folder window — most of them — from
 * growing a Sites tree that would hold exactly one row and a palette entry that
 * would offer exactly one choice. Nothing behind it is a gate either: every
 * site command re-reads the registry, and `SiteRegistry.setActive` refuses an
 * id it does not hold whether or not this key ever got written.
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
  fleetEnabled: 'zer0Cms:fleet:enabled',
  workspaceTrusted: 'zer0Cms:workspace:trusted',
  sitesMulti: 'zer0Cms:sites:multi',
} as const;

export type ContextKey = (typeof CONTEXT_KEYS)[keyof typeof CONTEXT_KEYS];

/** All eleven, for the "activation sets every key" test. */
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

  /** The active site's name, and how many folders are open. See `applySites`. */
  private siteName: string | undefined;
  private siteCount = 0;

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
   * Write all eleven keys from what is knowable without touching the disk.
   * Called once during activation so no `when` clause is ever evaluated
   * against an unset key, and again whenever the configuration changes.
   */
  applyConfig(cfg: Zer0Config, projectConfigPresent: boolean): void {
    this.set(CONTEXT_KEYS.enabled, projectConfigPresent && cfg.workspaceRoot !== '');
    this.set(CONTEXT_KEYS.governanceEnabled, cfg.governance.enabled);
    this.set(CONTEXT_KEYS.agentEnabled, cfg.agent.enabled);
    this.set(CONTEXT_KEYS.fleetEnabled, cfg.fleet.enabled);
    this.set(CONTEXT_KEYS.workspaceTrusted, workspaceTrusted());
    // These six have no answer yet at activation; an explicit `false` is a
    // better starting point than an unset key, which reads as `false` anyway
    // but cannot be distinguished from "we forgot".
    for (const key of [
      CONTEXT_KEYS.fileIsValid,
      CONTEXT_KEYS.dashboardOpen,
      CONTEXT_KEYS.contractPresent,
      CONTEXT_KEYS.agentRunning,
      CONTEXT_KEYS.folderRegistered,
      CONTEXT_KEYS.sitesMulti,
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
    this.set(CONTEXT_KEYS.fleetEnabled, snapshot.cfg.fleet.enabled);
    this.updateStatusBar(snapshot);
  }

  /** `zer0Cms:file:isValid` for the editor that just became active. */
  applyEditor(cfg: Zer0Config, editor: vscode.TextEditor | undefined): void {
    this.set(
      CONTEXT_KEYS.fileIsValid,
      editor !== undefined && isEditableDocument(cfg, editor.document),
    );
  }

  /**
   * `zer0Cms:sites:multi`, and the status bar's site badge.
   *
   * Called by the shell whenever the registry fires: a folder opened or closed,
   * or the active site moved. The count is what the key is about; the name is
   * what a person in a twelve-folder window needs to see before they publish
   * something into the wrong repository.
   */
  applySites(count: number, activeName: string | undefined): void {
    this.siteCount = count;
    this.siteName = activeName;
    this.set(CONTEXT_KEYS.sitesMulti, count > 1);
    // The status bar's other half comes from a snapshot, which may not exist
    // yet. Re-rendering with what we have keeps the badge from lagging a whole
    // refresh behind the switch that just happened.
    this.statusBar.command = count > 1 ? 'zer0Cms.site.pick' : 'zer0Cms.dashboard';
  }

  setDashboardOpen(open: boolean): void {
    this.set(CONTEXT_KEYS.dashboardOpen, open);
  }

  /**
   * Set from `onDidGrantWorkspaceTrust`, which fires without a configuration
   * change and so would otherwise leave the key saying `false` in a folder the
   * user has just trusted. There is no revoke event: VS Code reloads the window
   * instead, and activation writes the key again from scratch.
   */
  setWorkspaceTrusted(trusted: boolean): void {
    this.set(CONTEXT_KEYS.workspaceTrusted, trusted);
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
    // In a multi-root window the badge names the *site*, because "12 folders
    // open and one of them is armed to publish" is the only situation where a
    // permanent pixel has something urgent to say.
    const label = this.siteCount > 1 && this.siteName !== undefined ? this.siteName : 'zer0-CMS';
    this.statusBar.text = pending > 0 ? `$(book) ${label} $(circle-filled) ${pending}` : `$(book) ${label}`;
    const lines = [
      ...(this.siteCount > 1 ? [`site: ${this.siteName ?? '(none)'} of ${this.siteCount} open folder(s)`] : []),
      `${snapshot.pages.length} page(s) indexed`,
      `${snapshot.drafts.length} draft(s), ${pending} pending review`,
      snapshot.contract.present ? 'CMS contract present' : 'no .cms/ contract (scanning the workspace)',
      snapshot.cfg.governance.publishAllow ? 'publishing ENABLED' : 'publishing disabled',
    ];
    this.statusBar.tooltip = new vscode.MarkdownString(
      `**zer0-CMS**\n\n${lines.map((line) => `- ${line}`).join('\n')}\n\n` +
        (this.siteCount > 1 ? 'Click to switch site.' : 'Click to open the dashboard.'),
    );
    this.statusBar.show();
  }

  dispose(): void {
    this.statusBar.dispose();
  }
}
