/**
 * The host side of the studio's transport in a webview (PLAN G10, ADR 0006
 * decision 9) — the pure half, so every gate on it is testable without an
 * editor and reads in one place.
 *
 * When a platform is configured, the extension's webviews render the studio's
 * workspaces from `web/packages/` (`dist/studio.js`), and their API client
 * speaks postMessage (`web/packages/webview/src/transport.ts`). A webview names
 * a method, a path, a JSON body and the few headers the platform reads;
 * `sendToPlatform` turns that into a request to the platform with the URL from
 * the settings layer and the person's token from SecretStorage, both read fresh
 * for each request, and answers with the status, the body and the headers a
 * workspace reads. The rules (decisions D5, D11, D13):
 *
 *   - **The webview never sees the token.** It is added here, to a request
 *     whose origin is the configured platform's, and never posted, logged or
 *     put in an error. The platform is https, or plain http on this machine
 *     only, so the token never crosses a network in clear text.
 *   - **The webview is UI, never the gate.** Only a path under `/api/v2/` that
 *     is exactly the path the platform routes — no `%`, no `.`, `..` or empty
 *     segment, nothing the URL parser would rewrite — and only `GET`, `POST`,
 *     `PATCH`, `PUT` and `DELETE`; never the session endpoints (the extension
 *     signs in with a token). A request that changes a live site or reaches
 *     people past the platform — a page published, unpublished or scheduled,
 *     from the editor or by a story's move; a distribution post published; a
 *     newsletter issue sent — asks the person modally first, whatever the
 *     webview showed; the platform then checks their permissions.
 *   - **Network only from an explicit act.** Nothing here runs until a webview
 *     the person opened asks, or the Metadata view asks which file is a page;
 *     `fetch` and the stream opener are injected.
 *
 * A refusal answers like the platform would — the error envelope with a status
 * and a code — so the workspace shows it where the request was made. A body is
 * JSON text and a reply is text: the platform's API answers JSON and event
 * streams, and an upload (multipart) is refused by the webview's transport.
 */

/** A path the webview may ask for: the platform's API, nothing else. */
const API_PREFIX = '/api/v2/';
const METHODS: ReadonlySet<string> = new Set(['GET', 'POST', 'PATCH', 'PUT', 'DELETE']);
/** A session belongs to a browser; the extension authenticates with a token. */
const SESSION = /^\/api\/v2\/session(?:\/|$)/;
/** The request headers a workspace may set, because the platform reads them; every other header is the host's. */
const REQUEST_HEADERS: readonly string[] = ['Idempotency-Key', 'If-Match'];
/** The response headers a workspace may read, beside the status and the body. */
const RESPONSE_HEADERS: readonly string[] = ['Content-Type', 'Location', 'Retry-After', 'X-Request-Id'];
/** Hosts the token may reach over plain http: this machine. */
const LOOPBACK = /^(?:localhost|127(?:\.\d{1,3}){3}|\[::1\])$/;
const MAX_BODY = 1_000_000;
const MAX_PATH = 2048;
const MAX_HEADER = 255;
const MAX_STREAMS = 8;
/**
 * The requests that change what a live site shows, or send something past the
 * platform to people, and how to ask. An id is any one segment. A page goes
 * live from the editor (publish, unpublish, schedule) and from the newsroom (a
 * story moved to published or scheduled — the body's `status` says which, so
 * that question is asked of the body that is sent); a distribution post goes to
 * its channel (LinkedIn, WordPress, a pull request, a newsletter) and a
 * newsletter issue to its subscribers.
 */
const LIVE_CHANGES: ReadonlyArray<readonly [RegExp, string]> = [
  [/^\/api\/v2\/content\/pages\/([^/]+)\/publish\/$/, 'Publish page $1 on $origin?'],
  [/^\/api\/v2\/content\/pages\/([^/]+)\/unpublish\/$/, 'Take page $1 off the live site on $origin?'],
  [/^\/api\/v2\/content\/pages\/([^/]+)\/schedule\/$/, 'Schedule page $1 to go live (or come down) on $origin?'],
  [/^\/api\/v2\/distribution\/posts\/([^/]+)\/publish\/$/, 'Publish distribution post $1 to its channel from $origin?'],
  [/^\/api\/v2\/newsroom\/issues\/([^/]+)\/send\/$/, 'Send newsletter issue $1 to its subscribers from $origin?'],
];
/** A story's move that puts its page live, by the `status` the body asks for. */
const STORY_MOVE = /^\/api\/v2\/newsroom\/stories\/([^/]+)\/move\/$/;
const STORY_RELEASES: Readonly<Record<string, string>> = {
  published: 'Publish story $1 on $origin?',
  scheduled: 'Schedule story $1 to go live on $origin?',
};

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

/**
 * The platform's origin for a configured URL, or undefined when the token may
 * not be sent there: an https URL, or http on this machine (`localhost`,
 * `127.0.0.0/8`, `[::1]`) — never plain http across a network.
 */
export function platformOrigin(url: string | undefined): string | undefined {
  try {
    const parsed = new URL(url ?? '');
    const safe = parsed.protocol === 'https:' || (parsed.protocol === 'http:' && LOOPBACK.test(parsed.hostname));
    return safe ? parsed.origin : undefined;
  } catch {
    return undefined; // not a URL at all: there is no platform to talk to
  }
}

/** Where the person's token for `origin` is kept in SecretStorage: one per platform. */
export function tokenKey(origin: string): string {
  return `zer0Cms.platform.token:${origin}`;
}

/**
 * `path` as a request to `origin`, or undefined when it is not plainly a path
 * of the platform's API. The gates read the path the platform will route, so
 * the path part must be sent as written: no `%` (the platform decodes
 * `%70ublish` into `publish` before routing), no `.`, `..` or empty segment (a
 * URL parser drops the first two, a proxy merges the third), no backslash,
 * fragment or white space, nothing the URL parser rewrites, and never the
 * session endpoints. The query may encode anything (`?source=a%2Fb.md`).
 */
export function apiUrl(origin: string, path: unknown): URL | undefined {
  if (typeof path !== 'string' || path.length > MAX_PATH || !path.startsWith(API_PREFIX) || /[\\#\s]/.test(path)) {
    return undefined;
  }
  const pathname = path.split('?', 1)[0] ?? '';
  const segments = pathname.slice(API_PREFIX.length).split('/');
  const odd = segments.some((s, i) => s === '.' || s === '..' || (s === '' && i < segments.length - 1));
  if (pathname.includes('%') || odd || SESSION.test(pathname)) {
    return undefined;
  }
  const url = new URL(path, origin);
  return url.origin === origin && url.pathname === pathname ? url : undefined;
}

/** A question with the id and the origin put in; by function, so a `$` in the path is text, not a replacement pattern. */
function ask(question: string, id: string | undefined, origin: string): string {
  return question.replace('$1', () => id ?? '').replace('$origin', () => origin);
}

/** The `status` a JSON body asks for, if it is an object that names one. */
function askedStatus(body: unknown): string | undefined {
  if (typeof body !== 'string') {
    return undefined;
  }
  try {
    const parsed: unknown = JSON.parse(body);
    const status = record(parsed)?.status;
    return typeof status === 'string' ? status : undefined;
  } catch {
    return undefined; // not JSON: the platform refuses it, and nothing goes live
  }
}

/**
 * The question a person answers before `method pathname` (with `body`, the
 * text that is sent) changes a live site or reaches people past the platform,
 * or undefined.
 */
export function liveChange(method: string, pathname: string, origin: string, body?: unknown): string | undefined {
  if (method !== 'POST') {
    return undefined;
  }
  for (const [pattern, question] of LIVE_CHANGES) {
    const match = pattern.exec(pathname);
    if (match) {
      return ask(question, match[1], origin);
    }
  }
  const move = STORY_MOVE.exec(pathname);
  const status = move ? askedStatus(body) : undefined;
  const question = status === undefined ? undefined : STORY_RELEASES[status];
  return question === undefined ? undefined : ask(question, move?.[1], origin);
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

/** A reply to a request: what the webview hears, and all the host passes on. */
export interface PlatformReply {
  status: number;
  body: string;
  /** Only `RESPONSE_HEADERS`, each the platform sent. */
  headers: Record<string, string>;
}

/** What `sendToPlatform` needs: `BridgeDeps` without the webview. */
export type PlatformDeps = Pick<BridgeDeps, 'origin' | 'token' | 'confirm' | 'fetch'>;

function refusal(status: number, code: string, message: string): PlatformReply {
  return { status, body: envelope(status, code, message), headers: { 'Content-Type': 'application/json' } };
}

/** The request headers asked for, when each is one the platform reads and short visible text; otherwise undefined. */
function forwarded(asked: unknown): Record<string, string> | undefined {
  const names = asked === undefined ? {} : record(asked);
  if (names === undefined) {
    return undefined;
  }
  const out: Record<string, string> = {};
  for (const [name, value] of Object.entries(names)) {
    const known = REQUEST_HEADERS.find((header) => header.toLowerCase() === name.toLowerCase());
    if (known === undefined || typeof value !== 'string' || value.length > MAX_HEADER || !/^[\x21-\x7e]+$/.test(value)) {
      return undefined;
    }
    out[known] = value;
  }
  return out;
}

/**
 * One request — `{method, path, body?, headers?}`, from a webview or from the
 * host itself — through every gate above, sent with the platform's URL and the
 * person's token; or refused, the way the platform refuses. Never throws, and
 * no reply carries the token.
 */
export async function sendToPlatform(deps: PlatformDeps, request: Record<string, unknown>): Promise<PlatformReply> {
  const method = typeof request.method === 'string' ? request.method.toUpperCase() : '';
  const origin = deps.origin();
  if (origin === undefined) {
    return refusal(503, 'extension.no_platform', 'No platform is configured: set zer0Cms.platform.url.');
  }
  const url = apiUrl(origin, request.path);
  if (!METHODS.has(method) || url === undefined) {
    return refusal(403, 'extension.refused', `The extension does not send ${method || 'that'} ${String(request.path)}.`);
  }
  const body = request.body;
  if (body !== undefined && (typeof body !== 'string' || body.length > MAX_BODY || method === 'GET')) {
    return refusal(422, 'extension.refused', 'A request body is JSON text, sent only with a write.');
  }
  const extra = forwarded(request.headers);
  if (extra === undefined) {
    return refusal(422, 'extension.refused', `The extension forwards only ${REQUEST_HEADERS.join(' and ')}, as short text.`);
  }
  const token = await deps.token(origin);
  if (token === undefined) {
    return refusal(401, 'auth.no_token', `No token for ${origin}: run “zer0-CMS: Set platform token”.`);
  }
  const question = liveChange(method, url.pathname, origin, body);
  if (question !== undefined && !(await deps.confirm(question))) {
    return refusal(409, 'extension.cancelled', 'Cancelled: nothing was sent to the platform.');
  }
  const headers: Record<string, string> = { ...extra, Accept: 'application/json', Authorization: `Bearer ${token}` };
  if (typeof body === 'string') {
    headers['Content-Type'] = 'application/json';
  }
  try {
    const response = await deps.fetch(url.toString(), {
      method,
      headers,
      ...(typeof body === 'string' ? { body } : {}),
      redirect: 'error',
    });
    const kept: Record<string, string> = {};
    for (const name of RESPONSE_HEADERS) {
      const value = response.headers.get(name);
      if (value !== null) {
        kept[name] = value;
      }
    }
    return { status: response.status, body: await response.text(), headers: kept };
  } catch {
    // The reason is the network's (refused, a TLS failure, a redirect); the
    // message says where, never with what credential.
    return refusal(503, 'platform.unreachable', `The platform at ${origin} did not answer.`);
  }
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

  private async api(m: Record<string, unknown>): Promise<void> {
    if (typeof m.id === 'number') {
      this.deps.post({ type: 'api', id: m.id, ...(await sendToPlatform(this.deps, m)) });
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
    const close = this.deps.openStream(url.toString(), { Authorization: `Bearer ${token}` }, events, (event, data) => {
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
