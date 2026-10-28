// The VS Code extension's webviews, rendered as the extension renders them
// (PLAN G10): the same <App> dist/studio.js mounts, over a fake extension host
// that answers the postMessage transport from a fake platform. It proves the
// extension renders the studio's workspaces from the registry — the dashboard's
// tabs, the page behind the open file, the AI view — that every request it
// sends names a method, a path, a body and only the headers the platform reads,
// never a credential; that an upload is refused rather than sent as text; and
// that a destination a view does not show, a stream and a link go to the host.
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HOME, WORKSPACES, workspaceFor, type Destination } from '@zer0/ui';
import { describe, expect, it } from 'vitest';

import { App, type View } from '../src/App';
import { connect, type Port } from '../src/transport';
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
      const headers = { 'Content-Type': 'application/json', 'X-Request-Id': `req-${String(m.id)}` };
      queueMicrotask(() => void deliver({ type: 'api', id: m.id, status: reply.status, body: JSON.stringify(reply.body), headers }));
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
  'POST /api/v2/content/pages/5/publish/': () => pageDetail(),
  'GET /api/v2/content/pages/5/revisions/': () =>
    list([
      { id: 42, created_at: '2026-10-21T10:00:00Z', user: 'editor', approved_go_live_at: null, is_live: false, is_latest: true },
      { id: 41, created_at: '2026-10-20T10:00:00Z', user: 'editor', approved_go_live_at: null, is_live: true, is_latest: false },
    ]),
  'GET /api/v2/content/pages/5/revisions/compare/': () => ({
    a: { id: 41, created_at: '2026-10-20T10:00:00Z', user: 'editor', fields: { title: 'Backups' }, body: [], markdown: 'One.\n' },
    b: { id: 42, created_at: '2026-10-21T10:00:00Z', user: 'editor', fields: { title: 'Nightly backups' }, body: [], markdown: 'One.\n' },
    changed: ['title'],
  }),
  'POST /api/v2/content/pages/5/revisions/41/revert/': () => pageDetail({ status: 'changed' }),
  'POST /api/v2/suggestions/1/accept/': () => ({ ...suggestion, status: 'accepted' }),
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

  it('has a workspace for every destination the studio has, each the studio area for that path', () => {
    // HOME's keys are the whole Destination union (the type checker holds it to that); each names a registered workspace.
    const ids = WORKSPACES.map((w) => w.id);
    expect(ids).toEqual(['home', 'write', 'create', 'ideas', 'research', 'newsroom', 'books', 'review', 'ai', 'outbox', 'sites', 'distribution']);
    for (const [to, id] of Object.entries(HOME)) {
      expect(ids, to).toContain(id);
      expect(workspaceFor({ to } as Destination)?.id, to).toBe(id);
    }
    expect(WORKSPACES.filter((w) => w.id !== 'home').every((w) => Object.values(HOME).includes(w.id))).toBe(true);
  });

  it("opens main's newer workspaces at the destinations the host hands the dashboard", async () => {
    const host = open('dashboard');
    const workspaces = await screen.findByRole('tablist', { name: 'Workspaces' });
    const at = async (to: Destination, workspace: string, section?: [string, string]) => {
      await host.deliver({ type: 'go', to });
      expect(within(workspaces).getByRole('tab', { name: workspace, selected: true })).toBeInTheDocument();
      if (section) {
        const sections = await screen.findByRole('tablist', { name: section[0] });
        expect(within(sections).getByRole('tab', { name: section[1], selected: true })).toBeInTheDocument();
      }
    };
    await at({ to: 'briefs' }, 'Create', ['What to create', 'Briefs']);
    await at({ to: 'ideas' }, 'Ideas');
    await at({ to: 'source', id: 'src-1' }, 'Research');
    await at({ to: 'story', id: 'story-1' }, 'Newsroom');
    await at({ to: 'chapter', book: 3, id: 4 }, 'Books');
    await at({ to: 'assistant', id: 'a-1' }, 'AI', ['AI sections', 'Assistants']);
    await at({ to: 'ai', section: 'models' }, 'AI', ['AI sections', 'Models']);
    await at({ to: 'automation', id: 'auto-1' }, 'AI', ['AI sections', 'Automations']);
    await at({ to: 'trial', id: 'trial-1' }, 'Outbox');
    await at({ to: 'job', id: 'job-1' }, 'Sites');
    await at({ to: 'aieo', section: 'patterns' }, 'Sites');
    await at({ to: 'channel', id: 'ch-1' }, 'Distribution');

    // Each asked the platform for what it shows — through the host, by path, never with a credential.
    await waitFor(() => {
      const paths = host.sent.filter((m) => m.type === 'api').map((m) => String(m.path));
      for (const path of ['/api/v2/ai/briefs/', '/api/v2/research/sources/src-1/', '/api/v2/books/3/', '/api/v2/ai/assistants/a-1/', '/api/v2/jobs/job-1/']) {
        expect(paths.some((p) => p.startsWith(path)), path).toBe(true);
      }
    });
    expect(host.sent.filter((m) => m.type === 'api').every((m) => String(m.path).startsWith('/api/v2/') && !('headers' in m && JSON.stringify(m.headers).includes('Authorization')))).toBe(true);
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

  it('votes on an idea, and syncs a site and follows its job, each through the host', async () => {
    const jobId = 'b0b0b0b0-0000-4000-8000-000000000001';
    const idea = (votes: number, voted: boolean) => ({
      id: 'i1', owner: 'editor', site: null, visibility: 'private', created_at: '2026-10-22T09:00:00Z', updated_at: '2026-10-22T09:00:00Z',
      board: null, title: 'Backups in five minutes', notes: '', tags: [], status: 'new', origin: 'captured', url: '', sources: [],
      source_message: null, brief: null, page: null, votes, voted,
    });
    const job = (status: string) => ({
      id: jobId, kind: 'sync', status, is_final: status !== 'running', site: 3, params: {}, created_by: 'editor',
      created_at: '2026-10-22T10:00:00Z', started_at: '2026-10-22T10:00:01Z', finished_at: null, cancel_requested: false,
      result: {}, error: '', artifacts: [],
    });
    const site = {
      id: 3, name: 'drsai', hostname: 'drsai.localhost', port: 80, is_default: false, root_page_id: 9, can_manage: true,
      managed: {
        key: 'drsai', checkout: 'sites/drsai', content_source: 'files', render: 'jekyll-theme', theme_tag: 'v1.31.3', server: 'github-pages',
        domains: [], deploy_target: '/drsai/', last_synced_at: null, last_exported_at: null, last_doctor_at: null, errors: 0, warnings: 0,
      },
      pages: { total: 18, live: 16, drafts: 2 }, files: 17, jobs: [],
    };
    const host = fakeHost({
      ...PLATFORM,
      'GET /api/v2/ideas/boards/': () => ({ next: null, previous: null, results: [] }),
      'GET /api/v2/ideas/': () => ({ next: null, previous: null, results: [idea(2, false)] }),
      'POST /api/v2/ideas/i1/vote/': () => idea(3, true),
      'GET /api/v2/sites/3/': () => site,
      'GET /api/v2/sites/3/settings/': () => new Reply(404, { error: { code: 'resource.not_found', message: 'none', status: 404, details: [] } }),
      'POST /api/v2/sites/3/sync/': () => new Reply(202, { job: job('running') }),
      [`GET /api/v2/jobs/${jobId}/`]: () => ({ ...job('running'), lines: [{ idx: 0, at: '2026-10-22T10:00:01Z', level: 'info', text: 'Reading sites/drsai …' }] }),
    });
    render(<App view="dashboard" port={host.port} />);
    await screen.findByRole('tablist', { name: 'Workspaces' });

    await host.deliver({ type: 'go', to: { to: 'ideas' } });
    const card = await screen.findByRole('article', { name: 'Backups in five minutes' });
    await userEvent.click(within(card).getByRole('button', { name: 'Vote · 2' }));
    await waitFor(() => expect(host.sent).toContainEqual(expect.objectContaining({ type: 'api', method: 'POST', path: '/api/v2/ideas/i1/vote/' })));

    await host.deliver({ type: 'go', to: { to: 'site', id: 3 } });
    await userEvent.click(await screen.findByRole('button', { name: 'Sync' }));
    expect(await screen.findByText('Reading sites/drsai …')).toBeInTheDocument();
    const sync = host.sent.find((m) => m.type === 'api' && m.path === '/api/v2/sites/3/sync/');
    expect(sync).toMatchObject({ method: 'POST', headers: { 'Idempotency-Key': expect.stringMatching(/.{16,}/) } });
    const stream = host.sent.find((m) => m.type === 'stream');
    expect(stream).toMatchObject({ path: `/api/v2/jobs/${jobId}/stream/`, events: ['line', 'status', 'end'] });
    await host.deliver({ type: 'event', id: stream?.id, event: 'line', data: JSON.stringify({ idx: 1, at: '2026-10-22T10:00:02Z', level: 'warning', text: 'about.md: changed since the last import' }) });
    expect(await screen.findByText('about.md: changed since the last import')).toBeInTheDocument();
  });

  it('compares and reverts revisions, publishes and accepts a suggestion — each a request the host sends', async () => {
    const host = open('page');
    await host.deliver({ type: 'file', file: { path: '_posts/backups.md', name: 'backups.md' } });
    await screen.findByDisplayValue('Nightly backups');
    await userEvent.click(screen.getByRole('tab', { name: /Revisions/ }));
    await userEvent.click(await screen.findByRole('button', { name: 'Compare with latest' }));
    expect(await screen.findByText('Changes since revision #41')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Revert to this' }));
    await userEvent.click(screen.getByRole('button', { name: 'Publish' }));
    await waitFor(() =>
      expect(host.sent.filter((m) => m.type === 'api' && m.method === 'POST').map((m) => m.path)).toEqual([
        '/api/v2/content/pages/5/revisions/41/revert/',
        '/api/v2/content/pages/5/publish/',
      ]),
    );

    const dashboard = open('dashboard');
    await userEvent.click(await screen.findByRole('tab', { name: 'Review' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Accept' }));
    await waitFor(() => expect(dashboard.sent).toContainEqual(expect.objectContaining({ type: 'api', method: 'POST', path: '/api/v2/suggestions/1/accept/' })));
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
    // The AI area's own sections, and no workspace tabs: the agent view is the one workspace.
    expect(screen.queryByRole('tablist', { name: 'Workspaces' })).toBeNull();
    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual(['Runs', 'Assistants', 'Pipelines', 'Output schemas', 'Conversations', 'Providers', 'Models', 'Automations']);
    await userEvent.click(await screen.findByRole('button', { name: '#7' }));
    expect(await screen.findByText(/Run #7/)).toBeInTheDocument();
    const stream = host.sent.find((m) => m.type === 'stream');
    expect(stream).toMatchObject({ path: '/api/v2/agent-runs/7/stream/', events: ['step', 'status', 'end'] });
    await host.deliver({ type: 'event', id: stream?.id, event: 'step', data: JSON.stringify({ idx: 0, kind: 'tool', name: 'content.get_page', args: {}, result: {}, error: '', latency_ms: 3, tokens: 0 }) });
    expect(await screen.findByText('tool · content.get_page')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Review its suggestions' }));
    expect(host.sent).toContainEqual({ type: 'go', to: { to: 'review', runId: 7 } });
  });

  it('sends an Idempotency-Key with a run, refuses an upload, and reads the headers the host passes on', async () => {
    const host = fakeHost({ 'POST /api/v2/ai/pipelines/p-1/run/': () => new Reply(202, { run: 7 }) });
    const { api } = connect(host.port);
    const started = await api.POST('/api/v2/ai/pipelines/{public_id}/run/', {
      params: { path: { public_id: 'p-1' }, header: { 'Idempotency-Key': 'k-1' } },
      body: { input: {} } as never,
      headers: { 'X-Forwarded-For': '10.0.0.1' },
    });
    expect(started.response.status).toBe(202);
    expect(started.response.headers.get('X-Request-Id')).toBe('req-1');
    const sent = host.sent.find((m) => m.type === 'api');
    expect(sent).toMatchObject({ method: 'POST', path: '/api/v2/ai/pipelines/p-1/run/', headers: { 'Idempotency-Key': 'k-1' } });
    expect(Object.keys(sent?.headers as object)).toEqual(['Idempotency-Key']);

    const form = new FormData();
    form.append('file', new Blob(['%PDF-1.7'], { type: 'application/pdf' }), 'paper.pdf');
    const upload = await api.POST('/api/v2/ai/pipelines/{public_id}/run/', {
      params: { path: { public_id: 'p-1' } },
      body: form as never,
      bodySerializer: (body: unknown) => body as FormData,
    });
    expect(upload.response.status).toBe(415);
    expect(upload.error).toMatchObject({ error: { code: 'extension.unsupported_body' } });
    expect(host.sent.filter((m) => m.type === 'api')).toHaveLength(1);
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
