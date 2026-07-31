/**
 * `DashboardPanel` — the host behind the `zer0Cms.dashboard` editor tab.
 *
 * A singleton `WebviewPanel` with the same four jobs `PanelProvider` has, and
 * deliberately nothing else.
 *
 * **1. The view model.** Everything the five routes draw arrives as one full
 * `DashboardState` snapshot (decision D4): the page list, the draft queue and
 * its review pane, the four catering lanes, the settings form and the welcome
 * steps. It is rebuilt from `currentConfig()` and the workspace store on every
 * post; nothing here is cached across posts, so a `zer0.json` edit or a file
 * save is visible on the next snapshot without a reload.
 *
 * **2. The intent whitelist.** Inbound `command` messages are looked up in a
 * `Record<CommandId, Handler>` by *own* property, after checking membership in
 * the closed `CommandId` union. The union check rejects an id the protocol
 * never defined; `Object.hasOwn` rejects one that would resolve through
 * `Object.prototype`, so a forged `{"id":"constructor"}` cannot hand us a
 * callable that is not a handler. An id failing either check is logged and
 * dropped.
 *
 * **3. Decision D5, at the two places it matters.** `draft.approve` and
 * `draft.publish` route into the injected `GovernanceActions` — the same
 * `doApprove`/`doPublish` that `src/commands/governance.ts` registers for the
 * command palette, which re-read the draft from disk, re-run the brand guard,
 * re-evaluate `evaluatePublishGates()` and ask modally before writing a byte.
 * The webview supplies a draft path and nothing else. The blockers rendered
 * under a disabled button here are advisory; the ones that decide are computed
 * again, later, somewhere else.
 *
 * **4. Durable UI state.** Four preferences must survive the webview being
 * disposed — the sort order, the layout, the route and the selected draft — so
 * they are round-tripped through `setUiState` into `context.workspaceState`
 * under the keys PLAN §4.5 names. The key is looked up in a whitelist for the
 * same reason `updateSetting` is: a webview names a preference, it does not
 * address the workspace state store.
 *
 * ### What the dashboard does *not* do
 *
 * There is no media database, no snippet store, no taxonomy migrator and no
 * project switcher. Deleting a file goes to the OS trash and renaming goes
 * through `workspace.fs`; both are recoverable, both are confirmed in the
 * webview before the intent is even posted, and neither touches the ledger.
 * The governed actions are the only privileged ones, and they are not
 * implemented here.
 */

import { randomBytes } from 'node:crypto';
import * as path from 'node:path';
import * as vscode from 'vscode';

import {
  MIN_OBSERVATIONS,
  asString,
  buildPreview,
  canonicalUrl,
  commentaryOf,
  distributionDir,
  guardWithWorkspace,
  evaluateApproveGates,
  evaluatePublishGates,
  hasEvidence,
  previewRequestFromDraft,
  readDraft,
  relPath,
  searchPages,
  shareEntries,
  sourceOf,
  type CateringPlan,
  type ContentFolder,
  type DashboardView,
  type DraftFile,
  type GuardFinding,
  type Ledger,
  type PageEntry,
  type Zer0Config,
} from '../core';
import { currentConfig, hasProjectConfig, onConfigChange, readConfigFileJson, updateSetting } from '../config';
import { draftPathFrom, type GovernanceActions } from '../commands/governance';
import type { Zer0Shell } from '../extension';
import { describeError, log } from '../logger';
import { reportError } from '../uiState';
import type { Snapshot } from '../store';
import {
  COMMAND_IDS,
  type CateringState,
  type CommandId,
  type ContentsState,
  type CountedTab,
  type DashboardRoute,
  type DashboardState,
  type DashboardTab,
  type DraftSummary,
  type DraftsState,
  type FilterDimension,
  type FolderView,
  type GroupOption,
  type GuardFindingView,
  type LedgerStateView,
  type ReviewState,
  type RequestOp,
  type SettingItem,
  type SettingsState,
  type SortOption,
  type ViewMsg,
  type WelcomeState,
  type WelcomeStep,
} from '../webview/shared/protocol';

/** Snapshot posts are coalesced over this window. */
const POST_DEBOUNCE_MS = 80;

/** How many search hits the host is willing to ship in one reply. */
const SEARCH_LIMIT = 500;

/**
 * The two `command:` URIs the developer bar uses, and the entire allow-list.
 * `enableCommandUris: true` would let any anchor in the page invoke any command
 * in the workbench; naming two is the difference between a debug affordance and
 * a capability.
 */
const DEVELOPER_COMMAND_URIS: readonly string[] = [
  'workbench.action.webview.reloadWebviewAction',
  'workbench.action.webview.openDeveloperTools',
];

/** The five routes, in tab order. `catering` is dropped without a contract. */
const TABS: readonly DashboardTab[] = [
  { id: 'contents', label: 'Contents', icon: 'files' },
  { id: 'drafts', label: 'Drafts', icon: 'checklist' },
  { id: 'catering', label: 'Distribution', icon: 'graph' },
  { id: 'settings', label: 'Settings', icon: 'settings-gear' },
  { id: 'welcome', label: 'Welcome', icon: 'rocket' },
];

const ROUTE_IDS: ReadonlySet<string> = new Set<string>(TABS.map((tab) => tab.id));

/**
 * The durable UI preferences and where each lives in workspace state.
 *
 * PLAN §4.5 names four of these keys explicitly, including their inconsistent
 * prefixes; they are reproduced verbatim rather than normalised, because they
 * are the keys a workspace opened by an earlier build already holds. The
 * webview names a preference from this table or the write is dropped.
 */
const UI_STATE_KEYS: Readonly<Record<string, string>> = {
  'Contents:Sorting': 'zer0Cms:Dashboard:Contents:Sorting',
  'Contents:Grouping': 'zer0Cms:Dashboard:Contents:Grouping',
  'Contents:Tab': 'zer0Cms:Dashboard:Contents:Tab',
  PagesView: 'zer0Cms:PagesView',
  SelectedFolder: 'zer0Cms:SelectedFolder',
  Route: 'zer0Cms:Dashboard:Route',
  'Drafts:Selected': 'zer0Cms:Dashboard:Drafts:Selected',
};

/**
 * The settings the dashboard's General tab may write, and the `zer0Cms.*` ids
 * they map to. `cardFields.*` is special-cased below because it patches a
 * member of an object setting rather than replacing a scalar.
 */
const SETTING_KEYS: Readonly<Record<string, string>> = {
  'dashboard.openOnStartup': 'dashboard.openOnStartup',
  'dashboard.defaultView': 'dashboard.defaultView',
  'dashboard.defaultSorting': 'dashboard.defaultSorting',
  'dashboard.pageSize': 'dashboard.pageSize',
  'content.autoUpdateModifiedDate': 'content.autoUpdateModifiedDate',
  'panel.openOnSupportedFile': 'panel.openOnSupportedFile',
  'seo.enabled': 'seo.enabled',
  'agent.enabled': 'agent.enabled',
};

/** Card fields are members of one object setting; these are the two we offer. */
const CARD_FIELD_KEYS: readonly string[] = ['state', 'date'];

const VIEW_IDS: ReadonlySet<string> = new Set<string>(['grid', 'list', 'structure']);

/**
 * The six sort ids and their labels, alphabetised by label exactly as Front
 * Matter did before appending user entries. The media-only six went with the
 * media view.
 */
const SORT_OPTIONS: readonly SortOption[] = [
  { id: 'FileNameAsc', label: 'By filename (asc)' },
  { id: 'FileNameDesc', label: 'By filename (desc)' },
  { id: 'LastModifiedAsc', label: 'Last modified (asc)' },
  { id: 'LastModifiedDesc', label: 'Last modified (desc)' },
  { id: 'PublishedAsc', label: 'Published (asc)' },
  { id: 'PublishedDesc', label: 'Published (desc)' },
];

const SORT_IDS: ReadonlySet<string> = new Set<string>(SORT_OPTIONS.map((option) => option.id));

/**
 * The four italic empty-state sentences, byte-identical to the ones
 * `core/catering/worklist.ts` writes into the generated file.
 *
 * They are duplicated rather than imported because `renderWorklist` builds them
 * inline; if that function's prose changes, these four strings change with it.
 * The screen and the file saying different things about the same empty lane is
 * the bug this constant exists to make obvious.
 */
const LANE_EMPTY = {
  undistributed: 'Everything publishable has been distributed.',
  provenNoEvidence:
    'No audience data yet. Topic rankings need published posts with statistics read back; ' +
    'until then this lane is empty rather than guessed.',
  provenThin:
    `Not enough observations yet — a topic needs ${MIN_OBSERVATIONS} posts before its average ` +
    'means anything.',
  quiet: 'Nothing to report.',
  refresh: 'Nothing published has gone stale.',
} as const;

type Handler = (args: unknown) => void;

const COMMAND_ID_SET: ReadonlySet<string> = new Set<string>(COMMAND_IDS);

function isCommandId(value: unknown): value is CommandId {
  return typeof value === 'string' && COMMAND_ID_SET.has(value);
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function readString(source: unknown, key: string): string | undefined {
  const value = asRecord(source)?.[key];
  return typeof value === 'string' ? value : undefined;
}

function readStringList(source: unknown, key: string): string[] {
  const value = asRecord(source)?.[key];
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

/** `tags` → `Tags`. Used for custom filter and grouping labels. */
function firstToUpper(value: string): string {
  return value.length === 0 ? value : value.charAt(0).toUpperCase() + value.slice(1);
}

export class DashboardPanel implements vscode.Disposable {
  static readonly viewType = 'zer0Cms.dashboard';

  private panel: vscode.WebviewPanel | undefined;
  private readonly disposables: vscode.Disposable[] = [];
  private readonly handlers: Partial<Record<CommandId, Handler>>;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private posting = false;

  constructor(
    private readonly shell: Zer0Shell,
    private readonly governance: GovernanceActions,
  ) {
    this.handlers = {
      // --- project ---------------------------------------------------------
      init: () => this.run('init'),
      dashboard: () => {
        this.open();
      },
      'dashboard.close': () => {
        this.close();
      },
      refresh: () => this.run('refresh'),
      'cache.clear': () => this.run('cache.clear'),
      showOutput: () => this.run('showOutput'),
      registerFolder: (args) => this.run('registerFolder', args),
      unregisterFolder: (args) => this.run('unregisterFolder', args),
      // --- content ---------------------------------------------------------
      createContent: () => this.run('createContent'),
      createContentInFolder: (args) => this.run('createContentInFolder', args),
      openFile: (args) => this.run('openFile', args),
      // --- content types ---------------------------------------------------
      'contentType.generate': () => this.run('contentType.generate'),
      // --- governance: the gate, injected -----------------------------------
      'draft.new': (args) => this.run('draft.new', args),
      'draft.review': (args) => {
        void this.runGovernance('review', args);
      },
      'draft.approve': (args) => {
        void this.runGovernance('approve', args);
      },
      'draft.publish': (args) => {
        void this.runGovernance('publish', args);
      },
      'draft.guard': (args) => {
        void this.runGovernance('guard', args);
      },
      'draft.preview': (args) => {
        void this.runGovernance('preview', args);
      },
      // --- contract and distribution ---------------------------------------
      'catering.worklist': () => this.run('catering.worklist'),
      'contract.run': () => this.run('contract.run'),
      'contract.normalizePreview': () => this.run('contract.normalizePreview'),
      'contract.normalizeApply': () => this.run('contract.normalizeApply'),
      // --- agent -----------------------------------------------------------
      'agent.open': () => this.run('agent.open'),
      // --- surface-only ----------------------------------------------------
      openLink: (args) => {
        this.openLink(readString(args, 'url'));
      },
      openProject: () => {
        this.reveal(currentConfig().workspaceRoot);
      },
      revealFile: (args) => {
        this.reveal(readString(args, 'path'));
      },
      showProblems: () => {
        void vscode.commands.executeCommand('workbench.panel.markers.view.focus');
      },
      updateSetting: (args) => {
        void this.writeSetting(args);
      },
      deleteFile: (args) => {
        void this.deleteFiles(args);
      },
      renameFile: (args) => {
        void this.renameFile(args);
      },
    };
  }

  // -------------------------------------------------------------------------
  // Lifecycle
  // -------------------------------------------------------------------------

  /**
   * Reveal the dashboard, creating it if it is not open.
   *
   * `route` is validated against the closed route set and templated into the
   * shell as `data-route`, which is the boot route the webview reads once. It
   * is an enum literal, never workspace content — §4.4's rule that no file
   * text reaches the markup still holds. An already-open panel is revealed
   * rather than re-routed: the manifest's `zer0Cms.dashboard` takes no
   * argument, so that path exists only for a caller that has one.
   */
  open(route?: string): void {
    if (this.panel !== undefined) {
      this.panel.reveal(this.panel.viewColumn ?? vscode.ViewColumn.One, false);
      this.schedule(0);
      return;
    }

    const extensionUri = this.shell.context.extensionUri;
    const developer = this.shell.context.extensionMode !== vscode.ExtensionMode.Production;
    const panel = vscode.window.createWebviewPanel(
      DashboardPanel.viewType,
      'zer0-CMS Dashboard',
      { viewColumn: vscode.ViewColumn.One, preserveFocus: false },
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [
          vscode.Uri.joinPath(extensionUri, 'media'),
          vscode.Uri.joinPath(extensionUri, 'dist'),
        ],
        // Only outside a released build, and only these two commands.
        ...(developer ? { enableCommandUris: DEVELOPER_COMMAND_URIS } : {}),
      },
    );
    panel.iconPath = vscode.Uri.joinPath(extensionUri, 'media', 'zer0-cms-activity.svg');
    panel.webview.html = dashboardHtml(panel.webview, extensionUri, this.bootRoute(route));
    this.panel = panel;

    this.disposables.push(
      panel.webview.onDidReceiveMessage((message: unknown) => {
        this.receive(message);
      }),
      this.shell.store.onDidChange(() => {
        this.schedule();
      }),
      onConfigChange(() => {
        this.schedule();
      }),
      panel.onDidChangeViewState(() => {
        if (panel.visible) {
          this.schedule();
        }
      }),
    );
    panel.onDidDispose(() => {
      this.teardown();
    });

    this.shell.ui.setDashboardOpen(true);
    this.schedule(0);
  }

  /** Close the panel if it is open. A no-op otherwise. */
  close(): void {
    this.panel?.dispose();
  }

  dispose(): void {
    this.close();
    this.teardown();
  }

  private teardown(): void {
    if (this.timer !== undefined) {
      clearTimeout(this.timer);
      this.timer = undefined;
    }
    for (const disposable of this.disposables.splice(0)) {
      disposable.dispose();
    }
    this.panel = undefined;
    this.shell.ui.setDashboardOpen(false);
  }

  /** The explicit route, else the one the webview last reported, else Contents. */
  private bootRoute(route: string | undefined): DashboardRoute {
    if (route !== undefined && ROUTE_IDS.has(route)) {
      return route as DashboardRoute;
    }
    const stored = this.readUiState('Route');
    return stored !== undefined && ROUTE_IDS.has(stored) ? (stored as DashboardRoute) : 'contents';
  }

  // -------------------------------------------------------------------------
  // Messaging
  // -------------------------------------------------------------------------

  private post(message: unknown): void {
    const panel = this.panel;
    if (panel === undefined) {
      return;
    }
    void panel.webview.postMessage(message).then(undefined, (error: unknown) => {
      log.verbose(`dashboard: postMessage failed (${describeError(error)})`);
    });
  }

  /** Coalesce snapshot posts: a burst of watcher events costs one rebuild. */
  private schedule(delay: number = POST_DEBOUNCE_MS): void {
    if (this.panel === undefined) {
      return;
    }
    if (this.timer !== undefined) {
      clearTimeout(this.timer);
    }
    this.timer = setTimeout(() => {
      this.timer = undefined;
      void this.postState();
    }, delay);
  }

  private async postState(): Promise<void> {
    if (this.panel === undefined) {
      return;
    }
    if (this.posting) {
      // A build is already running against a snapshot older than whatever
      // triggered this call. Re-arming is correct; dropping would leave the
      // page one generation behind with nothing to bring it forward.
      this.schedule();
      return;
    }
    this.posting = true;
    try {
      const state = await this.buildState();
      this.post({ type: 'state', state });
    } catch (error) {
      log.error(`dashboard: could not build a snapshot (${describeError(error)})`);
    } finally {
      this.posting = false;
    }
  }

  private receive(message: unknown): void {
    const msg = asRecord(message) as ViewMsg | undefined;
    if (msg === undefined || typeof msg.type !== 'string') {
      return;
    }
    switch (msg.type) {
      case 'ready':
        this.schedule(0);
        return;
      case 'log':
        log[msg.level](`dashboard webview: ${msg.message}`);
        return;
      case 'command':
        this.dispatch(msg.id, msg.args);
        return;
      case 'request':
        void this.reply(msg.requestId, msg.op, msg.payload);
        return;
      case 'setUiState':
        void this.writeUiState(msg.key, msg.value);
        return;
      default:
        // `updateField` and `addTaxonomy` belong to the panel; the dashboard
        // edits nothing in place.
        log.verbose(`dashboard webview: ignored a "${msg.type}" message`);
        return;
    }
  }

  /**
   * The whitelist, and the only place a webview intent becomes an action.
   *
   * Two checks, both necessary. `isCommandId` rejects anything outside the
   * closed protocol union; `Object.hasOwn` rejects an id that would resolve
   * through `Object.prototype` — without it a forged `{"id":"toString"}` looks
   * like a handler and is callable.
   */
  private dispatch(id: unknown, args: unknown): void {
    if (!isCommandId(id) || !Object.hasOwn(this.handlers, id)) {
      log.warn(`dashboard webview: dropped unknown command "${String(id)}"`);
      return;
    }
    const handler = this.handlers[id];
    if (handler === undefined) {
      log.warn(`dashboard webview: dropped command "${id}" with no handler`);
      return;
    }
    handler(args);
  }

  /** Every non-governance intent is the palette command, unchanged. */
  private run(id: string, args?: unknown): void {
    void vscode.commands.executeCommand(`zer0Cms.${id}`, args).then(undefined, (error: unknown) => {
      reportError(error, `zer0Cms.${id}`);
    });
  }

  /**
   * The governance intents. They do **not** go through `executeCommand`: the
   * injected actions are the same functions the palette command bodies call,
   * so the webview reaches exactly one gate and cannot reach a shorter path.
   */
  private async runGovernance(
    action: 'approve' | 'publish' | 'review' | 'guard' | 'preview',
    args: unknown,
  ): Promise<void> {
    const draftPath = draftPathFrom(currentConfig(), args);
    if (draftPath === undefined) {
      log.warn(`dashboard webview: "draft.${action}" arrived without a draft path`);
      return;
    }
    // Clicking a draft in the queue selects it, whichever verb the click named.
    await this.writeUiState('Drafts:Selected', draftPath);
    try {
      switch (action) {
        case 'approve':
          await this.governance.approve(draftPath);
          break;
        case 'publish':
          await this.governance.publish(draftPath);
          break;
        case 'review':
          await this.governance.review(draftPath);
          break;
        case 'guard':
          await this.governance.guard(draftPath);
          break;
        case 'preview':
          await this.governance.preview(draftPath);
          break;
      }
    } catch (error) {
      reportError(error, `draft.${action}`);
    }
    this.schedule();
  }

  // -------------------------------------------------------------------------
  // The request channel
  // -------------------------------------------------------------------------

  private async reply(requestId: string, op: RequestOp, payload: unknown): Promise<void> {
    try {
      const value = await this.handleRequest(op, payload);
      this.post({ type: 'result', requestId, value });
    } catch (error) {
      // Rejecting would be invisible; the control that asked shows this message.
      this.post({ type: 'result', requestId, error: describeError(error) });
    }
  }

  /**
   * Three of the eight ops mean something on this surface.
   *
   * `searchContent` is the important one: the search box is debounced in the
   * webview and executed here, over the store's page list, by the same
   * `searchPages` the rest of the extension uses. Filtering in the webview
   * would work on whatever slice happened to be posted; filtering here works on
   * the index.
   */
  private async handleRequest(op: RequestOp, payload: unknown): Promise<unknown> {
    const cfg = currentConfig();
    switch (op) {
      case 'searchContent': {
        const snapshot = await this.shell.store.current();
        const query = (readString(payload, 'query') ?? '').trim();
        if (query === '') {
          return [] satisfies PageEntry[];
        }
        return searchPages(snapshot.pages, query).slice(0, SEARCH_LIMIT);
      }
      case 'guardText': {
        const findings: GuardFinding[] = await guardWithWorkspace(
          cfg,
          readString(payload, 'text') ?? '',
        );
        return findings satisfies GuardFindingView[];
      }
      case 'previewDraft': {
        const draftPath = readString(payload, 'draftPath');
        if (draftPath === undefined) {
          throw new Error('previewDraft needs a draft path.');
        }
        const draft = await readDraft(draftPath);
        const preview = await buildPreview(cfg, previewRequestFromDraft(draft));
        return {
          artifact: stringifyArtifact(preview.artifact),
          url: preview.url ?? null,
        };
      }
      default:
        // The remaining five ops are the panel's field widgets asking for a
        // slug, a picker or a placeholder. Nothing on this surface sends them.
        throw new Error(`The dashboard does not implement the "${op}" request.`);
    }
  }

  // -------------------------------------------------------------------------
  // Durable UI state and settings
  // -------------------------------------------------------------------------

  private readUiState(key: string): string | undefined {
    const id = UI_STATE_KEYS[key];
    if (id === undefined) {
      return undefined;
    }
    const value = this.shell.context.workspaceState.get<unknown>(id);
    return typeof value === 'string' ? value : undefined;
  }

  private async writeUiState(key: string, value: string): Promise<void> {
    const id = UI_STATE_KEYS[key];
    if (id === undefined) {
      log.warn(`dashboard webview: refused to persist the ui key "${key}"`);
      return;
    }
    try {
      await this.shell.context.workspaceState.update(id, value);
    } catch (error) {
      log.warn(`dashboard: could not persist ${id} (${describeError(error)})`);
      return;
    }
    // Selecting a draft changes what the review pane must contain, and that is
    // built here rather than in the webview — so this one key needs a re-post.
    if (key === 'Drafts:Selected') {
      this.schedule();
    }
  }

  /**
   * Write one setting from the General tab.
   *
   * The key is looked up in `SETTING_KEYS`, or matched against the two
   * card-field members, and nothing else is writable. `updateSetting` is an
   * intent naming a preference, not a path into the settings store.
   */
  private async writeSetting(args: unknown): Promise<void> {
    const key = readString(args, 'key');
    const value = asRecord(args)?.value;
    if (key === undefined || value === undefined) {
      log.warn('dashboard webview: updateSetting needs a key and a value');
      return;
    }

    const cardField = key.startsWith('dashboard.cardFields.')
      ? key.slice('dashboard.cardFields.'.length)
      : undefined;
    try {
      if (cardField !== undefined) {
        if (!CARD_FIELD_KEYS.includes(cardField) || typeof value !== 'boolean') {
          log.warn(`dashboard webview: refused to write the card field "${cardField}"`);
          return;
        }
        const next = { ...currentConfig().dashboard.cardFields, [cardField]: value };
        await updateSetting('dashboard.cardFields', next);
      } else {
        const id = SETTING_KEYS[key];
        if (id === undefined) {
          log.warn(`dashboard webview: refused to write the setting "${key}"`);
          return;
        }
        if (typeof value !== 'boolean' && typeof value !== 'string' && typeof value !== 'number') {
          log.warn(`dashboard webview: "${id}" expects a scalar`);
          return;
        }
        await updateSetting(id, value);
      }
      log.verbose(`dashboard: wrote ${key}`);
    } catch (error) {
      reportError(error, `zer0Cms.${key}`);
    }
    this.schedule();
  }

  // -------------------------------------------------------------------------
  // File operations
  // -------------------------------------------------------------------------

  private openLink(url: string | undefined): void {
    if (url === undefined) {
      return;
    }
    const uri = vscode.Uri.parse(url, true);
    if (uri.scheme !== 'https' && uri.scheme !== 'http') {
      // A `command:` or `file:` link from a webview is an escalation, not a
      // documentation link.
      log.warn(`dashboard webview: refused to open a "${uri.scheme}" link`);
      return;
    }
    void vscode.env.openExternal(uri);
  }

  private reveal(target: string | undefined): void {
    if (target === undefined || target === '') {
      return;
    }
    void vscode.commands.executeCommand('revealFileInOS', vscode.Uri.file(target));
  }

  /**
   * Delete the named files to the OS trash.
   *
   * The webview has already shown the confirmation Front Matter's `ActionsBar`
   * showed, and `useTrash` makes this recoverable from the desktop, so there is
   * no second modal here. This is not a governed action: nothing is written to
   * the ledger and no gate applies.
   */
  private async deleteFiles(args: unknown): Promise<void> {
    const cfg = currentConfig();
    const single = readString(args, 'path');
    const many = readStringList(args, 'paths');
    const targets = single === undefined ? many : [single, ...many];
    if (targets.length === 0) {
      return;
    }
    let removed = 0;
    for (const target of targets) {
      const filePath = path.isAbsolute(target) ? target : path.resolve(cfg.workspaceRoot, target);
      try {
        await vscode.workspace.fs.delete(vscode.Uri.file(filePath), {
          recursive: false,
          useTrash: true,
        });
        removed += 1;
      } catch (error) {
        reportError(error, `deleting ${relPath(cfg, filePath)}`);
      }
    }
    if (removed > 0) {
      log.info(`deleted ${removed} file(s) from the dashboard`);
      await this.shell.store.refresh();
    }
    this.schedule();
  }

  /** Rename one file, asking for the new basename in a native input box. */
  private async renameFile(args: unknown): Promise<void> {
    const cfg = currentConfig();
    const target = readString(args, 'path');
    if (target === undefined || target === '') {
      return;
    }
    const filePath = path.isAbsolute(target) ? target : path.resolve(cfg.workspaceRoot, target);
    const current = path.basename(filePath);
    const answer = await vscode.window.showInputBox({
      title: 'Rename content',
      prompt: `Rename ${relPath(cfg, filePath)}`,
      value: current,
      validateInput: (value) => {
        const trimmed = value.trim();
        if (trimmed === '') {
          return 'A file needs a name.';
        }
        return trimmed.includes('/') || trimmed.includes('\\')
          ? 'Give a file name, not a path — use the explorer to move a file.'
          : undefined;
      },
    });
    if (answer === undefined || answer.trim() === '' || answer.trim() === current) {
      return;
    }
    const next = vscode.Uri.file(path.join(path.dirname(filePath), answer.trim()));
    try {
      await vscode.workspace.fs.rename(vscode.Uri.file(filePath), next, { overwrite: false });
      log.info(`renamed ${current} to ${path.basename(next.fsPath)}`);
      await this.shell.store.refresh();
    } catch (error) {
      reportError(error, `renaming ${current}`);
    }
    this.schedule();
  }

  // -------------------------------------------------------------------------
  // The view model
  // -------------------------------------------------------------------------

  private async buildState(): Promise<DashboardState> {
    const cfg = currentConfig();
    const snapshot = await this.shell.store.current();
    const initialized = hasProjectConfig() && cfg.workspaceRoot !== '';
    const folders = folderViews(cfg);
    const custom = customDashboardConfig();

    const drafts = await this.buildDrafts(cfg, snapshot);

    return {
      kind: 'dashboard',
      initialized,
      // The welcome gate is derived, not remembered: a workspace with no
      // project config or no content folder has nothing for the other routes
      // to show, and a "seen it" flag would only hide that.
      showWelcome: !initialized,
      developer: this.shell.context.extensionMode !== vscode.ExtensionMode.Production,
      tabs: TABS.filter((tab) => tab.id !== 'catering' || snapshot.contract.present),
      contents: this.buildContents(cfg, snapshot, folders, custom),
      drafts,
      catering: buildCatering(snapshot, await this.lastWorklist(snapshot)),
      settings: buildSettings(cfg, folders),
      welcome: buildWelcome(cfg, initialized, folders),
      version: extensionVersion(this.shell.context),
    };
  }

  private buildContents(
    cfg: Zer0Config,
    snapshot: Snapshot,
    folders: FolderView[],
    custom: CustomDashboardConfig,
  ): ContentsState {
    const storedSorting = this.readUiState('Contents:Sorting');
    const storedView = this.readUiState('PagesView');
    const sortOptions = [
      ...SORT_OPTIONS,
      ...custom.sorting.filter((option) => !SORT_IDS.has(option.id)),
    ];
    return {
      pages: snapshot.pages,
      folders,
      tabs: draftTabs(cfg, snapshot.pages),
      sortOptions,
      groupOptions: groupOptions(snapshot.pages, custom.grouping),
      filters: filterDimensions(cfg, snapshot.pages, folders),
      pageSize: cfg.dashboard.pageSize,
      defaultView:
        storedView !== undefined && VIEW_IDS.has(storedView)
          ? (storedView as DashboardView)
          : cfg.dashboard.defaultView,
      defaultSorting:
        storedSorting !== undefined && sortOptions.some((option) => option.id === storedSorting)
          ? storedSorting
          : cfg.dashboard.defaultSorting,
      cardFields: cfg.dashboard.cardFields,
    };
  }

  /**
   * The governed queue, plus the review pane for whichever draft is selected.
   *
   * The review is expensive — it reads the draft, runs the workspace brand
   * guard and builds the exact publish artifact — so it is computed for one
   * draft, not for the whole queue. `buildPreview` performs no writes and no
   * network calls; a failure becomes a `previewFailed` blocker rather than an
   * empty pane, because "we could not build it" is itself a reason not to
   * publish.
   */
  private async buildDrafts(cfg: Zer0Config, snapshot: Snapshot): Promise<DraftsState> {
    const drafts = snapshot.drafts.map((draft) => draftSummary(draft));
    const counts = { pending: 0, approved: 0, published: 0, other: 0 };
    for (const draft of drafts) {
      if (draft.status === 'pending') {
        counts.pending += 1;
      } else if (draft.status === 'approved') {
        counts.approved += 1;
      } else if (draft.status === 'published') {
        counts.published += 1;
      } else {
        counts.other += 1;
      }
    }

    const stored = this.readUiState('Drafts:Selected');
    const selected =
      stored !== undefined && snapshot.drafts.some((draft) => samePath(draft.path, stored))
        ? snapshot.drafts.find((draft) => samePath(draft.path, stored))
        : snapshot.drafts.find((draft) => draft.status === 'pending') ?? snapshot.drafts[0];

    if (!cfg.governance.enabled || selected === undefined) {
      return {
        enabled: cfg.governance.enabled,
        drafts,
        counts,
        selected: selected?.path ?? null,
        review: null,
      };
    }

    let review: ReviewState | null = null;
    try {
      review = await this.buildReview(cfg, selected, snapshot.ledger);
    } catch (error) {
      log.warn(`dashboard: could not build the review pane (${describeError(error)})`);
    }
    return { enabled: true, drafts, counts, selected: selected.path, review };
  }

  private async buildReview(
    cfg: Zer0Config,
    draft: DraftFile,
    ledger: Ledger,
  ): Promise<ReviewState> {
    const guard: GuardFindingView[] = await guardWithWorkspace(cfg, commentaryOf(draft));
    const source = sourceOf(draft);
    const found = ledgerStateFor(cfg, ledger, source);

    let artifact = '';
    let previewError: string | undefined;
    try {
      const preview = await buildPreview(cfg, previewRequestFromDraft(draft));
      artifact = stringifyArtifact(preview.artifact);
    } catch (error) {
      previewError = describeError(error);
      artifact = `Preview failed: ${previewError}`;
    }

    const input = {
      cfg,
      draft,
      guard,
      ...(previewError === undefined ? {} : { previewError }),
      ...(found === undefined ? {} : { ledgerEntry: found.entry }),
    };

    return {
      draft: draftSummary(draft),
      guard,
      artifact,
      ledger: found?.view ?? null,
      approveBlockers: evaluateApproveGates(input),
      publishBlockers: evaluatePublishGates(input),
    };
  }

  /** The newest generated worklist, for the Distribution view's footer line. */
  private async lastWorklist(snapshot: Snapshot): Promise<string | null> {
    if (!snapshot.contract.present) {
      return null;
    }
    const dir = path.join(distributionDir(snapshot.contract), 'worklists');
    try {
      const entries = await vscode.workspace.fs.readDirectory(vscode.Uri.file(dir));
      const files = entries
        .filter(([, kind]) => kind === vscode.FileType.File)
        .map(([name]) => name)
        .filter((name) => name.endsWith('.md'))
        .sort();
      const newest = files[files.length - 1];
      return newest === undefined ? null : path.join(dir, newest);
    } catch {
      // No worklists directory yet. Not an error state — just an empty one.
      return null;
    }
  }
}

// ---------------------------------------------------------------------------
// Projections
// ---------------------------------------------------------------------------

function samePath(a: string, b: string): boolean {
  return path.resolve(a) === path.resolve(b);
}

/** A publish artifact is JSON in every built-in target; prose is passed through. */
function stringifyArtifact(artifact: unknown): string {
  return typeof artifact === 'string' ? artifact : JSON.stringify(artifact ?? null, null, 2);
}

function extensionVersion(context: vscode.ExtensionContext): string {
  const pkg: { version?: unknown } = context.extension.packageJSON;
  return typeof pkg.version === 'string' ? pkg.version : '0.0.0';
}

function draftSummary(draft: DraftFile): DraftSummary {
  const source = sourceOf(draft);
  return {
    path: draft.path,
    name: path.basename(draft.path),
    title: asString(draft.meta.title),
    description: asString(draft.meta.description),
    status: draft.status,
    type: draft.type,
    source: source === '' ? null : source,
    commentary: commentaryOf(draft),
  };
}

/**
 * What the ledger knows about this draft's source.
 *
 * The canonical URL is tried first because that is the ledger's key and the
 * lookup the publish path itself performs. The `source_file` scan is the
 * fallback for an entry written before a permalink changed — the artifact is
 * still out there, and reporting "never published" for it would invite a
 * duplicate.
 */
function ledgerStateFor(
  cfg: Zer0Config,
  ledger: Ledger,
  source: string,
): { view: LedgerStateView; entry: Ledger[string] } | undefined {
  if (source === '') {
    return undefined;
  }
  const url = canonicalUrl(cfg, source);
  const direct = ledger[url];
  if (direct !== undefined && typeof direct.urn === 'string' && direct.urn !== '') {
    const postedAt = typeof direct.posted_at === 'string' ? direct.posted_at : '';
    return { entry: direct, view: { url, urn: direct.urn, postedAt } };
  }
  for (const [key, entry] of shareEntries(ledger)) {
    const raw = ledger[key];
    if (entry.source_file === source && raw !== undefined) {
      return { entry: raw, view: { url: key, urn: entry.urn, postedAt: entry.posted_at } };
    }
  }
  return undefined;
}

function folderViews(cfg: Zer0Config): FolderView[] {
  return cfg.contentFolders.map((folder: ContentFolder) => ({
    title: folder.title,
    path: folder.path,
    relPath: relPath(cfg, folder.path),
    contentTypes: folder.contentTypes ?? [],
    disableCreation: folder.disableCreation === true,
  }));
}

/**
 * A page's draft state, as the navigation tabs and the status badge see it.
 *
 * `PageEntry.draft` already has the configured `invert` applied to booleans and
 * keeps a `choice` field's raw status word, so this is the whole rule. The
 * webview holds an identical copy in `contents.ts` — it cannot import from the
 * host — and the two must agree or a tab will show a count it does not fill.
 */
function draftStateOf(page: PageEntry, now: number): string {
  if (typeof page.draft === 'string') {
    return page.draft;
  }
  if (page.draft) {
    return 'draft';
  }
  return page.published !== null && page.published > now ? 'scheduled' : 'published';
}

/**
 * The draft-state navigation tabs with their counts.
 *
 * A single `All articles` tab is the "this workspace does not mark drafts"
 * answer, and the webview reads that as "hide the status badge too" — which is
 * what Front Matter did when `tabInfo` had one key.
 */
function draftTabs(cfg: Zer0Config, pages: readonly PageEntry[]): CountedTab[] {
  const all: CountedTab = { id: 'all', label: 'All articles', count: pages.length };
  const now = Date.now();

  if (cfg.draftField.type === 'choice') {
    const choices = cfg.draftField.choices ?? [];
    if (choices.length === 0) {
      return [all];
    }
    return [
      all,
      ...choices.map((choice) => ({
        id: choice,
        label: choice,
        count: pages.filter((page) => page.draft === choice).length,
      })),
    ];
  }

  const defines = pages.some((page) => Object.hasOwn(page.data, cfg.draftField.name));
  if (!defines) {
    return [all];
  }
  const counts = { draft: 0, scheduled: 0, published: 0 };
  for (const page of pages) {
    const state = draftStateOf(page, now);
    if (state === 'draft') {
      counts.draft += 1;
    } else if (state === 'scheduled') {
      counts.scheduled += 1;
    } else {
      counts.published += 1;
    }
  }
  const tabs: CountedTab[] = [all, { id: 'published', label: 'Published', count: counts.published }];
  if (counts.scheduled > 0) {
    tabs.push({ id: 'scheduled', label: 'Scheduled', count: counts.scheduled });
  }
  tabs.push({ id: 'draft', label: 'In draft', count: counts.draft });
  return tabs;
}

/**
 * Grouping options, built from what the pages actually carry.
 *
 * `None` is only prepended when there is something else to choose, so a
 * workspace with no dates and no draft field gets no grouping control at all
 * rather than a dropdown with one useless entry.
 */
function groupOptions(pages: readonly PageEntry[], custom: readonly GroupOption[]): GroupOption[] {
  const options: GroupOption[] = [...custom];
  if (pages.some((page) => yearOf(page) !== null)) {
    options.push({ id: 'year', label: 'Year' });
  }
  if (pages.some((page) => page.draft !== undefined)) {
    options.push({ id: 'draft', label: 'Draft/Published' });
  }
  return options.length === 0 ? [] : [{ id: 'none', label: 'None' }, ...options];
}

/** The year a page belongs to, from its publish date or its written date. */
function yearOf(page: PageEntry): number | null {
  if (page.published !== null) {
    return new Date(page.published).getUTCFullYear();
  }
  const match = /^(\d{4})/.exec((page.date ?? '').trim());
  return match?.[1] === undefined ? null : Number(match[1]);
}

/**
 * The filter dimensions, in Front Matter's order: content folder, tag,
 * category, then every custom taxonomy. A dimension with fewer than two values
 * is dropped — a filter that can only ever mean "all" is chrome.
 */
function filterDimensions(
  cfg: Zer0Config,
  pages: readonly PageEntry[],
  folders: readonly FolderView[],
): FilterDimension[] {
  const dimensions: FilterDimension[] = [];

  if (folders.length > 1) {
    dimensions.push({
      id: 'folder',
      label: 'Showing',
      values: [...new Set(folders.map((folder) => folder.title))].sort((a, b) => a.localeCompare(b)),
    });
  }

  const tags = harvest(cfg.taxonomy.tags, pages, (page) => page.tags);
  if (tags.length > 0) {
    dimensions.push({ id: 'tags', label: 'Tag', values: tags });
  }
  const categories = harvest(cfg.taxonomy.categories, pages, (page) => page.categories);
  if (categories.length > 0) {
    dimensions.push({ id: 'categories', label: 'Category', values: categories });
  }

  for (const taxonomy of cfg.taxonomy.custom) {
    const values = harvest(taxonomy.options, pages, (page) => {
      const raw = page.data[taxonomy.id];
      if (Array.isArray(raw)) {
        return raw.filter((item): item is string => typeof item === 'string');
      }
      return typeof raw === 'string' && raw !== '' ? [raw] : [];
    });
    if (values.length > 0) {
      dimensions.push({
        id: `taxonomy:${taxonomy.id}`,
        label: firstToUpper(taxonomy.id),
        values,
      });
    }
  }
  return dimensions;
}

/** Configured values first, then anything the corpus uses that they missed. */
function harvest(
  configured: readonly string[],
  pages: readonly PageEntry[],
  pick: (page: PageEntry) => string[],
): string[] {
  const seen = new Set<string>(configured.filter((value) => value.trim() !== ''));
  for (const page of pages) {
    for (const value of pick(page)) {
      if (value.trim() !== '') {
        seen.add(value);
      }
    }
  }
  return [...seen].sort((a, b) => a.localeCompare(b));
}

function buildCatering(snapshot: Snapshot, lastWorklist: string | null): CateringState {
  const plan: CateringPlan = snapshot.catering;
  return {
    present: snapshot.contract.present,
    observations: plan.observations,
    undistributed: plan.undistributed,
    proven: plan.proven,
    quiet: plan.quiet,
    refresh: plan.refresh,
    emptyStates: {
      undistributed: LANE_EMPTY.undistributed,
      proven: hasEvidence(plan) ? LANE_EMPTY.provenThin : LANE_EMPTY.provenNoEvidence,
      quiet: LANE_EMPTY.quiet,
      refresh: LANE_EMPTY.refresh,
    },
    lastWorklist,
  };
}

function buildSettings(cfg: Zer0Config, folders: FolderView[]): SettingsState {
  const general: SettingItem[] = [
    {
      key: 'dashboard.openOnStartup',
      label: 'Open dashboard on startup',
      description: 'Show this dashboard when the workspace loads.',
      kind: 'boolean',
      value: cfg.dashboard.openOnStartup,
    },
    {
      key: 'dashboard.defaultView',
      label: 'Default view',
      description: 'The layout the Contents view opens in.',
      kind: 'choice',
      value: cfg.dashboard.defaultView,
      choices: ['grid', 'list', 'structure'],
    },
    {
      key: 'dashboard.defaultSorting',
      label: 'Default sorting',
      description: 'The sort order the Contents view opens in.',
      kind: 'choice',
      value: cfg.dashboard.defaultSorting,
      choices: SORT_OPTIONS.map((option) => option.id),
    },
    {
      key: 'dashboard.pageSize',
      label: 'Items per page',
      description: '0 turns pagination off entirely.',
      kind: 'number',
      value: cfg.dashboard.pageSize,
    },
    {
      key: 'dashboard.cardFields.state',
      label: 'Show the draft state on cards',
      kind: 'boolean',
      value: cfg.dashboard.cardFields.state === true,
    },
    {
      key: 'dashboard.cardFields.date',
      label: 'Show the date on cards',
      kind: 'boolean',
      value: cfg.dashboard.cardFields.date === true,
    },
    {
      key: 'content.autoUpdateModifiedDate',
      label: 'Auto-update the modified date',
      description: "Stamp the content type's modified-date field on every field edit.",
      kind: 'boolean',
      value: cfg.content.autoUpdateModifiedDate,
    },
  ];
  return {
    general,
    folders,
    contentTypes: cfg.contentTypes.map((type) => type.name),
  };
}

/** Four steps, not Front Matter's nine: the ones a Jekyll repo actually needs. */
function buildWelcome(cfg: Zer0Config, initialized: boolean, folders: FolderView[]): WelcomeState {
  const hasFolders = folders.length > 0;
  const hasTypes = cfg.contentTypes.length > 0;
  const status = (done: boolean, ready: boolean): WelcomeStep['status'] =>
    done ? 'completed' : ready ? 'active' : 'notStarted';

  const steps: WelcomeStep[] = [
    {
      id: 'welcome-init',
      name: 'Initialize project',
      description:
        `Create ${cfg.configFile} with a starter configuration. Everything else reads from it.`,
      status: status(initialized, true),
      action: { id: 'init', label: 'Initialize project', primary: true },
    },
    {
      id: 'welcome-folders',
      name: 'Register a content folder',
      description:
        'Point zer0-CMS at the directory your markdown lives in. You can also right-click a ' +
        'folder in the explorer and register it there.',
      status: status(hasFolders, initialized),
      action: { id: 'registerFolder', label: 'Register a content folder' },
    },
    {
      id: 'welcome-content-type',
      name: 'Create your first content type',
      description:
        'Generate a content type from a file you already have. It becomes the field set the ' +
        'metadata panel draws.',
      status: status(hasTypes, hasFolders),
      action: { id: 'contentType.generate', label: 'Generate a content type' },
    },
    {
      id: 'welcome-dashboard',
      name: 'Open the dashboard',
      description: 'Once the steps above are done, the Contents view has something to show.',
      status: initialized && hasFolders ? 'active' : 'notStarted',
      action: {
        id: 'dashboard',
        label: 'Open the dashboard',
        disabled: !(initialized && hasFolders),
      },
    },
  ];
  return { steps };
}

// ---------------------------------------------------------------------------
// Custom sorting and grouping
// ---------------------------------------------------------------------------

interface CustomDashboardConfig {
  sorting: SortOption[];
  grouping: GroupOption[];
}

/**
 * User-declared sort and group entries from `zer0.json`.
 *
 * `Zer0Config` has no field for these — they are a dashboard nicety rather
 * than part of the content model — so they are read straight from the project
 * file and coerced defensively. A `customSorting` id follows Front Matter's
 * `<field>-<asc|desc>` convention, which is how the webview knows what to sort
 * by without a second schema.
 */
function customDashboardConfig(): CustomDashboardConfig {
  const dashboard = asRecord(readConfigFileJson().dashboard);
  const sorting: SortOption[] = [];
  const grouping: GroupOption[] = [];
  if (dashboard === undefined) {
    return { sorting, grouping };
  }

  const rawSorting = dashboard.customSorting;
  if (Array.isArray(rawSorting)) {
    for (const entry of rawSorting) {
      const record = asRecord(entry);
      const name = typeof record?.name === 'string' ? record.name : '';
      if (name === '') {
        continue;
      }
      const order = record?.order === 'desc' ? 'desc' : 'asc';
      const id = typeof record?.id === 'string' && record.id !== '' ? record.id : `${name}-${order}`;
      const title = typeof record?.title === 'string' && record.title !== '' ? record.title : name;
      sorting.push({ id, label: `${title} (${order})` });
    }
  }

  const rawGrouping = dashboard.grouping;
  if (Array.isArray(rawGrouping)) {
    for (const entry of rawGrouping) {
      const record = asRecord(entry);
      const name = typeof record?.name === 'string' ? record.name : '';
      if (name === '') {
        continue;
      }
      const title = typeof record?.title === 'string' && record.title !== '' ? record.title : firstToUpper(name);
      grouping.push({ id: `field:${name}`, label: title });
    }
  }
  return { sorting, grouping };
}

// ---------------------------------------------------------------------------
// The page shell
// ---------------------------------------------------------------------------

/** 128 cryptographic bits, regenerated for every render. */
function nonce(): string {
  return randomBytes(16).toString('base64');
}

/**
 * The static shell.
 *
 * **No page title, front-matter value, draft body or guard message is
 * templated in here.** The page ships empty; every character of content
 * arrives over `postMessage` and is written with `textContent` through `el()`.
 * That is what makes `default-src 'none'` a guarantee rather than a decoration.
 *
 * The single templated value is `data-route`, and it is one of five literals
 * from a closed set validated before it gets here — the boot route, which the
 * webview reads once so that reopening the dashboard lands where you left it.
 */
function dashboardHtml(
  webview: vscode.Webview,
  extensionUri: vscode.Uri,
  route: DashboardRoute,
): string {
  const token = nonce();
  const asset = (...parts: string[]): string =>
    webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, ...parts)).toString();

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'nonce-${token}'; script-src 'nonce-${token}'; font-src ${webview.cspSource}; img-src ${webview.cspSource} data: https:;">
<title>zer0-CMS Dashboard</title>
<link nonce="${token}" rel="stylesheet" href="${asset('media', 'tokens.css')}">
<link nonce="${token}" rel="stylesheet" href="${asset('media', 'base.css')}">
<link nonce="${token}" rel="stylesheet" href="${asset('media', 'dashboard.css')}">
</head>
<body>
<div id="z-dashboard" class="z-dash" data-route="${route}"></div>
<script nonce="${token}" src="${asset('dist', 'dashboard.js')}"></script>
</body>
</html>`;
}
