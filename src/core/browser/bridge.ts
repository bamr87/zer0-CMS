/**
 * The browser bridge's protocol — the pure half (decision D18), so every rule a
 * request is held to is testable without an editor and reads in one place.
 *
 * VS Code's integrated browser ships agent tools — open a page, read it, click,
 * type, screenshot — that only the editor's own chat and its extensions can
 * call. The bridge offers exactly those tools to an agent outside the editor
 * (Claude Code, any MCP client) as an MCP server over Streamable HTTP on this
 * machine: one POST endpoint, JSON-RPC 2.0 answered with JSON, no event stream
 * and no session. The shell (`src/browserBridge.ts`) owns the socket and the
 * editor call; this file decides what a request may do:
 *
 *   - **Loopback, and never from a web page.** The `Host` must name this
 *     machine, and a request that carries an `Origin` is refused: browsers send
 *     one and MCP clients do not, so no page — not even one the integrated
 *     browser is showing — can reach the bridge, DNS rebinding included.
 *   - **A bearer token,** new for every start, compared in constant time.
 *   - **Browser tools only.** `tools/list` and `tools/call` see the editor's
 *     integrated-browser tools named in `BROWSER_TOOLS` and nothing else, so the
 *     bridge never reaches a terminal, a file edit or any other tool the editor
 *     has registered. `run_playwright_code` is not one of them: a snippet can go
 *     to any URL and run anything in the page, so no rule here could hold it.
 *   - **Web pages only.** A URL handed to `open_browser_page` or `navigate_page`
 *     is http or https, and what a page shows comes back only from an http or
 *     https page: a `read_page` result must name its page's URL, a
 *     `screenshot_page` result is returned only when the editor's page list
 *     gives that page a web URL, and any result whose page summary names
 *     another scheme is withheld. A page the person opened on a file, say, is
 *     neither read nor shown, so the browser cannot be used to read the disk.
 */

import { timingSafeEqual } from 'node:crypto';

/** The integrated browser's tools, in the order `tools/list` returns them. */
export const BROWSER_TOOLS: readonly string[] = [
  'open_browser_page',
  'list_browser_pages',
  'navigate_page',
  'read_page',
  'screenshot_page',
  'click_element',
  'hover_element',
  'type_in_page',
  'drag_element',
  'handle_dialog',
];

/** The one path the bridge answers on. */
export const BRIDGE_PATH = '/mcp';
/** A JSON-RPC frame is small; anything larger is refused before it is parsed. */
export const BRIDGE_MAX_BODY = 1_000_000;
export const BRIDGE_SERVER_NAME = 'zer0-cms-browser';

const TOOL_SET: ReadonlySet<string> = new Set(BROWSER_TOOLS);
/** The tools that take a URL, which must be a web page's. */
const URL_TOOLS: ReadonlySet<string> = new Set(['open_browser_page', 'navigate_page']);
/**
 * One page in `list_browser_pages`' answer, as VS Code 1.144 writes it: a bullet,
 * `[<id>] <title> (<url>)`, an optional resource note, then where the page is.
 */
const LISTED_PAGE = /^\s*(?:-|\d+\.) \[([^\]]*)\] (.*?)(?: \(resource-backed; [^)]*\))? \((?:active|visible|not visible)\)$/;
const LOOPBACK_HOST = /^(?:localhost|127(?:\.\d{1,3}){3}|\[::1\])(?::\d{1,5})?$/;
const SUPPORTED_PROTOCOLS: ReadonlySet<string> = new Set(['2024-11-05', '2025-03-26', '2025-06-18']);
const DEFAULT_PROTOCOL = '2025-06-18';
const INSTRUCTIONS =
  'Tools that drive the VS Code integrated browser of the editor window that started this bridge. ' +
  'Open a page with open_browser_page, then pass the page id it returns to the other tools. ' +
  'Only http and https pages can be opened, read or captured. A person may be asked to confirm a step in the editor.';

/** A tool as the editor describes it. */
export interface BrowserTool {
  name: string;
  description: string;
  inputSchema: object;
}

/** One piece of a tool's result, as MCP carries it. */
export type BrowserPart =
  | { type: 'text'; text: string }
  | { type: 'image'; data: string; mimeType: string };

/** What the shell gives the protocol: the editor's tools and a way to call one. */
export interface BrowserHost {
  tools(): readonly BrowserTool[];
  invoke(name: string, input: Record<string, unknown>): Promise<readonly BrowserPart[]>;
}

/** A request as the socket read it; header names are lower case, as Node gives them. */
export interface BridgeRequest {
  method: string;
  path: string;
  headers: Readonly<Record<string, string | undefined>>;
  body: string;
}

export interface BridgeReply {
  status: number;
  headers: Record<string, string>;
  body: string;
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function plain(status: number, message: string, headers: Record<string, string> = {}): BridgeReply {
  return { status, headers: { 'Content-Type': 'text/plain; charset=utf-8', ...headers }, body: `${message}\n` };
}

function json(status: number, payload: unknown): BridgeReply {
  return { status, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) };
}

function rpcResult(id: unknown, result: unknown): BridgeReply {
  return json(200, { jsonrpc: '2.0', id, result });
}

function rpcError(status: number, id: unknown, code: number, message: string): BridgeReply {
  return json(status, { jsonrpc: '2.0', id, error: { code, message } });
}

function toolText(id: unknown, text: string, isError: boolean): BridgeReply {
  return rpcResult(id, { content: [{ type: 'text', text }], isError });
}

/** `Bearer <token>`, compared without leaking where the first difference is. */
function authorized(header: string | undefined, token: string): boolean {
  if (header === undefined || token === '') {
    return false;
  }
  const given = Buffer.from(header);
  const expected = Buffer.from(`Bearer ${token}`);
  return given.length === expected.length && timingSafeEqual(given, expected);
}

/** http or https, nothing else. */
export function isWebUrl(value: string): boolean {
  try {
    const { protocol } = new URL(value);
    return protocol === 'http:' || protocol === 'https:';
  } catch {
    return false;
  }
}

/**
 * The page a browser tool's result describes, from its page summary: VS Code's
 * tools answer with `URL: <url>`, after a `Page Title: <title>` line when the
 * page has one (a title never spans lines). `undefined` when the text is not a
 * summary.
 */
function summaryPageUrl(text: string): string | undefined {
  const [first = '', second = ''] = text.split('\n', 2);
  const line = first.startsWith('Page Title: ') ? second : first;
  return line.startsWith('URL: ') ? line.slice('URL: '.length) : undefined;
}

/**
 * The URL `list_browser_pages` gives the page `id`, or `undefined` when the
 * list does not show it with one. A URL never holds a space, so it is what
 * follows the line's last ` (`, whatever the page's title says.
 */
function listedPageUrl(listing: string, id: string): string | undefined {
  for (const line of listing.split('\n')) {
    const match = LISTED_PAGE.exec(line);
    if (match?.[1] !== id) {
      continue;
    }
    const rest = match[2] ?? '';
    const open = rest.lastIndexOf(' (');
    return open >= 0 && rest.endsWith(')') ? rest.slice(open + 2, -1) : undefined;
  }
  return undefined;
}

/**
 * Every page this result shows: the URLs its page summaries name and, for a
 * screenshot (an image, which names nothing), the URL the editor lists for the
 * page it was taken of. An entry that is not a web URL withholds the result;
 * `''` stands for a page the bridge could not place.
 */
async function pagesShown(name: string, input: Record<string, unknown>, content: readonly BrowserPart[], host: BrowserHost): Promise<string[]> {
  const pages = content.flatMap((part) => {
    const url = part.type === 'text' ? summaryPageUrl(part.text) : undefined;
    return url === undefined ? [] : [url];
  });
  if (name === 'read_page' && pages.length === 0) {
    pages.push('');
  }
  if (name === 'screenshot_page') {
    const listing = await host.invoke('list_browser_pages', {});
    const text = listing.flatMap((part) => (part.type === 'text' ? [part.text] : [])).join('\n');
    pages.push(listedPageUrl(text, typeof input.pageId === 'string' ? input.pageId : '') ?? '');
  }
  return pages;
}

/** The transport's rules, in order; `undefined` means the request may be read. */
function refusal(request: BridgeRequest, token: string): BridgeReply | undefined {
  if (request.path !== BRIDGE_PATH) {
    return plain(404, 'not found');
  }
  if (!LOOPBACK_HOST.test(request.headers.host ?? '')) {
    return plain(403, 'the bridge answers requests addressed to this machine only');
  }
  if (request.headers.origin !== undefined) {
    return plain(403, 'the bridge does not answer web pages');
  }
  if (!authorized(request.headers.authorization, token)) {
    return plain(401, 'a bearer token is required', { 'WWW-Authenticate': 'Bearer' });
  }
  if (request.method !== 'POST') {
    return plain(405, 'POST a JSON-RPC message; the bridge offers no event stream', { Allow: 'POST' });
  }
  if (!(request.headers['content-type'] ?? '').toLowerCase().startsWith('application/json')) {
    return plain(415, 'the body must be application/json');
  }
  if (request.body.length > BRIDGE_MAX_BODY) {
    return plain(413, 'the body is too large');
  }
  return undefined;
}

async function callTool(id: unknown, params: Record<string, unknown>, host: BrowserHost): Promise<BridgeReply> {
  const name = typeof params.name === 'string' ? params.name : '';
  if (!TOOL_SET.has(name) || !host.tools().some((tool) => tool.name === name)) {
    return rpcError(200, id, -32602, `unknown tool: ${name || '(none given)'}`);
  }
  const input = asRecord(params.arguments) ?? {};
  const url = input.url;
  if (URL_TOOLS.has(name) && typeof url === 'string' && !isWebUrl(url)) {
    return toolText(id, `refused: ${name} opens http and https pages only`, true);
  }
  try {
    const content = await host.invoke(name, input);
    if ((await pagesShown(name, input, content, host)).some((page) => !isWebUrl(page))) {
      return toolText(id, `refused: ${name} returns what http and https pages show only`, true);
    }
    return rpcResult(id, { content, isError: false });
  } catch (error) {
    // A tool that throws is answered as a flagged result; the next call still works.
    return toolText(id, `tool error: ${error instanceof Error ? error.message : String(error)}`, true);
  }
}

/**
 * Answer one HTTP request. `token` is the one this start of the bridge made;
 * `version` is the extension's, reported as the server's.
 */
export async function handleBridgeRequest(
  request: BridgeRequest,
  token: string,
  host: BrowserHost,
  version: string,
): Promise<BridgeReply> {
  const refused = refusal(request, token);
  if (refused !== undefined) {
    return refused;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(request.body);
  } catch {
    return rpcError(400, null, -32700, 'parse error');
  }
  const message = asRecord(parsed);
  if (message === undefined) {
    return rpcError(400, null, -32600, 'one JSON-RPC message per request');
  }
  if (typeof message.method !== 'string') {
    // A client's reply to us — we never ask, so there is nothing to match it to.
    return 'result' in message || 'error' in message ? { status: 202, headers: {}, body: '' } : rpcError(400, null, -32600, 'invalid request');
  }
  if (!('id' in message)) {
    // notifications/initialized, notifications/cancelled, … — accepted, never answered.
    return { status: 202, headers: {}, body: '' };
  }

  const { id } = message;
  const params = asRecord(message.params) ?? {};
  switch (message.method) {
    case 'initialize': {
      const requested = typeof params.protocolVersion === 'string' ? params.protocolVersion : '';
      return rpcResult(id, {
        protocolVersion: SUPPORTED_PROTOCOLS.has(requested) ? requested : DEFAULT_PROTOCOL,
        capabilities: { tools: { listChanged: false } },
        serverInfo: { name: BRIDGE_SERVER_NAME, version },
        instructions: INSTRUCTIONS,
      });
    }
    case 'ping':
      return rpcResult(id, {});
    case 'tools/list': {
      const offered = new Map(host.tools().map((tool) => [tool.name, tool]));
      const tools = BROWSER_TOOLS.flatMap((name) => {
        const tool = offered.get(name);
        return tool === undefined ? [] : [{ name, description: tool.description, inputSchema: tool.inputSchema }];
      });
      return rpcResult(id, { tools });
    }
    case 'tools/call':
      return callTool(id, params, host);
    default:
      return rpcError(200, id, -32601, `method not found: ${message.method}`);
  }
}

/** The JSON an MCP client is configured with, e.g. `claude mcp add-json zer0-browser '<this>'`. */
export function bridgeMcpConfig(url: string, token: string): string {
  return JSON.stringify({ type: 'http', url, headers: { Authorization: `Bearer ${token}` } });
}
