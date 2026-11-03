// The extension's proof standard (PLAN G10): a workspace driven through the real
// host gate. The same <App> dist/studio.js mounts renders over connect(port),
// and every message it posts goes to a real StudioBridge
// (src/core/studio/bridge.ts — pure, with no imports, so this suite loads it
// from the extension's tree). The bridge's deps are the only fakes: the
// platform behind fetch (web/test/harness.tsx's fakePlatform), a confirm that
// records each question, an in-memory token and a stream opener the test
// drives. So the path gate, the LIVE_CHANGES modal, the header allow-list, the
// token and the message contract between transport.ts and bridge.ts are in the
// loop for every row.
//
// One row per capability: where the person goes, what they do, the request
// that must reach the platform (with the configured origin and the person's
// Bearer token, never posted back to the webview), whether the host asked
// first (exactly when the change is live), and what the workspace shows from
// the reply. A ledger cell's proof names its row by title.
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { Destination } from '@zer0/ui';
import { describe, expect, it } from 'vitest';

import { StudioBridge } from '../../../../src/core/studio/bridge';
import { App, type View } from '../src/App';
import type { Port } from '../src/transport';
import { fakePlatform, pageDetail, Reply, type Handler } from '../../../test/harness';
import { agentRun, runRef, RUN as AI_RUN } from '../../ui/test/ai/fixtures';

const ORIGIN = 'https://platform.test';
const TOKEN = 'zer0u_host-test-token';

interface Sent {
  method: string;
  url: URL;
  headers: Record<string, string>;
}

interface Stream {
  url: string;
  headers: Record<string, string>;
  emit: (event: string, data: string | null) => Promise<void>;
}

/** The real host gate over a fake platform: what reached the network, what the person was asked, what streams were opened. */
function realHost(routes: Record<string, Handler>) {
  const platform = fakePlatform(routes);
  const listeners = new Set<(message: unknown) => void>();
  const sent: Sent[] = [];
  const asked: string[] = [];
  const streams: Stream[] = [];
  const posted: unknown[] = [];
  const deliver = (message: unknown) =>
    act(() => {
      posted.push(message);
      listeners.forEach((listen) => listen(message));
    });
  const bridge = new StudioBridge({
    post: (message) => void deliver(message),
    origin: () => ORIGIN,
    token: (origin) => Promise.resolve(origin === ORIGIN ? TOKEN : undefined),
    confirm: (question) => {
      asked.push(question);
      return Promise.resolve(true);
    },
    fetch: (url, init) => {
      const headers = { ...(init.headers as Record<string, string>) };
      sent.push({ method: String(init.method), url: new URL(url), headers });
      return platform.fetch(new Request(url, { method: init.method, headers, ...(init.body ? { body: init.body } : {}) }));
    },
    openStream: (url, headers, _events, onEvent) => {
      streams.push({ url, headers, emit: (event, data) => act(async () => onEvent(event, data)) });
      return () => undefined;
    },
    go: () => undefined,
    openExternal: () => undefined,
    trusted: () => true,
    save: () => Promise.resolve(),
    tell: () => undefined,
  });
  const port: Port = {
    post: (message) => void bridge.receive(message),
    listen: (handler) => {
      listeners.add(handler);
      return () => void listeners.delete(handler);
    },
  };
  return { port, sent, asked, streams, posted, deliver };
}

type Host = ReturnType<typeof realHost>;

interface Row {
  /** The capability's ledger id; the row's title starts with it. */
  title: string;
  view: View;
  /** Where the person starts: a destination the host hands the dashboard, or the file open in the editor (the page view). */
  at?: Destination;
  file?: { path: string; name: string };
  /** The platform's answers; a function when they change as the person acts. */
  routes: Record<string, Handler> | (() => Record<string, Handler>);
  /** What the person does. */
  act: (host: Host) => Promise<void>;
  /** The request that must reach the platform, by method and path; `STREAM` when the host follows an event stream. */
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE' | 'STREAM';
  path: string;
  /** A request header the platform reads that must cross, beside the token. */
  header?: 'Idempotency-Key';
  /** Whether the change is live, so the host must ask first. */
  live: boolean;
  /** What the workspace shows from the reply — in the element labelled `within`, when there is one. */
  shows: string | RegExp;
  within?: string;
}

const RUN = '7d1c5e3a-2b4f-4c6d-8e9f-0a1b2c3d4e5f';
const JOB = 'b0b0b0b0-0000-4000-8000-000000000001';
const list = (results: unknown[]) => ({ count: results.length, next: null, previous: null, results });
const cursor = (results: unknown[]) => ({ next: null, previous: null, results });
const notFound = () => new Reply(404, { error: { code: 'resource.not_found', message: 'none', status: 404, details: [] } });

const run = (status: string) => ({
  id: RUN, agent: 'seo', status, is_final: status !== 'running', trigger: 'rest', target: { type: 'articlepage', id: 5 }, input: {}, output: {},
  error: '', cost_usd: '0.000000', tokens: 120, trace_id: '', schema_version: '1', created_at: '2026-10-21T09:00:00Z', finished_at: null,
  links: { self: `/api/v2/agent-runs/${RUN}/`, stream: `/api/v2/agent-runs/${RUN}/stream/` }, steps: [],
});
const suggestion = {
  id: 's1', op: 'meta', block_id: '', field: 'seo_title', payload: {}, rationale: 'Clearer for search.', status: 'pending', agent: 'seo', run_id: RUN,
  created_at: '2026-10-21T09:00:00Z', target: { type: 'page', id: 5, title: 'Nightly backups' },
  change: { kind: 'field', label: 'seo_title', before: 'Backups', after: 'Nightly backups, explained', stale: false },
};
const summary = (id: number, title: string) => ({ ...pageDetail({ id, title }), fields: undefined, body: undefined });

/** What every view asks for as it opens: the sites, the inbox, the runs, the open file's page. */
const BASE: Record<string, Handler> = {
  'GET /api/v2/sites/': () => [{ id: 1, name: 'Test site', hostname: 'test.localhost', port: 80, is_default: true, root_page_id: 3 }],
  'GET /api/v2/review/suggestions/': () => list([suggestion]),
  'GET /api/v2/agent-runs/': () => list([run('succeeded')]),
  [`GET /api/v2/agent-runs/${RUN}/`]: () => run('running'),
  'GET /api/v2/content/types/': () => [{ type: 'cms.ArticlePage', label: 'Article page' }],
  'GET /api/v2/content/pages/': ({ url }) => (url.searchParams.get('source') === '_posts/backups.md' ? list([summary(5, 'Nightly backups')]) : list([])),
  'GET /api/v2/content/pages/5/': () => pageDetail(),
  'GET /api/v2/me': () => ({ authenticated: true, user: { id: 1, username: 'editor', name: 'Ed', email: '', is_staff: true, is_superuser: false }, permissions: [], csrf_token: 'x' }),
};
const BACKUPS = { path: '_posts/backups.md', name: 'backups.md' };

const idea = (votes: number, voted: boolean, rest: Record<string, unknown> = {}) => ({
  id: 'i1', owner: 'editor', site: null, visibility: 'private', created_at: '2026-10-22T09:00:00Z', updated_at: '2026-10-22T09:00:00Z',
  board: null, title: 'Backups in five minutes', notes: '', tags: [], status: 'new', origin: 'captured', url: '', sources: [],
  source_message: null, brief: null, page: null, votes, voted, ...rest,
});
const IDEAS: Record<string, Handler> = {
  'GET /api/v2/ideas/boards/': () => cursor([]),
  'GET /api/v2/ideas/': () => cursor([idea(2, false)]),
};
const job = (status: string) => ({
  id: JOB, kind: 'sync', status, is_final: status !== 'running', site: 3, params: {}, created_by: 'editor', created_at: '2026-10-22T10:00:00Z',
  started_at: '2026-10-22T10:00:01Z', finished_at: null, cancel_requested: false, result: {}, error: '', artifacts: [],
});
const SITE: Record<string, Handler> = {
  'GET /api/v2/sites/3/': () => ({
    id: 3, name: 'drsai', hostname: 'drsai.localhost', port: 80, is_default: false, root_page_id: 9, can_manage: true,
    managed: {
      key: 'drsai', checkout: 'sites/drsai', content_source: 'files', render: 'jekyll-theme', theme_tag: 'v1.31.3', server: 'github-pages',
      domains: [], deploy_target: '/drsai/', last_synced_at: null, last_exported_at: null, last_doctor_at: null, errors: 0, warnings: 0,
    },
    pages: { total: 18, live: 16, drafts: 2 }, files: 17, jobs: [],
  }),
  'GET /api/v2/sites/3/settings/': notFound,
  'POST /api/v2/sites/3/sync/': () => new Reply(202, { job: job('running') }),
  [`GET /api/v2/jobs/${JOB}/`]: () => ({ ...job('running'), lines: [{ idx: 0, at: '2026-10-22T10:00:01Z', level: 'info', text: 'Reading sites/drsai …' }] }),
};
const syncSite = async () => {
  await userEvent.click(await screen.findByRole('button', { name: 'Sync' }));
};

const owned = { owner: 'editor', site: null, visibility: 'private', created_at: '2026-10-22T09:00:00Z', updated_at: '2026-10-22T09:00:00Z' };
const source = {
  ...owned, id: 's1', kind: 'url', collection: 'c1', url: 'https://example.com/backups', title: 'Backups explained', author: 'Ada Lovelace',
  site_name: 'Example News', published: '2026-10-01', status: 'ready', error: '', robots: 'allowed', fetched_at: '2026-10-22T09:00:00Z', language: 'en',
  text: 'A nightly backup to a second disk costs almost nothing.', metadata: {}, summary: 'Nightly backups save small sites.',
  entities: [], highlights: ['A nightly backup to a second disk costs almost nothing.'], summary_run: null, feed: null,
};
const question = (text: string, answer: string) => ({
  ...owned, id: `q-${text.length}`, collection: 'c1', text, answer, citations: [], status: 'ready', error: '', run: runRef('r33'),
});
const RESEARCH: Record<string, Handler> = {
  'GET /api/v2/research/collections/': () => cursor([{ ...owned, id: 'c1', name: 'Backups', description: '' }]),
  'GET /api/v2/research/sources/': () => cursor([source]),
  'GET /api/v2/research/sources/s1/': () => source,
  'GET /api/v2/research/citations/': () => cursor([]),
};

const story = (rest: Record<string, unknown> = {}) => ({
  id: 's1', desk: 'd1', desk_name: 'Metro', slug: 'bridge-closes', headline: 'Bridge closes', summary: 'Six weeks of detours.', status: 'copy',
  priority: 3, assignee: null, deadline: null, slot_date: null, embargo: null, page: null, brief: null, wire_item: {}, breaking: false,
  fast_path_reason: '', bylines: [], moves: ['scheduled', 'published', 'drafting'], created_at: '2026-10-20T09:00:00Z', updated_at: '2026-10-20T09:00:00Z',
  ...rest,
});
const storyDetail = (rest: Record<string, unknown> = {}) => ({ events: [], corrections: [], ai_runs: [], is_editor: true, ...story(rest) });
const STORY_PAGE = { id: 5, title: 'Bridge closes', live: true, has_unpublished_changes: false, url_path: '/x/', first_published_at: null };

const book = (rest: Record<string, unknown> = {}) => ({
  id: 20, slug: 'impairment', title: 'The Impairment', status: 'drafting', page_status: 'live', profile: 'book', logline: '', genre: '',
  chapters: 1, planned_chapters: 14, word_count: 0, target_word_count: 90000, progress: 0, site_id: 1, template: false,
  stats: { chapters: 1, status_counts: {}, word_count: 0, target_word_count: 90000, planned_chapters: 14, average: 0, longest: null, shortest: null, progress: 0 },
  chapter_list: [], errors: 0, warnings: 0, documents: [], can_edit: true, can_add_chapter: true, ...rest,
});
const TASKS = [{ key: 'draft', label: 'Draft', description: 'Write the chapter body.', chapter: true, suggests: true }];

const auditOf = (rest: Record<string, unknown> = {}) => ({
  owner: 'editor', site: null, visibility: 'private', can_edit: true, created_at: '2026-10-22T09:00:00Z', updated_at: '2026-10-22T09:00:00Z',
  id: 'u1', kind: 'text', method: 'heuristic', provider: '', title: '', url: '', page: null, target: 'the text', format: 'markdown', max_pages: 25,
  visual: false, status: 'ready', score: 52, grade: 'D', scoring_method: 'heuristic', content_hash: 'x',
  result: {
    score: 52, grade: 'D', scoring_method: 'heuristic', word_count: 376, anti_pattern_penalties: 20,
    dimensions: { aieo: 52, seo: 20, readability: 81.8, humanity: 100, cro: 0 }, pattern_scores: {}, gaps: [], overall_assessment: '',
  },
  pages: [], benchmark: { percentile: 75, compared_with: 4, engines: {}, similar: [] }, screenshot: null, batch: '', origin: 'studio',
  run: runRef(), error: '', audited_at: '2026-10-22T09:00:00Z', ...rest,
});

const ROWS: Row[] = [
  {
    title: 'content.revisions: compares a revision with the latest and reverts to it, through the real host',
    view: 'page',
    file: BACKUPS,
    routes: {
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
    },
    act: async () => {
      await userEvent.click(await screen.findByRole('tab', { name: /Revisions/ }));
      await userEvent.click(await screen.findByRole('button', { name: 'Compare with latest' }));
      expect(await screen.findByText('Changes since revision #41')).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: 'Revert to this' }));
    },
    method: 'POST',
    path: '/api/v2/content/pages/5/revisions/41/revert/',
    live: false,
    shows: 'Reverted: the old content is now the latest draft',
  },
  {
    title: 'content.publish: publishes the page behind the open file, after the host asks, through the real host',
    view: 'page',
    file: BACKUPS,
    routes: { 'POST /api/v2/content/pages/5/publish/': () => pageDetail() },
    act: async () => {
      await screen.findByDisplayValue('Nightly backups');
      await userEvent.click(screen.getByRole('button', { name: 'Publish' }));
    },
    method: 'POST',
    path: '/api/v2/content/pages/5/publish/',
    live: true,
    shows: 'Published',
  },
  {
    title: 'ai.suggestions: accepts a suggestion from the Review inbox, through the real host',
    view: 'dashboard',
    at: { to: 'review' },
    routes: { 'POST /api/v2/suggestions/s1/accept/': () => ({ accepted: true, revision_id: 42 }) },
    act: async () => {
      expect(await screen.findByText('Clearer for search.')).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: 'Accept' }));
    },
    method: 'POST',
    path: '/api/v2/suggestions/s1/accept/',
    live: false,
    shows: 'Accepted as a draft revision',
  },
  {
    title: 'platform.shared-ui: the dashboard renders the registry and its Home asks the platform through the real host',
    view: 'dashboard',
    routes: {},
    act: async () => {
      expect((await screen.findAllByRole('tab')).length).toBeGreaterThan(10);
    },
    method: 'GET',
    path: '/api/v2/review/suggestions/',
    live: false,
    within: 'Suggestions to review',
    shows: '1',
  },
  {
    title: 'ideas.board: votes on an idea on the board, through the real host',
    view: 'dashboard',
    at: { to: 'ideas' },
    routes: () => {
      let voted = false;
      return {
        ...IDEAS,
        'GET /api/v2/ideas/': () => cursor([voted ? idea(3, true) : idea(2, false)]),
        'POST /api/v2/ideas/i1/vote/': () => {
          voted = true;
          return idea(3, true);
        },
      };
    },
    act: async () => {
      const card = await screen.findByRole('article', { name: 'Backups in five minutes' });
      await userEvent.click(within(card).getByRole('button', { name: 'Vote · 2' }));
    },
    method: 'POST',
    path: '/api/v2/ideas/i1/vote/',
    live: false,
    shows: 'Voted · 3',
  },
  {
    title: "sites.sync: syncs a site's files as a job with an Idempotency-Key, through the real host",
    view: 'dashboard',
    at: { to: 'site', id: 3 },
    routes: SITE,
    act: syncSite,
    method: 'POST',
    path: '/api/v2/sites/3/sync/',
    header: 'Idempotency-Key',
    live: false,
    shows: 'Reading sites/drsai …',
  },
  {
    title: "sites.jobs: follows a sync job's log live over the host's event stream, with the token",
    view: 'dashboard',
    at: { to: 'site', id: 3 },
    routes: SITE,
    act: async (host) => {
      await syncSite();
      await waitFor(() => expect(host.streams).toHaveLength(1));
      const line = { idx: 1, at: '2026-10-22T10:00:02Z', level: 'warning', text: 'about.md: changed since the last import' };
      await host.streams[0]?.emit('line', JSON.stringify(line));
    },
    method: 'STREAM',
    path: `/api/v2/jobs/${JOB}/stream/`,
    live: false,
    shows: 'about.md: changed since the last import',
  },
  {
    title: "ai.streaming: follows a run's steps live over the host's event stream, with the token",
    view: 'ai',
    routes: {},
    act: async (host) => {
      await userEvent.click(await screen.findByRole('button', { name: '7d1c5e3a' }));
      await waitFor(() => expect(host.streams).toHaveLength(1));
      const step = { idx: 0, kind: 'tool', name: 'content.get_page', args: {}, result: {}, error: '', latency_ms: 3, tokens: 0 };
      await host.streams[0]?.emit('step', JSON.stringify(step));
    },
    method: 'STREAM',
    path: `/api/v2/agent-runs/${RUN}/stream/`,
    live: false,
    shows: 'tool · content.get_page',
  },
  {
    title: 'ideas.brainstorm: brainstorms headlines with the assistant and shows its ideas to keep, through the real host',
    view: 'dashboard',
    at: { to: 'ideas' },
    routes: () => {
      const reply = (status: string, result: unknown = null) => ({
        id: 'm2', conversation: 'c1', seq: 2, role: 'assistant', text: '', result, assistant: 'a1', run: runRef('r40'), status,
        provider: 'fake', model: 'fake-1', usage: {}, error: '', created_at: '2026-10-22T09:00:00Z',
      });
      const ideas = { ideas: [{ title: 'Will you notice?', notes: 'A wake-up call.', kind: 'headline' }] };
      return {
        ...IDEAS,
        'POST /api/v2/ideas/brainstorm/': () => ({ conversation: 'c1', message: reply('completed'), reply: reply('queued'), run: runRef('r40') }),
        'GET /api/v2/ai/messages/m2/': () => reply('completed', ideas),
      };
    },
    act: async () => {
      await userEvent.click(await screen.findByRole('button', { name: 'Brainstorm' }));
      await userEvent.type(screen.getByLabelText('What should we brainstorm?'), 'nightly backups');
      await userEvent.click(screen.getAllByRole('button', { name: 'Brainstorm' }).at(-1) as HTMLElement);
    },
    method: 'POST',
    path: '/api/v2/ideas/brainstorm/',
    live: false,
    shows: 'Will you notice? (headline)',
  },
  {
    title: "research.sources: opens a source's page and keeps a passage as a quote, through the real host",
    view: 'dashboard',
    at: { to: 'source', id: 's1' },
    routes: {
      ...RESEARCH,
      'GET /api/v2/research/quotes/': () => cursor([]),
      'POST /api/v2/research/quotes/': () => ({ id: 'q1', source: 's1', text: 'A nightly backup', note: '', location: '', owner: 'editor', created_at: '' }),
    },
    act: async () => {
      expect(await screen.findByRole('heading', { name: 'Backups explained' })).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: 'Keep as a quote' }));
    },
    method: 'POST',
    path: '/api/v2/research/quotes/',
    live: false,
    shows: 'Kept as a quote',
  },
  {
    title: "research.synthesize: asks a collection's sources a question and shows its answer, through the real host",
    view: 'dashboard',
    at: { to: 'research' },
    routes: () => {
      let asked = false;
      return {
        ...RESEARCH,
        'GET /api/v2/research/questions/': () => cursor(asked ? [question('Which disk?', 'The second disk [S1].')] : []),
        'POST /api/v2/research/questions/': () => {
          asked = true;
          return { question: question('Which disk?', ''), run: runRef('r34') };
        },
      };
    },
    act: async () => {
      await userEvent.click(await screen.findByText('Backups'));
      await userEvent.click(await screen.findByRole('tab', { name: 'Ask' }));
      await userEvent.type(await screen.findByLabelText(/Ask your sources/), 'Which disk?');
      await userEvent.click(screen.getByRole('button', { name: 'Ask' }));
    },
    method: 'POST',
    path: '/api/v2/research/questions/',
    live: false,
    shows: 'The second disk [S1].',
  },
  {
    title: 'news.workflow: moves a story from copy to published on the budget board, after the host asks, through the real host',
    view: 'dashboard',
    at: { to: 'newsroom' },
    routes: () => {
      let published = false;
      return {
        'GET /api/v2/newsroom/stories/': ({ url }) => {
          const now = published ? story({ status: 'published', moves: ['updated', 'corrected'] }) : story();
          const wanted = url.searchParams.getAll('status');
          return list(wanted.length && !wanted.includes(now.status) ? [] : [now]);
        },
        'POST /api/v2/newsroom/stories/s1/move/': () => {
          published = true;
          return storyDetail({ status: 'published' });
        },
      };
    },
    act: async () => {
      await userEvent.click(await screen.findByRole('button', { name: 'Move “Bridge closes”' }));
      await userEvent.click(await screen.findByRole('menuitem', { name: 'Publish now' }));
      await userEvent.click(screen.getAllByRole('button', { name: 'Publish now' }).at(-1) as HTMLElement);
    },
    method: 'POST',
    path: '/api/v2/newsroom/stories/s1/move/',
    live: true,
    within: 'Published column',
    shows: 'Bridge closes',
  },
  {
    title: "news.corrections: posts a correction on a published story's page, after the host asks, through the real host",
    view: 'dashboard',
    at: { to: 'story', id: 's1' },
    routes: () => {
      let corrections: unknown[] = [];
      return {
        'GET /api/v2/newsroom/stories/': () => list([]),
        'GET /api/v2/newsroom/stories/s1/': () => storyDetail({ status: 'published', moves: ['updated', 'corrected'], page: STORY_PAGE, corrections }),
        'GET /api/v2/newsroom/desks/d1/people/': () => [],
        'GET /api/v2/newsroom/authors/': () => list([]),
        'POST /api/v2/newsroom/stories/s1/move/': ({ body }) => {
          const { text } = body as { text: string };
          corrections = [{ id: 'k1', kind: 'correction', text, created_at: '2026-10-22T09:00:00Z', created_by: 'editor' }];
          return storyDetail({ status: 'published', moves: ['updated', 'corrected'], page: STORY_PAGE, corrections });
        },
      };
    },
    act: async () => {
      await userEvent.type(await screen.findByLabelText(/^Note/), 'The vote is on Tuesday.');
      await userEvent.click(screen.getByRole('button', { name: 'Add a correction' }));
    },
    method: 'POST',
    path: '/api/v2/newsroom/stories/s1/move/',
    live: true,
    shows: /The vote is on Tuesday\./,
  },
  {
    title: 'books.create: outlines a premise with the AI and shows the chapter plan to make a book from, through the real host',
    view: 'dashboard',
    at: { to: 'books' },
    routes: {
      'GET /api/v2/books/': () => [],
      'POST /api/v2/books/premise/': () => ({ brief: { id: 'b-1', status: 'generating' }, run: runRef('r50') }),
      'GET /api/v2/ai/briefs/b-1/': () => ({
        id: 'b-1', status: 'ready',
        result: {
          title: 'The Quiet Part', logline: 'A speechwriter starts telling the truth.', genre: 'Satire', synopsis: 'Nell writes what the minister means.',
          themes: [], chapters: [{ number: 1, act: 1, title: 'Opening Remarks', beat: 'The slip.' }],
        },
      }),
    },
    act: async () => {
      await userEvent.click(await screen.findByRole('button', { name: 'From a premise' }));
      await userEvent.type(screen.getByLabelText(/^Premise/), 'A speechwriter starts telling the truth.');
      await userEvent.click(screen.getByRole('button', { name: 'Outline it' }));
    },
    method: 'POST',
    path: '/api/v2/books/premise/',
    live: false,
    shows: 'Opening Remarks',
  },
  {
    title: 'books.write: drafts a chapter with the book assistant, its writing arriving as suggestions, through the real host',
    view: 'dashboard',
    at: { to: 'chapter', book: 20, id: 31 },
    routes: {
      'GET /api/v2/books/20/': () => book(),
      'GET /api/v2/books/tasks/': () => TASKS,
      'GET /api/v2/books/20/issues/': () => [],
      'GET /api/v2/content/pages/31/': () => pageDetail({ id: 31, title: 'Chapter 1', type: 'cms.ChapterPage' }),
      'POST /api/v2/books/20/assist/': () => ({ run: runRef('r77') }),
      'GET /api/v2/agent-runs/r77/': () => ({ ...run('succeeded'), id: 'r77', agent: 'books', output: { task: 'draft', markdown: 'Ana sat.', suggestions: ['s501'] } }),
    },
    act: async () => {
      await userEvent.type(await screen.findByLabelText(/^Instruction/), 'Keep it short.');
      await userEvent.click(screen.getByRole('button', { name: 'Draft' }));
    },
    method: 'POST',
    path: '/api/v2/books/20/assist/',
    live: false,
    shows: '1 suggestion to review',
  },
  {
    title: 'aieo.scoring: audits a text as a run with an Idempotency-Key and shows its grade, through the real host',
    view: 'dashboard',
    at: { to: 'aieo' },
    routes: {
      'POST /api/v2/aieo/audits/': () => ({ audit: auditOf({ status: 'pending', score: null, grade: '', result: {} }), run: runRef() }),
      [`GET /api/v2/agent-runs/${AI_RUN}/`]: () => agentRun('succeeded', { audit: 'u1', score: 52 }),
      'GET /api/v2/aieo/audits/u1/': () => auditOf(),
      'GET /api/v2/aieo/audits/': () => list([auditOf()]),
    },
    act: async () => {
      const form = await screen.findByRole('form', { name: 'Audit' });
      await userEvent.type(within(form).getByLabelText('Text to audit'), '# Backups');
      await userEvent.click(within(form).getByRole('button', { name: 'Audit' }));
    },
    method: 'POST',
    path: '/api/v2/aieo/audits/',
    header: 'Idempotency-Key',
    live: false,
    within: 'Audit of the text',
    shows: 'Grade D',
  },
];

async function drive(row: Row): Promise<Host> {
  const host = realHost({ ...BASE, ...(typeof row.routes === 'function' ? row.routes() : row.routes) });
  render(<App view={row.view} port={host.port} />);
  if (row.file) await host.deliver({ type: 'file', file: row.file });
  if (row.at) {
    if (row.view === 'dashboard') await screen.findByRole('tablist', { name: 'Workspaces' });
    await host.deliver({ type: 'go', to: row.at });
  }
  await row.act(host);
  return host;
}

describe('the extension, through the real host gate', () => {
  it.each(ROWS)('$title', async (row) => {
    const host = await drive(row);
    if (row.method === 'STREAM') {
      await waitFor(() => expect(host.streams.map((s) => new URL(s.url).pathname)).toContain(row.path));
      const stream = host.streams.find((s) => new URL(s.url).pathname === row.path);
      expect(new URL(stream?.url ?? '').origin).toBe(ORIGIN);
      expect(stream?.headers).toEqual({ Authorization: `Bearer ${TOKEN}` });
    } else {
      await waitFor(() => expect(host.sent.map((s) => `${s.method} ${s.url.pathname}`)).toContain(`${row.method} ${row.path}`));
      const request = host.sent.find((s) => s.method === row.method && s.url.pathname === row.path);
      expect(request?.url.origin).toBe(ORIGIN);
      expect(request?.headers.Authorization).toBe(`Bearer ${TOKEN}`);
      if (row.header) expect(request?.headers[row.header]).toMatch(/^.{16,}$/);
    }
    if (row.within) expect(await screen.findByLabelText(row.within)).toHaveTextContent(row.shows);
    else expect(await screen.findByText(row.shows, {}, { timeout: 4000 })).toBeInTheDocument();
    // The host asked exactly for the live change, and nothing else.
    expect(host.asked).toHaveLength(row.live ? 1 : 0);
    if (row.live) expect(host.asked[0]).toContain(ORIGIN);
    // The token went to the platform and never back into the webview.
    expect(JSON.stringify(host.posted)).not.toContain(TOKEN);
  });
});
