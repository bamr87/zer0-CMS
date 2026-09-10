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
 * export function registerFleetCommands(shell: Zer0Shell): FleetActions;
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
 *   constructor(shell: Zer0Shell, governance: GovernanceActions, fleet: FleetActions);
 *   open(route?: string): void;
 *   close(): void;
 * }
 * ```
 *
 * `GovernanceActions` is declared by `src/commands/governance.ts` and holds the
 * two functions that are the single authoritative gate (decision D5): the panel
 * and the dashboard are handed the *same* `approve`/`publish` the command
 * palette calls, so a webview button cannot reach a shorter path.
 * `FleetActions` (`src/commands/fleet.ts`) is the same idea for the Fleet tab,
 * and it is where promise 1 above is relaxed — decision D11: network happens
 * only from an explicit user action, through an injected `fetch`, never here.
 */

import * as vscode from 'vscode';

import { currentConfig, hasProjectConfig, onConfigChange } from './config';
import { DiagnosticsManager } from './diagnostics';
import { log, type ExtensionLog } from './logger';
import { registerMcpProvider } from './mcpRegistration';
import { activeStoreView, SiteRegistry, type StoreView } from './sites';
import { WorkspaceStore } from './store';
import { UiState } from './uiState';

import { registerAgentCommands } from './commands/agent';
import { registerAuditCommands, type AuditActions } from './commands/audit';
import { registerHarnessCommands, type HarnessActions } from './commands/harness';
import { registerContentCommands } from './commands/content';
import { registerContentTypeCommands } from './commands/contentType';
import { registerContractCommands } from './commands/contract';
import { registerFleetCommands, type FleetActions } from './commands/fleet';
import { registerGovernanceCommands, type GovernanceActions } from './commands/governance';
import { registerProjectCommands } from './commands/project';
import { registerSiteCommands, type SiteActions } from './commands/site';
import { AgentPanel } from './agent/agentPanel';
import { DashboardPanel } from './dashboard/dashboardPanel';
import { PanelProvider } from './panel/panelProvider';
import { CateringTreeProvider } from './views/cateringTree';
import { ContentTreeProvider } from './views/contentTree';
import { DraftsTreeProvider } from './views/draftsTree';
import { PublishedTreeProvider } from './views/publishedTree';
import { SitesTreeProvider } from './views/sitesTree';

/**
 * The services every command, tree and webview host is handed. One object so
 * that adding a service does not mean changing eleven signatures.
 */
export interface Zer0Shell {
  context: vscode.ExtensionContext;
  /**
   * The **active site's** store. A window can hold twelve folders; this is
   * whichever one a command with no file argument is about. A command that
   * *does* have a file argument resolves that file's site instead — see
   * `docs/ARCHITECTURE.md`, "Sites, and the active-site rule".
   */
  readonly store: WorkspaceStore;
  sites: SiteRegistry;
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

  // --- 3. The sites, and a store for each ----------------------------------
  // One store per workspace folder, each reading that folder's configuration,
  // watching that folder's files and writing its own cache key. The registry
  // installs the active-folder resolver before it builds anything, because a
  // store's constructor asks for its folder's configuration and would
  // otherwise get folder zero's. Nothing here scans: the first refresh is a
  // background step 11, exactly as it was with one store.
  const sites = new SiteRegistry(context);
  context.subscriptions.push(sites);

  // A folderless window still needs a valid empty snapshot to render, and
  // building it lazily keeps the "zero watchers when there is no folder"
  // promise honest — a store with no folder installs none.
  let folderless: WorkspaceStore | undefined;
  const folderlessStore = (): WorkspaceStore => {
    if (folderless === undefined) {
      folderless = new WorkspaceStore({ state: context.workspaceState });
      context.subscriptions.push(folderless);
    }
    return folderless;
  };

  // --- 4. Diagnostics ------------------------------------------------------
  const diagnostics = new DiagnosticsManager();
  context.subscriptions.push(diagnostics);

  const shell: Zer0Shell = {
    context,
    get store(): WorkspaceStore {
      return sites.activeStore() ?? folderlessStore();
    },
    sites,
    ui,
    diagnostics,
    log,
  };

  // --- 5. Tree views -------------------------------------------------------
  // The four content trees render whichever site is active, through one view
  // that follows the registry — they are not given a store of their own,
  // because a second store on the same folder would double its watchers, its
  // scans and its cache writes. `zer0Cms.sites` renders the registry itself
  // and is hidden by its `when` clause until there is more than one folder.
  // None of them touches the disk.
  const activeView: StoreView = activeStoreView(sites, folderlessStore());
  context.subscriptions.push(
    vscode.window.createTreeView('zer0Cms.sites', {
      treeDataProvider: new SitesTreeProvider(sites),
    }),
    vscode.window.createTreeView('zer0Cms.drafts', {
      treeDataProvider: new DraftsTreeProvider(activeView),
    }),
    vscode.window.createTreeView('zer0Cms.content', {
      treeDataProvider: new ContentTreeProvider(activeView),
    }),
    vscode.window.createTreeView('zer0Cms.catering', {
      treeDataProvider: new CateringTreeProvider(activeView),
    }),
    vscode.window.createTreeView('zer0Cms.published', {
      treeDataProvider: new PublishedTreeProvider(activeView),
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
  // Fleet returns the toggle/dispatch pair the dashboard's Fleet tab is built
  // around, for the same reason governance does. Registration only: nothing
  // here reads a credential or opens a socket (D11).
  const fleet: FleetActions = registerFleetCommands(shell);
  // The audit's three verbs, and — like governance and fleet — the object the
  // dashboard is built around, so the webview can only ever name an intent.
  const audit: AuditActions = registerAuditCommands(shell);
  // Switching, previewing and picking a site: the same injected-actions shape,
  // so the dashboard's switcher goes through the function the palette calls.
  const site: SiteActions = registerSiteCommands(shell, sites);
  // The harness inventory, the lane preview, and the one write that puts a
  // lane's files on disk — behind the same injected-actions shape, so the
  // dashboard's Write button goes through the function the palette calls.
  const harness: HarnessActions = registerHarnessCommands(shell);

  // --- 7. The metadata panel ----------------------------------------------
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(
      PanelProvider.viewType,
      new PanelProvider(shell, governance),
      { webviewOptions: { retainContextWhenHidden: true } },
    ),
  );

  // --- 8. The dashboard and the agent panel --------------------------------
  // Constructed, not shown: the panel is created on first `open()`.
  const dashboard = new DashboardPanel(shell, governance, fleet, audit, site, harness);
  context.subscriptions.push(
    dashboard,
    vscode.commands.registerCommand('zer0Cms.dashboard', () => dashboard.open()),
    vscode.commands.registerCommand('zer0Cms.dashboard.close', () => dashboard.close()),
  );

  // The agent panel installs itself as the agent host in its constructor, which
  // is the whole reason this line exists: without it `setAgentHost` was never
  // called, and every `zer0Cms.agent.*` command ended at "not available in this
  // window" while `src/agent/README.md` documented wiring that did not exist.
  // Constructing it is cheap and honest — the Claude Agent SDK is still only
  // imported when a run actually starts, so this costs nothing at activation
  // and nothing at all when `zer0Cms.agent.enabled` is off.
  context.subscriptions.push(new AgentPanel(shell));

  // --- 9. MCP --------------------------------------------------------------
  // Registration only. The server process is not started here, and no secret
  // is read until the editor asks to start one.
  // One server per configured site, re-enumerated only when the folder set
  // actually changes — the registry fires on every store rebuild, and a dozen
  // watcher-driven rebuilds must not become a dozen re-enumerations.
  registerMcpProvider(context, sites.onDidChange);

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
    sites.onDidChange(() => {
      ui.applySites(sites.all().length, sites.active()?.name);
      const snapshot = shell.store.peek();
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
    // Trust is granted once and never revoked in a running window (VS Code
    // reloads to withdraw it), so this fires at most once — but when it does,
    // five execution vectors and the MCP registration all change their answer
    // (D13). The context key is a courtesy for `when` clauses; every gate still
    // re-asks `workspaceTrusted()` inside the function that spawns.
    vscode.workspace.onDidGrantWorkspaceTrust(() => {
      ui.setWorkspaceTrusted(true);
      ui.applyConfig(currentConfig(), hasProjectConfig());
    }),
  );
  ui.applyEditor(currentConfig(), vscode.window.activeTextEditor);
  diagnostics.validateVisible();

  // --- 11. First snapshot, in the background -------------------------------
  // Deliberately not awaited: activation returns, the trees render their empty
  // state, and the real data arrives through `onDidChange`.
  void shell.store.refresh().then(undefined, (error: unknown) => {
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
