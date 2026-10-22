// The test harness: a fake platform behind the real openapi-fetch client —
// routes keyed by "METHOD /path", every request recorded — and the providers
// every @zer0/ui component and the studio render inside. It is the same seam
// a host uses (an injected fetch), so nothing here reaches a network.
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { createSessionClient, type ApiClient } from '@zer0/api';
import { theme } from '@zer0/tokens';
import { StudioProvider, type Destination, type OpenStream } from '@zer0/ui';
import type { ReactNode } from 'react';
import { vi } from 'vitest';

export class Reply {
  constructor(
    readonly status: number,
    readonly body: unknown,
  ) {}
}

export type Handler = (request: { body: unknown; url: URL }) => unknown;

export interface Call {
  method: string;
  path: string;
  query: URLSearchParams;
  body: unknown;
  csrf: string | null;
}

export function fakePlatform(routes: Record<string, Handler>) {
  const calls: Call[] = [];
  const fetch = async (request: Request) => {
    const url = new URL(request.url);
    const text = request.method === 'GET' ? '' : await request.text();
    const body: unknown = text ? JSON.parse(text) : undefined;
    calls.push({ method: request.method, path: url.pathname, query: url.searchParams, body, csrf: request.headers.get('X-CSRFToken') });
    const handler = routes[`${request.method} ${url.pathname}`];
    const out = handler
      ? handler({ body, url })
      : new Reply(404, { error: { code: 'resource.not_found', message: `no fake for ${request.method} ${url.pathname}`, status: 404, details: [] } });
    const reply = out instanceof Reply ? out : new Reply(200, out);
    return new Response(JSON.stringify(reply.body), { status: reply.status, headers: { 'Content-Type': 'application/json' } });
  };
  const api: ApiClient = createSessionClient({ baseUrl: 'http://studio.test', fetch, csrfToken: () => 'test-csrf' });
  return { api, calls };
}

export const noStream: OpenStream = () => () => undefined;

/** The `at`-th of a list a query found, or a failed test that says so. */
export function nth<T>(items: T[], at = 0): T {
  const item = items[at];
  if (item === undefined) throw new Error(`expected an item at ${at}, found ${items.length}`);
  return item;
}

export function Providers({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <MantineProvider theme={theme} env="test">
        {children}
      </MantineProvider>
    </QueryClientProvider>
  );
}

export function renderUi(ui: ReactNode, host: { api: ApiClient; stream?: OpenStream; go?: (to: Destination) => void }) {
  const go = host.go ?? vi.fn();
  const result = render(
    <Providers>
      <StudioProvider api={host.api} stream={host.stream ?? noStream} go={go}>
        {ui}
      </StudioProvider>
    </Providers>,
  );
  return { ...result, go };
}

const PERMISSIONS = { edit: true, publish: true, unpublish: true, add_subpage: false, delete: false };

/** A page detail as the platform sends it, with overrides. */
export function pageDetail(overrides: Record<string, unknown> = {}) {
  return {
    id: 5,
    title: 'Nightly backups',
    slug: 'nightly-backups',
    type: 'cms.ArticlePage',
    type_label: 'Article page',
    status: 'live',
    live: true,
    has_unpublished_changes: false,
    locked: false,
    url_path: '/test-site/nightly-backups/',
    depth: 3,
    children: 0,
    go_live_at: null,
    latest_revision_created_at: '2026-10-20T10:00:00Z',
    last_published_at: '2026-10-20T10:00:00Z',
    parent: { id: 3, title: 'Test site' },
    site_id: 1,
    expire_at: null,
    first_published_at: '2026-10-20T10:00:00Z',
    latest_revision: { id: 41, created_at: '2026-10-20T10:00:00Z', user: 'editor' },
    live_revision_id: 41,
    fields: { title: 'Nightly backups', seo_title: '', search_description: '', tags: [] },
    field_specs: [
      { name: 'title', label: 'Title', group: 'content', kind: 'text', required: true, help_text: '', max_length: 255, choices: [] },
      { name: 'seo_title', label: 'Title tag', group: 'seo', kind: 'text', required: false, help_text: '', max_length: 255, choices: [] },
      { name: 'search_description', label: 'Meta description', group: 'seo', kind: 'textarea', required: false, help_text: '', max_length: null, choices: [] },
      { name: 'tags', label: 'Tags', group: 'content', kind: 'tags', required: false, help_text: '', max_length: null, choices: [] },
    ],
    body: [
      { id: 'b1', type: 'heading', value: { level: '2', text: 'How it works' } },
      { id: 'b2', type: 'markdown', value: 'We copy the site to a second disk every night.' },
    ],
    markdown: '## How it works\n\nWe copy the site to a second disk every night.\n',
    permissions: PERMISSIONS,
    lock: null,
    pending_suggestions: 0,
    preview_url: '/admin/pages/5/view_draft/',
    live_url: '/nightly-backups/',
    ...overrides,
  };
}
