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
// One row per capability, or per action its ledger row names (sites.registry:
// registering, the registry fields, the settings): where the person goes, what
// they do, the request that must reach the platform (with the configured origin
// and the person's Bearer token, never posted back to the webview, and the
// Idempotency-Key where the workspace sends one), whether the host asked first
// (exactly when the change is live), and what the workspace shows from the
// reply. Each title starts with its capability's id in
// docs/plan/capabilities.yml. Every capability whose `extension` proof there
// names this file has a row here; the other rows prove through the real host
// workspaces whose cells still name webview.test.tsx, or stay partial
// (sites.sync, ai.assistants).
//
// A mutation of the gate fails the rows that depend on it: without
// 'Idempotency-Key' in REQUEST_HEADERS every row that sends one (and
// sites.jobs, which follows the sync it starts); without the page publish
// pattern in LIVE_CHANGES content.publish; without `published` in
// STORY_RELEASES news.workflow.
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
const job = (status: string, kind = 'sync') => ({
  id: JOB, kind, status, is_final: status !== 'running', site: 3, params: {}, created_by: 'editor', created_at: '2026-10-22T10:00:00Z',
  started_at: '2026-10-22T10:00:01Z', finished_at: null, cancel_requested: false, result: {}, error: '', artifacts: [],
});
/** A managed site as /api/v2/sites/<id>/ sends it: drsai (3) unless told otherwise. */
const siteDetail = (id = 3, key = 'drsai', managed: Record<string, unknown> = {}) => ({
  id, name: key, hostname: `${key}.localhost`, port: 80, is_default: false, root_page_id: 9, can_manage: true,
  managed: {
    key, checkout: `sites/${key}`, content_source: 'files', render: 'jekyll-theme', theme_tag: 'v1.31.3', server: 'github-pages',
    domains: [], deploy_target: `/${key}/`, last_synced_at: null, last_exported_at: null, last_doctor_at: null, errors: 0, warnings: 0, ...managed,
  },
  pages: { total: 18, live: 16, drafts: 2 }, files: 17, jobs: [],
});
const SITE: Record<string, Handler> = {
  'GET /api/v2/sites/3/': () => siteDetail(),
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

/** The person signed in, with these Django permissions. */
const meWith = (permissions: string[]) => () => ({
  authenticated: true,
  user: { id: 1, username: 'editor', name: 'Ed', email: '', is_staff: false, is_superuser: false },
  permissions,
  csrf_token: 'x',
});

const OUTBOX_PERMISSIONS = ['send_handoff', 'deliver_belt', 'view_belt', 'add_trial', 'view_trial', 'add_claimcheck', 'change_claimcheck', 'view_claimcheck'];
const TRACE = 'a'.repeat(32);
const beltSummary = (pending = 0) => ({
  delivered: 2, dead_letters: 0, traces: 1, kinds: [{ kind: 'verdict', count: 1 }], seq_gapless: true, ids_unique: true, pending,
  stations: ['drafter', 'editor', 'planner', 'publisher', 'verifier'], editor: 'editor', harness: '0.1.0',
});
const verdict = {
  seq: 3, id: 'm3', kind: 'verdict', from: 'verifier', to: ['editor', 'ledger'], subject: 'hydra-guide', trace: TRACE, parent_id: 'm2',
  created_at: '2026-10-27T09:00:00Z', payload: { verdict: 'pass' }, ref: null,
};
const BELT: Record<string, Handler> = {
  'GET /api/v2/me': meWith(OUTBOX_PERMISSIONS.map((p) => `outboxdesk.${p}`)),
  'GET /api/v2/outbox/belt/': () => beltSummary(),
  'GET /api/v2/outbox/belt/messages/': () => list([verdict]),
  'GET /api/v2/outbox/belt/dead-letters/': () => [],
};
const trial = (rest: Record<string, unknown> = {}) => ({
  id: 't1', task: { id: 'T-stale-fact' }, lag_b: null, status: 'succeeded', error: '', run_dir: 'runs/trial-t1', requested_by: 'editor',
  created_at: '2026-10-27T09:00:00Z', started_at: '2026-10-27T09:00:01Z', finished_at: '2026-10-27T09:00:02Z',
  result: {
    task_id: 'T-stale-fact', family: 'stale_fact', latest_env_seq: 2, n_active_claims: 2, first_claim_from: 'claimant-a', resolved: true, correct: true,
    winner: { from: 'claimant-a', id: 'c', confidence: 0.86, env_seq: 2, answer: 'green', tick: 4 },
    confidence_inversion: false, retracts: 1, claims_per_agent: { 'claimant-a': 2, 'claimant-b': 1 }, expected_answer: 'green',
  },
  ...rest,
});
const claimCheck = (rest: Record<string, unknown> = {}) => ({
  id: 'k1', title: 'Hydra explainer', author: 'rhea', page: null, claim_count: 1, status: 'succeeded', passed: false, resolution_status: null,
  requested_by: 'editor', created_at: '2026-10-27T09:00:00Z', finished_at: '2026-10-27T09:00:02Z', resolved_at: null,
  claims: [{ id: 'hydra-status', question: 'What status does hydra report?', answer: 'amber' }], timeline: [], closes_at_tick: 8, lag_b: 2, error: '',
  report: {
    pass: false,
    claims: [
      {
        claim_id: 'hydra-status', question: 'What status does hydra report?', draft_answer: 'amber', verdict: 'block', reason: 'sources_disagree',
        supported_answer: 'green', winner_from: 'claimant-a', winner_confidence: 0.86, winner_env_seq: 2, latest_env_seq: 2,
      },
    ],
  },
  truth: null, resolutions: null, resolution_error: '', run_dir: 'runs/claims-k1',
  ...rest,
});

/** A row its owner may change, as the AI layer sends it. */
const editable = { ...owned, can_edit: true };
const assistant = { ...editable, id: 'a1', name: 'Headliner', description: '', instructions: 'Write headlines.', prompt_template: '', provider: null, model: null, params: {}, output_schema: null, tools: [], effect: 'propose' };
const ASSISTANTS: Record<string, Handler> = {
  'GET /api/v2/ai/providers/': () => list([]),
  'GET /api/v2/ai/models/': () => list([]),
  'GET /api/v2/ai/output-schemas/': () => list([]),
  'GET /api/v2/ai/assistants/tools/': () => [],
  'GET /api/v2/ai/assistants/': () => list([assistant]),
  'GET /api/v2/ai/pipelines/': () => list([]),
};
const provider = (health: Record<string, unknown>) => ({
  id: 'p-anthropic', slug: 'anthropic', display_name: 'Anthropic', enabled: true, is_default: false, default_model: '', monthly_budget_usd: null,
  has_credential: true, credential_source: 'database', capabilities: ['complete'], last_health: health, checked_at: null,
  created_at: '2026-10-22T09:00:00Z', updated_at: '2026-10-22T09:00:00Z', base_url: '', organization: '', project: '', extra: {},
});
const answered = (markdown: string) => agentRun('succeeded', { text: markdown, markdown, provider: 'fake', model: 'fake-1' });
const message = (seq: number, role: string, text: string, rest: Record<string, unknown> = {}) => ({
  id: `m${seq}`, conversation: 'c1', seq, role, text, result: null, assistant: role === 'assistant' ? 'a1' : null, run: null, status: 'completed',
  provider: '', model: '', usage: {}, error: '', created_at: '2026-10-22T09:00:00Z', ...rest,
});
const brief = (rest: Record<string, unknown> = {}) => ({
  ...editable, site: 1, id: 'b1', title: 'Backups, nightly', prompt: 'Why a small site needs nightly backups', source_text: '', assistant: 'a1', pipeline: null,
  output_schema: null, page_type: 'cms.ArticlePage', parent: 3, status: 'ready', result: null, markdown: '## Why it matters\n\nA copy every night.',
  metadata: { title: 'Backups, nightly', slug: 'backups-nightly' }, page: null, run: null, error: '', conversation: null, source_message: null,
  applied_at: null, ...rest,
});

const discovered = { key: 'wargames', checkout: 'sites/wargames', render: 'jekyll-theme', theme_tag: 'v1.31.3', server: 'jekyll-4', deploy_target: '/wargames/' };
const SITE_SETTINGS = {
  seo_title_suffix: '', seo_description: '', seo_image: '', noindex: false, ga4_measurement_id: '', search_console_property: '',
  navigation: [], brand_voice: '', banned_patterns: [], chapter_builtin_bans: true, skin: '', design_tokens: {}, monthly_budget_usd: null,
};
const pattern = {
  id: 'p1', name: 'faq_injection', display_name: 'FAQ Injection', category: 'content', description: 'Anticipate and answer common questions inline',
  weight: 15, max_score: 15, boost_min: 15, boost_max: 25, body: '## What to Evaluate', enabled: true, bundled: true, created_at: '', updated_at: '',
};

/**
 * Picks an option of the open Mantine dropdown. The webview's MantineProvider runs its transitions (the studio's
 * tests render with `env="test"`, which skips them), and jsdom never finishes one, so an open dropdown stays
 * `display: none`: its options are found as hidden ones, and clicking one picks it as it does in the editor.
 */
const pick = async (name: string) => userEvent.click(await screen.findByRole('option', { name, hidden: true }));

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
    title: "news.corrections: posts a correction on a published story's page without asking, through the real host",
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
    // The bridge asks before a story goes live (published, scheduled), not before a note on a live one: a correction
    // publishes nothing else (newsroom.services.correct), and src/test/webview.test.ts pins it as a move that does not ask.
    live: false,
    // The log's line (`<when> — <text>`), not the Note field the person typed into, which still holds the text when
    // the platform refuses the correction.
    shows: /— The vote is on Tuesday\./,
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
  {
    title: 'aieo.optimize: rewrites a text into a draft as a run with an Idempotency-Key and shows the uplift, through the real host',
    view: 'dashboard',
    at: { to: 'aieo', section: 'optimize' },
    routes: {
      'POST /api/v2/aieo/rewrites/': () => ({ run: runRef() }),
      [`GET /api/v2/agent-runs/${AI_RUN}/`]: () =>
        agentRun('succeeded', { markdown: 'Backups, defined.', score_before: 10, score_after: 30, uplift: 20, suggestions: [] }),
    },
    act: async () => {
      await userEvent.click(await screen.findByRole('radio', { name: 'A text (a draft)' }));
      await userEvent.type(screen.getByLabelText('Text'), 'Backups.');
      await userEvent.click(screen.getByRole('button', { name: 'Rewrite' }));
    },
    method: 'POST',
    path: '/api/v2/aieo/rewrites/',
    header: 'Idempotency-Key',
    live: false,
    shows: 'Score 10 → 30',
  },
  {
    title: 'aieo.patterns: applies a pattern to a page as a run with an Idempotency-Key, its suggestions waiting there, through the real host',
    view: 'dashboard',
    at: { to: 'aieo', section: 'patterns' },
    routes: {
      'GET /api/v2/me': meWith(['aieo.change_pattern']),
      'GET /api/v2/aieo/patterns/': () => [pattern],
      'GET /api/v2/content/pages/': () => list([{ ...summary(5, 'Nightly backups'), type_label: 'Article page' }]),
      'POST /api/v2/aieo/patterns/faq_injection/apply/': () => ({ run: runRef() }),
      [`GET /api/v2/agent-runs/${AI_RUN}/`]: () =>
        agentRun('succeeded', { markdown: '', score_before: 10, score_after: 30, uplift: 20, suggestions: ['s41', 's42'] }),
    },
    act: async () => {
      await userEvent.click(await screen.findByRole('button', { name: 'FAQ Injection' }));
      await userEvent.click(await screen.findByLabelText('Page', { selector: 'input' }));
      await pick('Nightly backups (Article page)');
      await userEvent.click(screen.getByRole('button', { name: 'Apply the pattern' }));
    },
    method: 'POST',
    path: '/api/v2/aieo/patterns/faq_injection/apply/',
    header: 'Idempotency-Key',
    live: false,
    shows: /2 suggestions wait on the page/,
  },
  {
    title: "outbox.belt: opens a message on the belt with its CloudEvent and its piece's journey, through the real host",
    view: 'dashboard',
    at: { to: 'outbox' },
    routes: {
      ...BELT,
      'GET /api/v2/outbox/belt/messages/m3/': () => ({
        ...verdict,
        cloudevent: {
          specversion: '1.0', id: 'm3', source: 'outbox://belt/verifier', type: 'dev.bamr87.outbox.verdict', subject: 'hydra-guide',
          time: verdict.created_at, datacontenttype: 'application/json', traceparent: `00-${TRACE}-m3-01`, data: {},
        },
      }),
      [`GET /api/v2/outbox/belt/traces/${TRACE}/`]: () => ({ trace: TRACE, messages: [verdict] }),
    },
    act: async () => {
      await userEvent.click(await screen.findByRole('button', { name: 'Open verdict 3' }));
    },
    method: 'GET',
    path: '/api/v2/outbox/belt/messages/m3/',
    live: false,
    within: 'CloudEvent',
    shows: 'dev.bamr87.outbox.verdict',
  },
  {
    title: 'outbox.handoff: sends an idea onto the belt as the editor station, and the belt then waits on it, through the real host',
    view: 'dashboard',
    at: { to: 'outbox' },
    routes: () => {
      let pending = 0;
      return {
        ...BELT,
        'GET /api/v2/outbox/belt/': () => beltSummary(pending),
        'POST /api/v2/outbox/belt/send/': ({ body }) => {
          pending = 1;
          return { ...verdict, ...(body as object), seq: null, id: 'new', from: 'editor' };
        },
      };
    },
    act: async () => {
      await userEvent.click(await screen.findByRole('button', { name: 'Send a handoff' }));
      const form = await screen.findByRole('form', { name: 'Send a handoff' });
      await userEvent.type(within(form).getByLabelText('Subject'), 'backups-guide');
      const payload = within(form).getByLabelText('Payload');
      await userEvent.clear(payload);
      await userEvent.type(payload, '{{"title": "Backups"}');
      await userEvent.click(within(form).getByRole('button', { name: 'Send' }));
    },
    method: 'POST',
    path: '/api/v2/outbox/belt/send/',
    live: false,
    within: 'Waiting',
    shows: '1',
  },
  {
    title: "outbox.trials: runs a task card as a trial with an Idempotency-Key and opens its scored result, through the real host",
    view: 'dashboard',
    at: { to: 'outbox', tab: 'trials' },
    routes: {
      ...BELT,
      'GET /api/v2/outbox/trials/': () => list([trial()]),
      'POST /api/v2/outbox/trials/': () => trial({ id: 't2', status: 'queued', result: null }),
      'GET /api/v2/outbox/trials/t2/': () => ({ ...trial({ id: 't2' }), ledger: [] }),
    },
    act: async () => {
      await userEvent.type(await screen.findByLabelText(/Claimant B's lag/), '6');
      await userEvent.click(screen.getByRole('button', { name: 'Run trial' }));
    },
    method: 'POST',
    path: '/api/v2/outbox/trials/',
    header: 'Idempotency-Key',
    live: false,
    shows: /claimant-a answered green at confidence 0.86/,
  },
  {
    title: "outbox.claim-desk: resolves a claim check against the truth with an Idempotency-Key and shows each claim's score, through the real host",
    view: 'dashboard',
    at: { to: 'claim-check', id: 'k1' },
    routes: () => {
      let resolved = false;
      const truth = { 'hydra-status': 'green' };
      const resolutions = [
        { claim_id: 'hydra-status', task_id: 'C-hydra-status', truth: 'green', winner_correct: true, confidence_inversion: false, draft_correct: false, brier: { 'claimant-a': 0.0196 }, draft_brier: 0.64 },
      ];
      return {
        ...BELT,
        'GET /api/v2/outbox/claim-checks/k1/': () => (resolved ? claimCheck({ resolution_status: 'succeeded', truth, resolutions }) : claimCheck()),
        'POST /api/v2/outbox/claim-checks/k1/resolve/': () => {
          resolved = true;
          return claimCheck({ resolution_status: 'queued', truth });
        },
      };
    },
    act: async () => {
      await userEvent.type(await screen.findByLabelText('Truth for hydra-status'), 'green');
      await userEvent.click(screen.getByRole('button', { name: 'Resolve' }));
    },
    method: 'POST',
    path: '/api/v2/outbox/claim-checks/k1/resolve/',
    header: 'Idempotency-Key',
    live: false,
    shows: 'draft wrong',
  },
  {
    title: 'ai.providers: tests a provider as a run with an Idempotency-Key and shows its health, through the real host',
    view: 'dashboard',
    at: { to: 'ai', section: 'providers' },
    routes: () => {
      let health = {};
      return {
        'GET /api/v2/me': meWith(['ai.change_providerconfig']),
        'GET /api/v2/ai/providers/': () => list([provider(health)]),
        'POST /api/v2/ai/providers/p-anthropic/test/': () => {
          health = { ok: true };
          return { run: runRef() };
        },
        [`GET /api/v2/agent-runs/${AI_RUN}/`]: () => agentRun('succeeded', { ok: true }),
      };
    },
    act: async () => {
      await userEvent.click(await screen.findByRole('button', { name: 'Test anthropic' }));
    },
    method: 'POST',
    path: '/api/v2/ai/providers/p-anthropic/test/',
    header: 'Idempotency-Key',
    live: false,
    shows: 'healthy',
  },
  {
    title: 'ai.assistants: runs an assistant on a prompt with an Idempotency-Key and shows its answer, through the real host',
    view: 'dashboard',
    at: { to: 'assistant', id: 'a1' },
    routes: {
      ...ASSISTANTS,
      'GET /api/v2/ai/assistants/a1/': () => assistant,
      'POST /api/v2/ai/assistants/a1/run/': () => ({ run: runRef() }),
      [`GET /api/v2/agent-runs/${AI_RUN}/`]: () => answered('## Cats win\n\nThe sofa is theirs.'),
    },
    act: async () => {
      await userEvent.type(await screen.findByLabelText('Prompt'), 'cats');
      await userEvent.click(screen.getByRole('button', { name: 'Run' }));
    },
    method: 'POST',
    path: '/api/v2/ai/assistants/a1/run/',
    header: 'Idempotency-Key',
    live: false,
    within: 'The answer',
    shows: 'The sofa is theirs.',
  },
  {
    title: 'ai.pipelines: runs a pipeline with an Idempotency-Key and shows what its last step wrote, through the real host',
    view: 'dashboard',
    at: { to: 'pipeline', id: 'p1' },
    routes: {
      ...ASSISTANTS,
      'GET /api/v2/ai/pipelines/p1/': () => ({
        ...editable, id: 'p1', name: 'Draft, then edit', description: '', steps: [{ position: 1, assistant: 'a1', source: 'previous', source_field: '' }],
      }),
      'POST /api/v2/ai/pipelines/p1/run/': () => ({ run: runRef() }),
      [`GET /api/v2/agent-runs/${AI_RUN}/`]: () => answered('A tight draft.'),
    },
    act: async () => {
      await userEvent.click(await screen.findByRole('button', { name: 'Run' }));
    },
    method: 'POST',
    path: '/api/v2/ai/pipelines/p1/run/',
    header: 'Idempotency-Key',
    live: false,
    within: 'The answer',
    shows: 'A tight draft.',
  },
  {
    title: 'ai.briefs: applies a ready brief as a draft, which opens on its suggestions, through the real host',
    view: 'dashboard',
    at: { to: 'brief', id: 'b1' },
    routes: {
      ...ASSISTANTS,
      'GET /api/v2/ai/briefs/b1/': () => brief(),
      'POST /api/v2/ai/briefs/b1/apply/': () => ({ brief: brief({ status: 'applied', page: 12 }), page_id: 12, suggestions: ['s1'] }),
      'GET /api/v2/content/pages/12/': () => pageDetail({ id: 12, title: 'Backups, nightly' }),
    },
    act: async () => {
      await userEvent.click(await screen.findByRole('button', { name: 'Apply as a draft' }));
    },
    method: 'POST',
    path: '/api/v2/ai/briefs/b1/apply/',
    live: false,
    shows: 'Clearer for search.',
  },
  {
    title: 'ai.conversations: sends a message with an Idempotency-Key and shows the answer its run wrote, through the real host',
    view: 'dashboard',
    at: { to: 'conversation', id: 'c1' },
    routes: () => {
      let messages = [message(1, 'user', 'I am Alice'), message(2, 'assistant', 'Hello Alice')];
      return {
        ...ASSISTANTS,
        'GET /api/v2/ai/conversations/c1/': () => ({ ...editable, id: 'c1', title: 'Names', assistant: 'a1', pipeline: null, page: null }),
        'GET /api/v2/ai/conversations/c1/messages/': ({ url }) => cursor(url.searchParams.get('ordering') === '-seq' ? [...messages].reverse() : messages),
        'POST /api/v2/ai/conversations/c1/messages/': () => {
          messages = [...messages, message(3, 'user', 'What is my name?'), message(4, 'assistant', 'Your name is Alice.', { run: runRef() })];
          return { message: messages[2], reply: messages[3], run: runRef() };
        },
        [`GET /api/v2/agent-runs/${AI_RUN}/`]: () => answered('Your name is Alice.'),
      };
    },
    act: async () => {
      await userEvent.type(await screen.findByLabelText('Your message'), 'What is my name?');
      await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    },
    method: 'POST',
    path: '/api/v2/ai/conversations/c1/messages/',
    header: 'Idempotency-Key',
    live: false,
    shows: 'Your name is Alice.',
  },
  {
    title: 'sites.registry: registers a checkout the workspace declares and opens the new site, through the real host',
    view: 'dashboard',
    at: { to: 'sites' },
    routes: {
      'GET /api/v2/me': meWith(['sites.manage_site']),
      'GET /api/v2/sites/discover/': () => [discovered],
      'POST /api/v2/sites/': () => new Reply(201, { site: siteDetail(7, 'wargames'), job: job('running') }),
      'GET /api/v2/sites/7/': () => siteDetail(7, 'wargames', { server: 'jekyll-4' }),
      'GET /api/v2/sites/7/settings/': notFound,
      [`GET /api/v2/jobs/${JOB}/`]: () => ({ ...job('running'), lines: [] }),
    },
    act: async () => {
      await userEvent.click(await screen.findByLabelText('A known checkout', { selector: 'input' }));
      await pick('wargames — sites/wargames');
      await userEvent.click(screen.getByRole('button', { name: 'Register and sync' }));
    },
    method: 'POST',
    path: '/api/v2/sites/',
    live: false,
    shows: 'Now: Jekyll theme v1.31.3 · jekyll-4',
  },
  {
    title: "sites.registry: saves a site's registry fields and shows what the platform kept, through the real host",
    view: 'dashboard',
    at: { to: 'site', id: 3 },
    routes: { ...SITE, 'PATCH /api/v2/sites/3/': () => siteDetail(3, 'drsai', { theme_tag: 'v1.32.0' }) },
    act: async () => {
      const tag = await screen.findByRole('textbox', { name: 'Theme tag' });
      await userEvent.clear(tag);
      await userEvent.type(tag, 'v1.32.0');
      await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    },
    method: 'PATCH',
    path: '/api/v2/sites/3/',
    live: false,
    shows: 'Now: Jekyll theme v1.32.0 · github-pages',
  },
  {
    title: "sites.registry: saves a site's settings — its brand voice — through the real host",
    view: 'dashboard',
    at: { to: 'site', id: 3 },
    routes: {
      ...SITE,
      'GET /api/v2/sites/3/settings/': () => SITE_SETTINGS,
      'PATCH /api/v2/sites/3/settings/': ({ body }) => ({ ...SITE_SETTINGS, ...(body as object) }),
    },
    act: async () => {
      await userEvent.click(await screen.findByRole('tab', { name: 'Settings' }));
      await userEvent.type(await screen.findByRole('textbox', { name: 'Brand voice' }), 'Plain and warm.');
      await userEvent.click(screen.getByRole('button', { name: 'Save settings' }));
    },
    method: 'PATCH',
    path: '/api/v2/sites/3/settings/',
    live: false,
    shows: 'Saved.',
  },
  {
    title: 'sites.doctor: runs the doctor as a job with an Idempotency-Key and shows its log, through the real host',
    view: 'dashboard',
    at: { to: 'site', id: 3 },
    routes: {
      ...SITE,
      'POST /api/v2/sites/3/doctor/': () => new Reply(202, { job: job('running', 'doctor') }),
      [`GET /api/v2/jobs/${JOB}/`]: () => ({ ...job('running', 'doctor'), lines: [{ idx: 0, at: '2026-10-22T10:00:01Z', level: 'info', text: 'Checking drsai …' }] }),
    },
    act: async () => {
      await userEvent.click(await screen.findByRole('button', { name: 'Run the doctor' }));
    },
    method: 'POST',
    path: '/api/v2/sites/3/doctor/',
    header: 'Idempotency-Key',
    live: false,
    shows: 'Checking drsai …',
  },
  {
    title: "sites.doctor: reads the doctor's findings, through the real host",
    view: 'dashboard',
    at: { to: 'site', id: 3 },
    routes: {
      ...SITE,
      'GET /api/v2/sites/3/findings/': () => [
        { check_id: 'cms', severity: 'warning', file: 'zer0.json', line: null, rule: 'no-zer0-json', evidence: 'no zer0.json', fingerprint: 'abc123def456' },
      ],
    },
    act: async () => {
      await userEvent.click(await screen.findByRole('tab', { name: 'Findings' }));
    },
    method: 'GET',
    path: '/api/v2/sites/3/findings/',
    live: false,
    shows: 'no-zer0-json',
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
    const { within: label, shows } = row;
    if (label) await waitFor(() => expect(screen.getByLabelText(label)).toHaveTextContent(shows), { timeout: 4000 });
    else expect(await screen.findByText(shows, {}, { timeout: 4000 })).toBeInTheDocument();
    // The host asked exactly for the live change, and nothing else.
    expect(host.asked).toHaveLength(row.live ? 1 : 0);
    if (row.live) expect(host.asked[0]).toContain(ORIGIN);
    // The token went to the platform and never back into the webview.
    expect(JSON.stringify(host.posted)).not.toContain(TOKEN);
  });
});
