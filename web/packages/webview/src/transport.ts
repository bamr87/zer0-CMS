// The webview's half of the host contract (@zer0/ui's StudioProvider) in the
// VS Code extension: the generated API client and the event streams, both
// over postMessage. The webview never reaches the platform itself — its CSP
// allows no connection — and never holds a credential: it names a method, a
// path, a JSON body and the headers the platform reads (`FORWARDED`), and the
// extension host (src/core/studio/bridge.ts) re-checks the request, adds the
// platform URL and the person's token from SecretStorage, sends it, and posts
// back the status, the body and the headers a workspace reads. A body that is
// not JSON — an upload — is refused here, with the platform's envelope, rather
// than sent as text it is not.
import { createSessionClient, type ApiClient } from '@zer0/api';
import type { Destination, OpenStream } from '@zer0/ui';

/** Where messages go and come from: `acquireVsCodeApi()` and `window` in a webview, a fake in tests. */
export interface Port {
  post: (message: unknown) => void;
  listen: (handler: (message: unknown) => void) => () => void;
}

/** The file open in the editor, as the host reports it for the page view. */
export interface OpenFile {
  /** POSIX path relative to the file's workspace folder. */
  path: string;
  name: string;
}

export interface Connection {
  api: ApiClient;
  stream: OpenStream;
  /** Follow what the host says outside a request: the open file, a destination to show. */
  onFile: (handler: (file: OpenFile | null) => void) => () => void;
  onGo: (handler: (to: Destination) => void) => () => void;
  post: (message: unknown) => void;
}

interface Reply {
  status: number;
  body: string;
  headers: Record<string, string>;
}

const BODILESS = new Set([101, 204, 205, 304]);
/** The request headers the platform reads (`Idempotency-Key` on a run): the host forwards these and nothing else. */
const FORWARDED = ['Idempotency-Key', 'If-Match'];
// Request URLs are built against this and never leave the webview: the host
// reads the path and query, and adds the platform's own origin.
const NOWHERE = 'https://platform.invalid';

function record(message: unknown): Record<string, unknown> | undefined {
  return typeof message === 'object' && message !== null ? (message as Record<string, unknown>) : undefined;
}

function parse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text; // a stream may send plain text; pass it on as it came
  }
}

export function connect(port: Port): Connection {
  let next = 0;
  const replies = new Map<number, (reply: Reply) => void>();
  const streams = new Map<number, (event: string, data: unknown) => void>();
  const files = new Set<(file: OpenFile | null) => void>();
  const goes = new Set<(to: Destination) => void>();

  port.listen((message) => {
    const m = record(message);
    if (m === undefined || typeof m.type !== 'string') return;
    if (m.type === 'api' && typeof m.id === 'number') {
      const headers = Object.entries(record(m.headers) ?? {}).filter((entry): entry is [string, string] => typeof entry[1] === 'string');
      replies.get(m.id)?.({ status: Number(m.status), body: String(m.body ?? ''), headers: Object.fromEntries(headers) });
      replies.delete(m.id);
    } else if (m.type === 'event' && typeof m.id === 'number' && typeof m.event === 'string') {
      // The host relays each event's text as it came; read it as the studio's EventSource does.
      streams.get(m.id)?.(m.event, typeof m.data === 'string' ? parse(m.data) : null);
      if (m.event === 'end') streams.delete(m.id);
    } else if (m.type === 'file') {
      const file = record(m.file);
      const open = file && typeof file.path === 'string' && typeof file.name === 'string' ? { path: file.path, name: file.name } : null;
      files.forEach((handler) => handler(open));
    } else if (m.type === 'go' && record(m.to) && typeof record(m.to)?.to === 'string') {
      goes.forEach((handler) => handler(m.to as Destination));
    }
  });

  const fetch = async (request: Request): Promise<Response> => {
    const id = ++next;
    const url = new URL(request.url);
    const body = request.method === 'GET' || request.method === 'HEAD' ? undefined : await request.text();
    const type = request.headers.get('Content-Type');
    if (body && type !== null && !/^application\/json\b/i.test(type)) {
      const message = `The editor sends JSON to the platform, not ${type.split(';')[0]}: do this in the studio in your browser.`;
      const error = { code: 'extension.unsupported_body', message, status: 415, details: [], request_id: null, retry_after: null };
      return new Response(JSON.stringify({ error }), { status: 415, headers: { 'Content-Type': 'application/json' } });
    }
    const headers = Object.fromEntries(FORWARDED.flatMap((name) => (request.headers.has(name) ? [[name, request.headers.get(name) ?? '']] : [])));
    const reply = await new Promise<Reply>((resolve) => {
      replies.set(id, resolve);
      port.post({
        type: 'api',
        id,
        method: request.method,
        path: url.pathname + url.search,
        ...(body ? { body } : {}),
        ...(Object.keys(headers).length ? { headers } : {}),
      });
    });
    return new Response(BODILESS.has(reply.status) ? null : reply.body, { status: reply.status, headers: reply.headers });
  };

  const stream: OpenStream = (path, events, onEvent) => {
    const id = ++next;
    streams.set(id, onEvent);
    port.post({ type: 'stream', id, path, events: [...events] });
    return () => {
      if (streams.delete(id)) port.post({ type: 'stream.close', id });
    };
  };

  const subscribe = <T>(set: Set<T>) => (handler: T) => {
    set.add(handler);
    return () => void set.delete(handler);
  };

  return {
    // No CSRF token: the host authenticates with the person's token, not a session.
    api: createSessionClient({ baseUrl: NOWHERE, fetch, csrfToken: () => undefined }),
    stream,
    onFile: subscribe(files),
    onGo: subscribe(goes),
    post: port.post,
  };
}
