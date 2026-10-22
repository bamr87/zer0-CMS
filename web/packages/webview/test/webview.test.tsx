// The VS Code extension's webviews, rendered as the extension renders them
// (PLAN G10): the same <App> dist/studio.js mounts, over a fake extension host
// that answers the postMessage transport from a fake platform. It proves the
// extension renders the studio's workspaces from the registry — the dashboard's
// tabs, the page behind the open file, the AI view — that every request it
// sends names a method, a path and a body and never a credential, and that a
// destination a view does not show, a stream and a link go to the host.
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { WORKSPACES } from '@zer0/ui';
import { describe, expect, it } from 'vitest';

import { App, type View } from '../src/App';
import type { Port } from '../src/transport';
import { pageDetail, Reply, type Handler } from '../../../test/harness';

type Message = Record<string, unknown>;

/** The extension host as the webview sees it: messages out, messages in, and the platform behind it. */
function fakeHost(routes: Record<string, Handler>) {
  const listeners = new Set<(message: unknown) => void>();
  const sent: Message[] = [];
  const deliver = (message: unknown) => act(() => listeners.forEach((listen) => listen(message)));
  const port: Port = {
    post: (message) => {
      const m = message as Message;
      sent.push(m);
      if (m.type !== 'api') return;
      const url = new URL(String(m.path), 'https://platform.test');
      const handler = routes[`${String(m.method)} ${url.pathname}`];
      const out = handler
        ? handler({ body: m.body ? JSON.parse(String(m.body)) : undefined, url })
        : new Reply(404, { error: { code: 'resource.not_found', message: `no fake for ${String(m.method)} ${url.pathname}`, status: 404, details: [] } });
      const reply = out instanceof Reply ? out : new Reply(200, out);
      queueMicrotask(() => void deliver({ type: 'api', id: m.id, status: reply.status, body: JSON.stringify(reply.body), contentType: 'application/json' }));
    },
    listen: (handler) => {
      listeners.add(handler);
      return () => void listeners.delete(handler);
    },
  };
  return { port, sent, deliver };
}

const list = (results: unknown[]) => ({ count: results.length, next: null, previous: null, results });
const summary = (id: number, title: string) => ({ ...pageDetail({ id, title }), fields: undefined, body: undefined });
const run = (status: string) => ({
  id: 7,
  agent: 'seo',
  status,
  is_final: status !== 'running',
  trigger: 'rest',
  target: { type: 'articlepage', id: 5 },
  input: {},
  output: {},
  error: '',
  cost_usd: '0.000000',
  tokens: 120,
  trace_id: '',
  schema_version: '1',
  created_at: '2026-10-21T09:00:00Z',
  finished_at: null,
  links: { self: '/api/v2/agent-runs/7/', stream: '/api/v2/agent-runs/7/stream/' },
  steps: [],
});
const suggestion = {
  id: 1,
  op: 'meta',
  block_id: '',
  field: 'seo_title',
  payload: {},
  rationale: 'Clearer for search.',
  status: 'pending',
  agent: 'seo',
  run_id: 7,
  created_at: '2026-10-21T09:00:00Z',
  target: { type: 'page', id: 5, title: 'Nightly backups' },
  change: { kind: 'field', label: 'seo_title', before: 'Backups', after: 'Nightly backups, explained', stale: false },
};

const PLATFORM: Record<string, Handler> = {
  'GET /api/v2/sites/': () => [{ id: 1, name: 'Test site', hostname: 'test.localhost', port: 80, is_default: true, root_page_id: 3 }],
  'GET /api/v2/review/suggestions/': () => list([suggestion]),
  'GET /api/v2/agent-runs/': () => list([run('succeeded')]),
  'GET /api/v2/agent-runs/7/': () => run('running'),
  'GET /api/v2/content/types/': () => [{ type: 'cms.ArticlePage', label: 'Article page' }],
  'GET /api/v2/content/pages/': ({ url }) => {
    const source = url.searchParams.get('source');
    if (source === '_posts/backups.md') return list([summary(5, 'Nightly backups')]);
    if (source === 'index.md') return list([summary(5, 'Nightly backups'), summary(6, 'Another site')]);
    if (source !== null) return list([]);
    return list([summary(5, 'Nightly backups')]);
  },
  'GET /api/v2/content/pages/5/': () => pageDetail(),
  'GET /api/v2/content/pages/5/revisions/': () => list([{ id: 41, created_at: '2026-10-20T10:00:00Z', user: 'editor', live: true, latest: true }]),
};

function open(view: View) {
  const host = fakeHost(PLATFORM);
  render(<App view={view} port={host.port} />);
  return host;
}

describe('the extension webviews', () => {
  it('renders every workspace the registry exports as a dashboard tab, starting at Home', async () => {
    open('dashboard');
    const tabs = await screen.findAllByRole('tab');
    expect(tabs.map((tab) => tab.textContent)).toEqual(WORKSPACES.map((w) => w.label));
    expect(await screen.findByLabelText('Suggestions to review')).toHaveTextContent('1');
  });

  it('works through the workspaces: Write opens a page in the editor, Review shows diffs, AI lists runs', async () => {
    const host = open('dashboard');
    await userEvent.click(await screen.findByRole('tab', { name: 'Write' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Nightly backups' }));
    expect(await screen.findByDisplayValue('Nightly backups')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Revisions/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Publish' })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('tab', { name: 'Review' }));
    expect(await screen.findByText('Clearer for search.')).toBeInTheDocument();
    expect(document.querySelector('ins')?.textContent).toContain('explained');

    await userEvent.click(screen.getByRole('tab', { name: 'AI' }));
    expect(await screen.findByRole('button', { name: '#7' })).toBeInTheDocument();

    // Every request names a method, a path and a body: no host, no header, no credential.
    const requests = host.sent.filter((m) => m.type === 'api');
    expect(requests.length).toBeGreaterThan(5);
    for (const request of requests) {
      expect(Object.keys(request).sort()).toEqual(expect.arrayContaining(['id', 'method', 'path', 'type']));
      expect(Object.keys(request).every((key) => ['body', 'id', 'method', 'path', 'type'].includes(key))).toBe(true);
      expect(String(request.path)).toMatch(/^\/api\/v2\//);
    }
  });

  it('opens the destination the host hands the dashboard', async () => {
    const host = open('dashboard');
    await screen.findAllByRole('tab');
    await host.deliver({ type: 'go', to: { to: 'page', id: 5 } });
    expect(await screen.findByDisplayValue('Nightly backups')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Write', selected: true })).toBeInTheDocument();
  });

  it('edits the page behind the open file, says when a file is not on the platform, and asks when it is two', async () => {
    const host = open('page');
    expect(screen.getByText(/Open a file of a site on the platform/)).toBeInTheDocument();
    await waitFor(() => expect(host.sent.some((m) => m.type === 'ready')).toBe(true));

    await host.deliver({ type: 'file', file: { path: '_posts/backups.md', name: 'backups.md' } });
    expect(await screen.findByDisplayValue('Nightly backups')).toBeInTheDocument();
    expect(host.sent.some((m) => m.type === 'api' && m.path === '/api/v2/content/pages/?source=_posts%2Fbackups.md')).toBe(true);

    await host.deliver({ type: 'file', file: { path: 'notes/draft.md', name: 'draft.md' } });
    expect(await screen.findByText('Not on the platform')).toBeInTheDocument();
    expect(screen.getByText(/draft\.md is not a page on the platform/)).toBeInTheDocument();

    await host.deliver({ type: 'file', file: { path: 'index.md', name: 'index.md' } });
    expect(await screen.findByText(/was imported into 2 pages/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Another site/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Nightly backups —/ }));
    expect(await screen.findByDisplayValue('Nightly backups')).toBeInTheDocument();
  });

  it('follows a run over the host, and hands the host what the AI view does not show', async () => {
    const host = open('ai');
    expect(screen.queryAllByRole('tab')).toEqual([]);
    await userEvent.click(await screen.findByRole('button', { name: '#7' }));
    expect(await screen.findByText(/Run #7/)).toBeInTheDocument();
    const stream = host.sent.find((m) => m.type === 'stream');
    expect(stream).toMatchObject({ path: '/api/v2/agent-runs/7/stream/', events: ['step', 'status', 'end'] });
    await host.deliver({ type: 'event', id: stream?.id, event: 'step', data: JSON.stringify({ idx: 0, kind: 'tool', name: 'content.get_page', args: {}, result: {}, error: '', latency_ms: 3, tokens: 0 }) });
    expect(await screen.findByText('tool · content.get_page')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Review its suggestions' }));
    expect(host.sent).toContainEqual({ type: 'go', to: { to: 'review', runId: 7 } });
  });

  it('hands a link to the host instead of following it', async () => {
    const host = open('page');
    await host.deliver({ type: 'file', file: { path: '_posts/backups.md', name: 'backups.md' } });
    const preview = await screen.findByRole('link', { name: /Preview/ });
    await userEvent.click(preview);
    expect(host.sent).toContainEqual({ type: 'open', href: '/admin/pages/5/view_draft/' });
    expect(within(document.body).queryByText('Not on the platform')).toBeNull();
  });
});
