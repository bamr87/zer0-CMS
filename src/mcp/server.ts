/**
 * The zer0-CMS MCP server — the CMS as tools, over stdio.
 *
 * Bundled to `dist/mcp-server.js` with **nothing marked external**, which is
 * how decision D1 is enforced: a stray `import 'vscode'` anywhere in this
 * graph is a build error, not a crash inside somebody's MCP client. The
 * extension registers this file through `vscode.lm`, but `node
 * dist/mcp-server.js` with only `cwd` set is a supported way to run it — Claude
 * Code, a `.vscode/mcp.json` entry, or a shell all work.
 *
 * **stdout is the protocol channel.** The first executable statements in this
 * file capture `process.stdout.write` and point every `console.*` method at
 * stderr. Nothing else may be imported at module scope: with a bundler,
 * dependencies evaluate *before* the entry file's body, so a static import
 * here would let a module-scope `console.log` three files away emit a line
 * into the JSON-RPC stream before the redirect ever ran. Everything the server
 * needs is therefore loaded inside `bootstrap()`, after the channel is safe.
 * The startup banner goes to stderr too.
 *
 * The transport is hand-rolled newline-delimited JSON-RPC 2.0 — no SDK, no
 * dependency. An unparseable line is skipped and the loop stays alive, because
 * one malformed frame from a client must not take the session with it.
 */

// --- Protect the protocol channel FIRST ------------------------------------
// Captured before the redirect so the server can still write frames.
const protocolWrite = process.stdout.write.bind(process.stdout);

function toStderr(...args: unknown[]): void {
  process.stderr.write(`${args.map(String).join(' ')}\n`);
}
console.log = toStderr;
console.info = toStderr;
console.warn = toStderr;
console.debug = toStderr;
console.error = toStderr;
// --- End of the protected prologue -----------------------------------------

// Type-only imports. These are erased at compile time and import nothing at
// runtime, so they cannot violate the rule above.
import type { Zer0Config } from '../core/shared/types';
import type { ToolArgs } from './tools';

type ToolsModule = typeof import('./tools');

export const SERVER_NAME = 'zer0-cms';
export const SERVER_VERSION = '0.1.0';

/** Echoed back when the client asks for one of these; otherwise ours wins. */
const SUPPORTED_PROTOCOLS: ReadonlySet<string> = new Set([
  '2024-11-05',
  '2025-03-26',
  '2025-06-18',
]);
const DEFAULT_PROTOCOL = '2025-06-18';

const INSTRUCTIONS =
  'Tools for a governed content repository. Reads and previews are always safe: ' +
  'zer0_status, zer0_list_content, zer0_get_content and zer0_preview never write. ' +
  'zer0_draft stages a pending draft for a human to approve — prefer it. ' +
  'zer0_publish writes real content and is off unless the server environment opts ' +
  'in and the call passes confirm=true.';

// ---------------------------------------------------------------------------
// JSON-RPC framing
// ---------------------------------------------------------------------------

interface JsonRpcMessage {
  id: unknown;
  /** A message with no `id` at all is a notification and gets no response. */
  hasId: boolean;
  method: string;
  params: Record<string, unknown>;
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

/** A line is a message only if it is a JSON object naming a method. */
function asMessage(value: unknown): JsonRpcMessage | undefined {
  const raw = asRecord(value);
  if (!raw || typeof raw.method !== 'string') {
    return undefined;
  }
  return {
    id: raw.id,
    hasId: 'id' in raw,
    method: raw.method,
    params: asRecord(raw.params) ?? {},
  };
}

function send(message: Record<string, unknown>): void {
  protocolWrite(`${JSON.stringify(message)}\n`);
}

function sendResult(id: unknown, result: unknown): void {
  send({ jsonrpc: '2.0', id, result });
}

function sendError(id: unknown, code: number, message: string): void {
  send({ jsonrpc: '2.0', id, error: { code, message } });
}

// ---------------------------------------------------------------------------
// Dispatch
// ---------------------------------------------------------------------------

interface Session {
  /** Workspace root. The extension sets `cwd`; a hand-run inherits the shell's. */
  root: string;
  tools: ToolsModule;
  /** Tail of the tool-execution chain. See `enqueue`. */
  queue: Promise<void>;
}

/**
 * Run tool calls one at a time.
 *
 * JSON-RPC lets a client pipeline requests, and `readline` hands us every
 * buffered line at once. Without this, two `zer0_publish` frames sent
 * back-to-back both read the ledger before either writes it, and the
 * publish-exactly-once guarantee — the whole reason the ledger exists —
 * quietly stops holding. `initialize`, `ping` and `tools/list` are not queued:
 * they touch nothing and must stay answerable while a slow engine run is in
 * flight.
 */
function enqueue(session: Session, work: () => Promise<void>): Promise<void> {
  const next = session.queue.then(
    () => work(),
    () => work(),
  );
  // The tail is a barrier, not a result: swallow rejections so one failed link
  // cannot break every later call. `callTool` answers its own failures.
  session.queue = next.then(
    () => undefined,
    () => undefined,
  );
  return next;
}

/**
 * Configuration is re-read from disk for every tool call rather than cached at
 * startup. A long-lived server would otherwise keep gating against a
 * `zer0.json` the author has since edited — and "the webview is never the
 * gate" is the same rule as "a stale snapshot is never the gate".
 */
async function currentConfig(session: Session): Promise<Zer0Config> {
  return session.tools.loadServerConfig(session.root);
}

async function callTool(session: Session, id: unknown, params: Record<string, unknown>): Promise<void> {
  const name = typeof params.name === 'string' ? params.name : '';
  const args: ToolArgs = asRecord(params.arguments) ?? {};
  const tool = session.tools.TOOLS_BY_NAME.get(name);
  if (!tool) {
    sendError(id, -32602, `unknown tool: ${name || '(none given)'}`);
    return;
  }
  try {
    const cfg = await currentConfig(session);
    const text = await tool.handler(cfg, args);
    sendResult(id, {
      content: [{ type: 'text', text }],
      isError: session.tools.isErrorText(text),
    });
  } catch (error) {
    // A tool throwing is a bug in the tool, not a reason to end the session.
    // The client gets a flagged result and the next call still works.
    const kind = error instanceof Error ? error.constructor.name : 'Error';
    const detail = error instanceof Error ? error.message : String(error);
    sendResult(id, {
      content: [{ type: 'text', text: `tool error: ${kind}: ${detail}` }],
      isError: true,
    });
  }
}

async function handle(message: JsonRpcMessage, session: Session): Promise<void> {
  const { id, method, params } = message;

  if (method === 'initialize') {
    const requested = typeof params.protocolVersion === 'string' ? params.protocolVersion : '';
    sendResult(id, {
      protocolVersion: SUPPORTED_PROTOCOLS.has(requested) ? requested : DEFAULT_PROTOCOL,
      capabilities: { tools: { listChanged: false } },
      serverInfo: { name: SERVER_NAME, version: SERVER_VERSION },
      instructions: INSTRUCTIONS,
    });
    return;
  }

  if (!message.hasId) {
    // notifications/initialized, notifications/cancelled, … — never answered.
    return;
  }

  if (method === 'ping') {
    sendResult(id, {});
    return;
  }

  if (method === 'tools/list') {
    sendResult(id, {
      tools: session.tools.TOOLS.map((tool) => ({
        name: tool.name,
        description: tool.description,
        inputSchema: tool.inputSchema,
      })),
    });
    return;
  }

  if (method === 'tools/call') {
    await enqueue(session, () => callTool(session, id, params));
    return;
  }

  sendError(id, -32601, `method not found: ${method}`);
}

// ---------------------------------------------------------------------------
// The loop
// ---------------------------------------------------------------------------

async function bootstrap(): Promise<void> {
  // Loaded here, not at module scope — see the header. Everything below this
  // line runs with stdout already reserved for the protocol. The `.js`
  // extension is what `moduleResolution: Node16` requires of a *dynamic*
  // import; both esbuild and the plain `tsc` output resolve it to this
  // directory's `tools`.
  const tools = await import('./tools.js');
  const readline = await import('node:readline');

  const session: Session = { root: process.cwd(), tools, queue: Promise.resolve() };
  const enabled = tools.publishEnabled(process.env) ? 'ENABLED' : 'disabled';
  process.stderr.write(
    `[${SERVER_NAME}] ready — cwd ${session.root}, publish ${enabled}\n`,
  );

  const rl = readline.createInterface({ input: process.stdin, terminal: false });
  rl.on('line', (line: string) => {
    const trimmed = line.trim();
    if (trimmed === '') {
      return;
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(trimmed);
    } catch {
      // An unparseable line is skipped in silence and the loop stays alive.
      // Clients emit stray output more often than anyone admits, and killing
      // the session over one bad frame loses every pending call with it.
      return;
    }
    const message = asMessage(parsed);
    if (!message) {
      return;
    }
    void handle(message, session).catch((error: unknown) => {
      if (message.hasId) {
        const detail = error instanceof Error ? error.message : String(error);
        sendError(message.id, -32603, `internal error: ${detail}`);
      }
    });
  });
}

/**
 * Start the server. Exported for tests and callers that embed it, and invoked
 * at module scope below — importing this file starts a server, deliberately:
 * `dist/mcp-server.js` is an executable, not a library.
 */
export function runServer(): void {
  void bootstrap().catch((error: unknown) => {
    const detail = error instanceof Error ? error.message : String(error);
    process.stderr.write(`[${SERVER_NAME}] failed to start: ${detail}\n`);
    process.exitCode = 1;
  });
}

runServer();
