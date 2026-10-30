/**
 * `Studio` — the studio's workspaces in the editor's webviews, once a platform
 * is configured (PLAN G10, ADR 0006 decision 9).
 *
 * The webviews load `dist/studio.js`, which esbuild builds from `web/packages/`:
 * the studio's own React workspaces, components, libraries and generated API
 * client, with nothing written twice. This file is the thin VS Code host around
 * them, and it holds nothing per workspace — `@zer0/ui`'s registry decides what
 * the dashboard shows:
 *
 *   - **where it renders**: the dashboard panel (every workspace), the Metadata
 *     view when the open file is a page on the platform (`modeFor`; the webview
 *     is told the file's path from its folder and nothing else — any other
 *     file keeps file mode) and the AI panel (the agent view);
 *   - **the page** each webview loads (`studioPage`: a strict CSP with a nonce);
 *   - **one `StudioBridge` per webview**, which re-checks every request and adds
 *     the platform URL (`settingsPlatformUrl`, the settings layer only) and the
 *     person's token (SecretStorage, one per platform origin) — the webview
 *     never holds the token;
 *   - **the token's two commands**, which `src/commands/platform.ts` registers.
 *
 * Nothing here opens a socket at activation (decision D11): a request leaves
 * only when a webview a person opened asks for it.
 */

import { randomBytes } from 'node:crypto';
import * as path from 'node:path';

import { EventSource } from 'eventsource';
import * as vscode from 'vscode';

import { currentConfig, onConfigChange, settingsPlatformUrl } from '../config';
import { platformOrigin, sendToPlatform, StudioBridge, studioPage, tokenKey, type StudioView } from '../core';
import { describeError, log } from '../logger';
import { confirm, isEditableDocument, notifyError, notifyInfo } from '../uiState';

type PanelView = Exclude<StudioView, 'page'>;

/**
 * A file as the platform knows it: its path from the workspace folder it is
 * in, starting with that folder's name (`drsai/_posts/a.md`), which is what
 * tells two sites' `_posts/a.md` apart (`?source=`, `importers/services.py`).
 * Undefined for a file in no folder, which no site can claim.
 */
export function sourcePath(uri: vscode.Uri): string | undefined {
  const folder = vscode.workspace.getWorkspaceFolder(uri);
  if (folder === undefined) {
    return undefined;
  }
  const inside = path.relative(folder.uri.fsPath, uri.fsPath).split(path.sep).join('/');
  return `${path.posix.basename(folder.uri.path)}/${inside}`;
}

/** A file the Metadata view would edit: a supported content file of its own site. */
function editable(document: vscode.TextDocument): boolean {
  return isEditableDocument(currentConfig(document.uri), document);
}

const TITLES: Record<PanelView, string> = { dashboard: 'zer0 studio', ai: 'zer0 AI' };

export class Studio implements vscode.Disposable {
  private readonly panels = new Map<PanelView, { panel: vscode.WebviewPanel; session: Session }>();
  private readonly sessions = new Set<Session>();
  private readonly disposables: vscode.Disposable[] = [];

  constructor(
    readonly context: vscode.ExtensionContext,
    /** The network (D11), injectable so a test can see what would be sent. */
    readonly network: (url: string, init: RequestInit) => Promise<Response> = (url, init) => fetch(url, init),
  ) {
    // A platform taken away closes its panels; the Metadata view goes back to
    // file mode itself (`PanelProvider`).
    this.disposables.push(
      onConfigChange(() => {
        if (!this.configured()) {
          for (const { panel } of [...this.panels.values()]) {
            panel.dispose();
          }
        }
      }),
    );
  }

  /** The configured platform's origin (settings layer, trusted workspace), read fresh. */
  origin(): string | undefined {
    return platformOrigin(settingsPlatformUrl());
  }

  configured(): boolean {
    return this.origin() !== undefined;
  }

  /** The dashboard, at `to` when a view asked for a destination it does not show. */
  openDashboard(to?: Record<string, unknown>): void {
    this.open('dashboard', to);
  }

  /** The agent view, as the AI workspace. */
  openAi(): void {
    this.open('ai');
  }

  /** The Metadata view's platform mode: the page behind the open file. */
  attachView(view: vscode.WebviewView): vscode.Disposable {
    return this.connect(view.webview, 'page', 'sidebar');
  }

  /**
   * What the Metadata view shows for `document` (PLAN G10): the studio's page
   * editor when the platform has a page imported from the file; file mode with
   * no platform, for a file in no folder, and when the platform has no page
   * for it — a site still on files, a file never imported — or cannot be
   * reached. Any other answer (no token, a refusal) is the page view, which
   * says why. Undefined for an editor the view would not edit (output, code):
   * it keeps what it shows. One request, because a person opened the file with
   * the view showing.
   */
  async modeFor(document: vscode.TextDocument | undefined): Promise<'page' | 'files' | undefined> {
    if (!this.configured()) {
      return 'files';
    }
    if (document === undefined || !editable(document)) {
      return undefined;
    }
    const source = sourcePath(document.uri);
    if (source === undefined) {
      return 'files';
    }
    const reply = await sendToPlatform(
      {
        origin: () => this.origin(),
        token: async (origin) => this.context.secrets.get(tokenKey(origin)),
        confirm: () => Promise.resolve(false), // a GET changes nothing
        fetch: this.network,
      },
      { method: 'GET', path: `/api/v2/content/pages/?${new URLSearchParams({ source }).toString()}` },
    );
    if (reply.status === 503) {
      return 'files';
    }
    try {
      return reply.status !== 200 || (JSON.parse(reply.body) as { count?: unknown }).count !== 0 ? 'page' : 'files';
    } catch {
      return 'page'; // a platform that answers something else: the page view shows what it said
    }
  }

  async setToken(): Promise<void> {
    const origin = this.origin();
    if (origin === undefined) {
      const choice = await notifyError(
        settingsPlatformUrl() === undefined
          ? 'set zer0Cms.platform.url to your platform first.'
          : 'zer0Cms.platform.url must be an https URL, or http on this machine (localhost, 127.0.0.1, [::1]): your token goes with every request, and over plain http it would cross the network in clear text.',
        'Open settings',
      );
      if (choice !== undefined) {
        await vscode.commands.executeCommand('workbench.action.openSettings', 'zer0Cms.platform.url');
      }
      return;
    }
    const token = await vscode.window.showInputBox({
      title: `zer0-CMS: your token for ${origin}`,
      prompt:
        'A personal token from the platform — in the studio, your menu → API tokens (or python manage.py user_token <you> --name "VS Code"). ' +
        "It is kept in the editor's secret storage and sent to this platform only.",
      password: true,
      ignoreFocusOut: true,
      validateInput: (value) => (value.trim() === '' ? 'Paste the token.' : undefined),
    });
    if (token === undefined) {
      return;
    }
    await this.context.secrets.store(tokenKey(origin), token.trim());
    this.reload();
    void notifyInfo(`your token for ${origin} is set.`);
  }

  async clearToken(): Promise<void> {
    const origin = this.origin();
    if (origin === undefined) {
      void notifyInfo('no platform is configured, so there is no token to clear.');
      return;
    }
    await this.context.secrets.delete(tokenKey(origin));
    this.reload();
    void notifyInfo(`your token for ${origin} is cleared.`);
  }

  /** Every open studio webview starts again, so it asks with the token as it is now. */
  reload(): void {
    for (const session of this.sessions) {
      session.render();
    }
  }

  forget(session: Session): void {
    this.sessions.delete(session);
  }

  dispose(): void {
    for (const { panel } of [...this.panels.values()]) {
      panel.dispose();
    }
    for (const session of [...this.sessions]) {
      session.dispose();
    }
    for (const disposable of this.disposables.splice(0)) {
      disposable.dispose();
    }
  }

  private open(view: PanelView, to?: Record<string, unknown>): void {
    const open = this.panels.get(view);
    if (open !== undefined) {
      open.panel.reveal();
      if (to !== undefined) {
        open.session.show(to);
      }
      return;
    }
    const panel = vscode.window.createWebviewPanel(`zer0Cms.studio.${view}`, TITLES[view], vscode.ViewColumn.Active, {
      enableScripts: true,
      retainContextWhenHidden: true,
    });
    panel.iconPath = vscode.Uri.joinPath(this.context.extensionUri, 'media', 'zer0-cms-activity.svg');
    const session = this.connect(panel.webview, view, 'panel');
    if (to !== undefined) {
      session.show(to);
    }
    this.panels.set(view, { panel, session });
    panel.onDidDispose(() => {
      this.panels.delete(view);
      session.dispose();
    });
  }

  private connect(webview: vscode.Webview, view: StudioView, surface: 'sidebar' | 'panel'): Session {
    const session = new Session(this, webview, view, surface);
    this.sessions.add(session);
    return session;
  }
}

/** One webview rendering the studio bundle, and its bridge. */
class Session implements vscode.Disposable {
  private readonly bridge: StudioBridge;
  private readonly disposables: vscode.Disposable[] = [];
  private ready = false;
  private pending: Record<string, unknown> | undefined;

  constructor(
    private readonly studio: Studio,
    private readonly webview: vscode.Webview,
    private readonly view: StudioView,
    private readonly surface: 'sidebar' | 'panel',
  ) {
    const root = studio.context.extensionUri;
    webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(root, 'media'), vscode.Uri.joinPath(root, 'dist')],
    };
    this.bridge = new StudioBridge({
      post: (message) => this.post(message),
      origin: () => studio.origin(),
      token: async (origin) => studio.context.secrets.get(tokenKey(origin)),
      confirm: (question) => confirm(question, 'Go ahead', 'The platform checks your permissions too.'),
      fetch: (url, init) => studio.network(url, init),
      openStream: (url, headers, events, onEvent) => followStream(studio.network, url, headers, events, onEvent),
      go: (to) => studio.openDashboard(to),
      openExternal: (url) => void vscode.env.openExternal(vscode.Uri.parse(url, true)),
    });
    this.disposables.push(webview.onDidReceiveMessage((message: unknown) => this.receive(message)));
    if (view === 'page') {
      this.disposables.push(vscode.window.onDidChangeActiveTextEditor(() => this.postFile()));
    }
    this.render();
  }

  render(): void {
    this.ready = false;
    this.bridge.dispose();
    this.webview.html = studioPage({
      cspSource: this.webview.cspSource,
      nonce: randomBytes(18).toString('base64'),
      asset: (...parts) => this.webview.asWebviewUri(vscode.Uri.joinPath(this.studio.context.extensionUri, ...parts)).toString(),
      view: this.view,
      surface: this.surface,
      origin: this.studio.origin(),
    });
  }

  /** A destination for the dashboard; held until the page says it is ready. */
  show(to: Record<string, unknown>): void {
    if (this.ready) {
      this.post({ type: 'go', to });
    } else {
      this.pending = to;
    }
  }

  dispose(): void {
    this.bridge.dispose();
    for (const disposable of this.disposables.splice(0)) {
      disposable.dispose();
    }
    this.studio.forget(this);
  }

  private post(message: unknown): void {
    void this.webview.postMessage(message).then(undefined, (error: unknown) => {
      log.verbose(`studio: postMessage failed (${describeError(error)})`);
    });
  }

  private receive(message: unknown): void {
    if (typeof message === 'object' && message !== null && (message as { type?: unknown }).type === 'ready') {
      this.ready = true;
      if (this.view === 'page') {
        this.postFile();
      }
      if (this.pending !== undefined) {
        this.post({ type: 'go', to: this.pending });
        this.pending = undefined;
      }
      return;
    }
    this.bridge.receive(message).catch((error: unknown) => log.warn(`studio: ${describeError(error)}`));
  }

  /**
   * The open file, as its path from its folder (`sourcePath`). An editor that
   * is not a content file (output, settings, code) leaves the last one shown;
   * a file in no folder is no file at all.
   */
  private postFile(): void {
    const document = vscode.window.activeTextEditor?.document;
    if (document === undefined || !editable(document)) {
      return;
    }
    const source = sourcePath(document.uri);
    this.post({ type: 'file', file: source === undefined ? null : { path: source, name: path.basename(document.uri.fsPath) } });
  }
}

/**
 * An event stream from the platform, with the token as a header — which the
 * browser's EventSource cannot send, so the host follows it with the
 * `eventsource` package's, which behaves the same: it reconnects after a drop
 * and gives up on a refusal, which the webview hears as the event `error`.
 */
function followStream(
  network: Studio['network'],
  url: string,
  headers: Record<string, string>,
  events: readonly string[],
  onEvent: (event: string, data: string | null) => void,
): () => void {
  const source = new EventSource(url, {
    fetch: (input, init) => network(String(input), { ...init, headers: { ...init.headers, ...headers } }),
  });
  for (const name of events) {
    source.addEventListener(name, (event) => onEvent(name, event.data));
  }
  source.addEventListener('error', () => {
    if (source.readyState === EventSource.CLOSED) {
      onEvent('error', null);
    }
  });
  return () => source.close();
}
