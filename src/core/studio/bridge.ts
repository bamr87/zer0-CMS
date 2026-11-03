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
 *     from the editor or by a story's move; a correction or an update posted
 *     on a published story; a distribution post published; a newsletter issue
 *     sent — asks the person modally first, whatever the webview showed; the
 *     platform then checks their permissions.
 *   - **Network only from an explicit act.** Nothing here runs until a webview
 *     the person opened asks, or the Metadata view asks which file is a page;
 *     `fetch` and the stream opener are injected.
 *   - **Nothing waits forever.** A request the platform has not answered, body
 *     and all, in `PLATFORM_TIMEOUT_MS` is answered 504 `platform.timeout`; the
 *     Metadata view waits `MODE_TIMEOUT_MS` and keeps file mode (`pageMode`).
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
/** How long the platform has to answer a request, its body included, before the host answers it 504. */
export const PLATFORM_TIMEOUT_MS = 30_000;
/** How long the Metadata view waits to learn whether a file is a page before it keeps file mode. */
export const MODE_TIMEOUT_MS = 5_000;
/**
 * The requests that change what a live site shows, or send something past the
 * platform to people, and how to ask. An id is any one segment. A page goes
 * live from the editor (publish, unpublish, schedule) and from the newsroom (a
 * story moved to published or scheduled, or a correction or an update posted on
 * it, whose note the live page shows at once — the body's `status` says which,
 * so that question is asked of the body that is sent); a distribution post goes
 * to its channel (LinkedIn, WordPress, a pull request, a newsletter) and a
 * newsletter issue to its subscribers.
 */
const LIVE_CHANGES: ReadonlyArray<readonly [RegExp, string]> = [
  [/^\/api\/v2\/content\/pages\/([^/]+)\/publish\/$/, 'Publish page $1 on $origin?'],
  [/^\/api\/v2\/content\/pages\/([^/]+)\/unpublish\/$/, 'Take page $1 off the live site on $origin?'],
  [/^\/api\/v2\/content\/pages\/([^/]+)\/schedule\/$/, 'Schedule page $1 to go live (or come down) on $origin?'],
  [/^\/api\/v2\/distribution\/posts\/([^/]+)\/publish\/$/, 'Publish distribution post $1 to its channel from $origin?'],
  [/^\/api\/v2\/newsroom\/issues\/([^/]+)\/send\/$/, 'Send newsletter issue $1 to its subscribers from $origin?'],
];
/** A story's move that changes its live page, by the `status` the body asks for. */
const STORY_MOVE = /^\/api\/v2\/newsroom\/stories\/([^/]+)\/move\/$/;
const STORY_RELEASES: Readonly<Record<string, string>> = {
  published: 'Publish story $1 on $origin?',
  scheduled: 'Schedule story $1 to go live on $origin?',
  corrected: 'Post a correction to story $1, shown on its live page on $origin at once?',
  updated: 'Post an update to story $1, shown on its live page on $origin at once?',
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

/** A wait, as the person reads it. */
function duration(ms: number): string {
  return ms < 1000 ? `${ms} ms` : `${ms / 1000} s`;
}

/** The status, the body and the headers a workspace reads, of one request sent. */
async function answer(deps: PlatformDeps, url: URL, init: RequestInit): Promise<PlatformReply> {
  const response = await deps.fetch(url.toString(), init);
  const kept: Record<string, string> = {};
  for (const name of RESPONSE_HEADERS) {
    const value = response.headers.get(name);
    if (value !== null) {
      kept[name] = value;
    }
  }
  return { status: response.status, body: await response.text(), headers: kept };
}

/**
 * One request — `{method, path, body?, headers?}`, from a webview or from the
 * host itself — through every gate above, sent with the platform's URL and the
 * person's token; or refused, the way the platform refuses. A platform that
 * has not answered in `timeoutMs` is a 504. Never throws, and no reply carries
 * the token.
 */
export async function sendToPlatform(
  deps: PlatformDeps,
  request: Record<string, unknown>,
  timeoutMs: number = PLATFORM_TIMEOUT_MS,
): Promise<PlatformReply> {
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
  // The signal ends the request in the network; the race answers even a fetch that ignores it.
  const signal = AbortSignal.timeout(timeoutMs);
  const late = new Promise<undefined>((resolve) => signal.addEventListener('abort', () => resolve(undefined), { once: true }));
  const timedOut = () => refusal(504, 'platform.timeout', `The platform at ${origin} did not answer within ${duration(timeoutMs)}.`);
  try {
    const init: RequestInit = { method, headers, ...(typeof body === 'string' ? { body } : {}), redirect: 'error', signal };
    return (await Promise.race([answer(deps, url, init), late])) ?? timedOut();
  } catch {
    // The reason is the network's (refused, a TLS failure, a redirect, the
    // timeout); the message says where, never with what credential.
    return signal.aborted ? timedOut() : refusal(503, 'platform.unreachable', `The platform at ${origin} did not answer.`);
  }
}

/** A reply's body as JSON, or undefined when it is not JSON. */
function json(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return undefined; // not JSON: the caller reads that as no answer it knows
  }
}

/** The code and message of a refusal the platform (or `sendToPlatform`) answered with; the status when it said none. */
function refusalOf(reply: PlatformReply): { code: string; message: string } {
  const error = record(record(json(reply.body))?.error);
  const code = typeof error?.code === 'string' ? error.code : '';
  const message = typeof error?.message === 'string' && error.message !== '' ? error.message : `the platform answered ${reply.status}`;
  return { code, message };
}

/** What the Metadata view shows for a file, and what to tell the person when the platform could not say. */
export interface PageMode {
  mode: 'page' | 'files';
  /** Why the file keeps file mode though a platform is configured; the shell says it once a session. */
  notice?: string;
  /** Whether setting the token is what would help. */
  askToken?: boolean;
}

/**
 * Whether the file at `source` (its path from its folder, the folder's name
 * first) is a page on the platform: the page view when the platform has one,
 * file mode when it has none or cannot be reached. A missing, expired or
 * refused token (401, 403) and a platform slower than `timeoutMs` (504) keep
 * file mode too — every content file would otherwise lose it — with a notice
 * that says why. Any other answer is the page view, which shows what was said.
 */
export async function pageMode(deps: PlatformDeps, source: string, timeoutMs: number = MODE_TIMEOUT_MS): Promise<PageMode> {
  const path = `/api/v2/content/pages/?${new URLSearchParams({ source }).toString()}`;
  const reply = await sendToPlatform({ ...deps, confirm: () => Promise.resolve(false) }, { method: 'GET', path }, timeoutMs);
  if (reply.status === 503) {
    return { mode: 'files' };
  }
  if (reply.status === 401 || reply.status === 403 || reply.status === 504) {
    const origin = deps.origin() ?? 'the platform';
    const { code, message } = refusalOf(reply);
    const notice =
      reply.status === 504
        ? `files stay in file mode: ${origin} did not answer within ${duration(timeoutMs)}.`
        : reply.status === 403
          ? `files stay in file mode: ${origin} refused to say which files are pages (${message}).`
          : code === 'auth.no_token'
            ? `files stay in file mode: there is no token for ${origin}. Set one to edit their pages here.`
            : `files stay in file mode: ${origin} did not accept your token (${message}). Set a new one to edit their pages here.`;
    return { mode: 'files', notice, askToken: reply.status === 401 };
  }
  if (reply.status !== 200) {
    return { mode: 'page' };
  }
  // A platform that answers something else: the page view shows what it said.
  const found = record(json(reply.body));
  return { mode: found !== undefined && found.count === 0 ? 'files' : 'page' };
}

/** What the platform says of a token before it is kept. */
export type TokenCheck =
  | { verdict: 'accepted'; username: string }
  | { verdict: 'rejected'; message: string }
  | { verdict: 'unchecked'; message: string };

/**
 * Keep `token` for `origin` in `secrets` unless the platform refuses it.
 * `GET /api/v2/me` with it says whose it is; a 401 or 403, or an answer that
 * reads it as nobody's, is a refusal and nothing is stored. A platform that
 * cannot be asked now (unreachable, slow, failing) leaves it kept and says it
 * was not checked. The token is in no message.
 */
export async function keepToken(
  fetch: PlatformDeps['fetch'],
  origin: string,
  token: string,
  secrets: { store(key: string, value: string): PromiseLike<void> },
): Promise<TokenCheck> {
  const candidate = token.trim();
  if (candidate === '') {
    return { verdict: 'rejected', message: 'the token is empty' };
  }
  const deps: PlatformDeps = { origin: () => origin, token: () => Promise.resolve(candidate), confirm: () => Promise.resolve(false), fetch };
  const reply = await sendToPlatform(deps, { method: 'GET', path: '/api/v2/me' });
  let check: TokenCheck;
  if (reply.status === 200) {
    const me = record(json(reply.body));
    const username = record(me?.user)?.username;
    check =
      me?.authenticated === true && typeof username === 'string'
        ? { verdict: 'accepted', username }
        : { verdict: 'rejected', message: `${origin} does not know this token` };
  } else if (reply.status === 401 || reply.status === 403) {
    check = { verdict: 'rejected', message: refusalOf(reply).message };
  } else {
    check = { verdict: 'unchecked', message: refusalOf(reply).message };
  }
  if (check.verdict !== 'rejected') {
    await secrets.store(tokenKey(origin), candidate);
  }
  return check;
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
