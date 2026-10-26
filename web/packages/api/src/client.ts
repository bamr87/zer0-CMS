// The studio's transport: openapi-fetch over same-origin requests that carry
// the session cookie, with Django's CSRF token on every unsafe request. The
// UI packages never build a client — they take one from context — so the
// extension's webviews (PLAN G10) can hand them one that speaks postMessage.
import createClient, { type Client, type Middleware } from 'openapi-fetch';

import type { paths } from './schema';

export type ApiClient = Client<paths>;

const SAFE = new Set(['GET', 'HEAD', 'OPTIONS', 'TRACE']);

/** Django's CSRF cookie (`csrftoken`) out of a `document.cookie` string. */
export function csrfFromCookie(cookie: string): string | undefined {
  return /(?:^|;\s*)csrftoken=([^;]+)/.exec(cookie)?.[1];
}

export interface SessionClientOptions {
  /** Defaults to the page's own origin. */
  baseUrl?: string;
  /** Defaults to the CSRF cookie of the page. */
  csrfToken?: () => string | undefined;
  /** Defaults to the global fetch; tests and hosts inject their own. */
  fetch?: (request: Request) => Promise<Response>;
}

export function createSessionClient(options: SessionClientOptions = {}): ApiClient {
  const client = createClient<paths>({
    baseUrl: options.baseUrl ?? '',
    credentials: 'same-origin',
    ...(options.fetch ? { fetch: options.fetch } : {}),
  });
  const token = options.csrfToken ?? (() => csrfFromCookie(document.cookie));
  const csrf: Middleware = {
    onRequest({ request }) {
      const value = SAFE.has(request.method) ? undefined : token();
      if (value) request.headers.set('X-CSRFToken', value);
      return request;
    },
  };
  client.use(csrf);
  return client;
}
