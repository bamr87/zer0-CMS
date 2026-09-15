/**
 * Project-level commands: initialize, refresh, clear cache, show the output
 * channel, register/unregister a content folder, open a file.
 *
 * Two things in here are worth knowing before you change them.
 *
 * **`zer0Cms.init` is reachable in a fresh workspace, on purpose.** Upstream's
 * equivalent was gated on a context key that only got set once a project config
 * already existed, which made "initialize a project" available exactly when you
 * no longer needed it. Ours is on `onCommand:` activation and has no `when`
 * clause, so a workspace with nothing in it can run it from the palette or from
 * the Content view's welcome link. `package.json` and this file agree about
 * that; do not add a `when`.
 *
 * **Folder registration edits `zer0.json`, not settings.** The project *schema*
 * — which folders hold content, what content types exist — lives in the file,
 * because it belongs to the repository and travels with it. The 34 VS Code
 * settings are for preferences. Paths are stored with the `[[workspace]]`
 * token so a checkout at a different location still resolves, and
 * `updateConfigFileJson` reads-modifies-writes rather than serialising a
 * resolved `Zer0Config` back out — that would rewrite every key the author
 * hand-formatted and drop the comments a JSONC file is allowed to have.
 */

import * as path from 'node:path';
import * as vscode from 'vscode';

import {
  DEFAULT_CONTENT_TYPE,
  WORKSPACE_PLACEHOLDER,
  absPath,
  relPath,
  type ContentFolder,
  type Zer0Config,
} from '../core';
import {
  configFilePath,
  currentConfig,
  hasProjectConfig,
  readConfigFileJson,
  updateConfigFileJson,
  workspaceFolder,
  workspaceRoot,
  writeConfigFileJson,
} from '../config';
import type { Zer0Shell } from '../extension';
import { confirm, notifyInfo, notifyWarning, reportError } from '../uiState';

// ---------------------------------------------------------------------------
// Shared helpers (imported by the other command modules)
// ---------------------------------------------------------------------------

/**
 * Register a command and hand its disposable to the extension context.
 *
 * Every command body is wrapped so a rejected promise becomes a notification
 * instead of an "extension host unhandled rejection" nobody sees. A command
 * that wants to report its own error still can — `reportError` is idempotent
 * in effect, and this is the last line of defence, not the first.
 */
export function register(
  shell: Zer0Shell,
  id: string,
  handler: (...args: unknown[]) => unknown,
): void {
  shell.context.subscriptions.push(
    vscode.commands.registerCommand(`zer0Cms.${id}`, (...args: unknown[]) => {
      let result: unknown;
      try {
        result = handler(...args);
      } catch (error) {
        reportError(error, `zer0Cms.${id}`);
        return undefined;
      }
      if (result instanceof Promise) {
        return result.then(undefined, (error: unknown) => {
          reportError(error, `zer0Cms.${id}`);
          return undefined;
        });
      }
      return result;
    }),
  );
}

/**
 * Coerce whatever a caller handed us into an absolute file path.
 *
 * The same command is invoked from four places with four argument shapes: a
 * `Uri` from the explorer context menu, a `TreeItem` from one of the views, a
 * plain string from a webview intent, and nothing at all from the palette. A
 * webview's string may be workspace-relative — it renders relative paths, so it
 * names them that way — which is why the `cfg` is needed to resolve it.
 */
export function toFilePath(cfg: Zer0Config, arg: unknown): string | undefined {
  if (arg instanceof vscode.Uri) {
    return arg.fsPath;
  }
  if (typeof arg === 'string') {
    const value = arg.trim();
    if (value === '') {
      return undefined;
    }
    return path.isAbsolute(value) ? value : absPath(cfg, value);
  }
  if (typeof arg === 'object' && arg !== null) {
    const record = arg as { resourceUri?: unknown; path?: unknown; filePath?: unknown };
    if (record.resourceUri instanceof vscode.Uri) {
      return record.resourceUri.fsPath;
    }
    for (const candidate of [record.filePath, record.path]) {
      if (typeof candidate === 'string' && candidate.trim() !== '') {
        return toFilePath(cfg, candidate);
      }
    }
  }
  return undefined;
}

/**
 * The same coercion, plus **the site that file belongs to**.
 *
 * This is the multi-root half of `toFilePath`, and the reason it exists is a
 * bug class rather than a feature: a command invoked on a file must act on
 * *that file's* site, not on whichever one happens to be active. Approve a
 * draft in one repository while the console is pointed at another and the gate
 * would read the wrong banned-patterns file, the wrong ledger and the wrong
 * publish target — and every one of those would look like it worked.
 *
 * Two passes, in this order, because they answer two different questions:
 *
 *   1. `toFilePath(active, arg)` resolves the argument. A `Uri` or an absolute
 *      path passes straight through; a **relative** string is resolved against
 *      the active site, which is right by construction — a webview renders the
 *      paths of the site it is showing, and that is the active one.
 *   2. The owning folder of the resulting absolute path decides the
 *      configuration. Only when that folder is not the active one is a second
 *      `currentConfig()` paid for; a file outside every open folder falls back
 *      to the active site, which is exactly what happened before multi-root.
 *
 * `currentConfig()` is deliberately uncached (decision D2), so this is two
 * `zer0.json` reads in the worst case — on a user-driven single action. That is
 * the right side of the trade; a cache here would be a cache of the one thing
 * the design says must never be cached.
 */
export function siteTarget(arg: unknown): { cfg: Zer0Config; filePath: string } | undefined {
  const active = currentConfig();
  const filePath = toFilePath(active, arg);
  if (filePath === undefined) {
    return undefined;
  }
  return { cfg: siteConfigFor(filePath, active), filePath };
}

/**
 * The configuration of the site that owns `filePath`, given the active one.
 *
 * Split out because several commands already have the path in hand and only
 * need the second question answered.
 */
export function siteConfigFor(filePath: string, active: Zer0Config = currentConfig()): Zer0Config {
  const owner = workspaceFolder(vscode.Uri.file(filePath));
  if (owner === undefined || owner.uri.fsPath === active.workspaceRoot) {
    return active;
  }
  return currentConfig(owner);
}

/** The active editor's document path, when it is a real file on disk. */
export function activeFilePath(): string | undefined {
  const editor = vscode.window.activeTextEditor;
  if (editor === undefined || editor.document.uri.scheme !== 'file') {
    return undefined;
  }
  return editor.document.uri.fsPath;
}

/** Open a document in the editor. One place, so "open" behaves the same way. */
export async function openInEditor(filePath: string): Promise<void> {
  const document = await vscode.workspace.openTextDocument(vscode.Uri.file(filePath));
  await vscode.window.showTextDocument(document, { preview: false });
}

/**
 * Show a generated report as an untitled document.
 *
 * Untitled rather than written to disk: engine output, guard findings and
 * publish previews are things you read once and close. Writing them would
 * litter the repository with files nobody asked for, and a preview that leaves
 * artifacts behind stops being a preview.
 */
export async function showReport(content: string, language = 'markdown'): Promise<void> {
  const document = await vscode.workspace.openTextDocument({ language, content });
  await vscode.window.showTextDocument(document, { preview: true });
}

// ---------------------------------------------------------------------------
// zer0.json bootstrapping
// ---------------------------------------------------------------------------

/**
 * What `zer0Cms.init` writes into an empty workspace.
 *
 * Deliberately small. It names the two things a CMS cannot infer — where the
 * content lives and what shape it has — and leaves every other key to the
 * defaults, so the file a new user opens is something they can read rather
 * than a 200-line dump of settings they never chose.
 */
export function starterConfig(): Record<string, unknown> {
  return {
    contentFolders: [
      { title: 'Pages', path: `${WORKSPACE_PLACEHOLDER}/pages` },
    ],
    contentTypes: [DEFAULT_CONTENT_TYPE],
  };
}

/** Configured content folders as they appear in `zer0.json`, not resolved. */
function configuredFolders(json: Record<string, unknown>): Array<Record<string, unknown>> {
  const raw = json.contentFolders;
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.filter(
    (entry): entry is Record<string, unknown> =>
      typeof entry === 'object' && entry !== null && !Array.isArray(entry),
  );
}

/** `true` when some configured folder resolves onto `folderPath`. */
export function isRegisteredFolder(cfg: Zer0Config, folderPath: string): boolean {
  const target = path.normalize(folderPath);
  return cfg.contentFolders.some(
    (folder: ContentFolder) => path.normalize(folder.path) === target,
  );
}

// ---------------------------------------------------------------------------
// Registration
// ---------------------------------------------------------------------------

export function registerProjectCommands(shell: Zer0Shell): void {
  // --- Initialize ----------------------------------------------------------
  register(shell, 'init', async () => {
    const root = workspaceRoot();
    const target = configFilePath();
    if (root === undefined || target === undefined) {
      await notifyWarning('open a folder before initializing a project.');
      return;
    }

    if (hasProjectConfig()) {
      await notifyInfo(`${path.basename(target)} already exists — opening it.`);
    } else {
      await writeConfigFileJson(starterConfig());
      shell.log.info(`initialized ${target}`);
    }

    // The context keys and the store both read the file, so both are re-seeded
    // before the editor opens — otherwise the welcome view would still be
    // showing "no zer0.json" behind the document that just created one.
    shell.ui.applyConfig(currentConfig(), hasProjectConfig());
    await openInEditor(target);
    await shell.store.refresh();
  });

  // --- Refresh -------------------------------------------------------------
  register(shell, 'refresh', async () => {
    const snapshot = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Window, title: 'zer0-CMS: refreshing…' },
      () => shell.store.refresh(),
    );
    shell.log.verbose(`refreshed: ${snapshot.pages.length} page(s)`);
  });

  // --- Clear cache ---------------------------------------------------------
  register(shell, 'cache.clear', async () => {
    await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Window, title: 'zer0-CMS: rebuilding the index…' },
      () => shell.store.clearCache(),
    );
    await notifyInfo('page index cache cleared.');
  });

  // --- Output channel ------------------------------------------------------
  register(shell, 'showOutput', () => {
    shell.log.show(false);
  });

  // --- Open a file ---------------------------------------------------------
  // `when: false` in the palette: this exists for tree rows and webview links,
  // which always pass a target. Invoked with nothing, it has nothing to open.
  register(shell, 'openFile', async (arg: unknown) => {
    // `siteTarget` rather than `toFilePath`: opening is harmless either way,
    // but this is the one place every "open this" in the extension funnels
    // through, and resolving the owning site here is what makes a relative
    // path from a webview and an absolute path from another site's tree row
    // both land on the right file.
    const target = siteTarget(arg);
    if (target === undefined) {
      return;
    }
    await openInEditor(target.filePath);
  });

  // --- Register a content folder -------------------------------------------
  register(shell, 'registerFolder', async (arg: unknown) => {
    const folderPath = await resolveFolderArgument(currentConfig(), arg, 'Register content folder');
    if (folderPath === undefined) {
      return;
    }
    // The folder the person clicked decides which site's `zer0.json` is
    // edited. Registering a content folder of site B into site A's config is
    // the multi-root bug this line exists to prevent — and `relative`, below,
    // is what refuses the cross-site case outright.
    const cfg = siteConfigFor(folderPath);
    const scope = vscode.Uri.file(folderPath);

    if (!hasProjectConfig(scope)) {
      const answer = await notifyWarning(
        `no ${cfg.configFile} in this workspace yet.`,
        'Initialize project',
      );
      if (answer !== 'Initialize project') {
        return;
      }
      await writeConfigFileJson(starterConfig(), scope);
    }

    if (isRegisteredFolder(siteConfigFor(folderPath), folderPath)) {
      await notifyInfo(`${path.basename(folderPath)} is already registered.`);
      shell.ui.setFolderRegistered(true);
      return;
    }

    const relative = relPath(cfg, folderPath);
    if (relative.startsWith('..')) {
      await notifyWarning('a content folder must live inside the workspace.');
      return;
    }

    await updateConfigFileJson((json) => {
      const folders = configuredFolders(json);
      folders.push({
        title: path.basename(folderPath),
        path: `${WORKSPACE_PLACEHOLDER}/${relative}`,
      });
      json.contentFolders = folders;
    }, scope);

    shell.ui.setFolderRegistered(true);
    shell.log.info(`registered content folder ${relative}`);
    await notifyInfo(`registered ${relative} as a content folder.`);
    await shell.store.refresh();
  });

  // --- Unregister a content folder -----------------------------------------
  register(shell, 'unregisterFolder', async (arg: unknown) => {
    const folderPath = await resolveFolderArgument(currentConfig(), arg, 'Unregister content folder');
    if (folderPath === undefined) {
      return;
    }

    const cfg = siteConfigFor(folderPath);
    const scope = vscode.Uri.file(folderPath);
    const json = readConfigFileJson(scope);
    const remaining = configuredFolders(json).filter((entry) => {
      const configured = typeof entry.path === 'string' ? entry.path : '';
      return configured === '' || path.normalize(absPath(cfg, configured)) !== path.normalize(folderPath);
    });

    if (remaining.length === configuredFolders(json).length) {
      await notifyInfo(`${path.basename(folderPath)} is not a registered content folder.`);
      shell.ui.setFolderRegistered(false);
      return;
    }

    // Unregistering hides content from every surface at once, so it asks.
    // Nothing on disk is touched — that is exactly why it needs saying.
    const ok = await confirm(
      `Unregister "${path.basename(folderPath)}" as a content folder?`,
      'Unregister',
      'The files stay on disk. They stop appearing in the dashboard, the trees and the index.',
    );
    if (!ok) {
      return;
    }

    await updateConfigFileJson((patch) => {
      patch.contentFolders = remaining;
    }, scope);

    shell.ui.setFolderRegistered(false);
    shell.log.info(`unregistered content folder ${relPath(cfg, folderPath)}`);
    await shell.store.refresh();
  });
}

/**
 * The folder a register/unregister command should act on: the explorer's
 * selection when there is one, otherwise a native folder picker.
 *
 * The picker exists because both commands are reachable from the palette,
 * where there is no selection — and a command that silently does nothing when
 * invoked the wrong way is a command people stop trusting.
 */
async function resolveFolderArgument(
  cfg: Zer0Config,
  arg: unknown,
  title: string,
): Promise<string | undefined> {
  const fromArgument = toFilePath(cfg, arg);
  if (fromArgument !== undefined) {
    return fromArgument;
  }
  const root = workspaceRoot();
  if (root === undefined) {
    await notifyWarning('open a folder first.');
    return undefined;
  }
  const picked = await vscode.window.showOpenDialog({
    title,
    canSelectFiles: false,
    canSelectFolders: true,
    canSelectMany: false,
    defaultUri: vscode.Uri.file(root),
    openLabel: 'Select folder',
  });
  return picked?.[0]?.fsPath;
}
