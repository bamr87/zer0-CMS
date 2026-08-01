/**
 * Content commands: create, slug, last-modified, insert image, and the three
 * that steer the metadata panel.
 *
 * ### Every write goes through the core
 *
 * Nothing in this file formats front matter. `createContent` decides the path
 * and the fields, `renderContentFile` produces the bytes, `writeArticle`
 * performs the line surgery that changes only the keys that changed (decision
 * D7). This module's job is to *ask the questions* — which folder, which
 * content type, what title — and to hand the answers over. When you find
 * yourself writing a `---` here, you are in the wrong file.
 *
 * ### The editor is saved before the file is rewritten
 *
 * `writeArticle` writes to disk. If the document were dirty, that write and the
 * user's unsaved buffer would be two versions of the same file racing to be
 * last. So a dirty document is saved first, deliberately and visibly, rather
 * than silently rewriting under an editor that will happily overwrite us back.
 *
 * ### The panel bridge
 *
 * `collapseSections`, `focusTags` and `focusCategories` are commands whose
 * whole effect is inside a webview: close every section, move focus into the
 * tags field. The host cannot do that itself — it can only post a message. The
 * panel host (`src/panel/panelProvider.ts`) registers itself here with
 * `setPanelBridge()`, and these commands call through it; with nothing
 * registered they still reveal the view and log, rather than throwing.
 *
 * The dependency points this way (panel → commands, never commands → panel) so
 * that the command palette keeps working in a window where the panel has never
 * been opened, and so this module has no import edge into the webview layer.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import * as vscode from 'vscode';

import {
  alignedFilePath,
  asString,
  createContent,
  createSlug,
  decorateSlug,
  folderForFile,
  getContentTypes,
  humanize,
  isSupported,
  readArticle,
  relPath,
  renderContentFile,
  resolveContentType,
  resolveFolders,
  stampModified,
  writeArticle,
  type Article,
  type ContentFolder,
  type ContentType,
  type CreateContentRequest,
  type Zer0Config,
} from '../core';
import { currentConfig } from '../config';
import type { Zer0Shell } from '../extension';
import { describeError } from '../logger';
import { isEditableDocument, notifyInfo, notifyWarning } from '../uiState';
import { openInEditor, register, toFilePath } from './project';

// ---------------------------------------------------------------------------
// The panel bridge
// ---------------------------------------------------------------------------

/**
 * The two imperative things a command can ask the metadata panel to do.
 *
 * Implemented by `PanelProvider`, which calls `setPanelBridge(this)` when it
 * resolves its view. Both methods are fire-and-forget: the panel may not be
 * visible, and a command that awaited a webview's acknowledgement would hang
 * whenever it is not.
 */
export interface PanelBridge {
  /** Post `{ type: 'collapseAll' }` to the panel webview. */
  collapseAll(): void;
  /** Post `{ type: 'focus', target }` to the panel webview. */
  focus(target: 'tags' | 'categories'): void;
}

let panelBridge: PanelBridge | undefined;

/**
 * Install the panel bridge. Returns a disposable that removes it again — and
 * only if it is still the one installed, so a panel that is disposed *after* a
 * replacement registered cannot unhook the replacement.
 */
export function setPanelBridge(bridge: PanelBridge): vscode.Disposable {
  panelBridge = bridge;
  return new vscode.Disposable(() => {
    if (panelBridge === bridge) {
      panelBridge = undefined;
    }
  });
}

/** The bridge, for tests and for the handful of callers that must check. */
export function panelBridgeInstalled(): boolean {
  return panelBridge !== undefined;
}

// ---------------------------------------------------------------------------
// Shared helpers (imported by contentType.ts)
// ---------------------------------------------------------------------------

export interface ActiveArticle {
  cfg: Zer0Config;
  filePath: string;
  article: Article;
  contentType: ContentType;
}

/**
 * The active editor as a parsed article, or `undefined` with the reason
 * already shown to the user.
 *
 * Saves a dirty document first — see the header. Every command that edits front
 * matter starts here, so the "is this a file I may touch?" question has exactly
 * one answer in the shell.
 */
export async function activeArticle(): Promise<ActiveArticle | undefined> {
  const editor = vscode.window.activeTextEditor;
  const cfg = currentConfig();

  if (editor === undefined || !isEditableDocument(cfg, editor.document)) {
    await notifyWarning('open a content file first.');
    return undefined;
  }
  if (editor.document.isDirty) {
    // Saving is not a courtesy here: the write below replaces the file on disk,
    // and an unsaved buffer would overwrite it the moment the user hits save.
    await editor.document.save();
  }

  const filePath = editor.document.uri.fsPath;
  const article = await readArticle(filePath);
  return {
    cfg,
    filePath,
    article,
    contentType: resolveContentType(cfg, article.data, filePath),
  };
}

/** Folders new content may be created in, `disableCreation` honoured. */
async function creatableFolders(cfg: Zer0Config): Promise<ContentFolder[]> {
  const folders = await resolveFolders(cfg);
  return folders.filter((folder) => folder.disableCreation !== true);
}

/** Ask which folder, skipping the question when there is only one answer. */
async function pickFolder(folders: ContentFolder[]): Promise<ContentFolder | undefined> {
  const only = folders[0];
  if (only !== undefined && folders.length === 1) {
    return only;
  }
  const picked = await vscode.window.showQuickPick(
    folders.map((folder) => ({
      label: folder.title,
      description: folder.originalPath ?? folder.path,
      folder,
    })),
    { placeHolder: 'Select a content folder', ignoreFocusOut: true },
  );
  return picked?.folder;
}

/**
 * Ask which content type. A folder that binds exactly one type does not ask —
 * it has already answered — and a folder that binds several offers only those.
 */
async function pickContentType(
  cfg: Zer0Config,
  folder: ContentFolder | undefined,
): Promise<ContentType | undefined> {
  const all = getContentTypes(cfg);
  const bound = folder?.contentTypes ?? [];
  const candidates =
    bound.length > 0 ? all.filter((ct) => bound.includes(ct.name)) : all;

  const only = candidates[0];
  if (only !== undefined && candidates.length === 1) {
    return only;
  }
  if (candidates.length === 0) {
    await notifyWarning(
      `no content type matches this folder (it declares: ${bound.join(', ') || 'none'}).`,
    );
    return undefined;
  }

  const picked = await vscode.window.showQuickPick(
    candidates.map((ct) => ({
      label: ct.name,
      description: `${ct.fields.length} field${ct.fields.length === 1 ? '' : 's'}`,
      contentType: ct,
    })),
    { placeHolder: 'Select a content type', ignoreFocusOut: true },
  );
  return picked?.contentType;
}

/** The whole create sequence, shared by both create commands. */
async function createInto(
  shell: Zer0Shell,
  folder: ContentFolder,
  subFolder: string | undefined,
): Promise<void> {
  const cfg = currentConfig();
  const contentType = await pickContentType(cfg, folder);
  if (contentType === undefined) {
    return;
  }

  const title = await vscode.window.showInputBox({
    title: `New ${contentType.name}`,
    prompt: 'Title',
    ignoreFocusOut: true,
    validateInput: (value) => (value.trim() === '' ? 'A title is required.' : undefined),
  });
  if (title === undefined || title.trim() === '') {
    return;
  }

  const request: CreateContentRequest = {
    contentType: contentType.name,
    title: title.trim(),
    // `folder.path` and not `folder.originalPath`: the configured form may be a
    // wildcard (`[[workspace]]/pages/*`), and creating a file inside a literal
    // directory called `*` is nobody's intent. `resolveFolders` already turned
    // that glob into the concrete directory this folder stands for.
    folderPath: folder.path,
    // `exactOptionalPropertyTypes`: an absent sub-folder is an absent key, not
    // a key holding `undefined`.
    ...(subFolder === undefined || subFolder === '' ? {} : { subFolder }),
  };

  const result = await createContent(cfg, request, shell.log);
  await fs.mkdir(path.dirname(result.filePath), { recursive: true });
  await fs.writeFile(result.filePath, renderContentFile(result, cfg), 'utf8');

  shell.log.info(`created ${relPath(cfg, result.filePath)}`);
  await openInEditor(result.filePath);
  await shell.store.refresh();
}

// ---------------------------------------------------------------------------
// Registration
// ---------------------------------------------------------------------------

export function registerContentCommands(shell: Zer0Shell): void {
  // --- Create content ------------------------------------------------------
  register(shell, 'createContent', async () => {
    const cfg = currentConfig();
    const folders = await creatableFolders(cfg);
    if (folders.length === 0) {
      const answer = await notifyWarning(
        'no content folder is registered yet.',
        'Register a folder',
      );
      if (answer === 'Register a folder') {
        await vscode.commands.executeCommand('zer0Cms.registerFolder');
      }
      return;
    }
    const folder = await pickFolder(folders);
    if (folder !== undefined) {
      await createInto(shell, folder, undefined);
    }
  });

  // --- Create content here (explorer context menu) -------------------------
  register(shell, 'createContentInFolder', async (arg: unknown) => {
    const cfg = currentConfig();
    const target = toFilePath(cfg, arg);
    if (target === undefined) {
      await vscode.commands.executeCommand('zer0Cms.createContent');
      return;
    }

    // The clicked directory is usually *inside* a registered folder rather
    // than being one, so the owning folder supplies the content types and the
    // clicked path becomes the sub-folder underneath it. Matching happens
    // against `resolveFolders` output, not `cfg.contentFolders`, because a
    // wildcard entry has not been expanded into real directories yet and would
    // never prefix-match anything on disk.
    const owner = folderForFile(await resolveFolders(cfg), target);
    if (owner === undefined) {
      const answer = await notifyWarning(
        `${path.basename(target)} is not inside a registered content folder.`,
        'Register it',
      );
      if (answer === 'Register it') {
        await vscode.commands.executeCommand('zer0Cms.registerFolder', vscode.Uri.file(target));
      }
      return;
    }
    if (owner.disableCreation === true) {
      await notifyWarning(`"${owner.title}" has content creation disabled.`);
      return;
    }

    const sub = path.relative(owner.path, target);
    await createInto(shell, owner, sub === '' ? undefined : sub);
  });

  // --- Generate slug -------------------------------------------------------
  register(shell, 'generateSlug', async () => {
    const active = await activeArticle();
    if (active === undefined) {
      return;
    }
    const { cfg, article, contentType, filePath } = active;

    const title = asString(article.data[cfg.seo.titleField]).trim();
    if (title === '') {
      await notifyWarning(`this file has no "${cfg.seo.titleField}" to build a slug from.`);
      return;
    }

    const slug = createSlug(cfg, title, contentType, filePath, article.data);
    if (slug === '') {
      await notifyWarning('the slug template produced nothing for this title.');
      return;
    }

    // A content type may name the field explicitly; otherwise the convention
    // is a key called `slug`. Writing to a key the type never declared would
    // be inventing schema on the author's behalf.
    const field = contentType.fields.find((candidate) => candidate.type === 'slug');
    const key = field?.name ?? 'slug';
    await writeArticle(article, [{ key, value: decorateSlug(cfg, slug) }], cfg);
    shell.log.info(`slug for ${relPath(cfg, filePath)}: ${slug}`);

    const renamed = alignedFilePath(cfg, filePath, slug);
    if (renamed !== undefined) {
      const answer = await notifyInfo(
        `rename the file to ${path.basename(renamed)}?`,
        'Rename',
      );
      if (answer === 'Rename') {
        await vscode.workspace.fs.rename(vscode.Uri.file(filePath), vscode.Uri.file(renamed), {
          overwrite: false,
        });
        await openInEditor(renamed);
      }
    }
    await shell.store.refresh();
  });

  // --- Set last-modified date ----------------------------------------------
  register(shell, 'setLastModified', async () => {
    const active = await activeArticle();
    if (active === undefined) {
      return;
    }
    const { cfg, article, contentType, filePath } = active;

    // The explicit command stamps regardless of
    // `content.autoUpdateModifiedDate` — that setting gates the *automatic*
    // path, not a deliberate one.
    const changes = stampModified(article, cfg, contentType);
    if (changes.length === 0) {
      await notifyInfo('no modified-date field to stamp (or it is already current).');
      return;
    }
    await writeArticle(article, changes, cfg);
    shell.log.info(`stamped ${changes.map((change) => change.key).join(', ')} in ${relPath(cfg, filePath)}`);
    await shell.store.refresh();
  });

  // --- Insert image --------------------------------------------------------
  register(shell, 'insertImage', async () => {
    const editor = vscode.window.activeTextEditor;
    const cfg = currentConfig();
    if (editor === undefined || !isSupported(cfg, editor.document.uri.fsPath)) {
      await notifyWarning('open a content file first.');
      return;
    }

    const picked = await vscode.window.showOpenDialog({
      title: 'Insert image',
      canSelectMany: true,
      openLabel: 'Insert',
      defaultUri: vscode.Uri.file(imageDialogRoot(cfg, editor.document.uri.fsPath)),
      filters: { Images: ['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'avif'] },
    });
    if (picked === undefined || picked.length === 0) {
      return;
    }

    const markdown = picked
      .map((uri) => {
        const alt = humanize(path.parse(uri.fsPath).name);
        return `![${alt}](${imageReference(cfg, editor.document.uri.fsPath, uri.fsPath)})`;
      })
      .join('\n');

    await editor.edit((builder) => {
      for (const selection of editor.selections) {
        builder.replace(selection, markdown);
      }
    });
  });

  // --- Panel steering ------------------------------------------------------
  register(shell, 'collapseSections', () => {
    if (panelBridge === undefined) {
      shell.log.verbose('collapseSections: the metadata panel is not open.');
      return;
    }
    panelBridge.collapseAll();
  });

  register(shell, 'focusTags', async () => {
    await focusTaxonomy(shell, 'tags');
  });

  register(shell, 'focusCategories', async () => {
    await focusTaxonomy(shell, 'categories');
  });
}

/**
 * Reveal the panel, then ask it to focus a field.
 *
 * The reveal comes first and happens either way: a keybinding pressed while
 * the panel is hidden should show the thing it is about to focus, and if no
 * bridge is registered yet, revealing the view is what causes the provider to
 * resolve and register one.
 */
async function focusTaxonomy(shell: Zer0Shell, target: 'tags' | 'categories'): Promise<void> {
  try {
    // VS Code contributes `<viewId>.focus` for every declared view. Revealing a
    // view that is hidden behind a `when` clause rejects rather than throwing
    // at registration time, and that is not worth a notification.
    await vscode.commands.executeCommand('zer0Cms.panel.focus');
  } catch (error) {
    shell.log.verbose(`could not reveal the metadata panel: ${describeError(error)}`);
  }
  if (panelBridge === undefined) {
    shell.log.verbose(`focus ${target}: the metadata panel is not open.`);
    return;
  }
  panelBridge.focus(target);
}

// ---------------------------------------------------------------------------
// Image paths
// ---------------------------------------------------------------------------

/** Where the picker opens: the public folder if configured, else the file's own. */
function imageDialogRoot(cfg: Zer0Config, documentPath: string): string {
  const publicFolder = cfg.content.publicFolder.trim();
  if (publicFolder !== '') {
    return path.resolve(cfg.workspaceRoot, publicFolder);
  }
  return path.dirname(documentPath);
}

/**
 * The path written into the markdown.
 *
 * With a `publicFolder` configured, a site serves that directory at its root,
 * so the correct reference is absolute-from-the-site-root (`/img/x.png`) and
 * stays correct however deep the page is. Without one, the only reference that
 * can be right is relative to the document. Anything outside the workspace
 * falls back to a relative path too — an absolute filesystem path in a
 * markdown file is never what anybody meant.
 */
function imageReference(cfg: Zer0Config, documentPath: string, imagePath: string): string {
  const publicFolder = cfg.content.publicFolder.trim();
  if (publicFolder !== '') {
    const root = path.resolve(cfg.workspaceRoot, publicFolder);
    const inside = path.relative(root, imagePath);
    if (!inside.startsWith('..') && !path.isAbsolute(inside)) {
      return `/${inside.split(path.sep).join('/')}`;
    }
  }
  const relative = path.relative(path.dirname(documentPath), imagePath).split(path.sep).join('/');
  return relative.startsWith('.') ? relative : `./${relative}`;
}
