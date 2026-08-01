/**
 * `PanelProvider` — the host behind the `zer0Cms.panel` sidebar view.
 *
 * It owns four things and deliberately nothing else.
 *
 * **1. The view model.** Everything the panel draws arrives as one full
 * `PanelState` snapshot (decision D4). There are no incremental patches, so the
 * webview holds no derived state that could disagree with the disk. Building a
 * snapshot reads the active file, resolves its content type, runs the SEO
 * insights and — when governance is on — the brand guard and the publish gates.
 * All of it is recomputed from `currentConfig()` and the workspace store on
 * every post; nothing here is cached across posts.
 *
 * **2. The intent whitelist.** Inbound `command` messages are looked up in a
 * `Record<CommandId, Handler>` by *own* property, after checking membership in
 * the closed `CommandId` union. Both checks matter: the union check rejects an
 * id the protocol never defined, and `Object.hasOwn` rejects one that resolves
 * through `Object.prototype` — a forged `{"id":"constructor"}` would otherwise
 * hand us a callable that is not a handler. An id that fails either check is
 * logged and dropped, so a forged intent provably runs no handler.
 *
 * **3. Decision D5, at the two places it matters.** `draft.approve` and
 * `draft.publish` route into the injected `GovernanceActions` — the very
 * `doApprove`/`doPublish` that `src/commands/governance.ts` registers for the
 * command palette, which re-read the draft from disk, re-run the brand guard,
 * re-evaluate `evaluatePublishGates()` and ask modally before writing a byte.
 * The webview supplies a draft path and nothing else. The blockers rendered
 * under a disabled button are advisory; the ones that decide are computed
 * again, later, somewhere else.
 *
 * **4. The panel bridge.** `zer0Cms.collapseSections`, `focusTags` and
 * `focusCategories` are commands whose whole effect is inside the webview.
 * `setPanelBridge(this)` registers the two posts that implement them, and the
 * registration is disposed with the view — so a command invoked after the panel
 * is closed logs rather than posting into a dead webview.
 *
 * ### The request channel
 *
 * `ViewMsg.request` is how a field widget asks the host to compute something.
 * The op vocabulary is closed by `RequestOp`; the payload and result shapes are:
 *
 * | op | payload | result |
 * |---|---|---|
 * | `generateSlug` | `{ title?: string }` | `{ slug: string }` (prefix/suffix applied) |
 * | `searchContent` | `{ contentType?: string; query?: string }` | `PageEntry[]`, capped at 50 |
 * | `resolvePlaceholder` | `{ value: string }` | `{ value: string }` |
 * | `taxonomyOptions` | — | `TaxonomyOptions` |
 * | `pickImage` | `{ multiple?: boolean }` | `string[]` — references, site-rooted or document-relative |
 * | `pickFile` | `{ multiple?: boolean; extensions?: string[] }` | `string[]` — document-relative paths |
 * | `guardText` | `{ text: string }` | `GuardFindingView[]` |
 * | `previewDraft` | `{ draftPath: string }` | `{ artifact: string; url: string \| null }` |
 *
 * A handler that throws replies `{error}` rather than rejecting, because the
 * webview's `Messenger.request` shows the message in the control that asked.
 */

import { randomBytes } from 'node:crypto';
import * as path from 'node:path';
import * as vscode from 'vscode';

import {
  asString,
  buildPreview,
  canonicalUrl,
  commentaryOf,
  createSlug,
  decorateSlug,
  emptyValueFor,
  evaluateApproveGates,
  evaluatePublishGates,
  findField,
  getArticleDetails,
  guardWithWorkspace,
  inlineFieldCollections,
  keywordAnalysis,
  keywordsOf,
  missingFields,
  previewRequestFromDraft,
  processPlaceholders,
  readArticle,
  readDraft,
  relPath,
  resolveContentType,
  seoInsights,
  setFieldValue,
  setOwn,
  shareEntries,
  sourceOf,
  stampModified,
  validateFields,
  writeArticle,
  type Article,
  type ContentType,
  type DraftFile,
  type Field,
  type FmValue,
  type FrontMatter,
  type KeyChange,
  type Ledger,
  type PageEntry,
  type Zer0Config,
} from '../core';
import { currentConfig, hasProjectConfig, onConfigChange, updateConfigFileJson, updateSetting } from '../config';
import { setPanelBridge, type PanelBridge } from '../commands/content';
import { draftPathFrom, type GovernanceActions } from '../commands/governance';
import type { Zer0Shell } from '../extension';
import { describeError, log } from '../logger';
import { isEditableDocument, reportError } from '../uiState';
import {
  COMMAND_IDS,
  type ActionItem,
  type CommandId,
  type GovernanceState,
  type GuardFindingView,
  type LedgerStateView,
  type PanelState,
  type RecentFile,
  type RecentFolder,
  type RequestOp,
  type SeoState,
  type TaxonomyOptions,
  type ViewMsg,
} from '../webview/shared/protocol';

/** Ten files per folder in "Recently modified", as Front Matter had it. */
const FILE_LIMIT = 10;

/** Filenames that say nothing; the folder's own name is shown instead. */
const VAGUE_NAMES: ReadonlySet<string> = new Set(['index', '+page', 'readme']);

const MARKDOWN_EXTENSIONS: ReadonlySet<string> = new Set(['.md', '.markdown', '.mdx']);

/** Snapshot posts are coalesced over this window. */
const POST_DEBOUNCE_MS = 80;

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

/**
 * The four settings the Global settings section may write, and the `zer0Cms.*`
 * ids they map to. The webview names a key from this table or nothing happens:
 * `updateSetting` is an intent, not a path into the settings store.
 */
const SETTING_KEYS: Readonly<Record<string, string>> = {
  autoUpdateModifiedDate: 'content.autoUpdateModifiedDate',
  openOnSupportedFile: 'panel.openOnSupportedFile',
  seoEnabled: 'seo.enabled',
  agentEnabled: 'agent.enabled',
};

/** The content-type mismatch prose, split on newlines by the webview. */
const CONTENT_TYPE_HINT = [
  'We noticed field differences between the content-type and the front matter data.',
  'Would you like to create, update, or set the content-type for this content?',
].join('\n');

const CONTENT_TYPE_ACTIONS: readonly ActionItem[] = [
  { id: 'contentType.generate', label: 'Create content-type' },
  { id: 'contentType.addMissingFields', label: 'Add missing fields to content-type' },
  { id: 'contentType.set', label: 'Change content-type of the file' },
];

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

function readBoolean(source: unknown, key: string): boolean {
  return asRecord(source)?.[key] === true;
}

function readStringList(source: unknown, key: string): string[] {
  const value = asRecord(source)?.[key];
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

/**
 * Coerce a value that crossed `postMessage` into something the front-matter
 * serializer can write. Anything that is not JSON-shaped becomes `null` rather
 * than the string `"[object Object]"`.
 */
function toFmValue(value: unknown): FmValue {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') {
    return value;
  }
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : null;
  }
  if (Array.isArray(value)) {
    return value.map(toFmValue);
  }
  const record = asRecord(value);
  if (record === undefined) {
    return null;
  }
  const out: { [key: string]: FmValue } = {};
  for (const [key, item] of Object.entries(record)) {
    // The webview supplies these keys, so `out[key] =` would let a forged
    // `__proto__` reshape the object on its way into the front-matter writer.
    setOwn(out, key, toFmValue(item));
  }
  return out;
}

function isMarkdown(filePath: string): boolean {
  return MARKDOWN_EXTENSIONS.has(path.extname(filePath).toLowerCase());
}

/**
 * A comment-only or empty front-matter block parses to zero keys, which is not
 * an error. A block with real content that produced zero keys is one.
 */
function unreadableFrontMatter(article: Article): boolean {
  const block = article.block;
  if (block === null || Object.keys(article.data).length > 0) {
    return false;
  }
  return block.raw
    .split('\n')
    .some((line) => line.trim() !== '' && !line.trimStart().startsWith('#'));
}

export class PanelProvider implements vscode.WebviewViewProvider, PanelBridge, vscode.Disposable {
  static readonly viewType = 'zer0Cms.panel';

  private view: vscode.WebviewView | undefined;
  private readonly disposables: vscode.Disposable[] = [];
  private readonly handlers: Partial<Record<CommandId, Handler>>;

  /** The active editable file, tracked rather than read: focus inside the
   *  webview can leave `activeTextEditor` undefined for a frame. */
  private activeFile: string | null = null;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private posting = false;

  constructor(
    private readonly shell: Zer0Shell,
    private readonly governance: GovernanceActions,
  ) {
    this.handlers = {
      // --- project ---------------------------------------------------------
      init: () => this.run('init'),
      dashboard: () => this.run('dashboard'),
      refresh: () => this.run('refresh'),
      showOutput: () => this.run('showOutput'),
      // --- content ---------------------------------------------------------
      createContent: () => this.run('createContent'),
      generateSlug: () => this.run('generateSlug'),
      insertImage: () => this.run('insertImage'),
      openFile: (args) => this.run('openFile', args),
      collapseSections: () => {
        this.collapseAll();
      },
      // --- content types ---------------------------------------------------
      'contentType.generate': () => this.run('contentType.generate'),
      'contentType.addMissingFields': () => this.run('contentType.addMissingFields'),
      'contentType.set': () => this.run('contentType.set'),
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
      // --- contract --------------------------------------------------------
      'contract.run': () => this.run('contract.run'),
      'contract.normalizePreview': () => this.run('contract.normalizePreview'),
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
    };
  }

  // -------------------------------------------------------------------------
  // Lifecycle
  // -------------------------------------------------------------------------

  resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    const extensionUri = this.shell.context.extensionUri;
    const developer = this.shell.context.extensionMode !== vscode.ExtensionMode.Production;

    view.webview.options = {
      enableScripts: true,
      localResourceRoots: [
        vscode.Uri.joinPath(extensionUri, 'media'),
        vscode.Uri.joinPath(extensionUri, 'dist'),
      ],
      // Only outside a released build, and only these two commands.
      ...(developer ? { enableCommandUris: DEVELOPER_COMMAND_URIS } : {}),
    };
    view.webview.html = panelHtml(view.webview, extensionUri);

    const editor = vscode.window.activeTextEditor;
    this.activeFile =
      editor !== undefined && isEditableDocument(currentConfig(), editor.document)
        ? editor.document.uri.fsPath
        : null;

    this.disposables.push(
      view.webview.onDidReceiveMessage((message: unknown) => {
        this.receive(message);
      }),
      // The two imperative posts three commands need. Disposed with the view.
      setPanelBridge(this),
      vscode.window.onDidChangeActiveTextEditor((next) => {
        this.onEditorChanged(next);
      }),
      vscode.workspace.onDidSaveTextDocument((document) => {
        if (document.uri.fsPath === this.activeFile) {
          this.schedule();
        }
      }),
      this.shell.store.onDidChange(() => {
        this.schedule();
      }),
      onConfigChange(() => {
        this.schedule();
      }),
      view.onDidChangeVisibility(() => {
        if (view.visible) {
          this.schedule();
        }
      }),
    );
    view.onDidDispose(() => {
      this.teardown();
    });

    this.updateTitle();
    this.schedule();
  }

  dispose(): void {
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
    this.view = undefined;
  }

  /**
   * Track the active file and, when `zer0Cms.panel.openOnSupportedFile` is on,
   * surface the panel for it.
   *
   * `show(true)` preserves focus: revealing the panel must never take the caret
   * out of the document somebody is typing in. The view is only shown when it
   * already exists — forcing the whole sidebar container open because a file was
   * opened is a different, much ruder, feature.
   */
  private onEditorChanged(editor: vscode.TextEditor | undefined): void {
    const cfg = currentConfig();
    const next =
      editor !== undefined && isEditableDocument(cfg, editor.document)
        ? editor.document.uri.fsPath
        : null;
    if (next === this.activeFile) {
      return;
    }
    this.activeFile = next;
    this.updateTitle();
    this.schedule();
    if (next !== null && cfg.panel.openOnSupportedFile && this.view !== undefined && !this.view.visible) {
      this.view.show(true);
    }
  }

  /** The file's basename, or the literal `General` with nothing open. */
  private updateTitle(): void {
    if (this.view !== undefined) {
      this.view.title = this.activeFile === null ? 'General' : path.basename(this.activeFile);
    }
  }

  // -------------------------------------------------------------------------
  // PanelBridge
  // -------------------------------------------------------------------------

  collapseAll(): void {
    this.post({ type: 'collapseAll' });
  }

  focus(target: 'tags' | 'categories'): void {
    this.view?.show(true);
    this.post({ type: 'focus', target });
  }

  // -------------------------------------------------------------------------
  // Messaging
  // -------------------------------------------------------------------------

  private post(message: unknown): void {
    const view = this.view;
    if (view === undefined) {
      return;
    }
    void view.webview.postMessage(message).then(undefined, (error: unknown) => {
      log.verbose(`panel: postMessage failed (${describeError(error)})`);
    });
  }

  private progress(scope: 'panel' | 'field', segments: string[] | undefined, message: string | null): void {
    this.post(
      segments === undefined
        ? { type: 'progress', scope, message }
        : { type: 'progress', scope, path: segments, message },
    );
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
        log[msg.level](`panel webview: ${msg.message}`);
        return;
      case 'command':
        this.dispatch(msg.id, msg.args);
        return;
      case 'updateField':
        void this.applyFieldUpdate(msg.path, msg.value);
        return;
      case 'addTaxonomy':
        void this.addTaxonomy(msg.kind, msg.taxonomyId, msg.value);
        return;
      case 'request':
        void this.reply(msg.requestId, msg.op, msg.payload);
        return;
      case 'setUiState':
        void this.shell.context.workspaceState.update(`zer0Cms:Panel:${msg.key}`, msg.value);
        return;
      default:
        log.verbose('panel webview: ignored an unrecognised message');
        return;
    }
  }

  /**
   * The whitelist, and the only place a webview intent becomes an action.
   *
   * Two checks, both necessary. `isCommandId` rejects anything outside the
   * closed protocol union. `Object.hasOwn` rejects an id that would resolve
   * through `Object.prototype` — without it a forged `{"id":"toString"}` looks
   * like a handler and is callable.
   */
  private dispatch(id: unknown, args: unknown): void {
    if (!isCommandId(id) || !Object.hasOwn(this.handlers, id)) {
      log.warn(`panel webview: dropped unknown command "${String(id)}"`);
      return;
    }
    const handler = this.handlers[id];
    if (handler === undefined) {
      log.warn(`panel webview: dropped command "${id}" with no handler`);
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
    try {
      const draftPath = draftPathFrom(currentConfig(), args);
      if (draftPath === undefined) {
        log.warn(`panel webview: "draft.${action}" arrived without a draft path`);
        return;
      }
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

  private openLink(url: string | undefined): void {
    if (url === undefined) {
      return;
    }
    const uri = vscode.Uri.parse(url, true);
    if (uri.scheme !== 'https' && uri.scheme !== 'http') {
      // A `command:` or `file:` link from a webview is an escalation, not a
      // documentation link.
      log.warn(`panel webview: refused to open a "${uri.scheme}" link`);
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

  private async writeSetting(args: unknown): Promise<void> {
    const key = readString(args, 'key');
    const id = key === undefined ? undefined : SETTING_KEYS[key];
    if (id === undefined) {
      log.warn(`panel webview: refused to write the setting "${String(key)}"`);
      return;
    }
    const value = asRecord(args)?.value;
    if (typeof value !== 'boolean') {
      log.warn(`panel webview: "${id}" expects a boolean`);
      return;
    }
    try {
      await updateSetting(id, value);
    } catch (error) {
      reportError(error, `zer0Cms.${id}`);
    }
    this.schedule();
  }

  // -------------------------------------------------------------------------
  // Field writes
  // -------------------------------------------------------------------------

  /**
   * Write one front-matter key.
   *
   * The article is re-read from disk rather than taken from the snapshot the
   * webview rendered: between the render and the click somebody may have saved
   * the file, and line surgery against a stale copy would put the change on the
   * wrong line. A dirty editor is saved first for the same reason `activeArticle`
   * does it — the buffer would otherwise overwrite us the moment the user saves.
   */
  private async applyFieldUpdate(segments: string[], value: unknown): Promise<void> {
    const filePath = this.activeFile;
    if (filePath === null || segments.length === 0) {
      return;
    }
    const cfg = currentConfig();
    this.progress('field', segments, 'Saving…');
    try {
      const document = vscode.workspace.textDocuments.find(
        (candidate) => candidate.uri.fsPath === filePath,
      );
      if (document?.isDirty === true) {
        await document.save();
      }

      const article = await readArticle(filePath);
      const contentType = resolveContentType(cfg, article.data, filePath);
      const next =
        value === undefined ? this.emptyFor(cfg, contentType, segments) : toFmValue(value);
      const changes: KeyChange[] = setFieldValue(article.data, segments, next);

      if (cfg.content.autoUpdateModifiedDate) {
        const touched = new Set(changes.map((change) => change.key));
        for (const change of stampModified(article, cfg, contentType)) {
          // The edited field may itself be the modified date; writing it twice
          // would make the second change fight the first.
          if (!touched.has(change.key)) {
            changes.push(change);
          }
        }
      }

      await writeArticle(article, changes, cfg);
      log.verbose(`panel: wrote ${segments.join('.')} in ${relPath(cfg, filePath)}`);
      await this.shell.store.refresh();
    } catch (error) {
      reportError(error, `updating ${segments.join('.')}`);
    } finally {
      this.progress('field', segments, null);
    }
    this.schedule();
  }

  /** What "cleared" means for this field — its declared empty value. */
  private emptyFor(cfg: Zer0Config, contentType: ContentType, segments: string[]): FmValue {
    const leaf = segments[segments.length - 1];
    if (leaf === undefined) {
      return null;
    }
    const fields = inlineFieldCollections(contentType.fields, cfg.fieldGroups);
    const field = findField(fields, leaf);
    return field === undefined ? null : emptyValueFor(field, cfg);
  }

  /**
   * Add a value to the *configured* taxonomy — the `+` on an unknown tag pill.
   * This writes `zer0.json`, not the article: the article already carries the
   * value, and what the user asked for is that it stop being unknown.
   */
  private async addTaxonomy(
    kind: 'tags' | 'categories' | 'custom',
    taxonomyId: string | undefined,
    value: string,
  ): Promise<void> {
    const option = value.trim();
    if (option === '') {
      return;
    }
    try {
      await updateConfigFileJson((json) => {
        const taxonomy = asRecord(json.taxonomy) ?? {};
        if (kind === 'custom') {
          const id = (taxonomyId ?? '').trim();
          if (id === '') {
            return;
          }
          const list = Array.isArray(taxonomy.custom) ? [...taxonomy.custom] : [];
          const index = list.findIndex((entry) => readString(entry, 'id') === id);
          const entry = index >= 0 ? (asRecord(list[index]) ?? {}) : { id, options: [] };
          const options = Array.isArray(entry.options)
            ? entry.options.filter((item): item is string => typeof item === 'string')
            : [];
          if (!options.includes(option)) {
            options.push(option);
            options.sort((a, b) => a.localeCompare(b));
          }
          entry.options = options;
          if (index >= 0) {
            list[index] = entry;
          } else {
            list.push(entry);
          }
          taxonomy.custom = list;
        } else {
          const current = taxonomy[kind];
          const list = Array.isArray(current)
            ? current.filter((item): item is string => typeof item === 'string')
            : [];
          if (!list.includes(option)) {
            list.push(option);
            list.sort((a, b) => a.localeCompare(b));
          }
          taxonomy[kind] = list;
        }
        json.taxonomy = taxonomy;
      });
      log.info(`added "${option}" to ${kind === 'custom' ? `taxonomy ${taxonomyId ?? ''}` : kind}`);
    } catch (error) {
      reportError(error, 'updating the taxonomy');
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
      // Rejecting would be invisible; the field that asked shows this message.
      this.post({ type: 'result', requestId, error: describeError(error) });
    }
  }

  private async handleRequest(op: RequestOp, payload: unknown): Promise<unknown> {
    const cfg = currentConfig();
    switch (op) {
      case 'generateSlug': {
        const filePath = this.activeFile;
        const article = filePath === null ? undefined : await readArticle(filePath);
        const data = article?.data ?? {};
        const contentType = filePath === null ? undefined : resolveContentType(cfg, data, filePath);
        const title = readString(payload, 'title') ?? asString(data[cfg.seo.titleField]);
        const slug = createSlug(cfg, title, contentType, filePath ?? undefined, data);
        return { slug: slug === '' ? '' : decorateSlug(cfg, slug) };
      }
      case 'searchContent': {
        const snapshot = await this.shell.store.current();
        const wanted = readString(payload, 'contentType');
        const query = (readString(payload, 'query') ?? '').trim().toLowerCase();
        const matches = snapshot.pages.filter((page) => {
          if (wanted !== undefined && wanted !== '' && page.contentType !== wanted) {
            return false;
          }
          if (query === '') {
            return true;
          }
          return (
            page.title.toLowerCase().includes(query) || page.slug.toLowerCase().includes(query)
          );
        });
        return matches.slice(0, 50);
      }
      case 'resolvePlaceholder': {
        const value = readString(payload, 'value') ?? '';
        const filePath = this.activeFile;
        const article = filePath === null ? undefined : await readArticle(filePath);
        const contentType =
          filePath === null ? undefined : resolveContentType(cfg, article?.data ?? {}, filePath);
        const resolved = await processPlaceholders(value, {
          cfg,
          data: article?.data ?? {},
          log,
          ...(contentType === undefined ? {} : { contentType }),
          ...(filePath === null ? {} : { filePath }),
        });
        return { value: resolved };
      }
      case 'taxonomyOptions':
        return taxonomyOptions(cfg);
      case 'pickImage':
        return this.pickPaths({
          title: 'Select an image',
          multiple: readBoolean(payload, 'multiple'),
          filters: { Images: ['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'avif'] },
          siteRooted: true,
        });
      case 'pickFile': {
        const extensions = readStringList(payload, 'extensions').map((ext) =>
          ext.replace(/^\./, ''),
        );
        return this.pickPaths({
          title: 'Select a file',
          multiple: readBoolean(payload, 'multiple'),
          siteRooted: false,
          ...(extensions.length === 0 ? {} : { filters: { Files: extensions } }),
        });
      }
      case 'guardText': {
        const findings = await guardWithWorkspace(cfg, readString(payload, 'text') ?? '');
        return findings satisfies GuardFindingView[];
      }
      case 'previewDraft': {
        const draftPath = readString(payload, 'draftPath');
        if (draftPath === undefined) {
          throw new Error('previewDraft needs a draft path.');
        }
        const draft = await readDraft(draftPath);
        const preview = await buildPreview(cfg, previewRequestFromDraft(draft));
        const artifact = preview.artifact;
        return {
          artifact:
            typeof artifact === 'string' ? artifact : JSON.stringify(artifact ?? null, null, 2),
          url: preview.url ?? null,
        };
      }
    }
  }

  /**
   * The native picker, and the reference it produces.
   *
   * With a `content.publicFolder` configured, a site serves that directory at
   * its root, so an image reference is absolute-from-the-site-root and stays
   * correct however deep the page is. Everything else — and anything outside
   * the public folder — is relative to the document, because an absolute
   * filesystem path in a content file is never what anybody meant.
   */
  private async pickPaths(options: {
    title: string;
    multiple: boolean;
    siteRooted: boolean;
    filters?: Record<string, string[]>;
  }): Promise<string[]> {
    const cfg = currentConfig();
    const documentPath = this.activeFile;
    const root = cfg.content.publicFolder.trim();
    const defaultUri =
      root !== ''
        ? vscode.Uri.file(path.resolve(cfg.workspaceRoot, root))
        : documentPath !== null
          ? vscode.Uri.file(path.dirname(documentPath))
          : undefined;

    const picked = await vscode.window.showOpenDialog({
      title: options.title,
      canSelectMany: options.multiple,
      openLabel: 'Select',
      ...(defaultUri === undefined ? {} : { defaultUri }),
      ...(options.filters === undefined ? {} : { filters: options.filters }),
    });
    if (picked === undefined) {
      return [];
    }
    return picked.map((uri) => reference(cfg, documentPath, uri.fsPath, options.siteRooted));
  }

  // -------------------------------------------------------------------------
  // The snapshot
  // -------------------------------------------------------------------------

  /** Ask for a post soon. Bursts — a save plus a store refresh plus a config
   *  change all land together — collapse into one snapshot. */
  private schedule(delay: number = POST_DEBOUNCE_MS): void {
    if (this.view === undefined) {
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
    if (this.view === undefined || this.posting) {
      return;
    }
    this.posting = true;
    try {
      const state = await this.buildState();
      this.updateTitle();
      this.post({ type: 'state', state });
    } catch (error) {
      // A panel that cannot build a snapshot must not also be a panel that
      // never clears its spinner.
      log.error(`panel: could not build a snapshot (${describeError(error)})`);
      this.progress('panel', undefined, null);
    } finally {
      this.posting = false;
    }
  }

  private async buildState(): Promise<PanelState> {
    const cfg = currentConfig();
    const snapshot = await this.shell.store.current();
    const filePath = this.activeFile;

    let article: Article | undefined;
    let fmError: string | null = null;
    if (filePath !== null) {
      try {
        article = await readArticle(filePath);
        if (unreadableFrontMatter(article)) {
          fmError = `The ${article.block?.format ?? 'yaml'} front matter in ${path.basename(
            filePath,
          )} could not be read. Every key was skipped.`;
        }
      } catch (error) {
        fmError = describeError(error);
      }
    }

    const data: FrontMatter = article?.data ?? {};
    const contentType =
      filePath === null ? undefined : resolveContentType(cfg, data, filePath);
    const fields: Field[] =
      contentType === undefined ? [] : inlineFieldCollections(contentType.fields, cfg.fieldGroups);

    const missing = contentType === undefined ? [] : missingFields(contentType, data);
    const violations =
      contentType === undefined ? [] : validateFields(fields, data, cfg);

    return {
      kind: 'panel',
      initialized: hasProjectConfig(),
      developer: this.shell.context.extensionMode !== vscode.ExtensionMode.Production,
      fileName: filePath === null ? null : path.basename(filePath),
      filePath,
      sections: cfg.panel.sections,
      contentTypeName: contentType?.name ?? null,
      contentTypeHint:
        missing.length === 0
          ? null
          : { message: CONTENT_TYPE_HINT, actions: [...CONTENT_TYPE_ACTIONS] },
      fields,
      metadata: article === undefined ? null : data,
      fmError,
      violations: violations.map((violation) => ({
        path: violation.path,
        message: violation.message,
      })),
      taxonomy: taxonomyOptions(cfg),
      seo:
        cfg.seo.enabled && article !== undefined && fmError === null
          ? seoState(cfg, data, contentType, article, snapshot.pages)
          : null,
      governance: cfg.governance.enabled
        ? await this.governanceState(cfg, filePath, snapshot.drafts, snapshot.ledger, violations)
        : null,
      recent: recentFolders(cfg, snapshot.pages),
      settings: {
        autoUpdateModifiedDate: cfg.content.autoUpdateModifiedDate,
        openOnSupportedFile: cfg.panel.openOnSupportedFile,
        seoEnabled: cfg.seo.enabled,
        agentEnabled: cfg.agent.enabled,
      },
      dateFormat: cfg.date.format,
      timezone: cfg.date.timezone,
    };
  }

  /**
   * The advisory governance view.
   *
   * Deliberately cheaper than `collectGateContext` in `commands/governance.ts`:
   * it runs the brand guard, but it does **not** build a publish preview. A
   * preview resolves the source page and renders the artifact the target would
   * write, which is the right thing to do once, when somebody presses Publish —
   * not on every keystroke that changes the active editor. The consequence is
   * honest and bounded: the panel can omit the `previewFailed` blocker, and it
   * only knows about `requiredFieldMissing` when the draft's source happens to
   * be the file that is open. The authoritative evaluation runs later, in
   * `doPublish`, with everything.
   */
  private async governanceState(
    cfg: Zer0Config,
    filePath: string | null,
    drafts: readonly DraftFile[],
    ledger: Ledger,
    violations: readonly { path: string[]; field: Field; message: string }[],
  ): Promise<GovernanceState> {
    const draft = findDraft(cfg, drafts, filePath);
    const base: GovernanceState = {
      enabled: true,
      draft: null,
      guard: [],
      approveBlockers: [],
      publishBlockers: [],
      ledger: null,
      publishAllow: cfg.governance.publishAllow,
      target: cfg.governance.target,
    };
    if (draft === undefined) {
      return base;
    }

    const guard: GuardFindingView[] = await guardWithWorkspace(cfg, commentaryOf(draft));
    const source = sourceOf(draft);
    const found = ledgerStateFor(cfg, ledger, source);
    // Required-field violations belong to the source page. We only have them
    // when that page is the one on screen; claiming otherwise would invent a
    // blocker or hide one.
    const sourceIsOpen =
      filePath !== null && source !== '' && relPath(cfg, filePath) === source;

    const input = {
      cfg,
      draft,
      guard,
      ...(sourceIsOpen ? { violations } : {}),
      ...(found === undefined ? {} : { ledgerEntry: found.entry }),
    };

    return {
      ...base,
      draft: {
        path: draft.path,
        name: path.basename(draft.path),
        title: asString(draft.meta.title),
        description: asString(draft.meta.description),
        status: draft.status,
        type: draft.type,
        source: source === '' ? null : source,
        commentary: commentaryOf(draft),
      },
      guard,
      approveBlockers: evaluateApproveGates(input),
      publishBlockers: evaluatePublishGates(input),
      ledger: found?.view ?? null,
    };
  }
}

// ---------------------------------------------------------------------------
// Projections
// ---------------------------------------------------------------------------

function taxonomyOptions(cfg: Zer0Config): TaxonomyOptions {
  return {
    tags: cfg.taxonomy.tags,
    categories: cfg.taxonomy.categories,
    custom: cfg.taxonomy.custom.map((entry) => ({ id: entry.id, options: entry.options })),
    freeform: cfg.panel.freeformTaxonomy,
  };
}

/**
 * Every keyword already used anywhere in the workspace, as the picker's
 * suggestions. Keywords are not a configured taxonomy — there is no list to
 * read — so the corpus is the only honest source of "words you already use".
 */
function keywordSuggestions(pages: readonly PageEntry[], exclude: readonly string[]): string[] {
  const taken = new Set(exclude.map((keyword) => keyword.toLowerCase()));
  const seen = new Set<string>();
  const out: string[] = [];
  for (const page of pages) {
    for (const keyword of keywordsOf(page.data as FrontMatter)) {
      const key = keyword.toLowerCase();
      if (taken.has(key) || seen.has(key)) {
        continue;
      }
      seen.add(key);
      out.push(keyword);
    }
  }
  return out.sort((a, b) => a.localeCompare(b));
}

function seoState(
  cfg: Zer0Config,
  data: FrontMatter,
  contentType: ContentType | undefined,
  article: Article,
  pages: readonly PageEntry[],
): SeoState {
  const details = getArticleDetails(article.body);
  const keywords = keywordsOf(data);
  return {
    titleField: cfg.seo.titleField,
    descriptionField: cfg.seo.descriptionField,
    titleLength: cfg.seo.titleLength,
    descriptionLength: cfg.seo.descriptionLength,
    hasTitle: asString(data[cfg.seo.titleField]).trim() !== '',
    hasDescription: asString(data[cfg.seo.descriptionField]).trim() !== '',
    rows: seoInsights(cfg, data, contentType, details),
    keywords: keywords.map((keyword) => keywordAnalysis(keyword, data, details, cfg)),
    suggestions: keywordSuggestions(pages, keywords),
    wordCount: details.wordCount,
    headings: details.headings,
    paragraphs: details.paragraphs,
    images: details.images,
    internalLinks: details.internalLinks,
    externalLinks: details.externalLinks,
  };
}

/**
 * The draft this file is about: the file *is* a queue entry, or a queue entry
 * names it as its source. Path comparison is on the resolved absolute path so
 * a draft written on Windows and a path read from an editor agree.
 */
function findDraft(
  cfg: Zer0Config,
  drafts: readonly DraftFile[],
  filePath: string | null,
): DraftFile | undefined {
  if (filePath === null) {
    return undefined;
  }
  const direct = drafts.find((draft) => path.resolve(draft.path) === path.resolve(filePath));
  if (direct !== undefined) {
    return direct;
  }
  const rel = relPath(cfg, filePath);
  return drafts.find((draft) => sourceOf(draft) === rel);
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
    // The raw record, not `shareEntries`' projection: the gate takes the
    // ledger's own value type, which carries the keys other lanes wrote.
    const raw = ledger[key];
    if (entry.source_file === source && raw !== undefined) {
      return {
        entry: raw,
        view: { url: key, urn: entry.urn, postedAt: entry.posted_at },
      };
    }
  }
  return undefined;
}

/**
 * "Recently modified", grouped by the folder each page was indexed under.
 *
 * The grouping key is `PageEntry.folder`, which is a *resolved* directory — a
 * wildcard content folder expands to several of them — so the display title is
 * looked up by longest configured prefix and falls back to the directory's own
 * name rather than to a blank label.
 */
function recentFolders(cfg: Zer0Config, pages: readonly PageEntry[]): RecentFolder[] {
  const groups = new Map<string, PageEntry[]>();
  for (const page of pages) {
    const list = groups.get(page.folder);
    if (list === undefined) {
      groups.set(page.folder, [page]);
    } else {
      list.push(page);
    }
  }

  const defaultNames = new Set(
    cfg.contentTypes
      .map((type) => (type.defaultFileName ?? '').replace(/\.[^./]+$/, '').toLowerCase())
      .filter((name) => name !== ''),
  );

  const out: RecentFolder[] = [];
  for (const [folder, group] of groups) {
    const configured = cfg.contentFolders
      .filter((candidate) => folder === candidate.path || folder.startsWith(`${candidate.path}${path.sep}`))
      .sort((a, b) => b.path.length - a.path.length)[0];
    const files: RecentFile[] = [...group]
      .sort((a, b) => b.modified - a.modified)
      .slice(0, FILE_LIMIT)
      .map((page) => ({
        path: page.filePath,
        name: displayName(page.filePath, defaultNames),
        markdown: isMarkdown(page.filePath),
      }));
    out.push({
      title: configured?.title ?? path.basename(folder),
      totalFiles: group.length,
      files,
    });
  }
  return out.sort((a, b) => a.title.localeCompare(b.title));
}

/** A vague filename (`index`, `+page`, a content type's default) shows the
 *  folder it lives in instead — otherwise half the list reads "index". */
function displayName(filePath: string, defaultNames: ReadonlySet<string>): string {
  const stem = path.basename(filePath, path.extname(filePath));
  if (VAGUE_NAMES.has(stem.toLowerCase()) || defaultNames.has(stem.toLowerCase())) {
    return path.basename(path.dirname(filePath));
  }
  return stem;
}

/** A site-rooted or document-relative reference to a picked file. */
function reference(
  cfg: Zer0Config,
  documentPath: string | null,
  target: string,
  siteRooted: boolean,
): string {
  const publicFolder = cfg.content.publicFolder.trim();
  if (siteRooted && publicFolder !== '') {
    const root = path.resolve(cfg.workspaceRoot, publicFolder);
    const inside = path.relative(root, target);
    if (!inside.startsWith('..') && !path.isAbsolute(inside)) {
      return `/${inside.split(path.sep).join('/')}`;
    }
  }
  if (documentPath === null) {
    return relPath(cfg, target);
  }
  const relative = path.relative(path.dirname(documentPath), target).split(path.sep).join('/');
  return relative.startsWith('.') ? relative : `./${relative}`;
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
 * **No file name, front-matter value, draft body or guard message is templated
 * in here.** The page ships empty; every character of content arrives over
 * `postMessage` and is written with `textContent` through `el()`. That is what
 * makes `default-src 'none'` a guarantee rather than a decoration — there is no
 * code path from a workspace file to markup, so the CSP has nothing to catch.
 *
 * `img-src` allows `https:` because an image field may preview a remote asset;
 * everything else resolves through `asWebviewUri` from the two roots the view
 * declares. Scripts and styles carry the per-render nonce and nothing else can.
 */
function panelHtml(webview: vscode.Webview, extensionUri: vscode.Uri): string {
  const token = nonce();
  const asset = (...parts: string[]): string =>
    webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, ...parts)).toString();

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'nonce-${token}'; script-src 'nonce-${token}'; font-src ${webview.cspSource}; img-src ${webview.cspSource} data: https:;">
<title>zer0-CMS metadata</title>
<link nonce="${token}" rel="stylesheet" href="${asset('dist', 'media', 'codicon.css')}">
<link nonce="${token}" rel="stylesheet" href="${asset('media', 'tokens.css')}">
<link nonce="${token}" rel="stylesheet" href="${asset('media', 'base.css')}">
<link nonce="${token}" rel="stylesheet" href="${asset('media', 'panel.css')}">
</head>
<body>
<div id="z-panel" class="z-panel"></div>
<script nonce="${token}" src="${asset('dist', 'panel.js')}"></script>
</body>
</html>`;
}
