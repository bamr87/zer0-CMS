/**
 * The site registry — the thing that makes "many sites" real.
 *
 * Until this file existed, every surface in the extension resolved
 * `vscode.workspace.workspaceFolders[0]`. That is a correct answer for a
 * one-folder window and a wrong one for the workspace this fleet actually
 * opens: twelve folders, seven of them Jekyll sites this extension can detect
 * and audit and two of them carrying a project config, eleven of them invisible. The registry keeps **one `WorkspaceStore` per open
 * folder**, decides which of them is active, and installs itself as
 * `config.ts`'s `ActiveFolderResolver` so that `currentConfig()` with no
 * argument stops meaning "folder zero" and starts meaning "the site the person
 * is looking at" — without a single existing call site having to pass anything.
 *
 * Four properties are load-bearing:
 *
 *   - **Activation still scans nothing.** Constructing N stores is N sets of
 *     watchers and zero reads: `WorkspaceStore`'s constructor installs
 *     watchers, and nothing here calls `refresh()`. The first scan is the
 *     background one `extension.ts` kicks off for the active site; the others
 *     scan when something asks them to (`refreshAll()`, from the Sites tab).
 *     A folderless window therefore still installs **zero** watchers, because
 *     there are zero folders and so zero stores.
 *   - **Only the active site's id is persisted.** `workspaceState` holds one
 *     string. A per-site cache of anything else here would be a second copy of
 *     what the stores already hold, and the two would disagree.
 *   - **The rule is pure and lives in `siteRule.ts`.** See that file.
 *   - **Detection is memoised per folder, never re-probed per render.** A
 *     folder whose store has a snapshot reports that snapshot's
 *     `ResolvedPlatform`, which is the one the index was built under; a folder
 *     that has never been scanned is probed once — a handful of `stat`s — and
 *     the answer is cached until the folder set changes. `currentConfig()`
 *     stays uncached (decision D2); this caches a *probe*, not a config.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import * as vscode from 'vscode';

import {
  absPath,
  detectPlatform,
  relPath,
  type PlatformIo,
  type ResolvedPlatform,
  type Zer0Config,
} from './core';
import {
  currentConfig,
  hasProjectConfig,
  setActiveFolderResolver,
  workspaceTrusted,
} from './config';
import { describeError, log as sharedLog } from './logger';
import { resolveActiveSite } from './siteRule';
import { WorkspaceStore, type Snapshot } from './store';
import type { SitesState, SiteView } from './webview/shared/protocol';

export { resolveActiveSite } from './siteRule';

/**
 * Where the active site's id is remembered between windows.
 *
 * One key, one string, and deliberately not one of the seven legacy
 * `UI_STATE_KEYS`: those are per-window UI preferences that predate multi-root
 * and must keep their exact names, and this is the only new row that is about
 * *which site*.
 */
export const ACTIVE_SITE_KEY = 'zer0Cms:Sites:Active';

/** One open workspace folder, with the store that reads it. */
export interface Site {
  /** `folder.uri.toString()` — stable, unique, and safe in a Memento. */
  readonly id: string;
  readonly folder: vscode.WorkspaceFolder;
  /** The folder's own name, as the workspace file or the path gave it. */
  readonly name: string;
  /** This folder's snapshot. Scoped to it: its config, watchers and cache key. */
  readonly store: WorkspaceStore;
  /** `true` when a project config exists in this folder, read fresh. */
  configured(): boolean;
}

/** Options a test uses to keep a registry out of the real `workspaceState`. */
export interface SiteRegistryOptions {
  /** Defaults to `context.workspaceState`. */
  state?: vscode.Memento;
  log?: typeof sharedLog;
}

/** The `uri` every `ConfigurationScope` variant either is or carries. */
function scopeUri(scope: vscode.ConfigurationScope | undefined): vscode.Uri | undefined {
  if (scope === undefined || scope === null) {
    return undefined;
  }
  if (scope instanceof vscode.Uri) {
    return scope;
  }
  return (scope as { uri?: vscode.Uri }).uri;
}

/** Workspace-relative reads for the platform prober. Bounded, and only on demand. */
function siteIo(root: string): PlatformIo {
  return {
    async exists(rel: string): Promise<boolean> {
      try {
        await vscode.workspace.fs.stat(vscode.Uri.file(path.join(root, rel)));
        return true;
      } catch {
        return false;
      }
    },
    async read(rel: string): Promise<string | undefined> {
      try {
        const bytes = await vscode.workspace.fs.readFile(vscode.Uri.file(path.join(root, rel)));
        return Buffer.from(bytes).toString('utf8');
      } catch {
        return undefined;
      }
    },
  };
}

/**
 * Every open folder, which one is active, and one store each.
 *
 * Constructed once, at step 2.5 of `activate()`, before anything reads a
 * configuration — it installs the resolver in its constructor, and a
 * `currentConfig()` that ran first would have answered for folder zero.
 */
export class SiteRegistry implements vscode.Disposable {
  private readonly emitter = new vscode.EventEmitter<void>();

  /** Fires when the folder set changes, the active site changes, or any site's store rebuilds. */
  readonly onDidChange: vscode.Event<void> = this.emitter.event;

  private readonly state: vscode.Memento;
  private readonly log: typeof sharedLog;
  private readonly subscriptions: vscode.Disposable[] = [];
  private readonly storeSubscriptions = new Map<string, vscode.Disposable>();
  private readonly probed = new Map<string, ResolvedPlatform>();

  private sites = new Map<string, Site>();
  /** The id a person picked, whether or not it still exists. */
  private explicit: string | undefined;
  private activeId: string | undefined;
  private disposed = false;

  constructor(context: vscode.ExtensionContext, options: SiteRegistryOptions = {}) {
    this.state = options.state ?? context.workspaceState;
    this.log = options.log ?? sharedLog;

    const remembered = this.state.get<unknown>(ACTIVE_SITE_KEY);
    this.explicit = typeof remembered === 'string' && remembered !== '' ? remembered : undefined;

    // Installed before the first store is constructed: a store's constructor
    // calls `currentConfig(folder)`, and that call goes through this resolver.
    setActiveFolderResolver((scope) => this.folderFor(scope));

    this.rebuild();

    this.subscriptions.push(
      vscode.workspace.onDidChangeWorkspaceFolders(() => {
        this.rebuild();
        this.emitter.fire();
      }),
      // With no explicit pick, the file in front of the person decides. With
      // one, this changes nothing — see `resolveActiveSite`.
      vscode.window.onDidChangeActiveTextEditor(() => {
        if (this.reresolve()) {
          this.emitter.fire();
        }
      }),
    );
  }

  // -------------------------------------------------------------------------
  // Reading
  // -------------------------------------------------------------------------

  /** Every open folder, in the workspace's own order. */
  all(): readonly Site[] {
    return [...this.sites.values()];
  }

  /** The active site, or `undefined` in a folderless window. */
  active(): Site | undefined {
    return this.activeId === undefined ? undefined : this.sites.get(this.activeId);
  }

  /** The active site's store — what `Zer0Shell.store` should return. */
  activeStore(): WorkspaceStore | undefined {
    return this.active()?.store;
  }

  /** More than one folder is open: the switcher, the tree and the key are worth having. */
  multi(): boolean {
    return this.sites.size > 1;
  }

  /** The site that owns `uri`, or `undefined` when it belongs to no open folder. */
  forUri(uri: vscode.Uri): Site | undefined {
    const owner = vscode.workspace.getWorkspaceFolder(uri);
    return owner === undefined ? undefined : this.sites.get(owner.uri.toString());
  }

  /** The site with this id, or `undefined`. The host's own allow-list for a webview message. */
  byId(id: string): Site | undefined {
    return this.sites.get(id);
  }

  // -------------------------------------------------------------------------
  // Writing
  // -------------------------------------------------------------------------

  /**
   * Make one site active. Returns `false` — and changes nothing — for an id
   * this registry does not hold.
   *
   * That check is the whole reason the webview may send an id: a message names
   * a target, the host validates it against its own state, and a forged or
   * stale id is dropped rather than dispatched (decision D5).
   */
  setActive(id: string): boolean {
    if (!this.sites.has(id)) {
      this.log.warn(`site: refused to activate "${id}" — no such folder is open`);
      return false;
    }
    this.explicit = id;
    void this.state.update(ACTIVE_SITE_KEY, id).then(undefined, (error: unknown) => {
      this.log.warn(`site: could not persist the active site (${describeError(error)})`);
    });
    if (this.activeId !== id) {
      this.activeId = id;
      this.log.info(`site: active is now ${this.sites.get(id)?.name ?? id}`);
    }
    this.emitter.fire();
    return true;
  }

  /**
   * Refresh every site's snapshot.
   *
   * Deliberately not called at activation — that is what would turn N stores
   * into N scans. The Sites surfaces call it, because a table of per-site page
   * counts is a person asking for exactly that work.
   */
  async refreshAll(): Promise<void> {
    await Promise.all(
      this.all().map((site) =>
        site.store.refresh().then(
          () => undefined,
          (error: unknown) => {
            this.log.warn(`site ${site.name}: refresh failed (${describeError(error)})`);
          },
        ),
      ),
    );
  }

  // -------------------------------------------------------------------------
  // The view model
  // -------------------------------------------------------------------------

  /**
   * What this folder is, and what said so.
   *
   * A scanned site answers from its snapshot — the same `ResolvedPlatform` the
   * page index was built under, so the Sites tab and the Contents tab cannot
   * disagree about what kind of site this is. An unscanned one is probed once
   * and remembered, because "unknown" in that column is a worse answer than a
   * `stat` of `_config.yml`.
   */
  async platformOf(site: Site): Promise<ResolvedPlatform> {
    const snapshot = site.store.peek();
    if (snapshot !== undefined) {
      return snapshot.platform;
    }
    const cached = this.probed.get(site.id);
    if (cached !== undefined) {
      return cached;
    }
    const cfg = currentConfig(site.folder);
    const resolved = await detectPlatform(cfg.workspaceRoot, siteIo(cfg.workspaceRoot), cfg.platform);
    this.probed.set(site.id, resolved);
    return resolved;
  }

  /** One row per open folder, as the Sites tab and the Sites tree draw them. */
  async views(): Promise<SiteView[]> {
    const trusted = workspaceTrusted();
    return Promise.all(
      this.all().map(async (site): Promise<SiteView> => {
        const cfg = currentConfig(site.folder);
        const platform = await this.platformOf(site);
        const snapshot = site.store.peek();
        return {
          id: site.id,
          name: site.name,
          root: site.folder.uri.fsPath,
          scheme: site.folder.uri.scheme,
          platform: platform.profile.id,
          overlay: platform.profile.overlay,
          detectionSource: snapshot === undefined ? `${platform.source} (not scanned)` : platform.source,
          configured: site.configured(),
          contentRoots: cfg.contentFolders.map((folder) => relPath(cfg, folder.path)),
          manifestPresent: manifestPresent(cfg),
          trusted,
          counts: {
            pages: snapshot?.pages.length ?? 0,
            drafts: snapshot?.drafts.length ?? 0,
          },
          active: site.id === this.activeId,
        };
      }),
    );
  }

  /** The whole slice, ready to drop into `DashboardState.sites`. */
  async sitesState(): Promise<SitesState> {
    return {
      sites: await this.views(),
      activeId: this.activeId ?? null,
      multi: this.multi(),
    };
  }

  // -------------------------------------------------------------------------
  // Internals
  // -------------------------------------------------------------------------

  /**
   * `config.ts`'s `ActiveFolderResolver`: which folder is this call about?
   *
   * A scope that names a file answers with the folder that owns it — that is
   * what makes a command invoked on a file act on *that file's* site. Anything
   * else answers with the active site, which is this whole file's point.
   */
  private folderFor(scope?: vscode.ConfigurationScope): vscode.WorkspaceFolder | undefined {
    const uri = scopeUri(scope);
    if (uri !== undefined) {
      const owner = vscode.workspace.getWorkspaceFolder(uri);
      if (owner !== undefined) {
        return owner;
      }
    }
    return this.active()?.folder;
  }

  /** The id of the folder owning the active editor, when there is one. */
  private editorFolderId(): string | undefined {
    const editor = vscode.window.activeTextEditor;
    if (editor === undefined) {
      return undefined;
    }
    const owner = vscode.workspace.getWorkspaceFolder(editor.document.uri);
    return owner?.uri.toString();
  }

  /** Re-run the rule. Returns `true` when the active site actually moved. */
  private reresolve(): boolean {
    const next = resolveActiveSite([...this.sites.keys()], this.explicit, this.editorFolderId());
    if (next === this.activeId) {
      return false;
    }
    this.activeId = next;
    return true;
  }

  /**
   * Build the site map from the folders that are open right now.
   *
   * Stores are *kept* across a rebuild whenever their folder is still open —
   * disposing and re-creating one would drop its snapshot, its watchers and its
   * cache for no reason. Removed folders' stores are disposed, which is what
   * takes their watchers down with them.
   */
  private rebuild(): void {
    const folders = vscode.workspace.workspaceFolders ?? [];
    const next = new Map<string, Site>();

    // The active id is resolved from the *new* folder list before any store is
    // constructed, because a store's constructor reads `currentConfig(folder)`
    // and that call comes back through `folderFor`.
    this.activeId = resolveActiveSite(
      folders.map((folder) => folder.uri.toString()),
      this.explicit,
      this.editorFolderId(),
    );

    for (const folder of folders) {
      const id = folder.uri.toString();
      const existing = this.sites.get(id);
      next.set(id, existing ?? this.makeSite(id, folder));
    }

    for (const [id, site] of this.sites) {
      if (!next.has(id)) {
        this.storeSubscriptions.get(id)?.dispose();
        this.storeSubscriptions.delete(id);
        this.probed.delete(id);
        site.store.dispose();
      }
    }

    this.sites = next;
    this.log.verbose(`sites: ${this.sites.size} folder(s), active ${this.active()?.name ?? '(none)'}`);
  }

  private makeSite(id: string, folder: vscode.WorkspaceFolder): Site {
    const store = new WorkspaceStore({ state: this.state, log: this.log, folder });
    // Forwarded so the Sites tree and the Sites tab update when *any* site
    // rebuilds, not only the active one. The dashboard already listens to the
    // active store; this is what makes the other eleven rows honest.
    this.storeSubscriptions.set(
      id,
      store.onDidChange(() => {
        this.probed.delete(id);
        this.emitter.fire();
      }),
    );
    return {
      id,
      folder,
      name: folder.name,
      store,
      configured: () => hasProjectConfig(folder),
    };
  }

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    // Put `currentConfig()` back on its default answer before the stores go:
    // a resolver whose registry has been disposed would answer `undefined` for
    // every call in a window that still has folders open.
    setActiveFolderResolver(null);
    for (const subscription of this.storeSubscriptions.values()) {
      subscription.dispose();
    }
    this.storeSubscriptions.clear();
    for (const site of this.sites.values()) {
      site.store.dispose();
    }
    this.sites = new Map<string, Site>();
    for (const subscription of this.subscriptions) {
      subscription.dispose();
    }
    this.subscriptions.length = 0;
    this.emitter.dispose();
  }
}

/**
 * The two members every tree view actually uses from a `WorkspaceStore`.
 *
 * `WorkspaceStore` has private fields, so a plain object can never be
 * *assignable* to it — which is why the four legacy tree providers, whose
 * constructors name the class, cannot be handed anything that follows the
 * active site. Widening their parameter to this interface is a one-word change
 * each and costs nothing: a real `WorkspaceStore` satisfies it.
 */
export interface StoreView {
  readonly onDidChange: vscode.Event<void>;
  current(): Promise<Snapshot>;
}

/**
 * A store-shaped view of **whichever site is active**, for the four trees that
 * render the active site's content.
 *
 * The alternative — giving those trees their own folderless `WorkspaceStore`,
 * which the resolver would also point at the active site — would double every
 * watcher and every scan on that folder, and both copies would write the same
 * `workspaceState` cache key. One store per folder, and this view on top of it.
 *
 * `onDidChange` is the registry's, not one store's, so a tree re-reads both when
 * its site rebuilds *and* when the active site moves out from under it.
 */
export function activeStoreView(registry: SiteRegistry, folderless: StoreView): StoreView {
  return {
    onDidChange: registry.onDidChange,
    current: () => (registry.activeStore() ?? folderless).current(),
  };
}

/**
 * Does this site carry a fleet manifest?
 *
 * `existsSync` rather than a read: the Sites table reports presence, and the
 * Fleet tab is where the file is parsed. One `stat` per row per render is the
 * cheapest honest answer, and it is only ever asked from a surface a person
 * opened.
 */
function manifestPresent(cfg: Zer0Config): boolean {
  if (cfg.workspaceRoot === '') {
    return false;
  }
  try {
    return fs.existsSync(absPath(cfg, cfg.fleet.manifestPath));
  } catch {
    return false;
  }
}
