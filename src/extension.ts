/**
 * `activate()` — twelve ordered steps, and nothing else.
 *
 * This file wires; it does not implement. Command bodies live in
 * `src/commands/`, tree rendering in `src/views/`, webview hosting in
 * `src/panel/` and `src/dashboard/`. If you find yourself writing an `if` here
 * that is about *content*, it belongs somewhere else.
 *
 * Three promises this function keeps, in order of how badly breaking them
 * would hurt:
 *
 *   1. **No network, no telemetry, no authentication on activation.** Nothing
 *      here opens a socket. The upstream this replaces initialised Sentry,
 *      fetched sponsor state and checked a licence before the user had done
 *      anything at all.
 *   2. **A folderless window completes without throwing and installs zero file
 *      watchers.** Every step below either no-ops or produces an empty-but-
 *      valid object when `vscode.workspace.workspaceFolders` is undefined.
 *   3. **Activation scans nothing.** The only synchronous file access is the
 *      handful of `existsSync` calls and the one small read that answer "is
 *      there a `zer0.json`?" — and in a folderless window even those do not
 *      happen. The first content scan is kicked off in the background at step
 *      11; every surface renders its empty state until it lands.
 *
 * ---
 *
 * ### The shell contract
 *
 * Everything after step 5 is written by other packages, against this shape:
 *
 * ```ts
 * // src/commands/*.ts
 * export function registerProjectCommands(shell: Zer0Shell): void;
 * export function registerContentCommands(shell: Zer0Shell): void;
 * export function registerContentTypeCommands(shell: Zer0Shell): void;
 * export function registerGovernanceCommands(shell: Zer0Shell): GovernanceActions;
 * export function registerContractCommands(shell: Zer0Shell): void;
 * export function registerAgentCommands(shell: Zer0Shell): void;
 *
 * // src/views/*.ts   — each a vscode.TreeDataProvider built from the store
 * export class DraftsTreeProvider    { constructor(store: WorkspaceStore); … }
 * export class ContentTreeProvider   { constructor(store: WorkspaceStore); … }
 * export class CateringTreeProvider  { constructor(store: WorkspaceStore); … }
 * export class PublishedTreeProvider { constructor(store: WorkspaceStore); … }
 *
 * // src/panel/panelProvider.ts
 * export class PanelProvider implements vscode.WebviewViewProvider {
 *   static readonly viewType = 'zer0Cms.panel';
 *   constructor(shell: Zer0Shell, governance: GovernanceActions);
 * }
 *
 * // src/dashboard/dashboardPanel.ts
 * export class DashboardPanel implements vscode.Disposable {
 *   constructor(shell: Zer0Shell, governance: GovernanceActions);
 *   open(route?: string): void;
 *   close(): void;
 * }
 * ```
 *
 * `GovernanceActions` is declared by `src/commands/governance.ts` and holds the
 * two functions that are the single authoritative gate (decision D5): the panel
 * and the dashboard are handed the *same* `approve`/`publish` the command
 * palette calls, so a webview button cannot reach a shorter path.
 */

import * as vscode from 'vscode';

import { currentConfig, hasProjectConfig, onConfigChange } from './config';
import { DiagnosticsManager } from './diagnostics';
import { log, type ExtensionLog } from './logger';
import { registerMcpProvider } from './mcpRegistration';
import { WorkspaceStore } from './store';
import { UiState } from './uiState';

import { registerAgentCommands } from './commands/agent';
import { registerContentCommands } from './commands/content';
import { registerContentTypeCommands } from './commands/contentType';
import { registerContractCommands } from './commands/contract';
import { registerGovernanceCommands, type GovernanceActions } from './commands/governance';
import { registerProjectCommands } from './commands/project';
import { DashboardPanel } from './dashboard/dashboardPanel';
import { PanelProvider } from './panel/panelProvider';
import { CateringTreeProvider } from './views/cateringTree';
import { ContentTreeProvider } from './views/contentTree';
import { DraftsTreeProvider } from './views/draftsTree';
import { PublishedTreeProvider } from './views/publishedTree';

/**
 * The services every command, tree and webview host is handed. One object so
 * that adding a service does not mean changing eleven signatures.
 */
export interface Zer0Shell {
  context: vscode.ExtensionContext;
  store: WorkspaceStore;
  ui: UiState;
  diagnostics: DiagnosticsManager;
  log: ExtensionLog;
}

export function activate(context: vscode.ExtensionContext): void {
  const started = Date.now();

  // --- 1. Logging ----------------------------------------------------------
  // The channel itself is created lazily on the first line written, so an
  // activation that does nothing costs nothing.
  context.subscriptions.push(log);
  log.verbose('activating');

  // --- 2. Context keys and the status bar ----------------------------------
  // Read the configuration once here purely to seed the keys; every later
  // reader calls `currentConfig()` again, fresh.
  const ui = new UiState();
  context.subscriptions.push(ui);
  ui.applyConfig(currentConfig(), hasProjectConfig());

  // --- 3. The workspace store ----------------------------------------------
  // Installs its own watchers — none of them in a folderless window.
  const store = new WorkspaceStore({ state: context.workspaceState });
  context.subscriptions.push(store);

  // --- 4. Diagnostics ------------------------------------------------------
  const diagnostics = new DiagnosticsManager();
  context.subscriptions.push(diagnostics);

  const shell: Zer0Shell = { context, store, ui, diagnostics, log };

  // --- 5. Tree views -------------------------------------------------------
  // All four render from `store.current()`; none of them touches the disk.
  // The `when` clauses in package.json decide which are visible.
  context.subscriptions.push(
    vscode.window.createTreeView('zer0Cms.drafts', {
      treeDataProvider: new DraftsTreeProvider(store),
    }),
    vscode.window.createTreeView('zer0Cms.content', {
      treeDataProvider: new ContentTreeProvider(store),
    }),
    vscode.window.createTreeView('zer0Cms.catering', {
      treeDataProvider: new CateringTreeProvider(store),
    }),
    vscode.window.createTreeView('zer0Cms.published', {
      treeDataProvider: new PublishedTreeProvider(store),
    }),
  );

  // --- 6. Commands ---------------------------------------------------------
  // Governance is registered first because it returns the approve/publish
  // pair that the two webview hosts are then built around (D5).
  const governance: GovernanceActions = registerGovernanceCommands(shell);
  registerProjectCommands(shell);
  registerContentCommands(shell);
  registerContentTypeCommands(shell);
  registerContractCommands(shell);
  registerAgentCommands(shell);

  // --- 7. The metadata panel ----------------------------------------------
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(
      PanelProvider.viewType,
      new PanelProvider(shell, governance),
      { webviewOptions: { retainContextWhenHidden: true } },
    ),
  );

  // --- 8. The dashboard ----------------------------------------------------
  // Constructed, not shown: the panel is created on first `open()`.
  const dashboard = new DashboardPanel(shell, governance);
  context.subscriptions.push(
    dashboard,
    vscode.commands.registerCommand('zer0Cms.dashboard', () => dashboard.open()),
    vscode.commands.registerCommand('zer0Cms.dashboard.close', () => dashboard.close()),
  );

  // --- 9. MCP --------------------------------------------------------------
  // Registration only. The server process is not started here, and no secret
  // is read until the editor asks to start one.
  registerMcpProvider(context);

  // --- 10. Reactive wiring -------------------------------------------------
  context.subscriptions.push(
    // A settings change can flip governance, the agent, or which file is the
    // project config. The store rebuilds its own watchers; this re-seeds keys.
    onConfigChange(() => {
      const cfg = currentConfig();
      ui.applyConfig(cfg, hasProjectConfig());
      ui.applyEditor(cfg, vscode.window.activeTextEditor);
    }),
    // A snapshot is the only thing that knows whether `.cms/` is present or
    // how many drafts are pending.
    store.onDidChange(() => {
      const snapshot = store.peek();
      if (snapshot !== undefined) {
        ui.applySnapshot(snapshot);
      }
    }),
    vscode.window.onDidChangeActiveTextEditor((editor) => {
      ui.applyEditor(currentConfig(), editor);
    }),
    // Opening a folder in a previously folderless window must light everything
    // up without a reload.
    vscode.workspace.onDidChangeWorkspaceFolders(() => {
      ui.applyConfig(currentConfig(), hasProjectConfig());
    }),
  );
  ui.applyEditor(currentConfig(), vscode.window.activeTextEditor);
  diagnostics.validateVisible();

  // --- 11. First snapshot, in the background -------------------------------
  // Deliberately not awaited: activation returns, the trees render their empty
  // state, and the real data arrives through `onDidChange`.
  void store.refresh().then(undefined, (error: unknown) => {
    log.error(`initial refresh failed: ${error instanceof Error ? error.message : String(error)}`);
  });

  // --- 12. Optional startup dashboard --------------------------------------
  if (hasProjectConfig() && currentConfig().dashboard.openOnStartup) {
    dashboard.open();
  }
  log.info(`activated in ${Date.now() - started}ms`);
}

export function deactivate(): void {
  // Everything registered above went into `context.subscriptions`, which VS
  // Code disposes for us. Nothing is left running: no timers outside the
  // store, no watchers outside the store, no child processes.
}
