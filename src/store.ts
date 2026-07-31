/**
 * One snapshot of the workspace, shared by everything that renders it.
 *
 * Four tree views, the metadata panel and the dashboard all need the same
 * answers — what pages exist, what is in the draft queue, what the ledger says
 * was published, what the `.cms/` contract thinks, what the catering lanes
 * hold. Each of them re-deriving that from disk would mean six scans per
 * keystroke and six chances to disagree with each other. So the disk is read
 * here, once, into a `Snapshot`, and every surface reads the same object.
 *
 * Three properties are load-bearing:
 *
 *   - **Refresh coalesces.** Five concurrent `refresh()` calls share one
 *     rebuild and one `onDidChange` event. Bursts from file watchers are
 *     additionally debounced, and a burst that lands mid-rebuild re-arms the
 *     timer rather than joining the in-flight promise — otherwise the change
 *     that triggered it would be missed by exactly one generation.
 *   - **Watchers are rebuilt, never accumulated.** A settings change, a
 *     `zer0.json` change or a workspace-folder change disposes every watcher
 *     and installs the set the new configuration asks for. Content folders are
 *     configuration, so a config change is a watcher change.
 *   - **A folderless window costs nothing.** No watchers, no `fs` calls, and a
 *     valid empty snapshot so the trees render "nothing here" instead of
 *     throwing.
 */

import * as path from 'node:path';
import * as vscode from 'vscode';

import {
  absPath,
  asIndexCache,
  buildCatering,
  buildIndex,
  distributable,
  listQueue,
  loadContract,
  loadLedger,
  loadPerformance,
  pageToRecord,
  publishedSourceFiles,
  shareEntries,
  type CateringPlan,
  type ContentRecord,
  type Contract,
  type DraftFile,
  type IndexCache,
  type Ledger,
  type LedgerEntry,
  type LogSink,
  type PageEntry,
  type PerfStats,
  type Zer0Config,
} from './core';
import { currentConfig, onConfigChange, workspaceRoot } from './config';
import { describeError, log as sharedLog } from './logger';

/** Everything the UI reads, as of one moment. Treat it as immutable. */
export interface Snapshot {
  cfg: Zer0Config;
  /** Every content file the page index found. */
  pages: PageEntry[];
  /** `.cms/`, or the page index standing in for it (decision D9). */
  contract: Contract;
  /** Publishable records, best health first. */
  distributable: ContentRecord[];
  /** The governed queue, in queue order. */
  drafts: DraftFile[];
  ledger: Ledger;
  /** Ledger shares as `[canonicalUrl, entry]`, metadata keys excluded. */
  published: Array<[string, LedgerEntry]>;
  /** Workspace-relative source paths that already have a ledger record. */
  publishedSourceFiles: Set<string>;
  catering: CateringPlan;
  performance: Record<string, PerfStats>;
}

/** Where the mtime-keyed page-index cache lives between windows. */
export const INDEX_CACHE_KEY = 'zer0Cms.pageIndex.v1';

/** File-watcher bursts are collapsed over this window. */
const DEBOUNCE_MS = 250;

export interface WorkspaceStoreOptions {
  /** `context.workspaceState`. Omit it and the page index rebuilds each time. */
  state?: vscode.Memento;
  log?: LogSink;
}

/** A snapshot with no disk behind it — the folderless-window answer. */
export function emptySnapshot(cfg: Zer0Config): Snapshot {
  const contract: Contract = {
    root: cfg.workspaceRoot,
    dir: '',
    present: false,
    generatedAt: '',
    records: [],
    summary: {},
  };
  return {
    cfg,
    pages: [],
    contract,
    distributable: [],
    drafts: [],
    ledger: {},
    published: [],
    publishedSourceFiles: new Set<string>(),
    // Pure: four empty lanes, no I/O, and the same object shape the real path
    // produces — so the dashboard has one code path, not two.
    catering: buildCatering(contract, {}, new Set<string>()),
    performance: {},
  };
}

export class WorkspaceStore implements vscode.Disposable {
  private readonly emitter = new vscode.EventEmitter<void>();

  /** Fires after every successful rebuild, with no payload: read `current()`. */
  readonly onDidChange: vscode.Event<void> = this.emitter.event;

  private readonly log: LogSink;
  private readonly state: vscode.Memento | undefined;
  private readonly subscriptions: vscode.Disposable[] = [];
  private watchers: vscode.FileSystemWatcher[] = [];

  private snapshot: Snapshot | undefined;
  private inFlight: Promise<Snapshot> | undefined;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private disposed = false;

  constructor(options: WorkspaceStoreOptions = {}) {
    this.log = options.log ?? sharedLog;
    this.state = options.state;

    this.subscriptions.push(
      onConfigChange(() => {
        this.installWatchers();
        this.scheduleRefresh();
      }),
      vscode.workspace.onDidChangeWorkspaceFolders(() => {
        this.installWatchers();
        this.scheduleRefresh();
      }),
    );
    this.installWatchers();
  }

  // -------------------------------------------------------------------------
  // Reading
  // -------------------------------------------------------------------------

  /** The current snapshot, building one on first use. */
  async current(): Promise<Snapshot> {
    if (this.snapshot !== undefined) {
      return this.snapshot;
    }
    return this.refresh();
  }

  /**
   * The snapshot if one has been built, without building one. For synchronous
   * callers — a `TreeItem` label, a status-bar update — that would rather show
   * nothing for one frame than block.
   */
  peek(): Snapshot | undefined {
    return this.snapshot;
  }

  /**
   * Rebuild. Concurrent calls share the in-flight promise, so five callers
   * cause exactly one scan and exactly one `onDidChange`.
   */
  async refresh(): Promise<Snapshot> {
    if (this.inFlight !== undefined) {
      return this.inFlight;
    }
    this.inFlight = this.rebuild().finally(() => {
      this.inFlight = undefined;
    });
    return this.inFlight;
  }

  /**
   * Ask for a rebuild soon. Watcher events land in bursts (a `git checkout`
   * touches hundreds of files), and a rebuild per event would be pointless
   * work. If a rebuild is already running the timer is re-armed rather than
   * joined: the change that triggered this call happened *after* that rebuild
   * started reading, so joining it would return a snapshot that cannot contain
   * the change.
   */
  scheduleRefresh(): void {
    if (this.disposed) {
      return;
    }
    if (this.timer !== undefined) {
      clearTimeout(this.timer);
    }
    this.timer = setTimeout(() => {
      this.timer = undefined;
      if (this.inFlight !== undefined) {
        this.scheduleRefresh();
        return;
      }
      void this.refresh().then(undefined, (error: unknown) => {
        this.log.error(`refresh failed: ${describeError(error)}`);
      });
    }, DEBOUNCE_MS);
  }

  /** Drop the persisted page-index cache and rebuild from the filesystem. */
  async clearCache(): Promise<Snapshot> {
    if (this.state !== undefined) {
      await this.state.update(INDEX_CACHE_KEY, undefined);
    }
    this.snapshot = undefined;
    this.log.info('page index cache cleared');
    return this.refresh();
  }

  // -------------------------------------------------------------------------
  // Building
  // -------------------------------------------------------------------------

  private async rebuild(): Promise<Snapshot> {
    const started = Date.now();
    const cfg = currentConfig();

    if (cfg.workspaceRoot === '') {
      // Folderless window. Not an error state — just one with no disk.
      const snapshot = emptySnapshot(cfg);
      this.snapshot = snapshot;
      this.emitter.fire();
      return snapshot;
    }

    let snapshot: Snapshot;
    try {
      snapshot = await this.readWorkspace(cfg);
    } catch (error) {
      // A snapshot is what four trees and two webviews render from. Failing to
      // build one must degrade to "empty", never to a rejected promise that
      // every consumer would have to catch.
      this.log.error(`snapshot build failed: ${describeError(error)}`);
      snapshot = emptySnapshot(cfg);
    }

    this.snapshot = snapshot;
    this.log.verbose(
      `snapshot: ${snapshot.pages.length} page(s), ${snapshot.drafts.length} draft(s), ` +
        `${snapshot.published.length} published, contract ${snapshot.contract.present ? 'present' : 'absent'} ` +
        `(${Date.now() - started}ms)`,
    );
    this.emitter.fire();
    return snapshot;
  }

  private async readWorkspace(cfg: Zer0Config): Promise<Snapshot> {
    const draftsDir = absPath(cfg, cfg.governance.draftsFolder);
    const ledgerPath = absPath(cfg, cfg.governance.ledgerPath);
    const contractDir = absPath(cfg, cfg.cms.root);

    const [index, contract, ledger, drafts] = await Promise.all([
      buildIndex(cfg, this.readIndexCache(), this.log),
      loadContract(cfg.workspaceRoot, { dir: contractDir }),
      loadLedger(ledgerPath),
      cfg.governance.enabled ? listQueue(draftsDir) : Promise.resolve<DraftFile[]>([]),
    ]);

    this.writeIndexCache(index.cache);

    // Decision D9: with no `.cms/` the page index supplies the same record
    // shape with `health: -1`. Projecting the index we already built keeps that
    // to one scan — `loadContractOrScan` would run a second one.
    if (!contract.present) {
      contract.records = index.pages.map((page) => pageToRecord(cfg, page));
    }

    const performance = await loadPerformance(contract);
    const published = publishedSourceFiles(ledger);

    return {
      cfg,
      pages: index.pages,
      contract,
      distributable: distributable(contract),
      drafts,
      ledger,
      published: shareEntries(ledger),
      publishedSourceFiles: published,
      catering: buildCatering(contract, performance, published),
      performance,
    };
  }

  private readIndexCache(): IndexCache | undefined {
    if (this.state === undefined) {
      return undefined;
    }
    // Anything that is not a v1 cache is treated as no cache: a bad cache must
    // cost a rescan, never a wrong page list.
    return asIndexCache(this.state.get<unknown>(INDEX_CACHE_KEY));
  }

  private writeIndexCache(cache: IndexCache): void {
    if (this.state === undefined) {
      return;
    }
    void this.state.update(INDEX_CACHE_KEY, cache).then(undefined, (error: unknown) => {
      this.log.warn(`could not persist the page index cache: ${describeError(error)}`);
    });
  }

  // -------------------------------------------------------------------------
  // Watchers
  // -------------------------------------------------------------------------

  /**
   * Dispose every watcher and install the set this configuration asks for.
   *
   * Called on construction, on a settings change, on a `zer0.json` change and
   * on a workspace-folder change — all four can move the folders being
   * watched, so all four rebuild rather than patch.
   */
  private installWatchers(): void {
    for (const watcher of this.watchers) {
      watcher.dispose();
    }
    this.watchers = [];

    const root = workspaceRoot();
    if (root === undefined) {
      // The folderless-window guarantee: zero watchers, zero file-system reads.
      return;
    }

    let cfg: Zer0Config;
    try {
      cfg = currentConfig();
    } catch (error) {
      this.log.warn(`watchers not installed: ${describeError(error)}`);
      return;
    }

    const patterns: vscode.RelativePattern[] = [
      // The project config itself. Both conventional locations are watched, so
      // creating `zer0.json` in a workspace that had none lights the extension
      // up without a reload.
      new vscode.RelativePattern(root, cfg.configFile),
      new vscode.RelativePattern(root, 'zer0.json'),
      new vscode.RelativePattern(root, '.zer0/config.json'),
      // The engine's output.
      new vscode.RelativePattern(vscode.Uri.file(absPath(cfg, cfg.cms.root)), '**/*'),
    ];

    if (cfg.governance.enabled) {
      patterns.push(
        // Top-level `*.md` only: the queue is flat by definition, and a
        // recursive pattern would watch every attachment beside it.
        new vscode.RelativePattern(vscode.Uri.file(absPath(cfg, cfg.governance.draftsFolder)), '*.md'),
      );
      const ledgerPath = absPath(cfg, cfg.governance.ledgerPath);
      patterns.push(
        new vscode.RelativePattern(vscode.Uri.file(path.dirname(ledgerPath)), path.basename(ledgerPath)),
      );
    }

    for (const folder of cfg.contentFolders) {
      patterns.push(new vscode.RelativePattern(vscode.Uri.file(folder.path), '**/*'));
    }

    for (const pattern of patterns) {
      const watcher = vscode.workspace.createFileSystemWatcher(pattern);
      const kick = (): void => this.scheduleRefresh();
      watcher.onDidCreate(kick);
      watcher.onDidChange(kick);
      watcher.onDidDelete(kick);
      this.watchers.push(watcher);
    }
    this.log.verbose(`watching ${this.watchers.length} pattern(s)`);
  }

  /** How many watchers are installed. The folderless-window test reads this. */
  get watcherCount(): number {
    return this.watchers.length;
  }

  dispose(): void {
    this.disposed = true;
    if (this.timer !== undefined) {
      clearTimeout(this.timer);
      this.timer = undefined;
    }
    for (const watcher of this.watchers) {
      watcher.dispose();
    }
    this.watchers = [];
    for (const subscription of this.subscriptions) {
      subscription.dispose();
    }
    this.subscriptions.length = 0;
    this.emitter.dispose();
  }
}
