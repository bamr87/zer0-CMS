/**
 * The host side of the studio's transport in a webview (PLAN G10, ADR 0006
 * decision 9) — the pure half, so every gate on it is testable without an
 * editor and reads in one place.
 *
 * When a platform is configured, the extension's webviews render the studio's
 * workspaces from `web/packages/` (`dist/studio.js`), and their API client
 * speaks postMessage (`web/packages/webview/src/transport.ts`). A webview names
 * a method, a path and a JSON body; this turns the message into a request to
 * the platform with the URL from the settings layer and the person's token
 * from SecretStorage, both read fresh for each request, and posts back the
 * status and the body. The rules (decisions D5, D11, D13):
 *
 *   - **The webview never sees the token.** It is added here, to a request
 *     whose origin is the configured platform's, and never posted, logged or
 *     put in an error.
 *   - **The webview is UI, never the gate.** Only a path under `/api/v2/`,
 *     with no way out of it (`..`, a scheme, a second origin), and only
 *     `GET`, `POST`, `PATCH`, `PUT` and `DELETE`; never the session endpoints
 *     (the extension signs in with a token). A request that changes the live
 *     site — publish, unpublish, schedule — asks the person modally first,
 *     whatever the webview showed; the platform then checks their permissions.
 *   - **Network only from an explicit act.** Nothing here runs until a webview
 *     the person opened asks; `fetch` and the stream opener are injected.
 *
 * A refusal answers like the platform would — the error envelope with a status
 * and a code — so the workspace shows it where the request was made.
 */

/** A path the webview may ask for: the platform's API, nothing else. */
const API_PREFIX = '/api/v2/';
const METHODS: ReadonlySet<string> = new Set(['GET', 'POST', 'PATCH', 'PUT', 'DELETE']);
/** A session belongs to a browser; the extension authenticates with a token. */
const SESSION_PREFIX = '/api/v2/session/';
const MAX_BODY = 1_000_000;
const MAX_PATH = 2048;
const MAX_STREAMS = 8;
/** The three requests that change what the live site shows, and how to ask. */
const LIVE_CHANGES: ReadonlyArray<readonly [RegExp, string]> = [
  [/^\/api\/v2\/content\/pages\/(\d+)\/publish\/$/, 'Publish page $1 on $origin?'],
  [/^\/api\/v2\/content\/pages\/(\d+)\/unpublish\/$/, 'Take page $1 off the live site on $origin?'],
  [/^\/api\/v2\/content\/pages\/(\d+)\/schedule\/$/, 'Schedule page $1 to go live (or come down) on $origin?'],
];

export interface BridgeDeps {
  /** Posts a message into the webview. */
  post(message: unknown): void;
  /** The platform's origin from the settings layer, read fresh; undefined when none is configured. */
  origin(): string | undefined;
  /** The person's token for that origin, from SecretStorage; undefined when none is set. */
  token(origin: string): Promise<string | undefined>;
  /** Asks the person modally; true to go ahead. */
  confirm(question: string): Promise<boolean>;
  /** The network (decision D11): injected, so a test can prove what is sent. */
  fetch(url: string, init: RequestInit): Promise<Response>;
  /** Follows an event stream with these headers; each event's text is handed on as it came. */
  openStream(
    url: string,
    headers: Record<string, string>,
    events: readonly string[],
    onEvent: (event: string, data: string | null) => void,
  ): () => void;
  /** Hands a destination to the dashboard (it opens there). */
  go(to: Record<string, unknown>): void;
  /** Opens a URL outside the editor. */
  openExternal(url: string): void;
}

/** The platform's origin for a configured URL, or undefined when it is not an http(s) URL. */
export function platformOrigin(url: string | undefined): string | undefined {
  if (!url) {
    return undefined;
  }
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? parsed.origin : undefined;
  } catch {
    return undefined; // not a URL at all: there is no platform to talk to
  }
}

/** Where the person's token for `origin` is kept in SecretStorage: one per platform. */
export function tokenKey(origin: string): string {
  return `zer0Cms.platform.token:${origin}`;
}

/**
 * `path` as a request to `origin`, or undefined when it could leave the API:
 * not under `/api/v2/`, a `..` or an encoded one, a backslash, a fragment, a
 * control character, or anything that resolves to another origin or path.
 */
export function apiUrl(origin: string, path: unknown): string | undefined {
  if (typeof path !== 'string' || path.length > MAX_PATH || !path.startsWith(API_PREFIX)) {
    return undefined;
  }
  // The query may encode anything (`?source=_posts%2Fa.md`); the path may not.
  const query = path.indexOf('?');
  const pathname = query < 0 ? path : path.slice(0, query);
  if (/[\\#\s]/.test(path) || /%2e|%2f|%5c/i.test(pathname) || pathname.split('/').includes('..')) {
    return undefined;
  }
  const url = new URL(path, origin);
  return url.origin === origin && url.pathname.startsWith(API_PREFIX) ? url.toString() : undefined;
}

/** The question a person answers before `method path` changes the live site, or undefined. */
export function liveChange(method: string, path: string, origin: string): string | undefined {
  if (method !== 'POST') {
    return undefined;
  }
  const bare = path.split('?')[0] ?? '';
  for (const [pattern, question] of LIVE_CHANGES) {
    const match = pattern.exec(bare);
    if (match) {
      return question.replace('$1', match[1] ?? '').replace('$origin', origin);
    }
  }
  return undefined;
}

/** A link in a webview, made something to open: a platform path against its origin, or an http(s) URL. */
export function linkTarget(href: unknown, origin: string | undefined): string | undefined {
  if (typeof href !== 'string' || href.length > MAX_PATH) {
    return undefined;
  }
  if (href.startsWith('/') && !href.startsWith('//')) {
    return origin === undefined ? undefined : new URL(href, origin).toString();
  }
  return platformOrigin(href) === undefined ? undefined : new URL(href).toString();
}

/** The platform's error envelope, as the host answers a refusal. */
export function envelope(status: number, code: string, message: string): string {
  return JSON.stringify({ error: { code, message, status, details: [], request_id: null, retry_after: null } });
}

function record(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

/** A destination is the dashboard's to read: a small JSON object with a string `to`, nothing more. */
function destination(value: unknown): Record<string, unknown> | undefined {
  const to = record(value);
  if (to === undefined || typeof to.to !== 'string') {
    return undefined;
  }
  const text = JSON.stringify(to);
  return text.length <= 512 ? (JSON.parse(text) as Record<string, unknown>) : undefined;
}

export class StudioBridge {
  private readonly streams = new Map<number, () => void>();

  constructor(private readonly deps: BridgeDeps) {}

  /** One message from the webview. Anything it does not recognise is dropped. */
  async receive(message: unknown): Promise<void> {
    const m = record(message);
    if (m === undefined) {
      return;
    }
    switch (m.type) {
      case 'api':
        return this.api(m);
      case 'stream':
        return this.stream(m);
      case 'stream.close':
        this.close(m.id);
        return;
      case 'go': {
        const to = destination(m.to);
        if (to !== undefined) {
          this.deps.go(to);
        }
        return;
      }
      case 'open': {
        const url = linkTarget(m.href, this.deps.origin());
        if (url !== undefined) {
          this.deps.openExternal(url);
        }
        return;
      }
      default:
        return;
    }
  }

  /** Closes every stream this webview opened. */
  dispose(): void {
    for (const id of [...this.streams.keys()]) {
      this.close(id);
    }
  }

  private reply(id: number, status: number, body: string, contentType = 'application/json'): void {
    this.deps.post({ type: 'api', id, status, body, contentType });
  }

  private async api(m: Record<string, unknown>): Promise<void> {
    const id = m.id;
    if (typeof id !== 'number') {
      return;
    }
    const method = typeof m.method === 'string' ? m.method.toUpperCase() : '';
    const origin = this.deps.origin();
    if (origin === undefined) {
      return this.reply(id, 503, envelope(503, 'extension.no_platform', 'No platform is configured: set zer0Cms.platform.url.'));
    }
    const url = apiUrl(origin, m.path);
    const body = m.body;
    if (!METHODS.has(method) || url === undefined || String(m.path).startsWith(SESSION_PREFIX)) {
      return this.reply(id, 403, envelope(403, 'extension.refused', `The extension does not send ${method || 'that'} ${String(m.path)}.`));
    }
    if (body !== undefined && (typeof body !== 'string' || body.length > MAX_BODY || method === 'GET')) {
      return this.reply(id, 422, envelope(422, 'extension.refused', 'A request body is JSON text, sent only with a write.'));
    }
    const token = await this.deps.token(origin);
    if (token === undefined) {
      return this.reply(
        id,
        401,
        envelope(401, 'auth.no_token', `No token for ${origin}: run “zer0-CMS: Set platform token”.`),
      );
    }
    const question = liveChange(method, String(m.path), origin);
    if (question !== undefined && !(await this.deps.confirm(question))) {
      return this.reply(id, 409, envelope(409, 'extension.cancelled', 'Cancelled: nothing was sent to the platform.'));
    }
    const headers: Record<string, string> = { Accept: 'application/json', Authorization: `Bearer ${token}` };
    if (typeof body === 'string') {
      headers['Content-Type'] = 'application/json';
    }
    try {
      const response = await this.deps.fetch(url, {
        method,
        headers,
        ...(typeof body === 'string' ? { body } : {}),
        redirect: 'error',
      });
      this.reply(id, response.status, await response.text(), response.headers.get('Content-Type') ?? 'application/json');
    } catch {
      // The reason is the network's (refused, a TLS failure, a redirect); the
      // message says where, never with what credential.
      this.reply(id, 503, envelope(503, 'platform.unreachable', `The platform at ${origin} did not answer.`));
    }
  }

  private async stream(m: Record<string, unknown>): Promise<void> {
    const id = m.id;
    if (typeof id !== 'number' || this.streams.has(id)) {
      return;
    }
    const events = Array.isArray(m.events) ? m.events.filter((e): e is string => typeof e === 'string').slice(0, 16) : [];
    const failed = () => this.deps.post({ type: 'event', id, event: 'error', data: null });
    const origin = this.deps.origin();
    const url = origin === undefined ? undefined : apiUrl(origin, m.path);
    if (origin === undefined || url === undefined || this.streams.size >= MAX_STREAMS) {
      return failed();
    }
    const token = await this.deps.token(origin);
    if (token === undefined) {
      return failed();
    }
    const close = this.deps.openStream(url, { Authorization: `Bearer ${token}` }, events, (event, data) => {
      this.deps.post({ type: 'event', id, event, data });
      if (event === 'end') {
        this.close(id);
      }
    });
    this.streams.set(id, close);
  }

  private close(id: unknown): void {
    if (typeof id !== 'number') {
      return;
    }
    const close = this.streams.get(id);
    this.streams.delete(id);
    close?.();
  }
}
