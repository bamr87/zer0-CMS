/**
 * The browser bridge's host (decision D18): the loopback socket, the call into
 * the editor's integrated-browser tools, the status bar item and the
 * connection file. Every rule a request is held to is in
 * `core/browser/bridge.ts`; this file wires it to `node:http` and `vscode.lm`.
 *
 * Nothing here runs at activation (D11): `start()` is the
 * `zer0Cms.browserBridge.start` command — a person's act — in a trusted
 * workspace only (D13). The socket binds 127.0.0.1 on a port the system picks.
 * The token is new for every start and lives in memory and in the connection
 * file (mode 0600, in this extension's global storage, where a local agent
 * reads it) — never in a setting, a log line or an error. `stop()`, closing the
 * window and disabling the extension each close the socket and delete the file.
 */

import { randomBytes } from 'node:crypto';
import * as fs from 'node:fs';
import * as http from 'node:http';
import * as path from 'node:path';

import * as vscode from 'vscode';

import { workspaceTrusted } from './config';
import {
  BRIDGE_MAX_BODY,
  BRIDGE_PATH,
  BROWSER_TOOLS,
  bridgeMcpConfig,
  handleBridgeRequest,
  type BrowserHost,
  type BrowserPart,
} from './core';
import { describeError, log } from './logger';
import { notifyInfo, notifyWarning } from './uiState';

/** Where a local agent finds the URL and token, inside the extension's global storage. */
export const CONNECTION_FILE = 'browser-bridge.json';
/** A browser step that has not answered in two minutes is cancelled. */
const CALL_TIMEOUT_MS = 120_000;
const COPY = 'Copy MCP config';
const STOP = 'Stop';

/** A data part as `vscode.lm` returns it; typed structurally because the 1.101 API has no class for it. */
function isDataPart(part: unknown): part is { mimeType: string; data: Uint8Array } {
  return (
    typeof part === 'object' &&
    part !== null &&
    'mimeType' in part &&
    'data' in part &&
    typeof part.mimeType === 'string' &&
    part.data instanceof Uint8Array
  );
}

/** One part of a tool result, as MCP carries it: text, or an image as base64. */
function toPart(part: unknown): BrowserPart {
  if (part instanceof vscode.LanguageModelTextPart) {
    return { type: 'text', text: part.value };
  }
  if (isDataPart(part)) {
    const bytes = Buffer.from(part.data);
    return part.mimeType.startsWith('image/')
      ? { type: 'image', data: bytes.toString('base64'), mimeType: part.mimeType }
      : { type: 'text', text: bytes.toString('utf8') };
  }
  if (part instanceof vscode.LanguageModelPromptTsxPart) {
    return { type: 'text', text: JSON.stringify(part.value) };
  }
  return { type: 'text', text: '(a result part the bridge cannot carry)' };
}

/** The editor's side of the protocol: its browser tools, and a cancellable call into one. */
const editorBrowser: BrowserHost = {
  tools: () =>
    vscode.lm.tools
      .filter((tool) => BROWSER_TOOLS.includes(tool.name))
      .map((tool) => ({ name: tool.name, description: tool.description, inputSchema: tool.inputSchema ?? { type: 'object' } })),
  invoke: async (name, input) => {
    const cancel = new vscode.CancellationTokenSource();
    const timer = setTimeout(() => cancel.cancel(), CALL_TIMEOUT_MS);
    try {
      const result = await vscode.lm.invokeTool(name, { input, toolInvocationToken: undefined }, cancel.token);
      return result.content.map(toPart);
    } finally {
      clearTimeout(timer);
      cancel.dispose();
    }
  },
};

/** Node's headers, one string per name, as the protocol reads them. */
function flatHeaders(headers: http.IncomingHttpHeaders): Record<string, string | undefined> {
  const flat: Record<string, string | undefined> = {};
  for (const [name, value] of Object.entries(headers)) {
    flat[name] = Array.isArray(value) ? value.join(', ') : value;
  }
  return flat;
}

/** Read at most one byte past the limit, so an oversized body is refused without being held. */
async function readBody(request: http.IncomingMessage): Promise<string> {
  let body = '';
  request.setEncoding('utf8');
  for await (const chunk of request) {
    body += String(chunk);
    if (body.length > BRIDGE_MAX_BODY) {
      break;
    }
  }
  return body;
}

export class BrowserBridge implements vscode.Disposable {
  private server: http.Server | undefined;
  private token = '';
  private url = '';
  private status: vscode.StatusBarItem | undefined;

  constructor(private readonly context: vscode.ExtensionContext) {}

  private get connectionFile(): string {
    return path.join(this.context.globalStorageUri.fsPath, CONNECTION_FILE);
  }

  private get version(): string {
    const manifest = this.context.extension.packageJSON as { version?: unknown };
    return typeof manifest.version === 'string' ? manifest.version : '0.0.0';
  }

  /** Start listening, or say where it already is. */
  async start(): Promise<void> {
    if (this.server !== undefined) {
      await this.announce();
      return;
    }
    if (!workspaceTrusted()) {
      void notifyWarning('the browser bridge lets an agent drive the integrated browser, so it needs a trusted workspace.');
      return;
    }
    const token = randomBytes(32).toString('hex');
    const server = http.createServer((request, response) => {
      void this.serve(request, response, token);
    });
    await new Promise<void>((resolve, reject) => {
      server.once('error', reject);
      server.listen(0, '127.0.0.1', () => {
        server.off('error', reject);
        resolve();
      });
    });
    const address = server.address();
    if (address === null || typeof address === 'string') {
      server.close();
      throw new Error('the browser bridge could not read the port it was given');
    }
    this.server = server;
    this.token = token;
    this.url = `http://127.0.0.1:${address.port}${BRIDGE_PATH}`;
    this.writeConnectionFile();
    this.showStatus(address.port);
    log.info(`browser bridge listening on ${this.url}; connection file ${this.connectionFile}`);
    await this.announce();
  }

  /** Close the socket and delete the connection file. */
  stop(): void {
    if (this.server === undefined) {
      void notifyInfo('the browser bridge is not running.');
      return;
    }
    this.close();
    void notifyInfo('browser bridge stopped.');
  }

  dispose(): void {
    this.close();
  }

  private close(): void {
    const server = this.server;
    if (server === undefined) {
      return;
    }
    server.close();
    server.closeAllConnections();
    this.server = undefined;
    this.removeConnectionFile();
    this.token = '';
    this.url = '';
    this.status?.hide();
    log.info('browser bridge stopped');
  }

  private async announce(): Promise<void> {
    const choice = await notifyInfo(`browser bridge listening on ${this.url} — agents can drive the integrated browser.`, COPY, STOP);
    if (choice === COPY && this.server !== undefined) {
      await vscode.env.clipboard.writeText(bridgeMcpConfig(this.url, this.token));
      void notifyInfo('MCP config copied. It holds this start\'s token; stopping the bridge retires it.');
    } else if (choice === STOP) {
      this.stop();
    }
  }

  private async serve(request: http.IncomingMessage, response: http.ServerResponse, token: string): Promise<void> {
    try {
      const reply = await handleBridgeRequest(
        {
          method: request.method ?? '',
          path: (request.url ?? '').split('?')[0] ?? '',
          headers: flatHeaders(request.headers),
          body: await readBody(request),
        },
        token,
        editorBrowser,
        this.version,
      );
      response.writeHead(reply.status, { ...reply.headers, 'Cache-Control': 'no-store' });
      response.end(reply.body);
    } catch (error) {
      log.error(`browser bridge: ${describeError(error)}`);
      if (!response.headersSent) {
        response.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' });
      }
      response.end('internal error\n');
    }
  }

  private showStatus(port: number): void {
    if (this.status === undefined) {
      this.status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 90);
      this.status.command = 'zer0Cms.browserBridge.stop';
      this.context.subscriptions.push(this.status);
    }
    this.status.text = `$(globe) Browser bridge :${port}`;
    this.status.tooltip = 'zer0-CMS: an agent can drive the integrated browser through this bridge. Click to stop it.';
    this.status.show();
  }

  private writeConnectionFile(): void {
    const file = this.connectionFile;
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const folders = (vscode.workspace.workspaceFolders ?? []).map((folder) => folder.uri.fsPath);
    const body = { url: this.url, token: this.token, pid: process.pid, startedAt: new Date().toISOString(), folders };
    fs.writeFileSync(file, `${JSON.stringify(body, null, 2)}\n`, { mode: 0o600 });
    fs.chmodSync(file, 0o600);
  }

  /** Delete the file only if it is still this start's — another window may have started its own since. */
  private removeConnectionFile(): void {
    try {
      const current = JSON.parse(fs.readFileSync(this.connectionFile, 'utf8')) as { token?: unknown };
      if (current.token === this.token) {
        fs.unlinkSync(this.connectionFile);
      }
    } catch (error) {
      log.verbose(`browser bridge: no connection file to remove (${describeError(error)})`);
    }
  }
}
