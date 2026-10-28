// The AIEO workspace and the editor's citability panel: an audit is asked for
// (with an Idempotency-Key), followed to its end and opened with its score
// breakdown — the five dimensions, the patterns' evidence, the gaps — and, for
// a site, its pages and link map; a rewrite of a text is a draft beside the
// original, of a page suggestions to review; the pattern library is changed
// only by its keepers; an agent runs on a text; a tracked question is asked
// of its engines and its share of voice shown; a connector's credential is
// sent once and never shown; priorities, reports and the brand context. A
// fake platform stands behind the real client.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { AieoWorkspace, PageScore } from '../src';
import { fakePlatform, renderUi, type Call } from '../../../test/harness';
import { agentRun, EMPTY, me, page, runRef } from './ai/fixtures';

const OWNED = { owner: 'editor', site: 1, visibility: 'site', can_edit: true, created_at: '2026-10-22T09:00:00Z', updated_at: '2026-10-22T09:00:00Z' };
const RESULT = {
  score: 52,
  grade: 'D',
  scoring_method: 'heuristic',
  word_count: 376,
  anti_pattern_penalties: 20,
  dimensions: { aieo: 52, seo: 20, readability: 81.8, humanity: 100, cro: 0 },
  pattern_scores: {
    structured_data: { score: 20, max: 20, detected: true, evidence: ['1 tables, 2 lists, 7 headers'], recommendation: 'Add tables.' },
    meta_context: { score: 2, max: 10, detected: true, evidence: ['1 meta-context signals'], recommendation: 'Explain why it matters.' },
  },
  gaps: [{ id: 'gap_meta_context', category: 'meta_context', severity: 'medium', description: 'Explain why your content matters to the reader.' }],
  overall_assessment: 'Scored with heuristic fallback.',
};
const audit = (rest: Record<string, unknown> = {}) => ({
  ...OWNED,
  id: 'u1',
  kind: 'text',
  method: 'heuristic',
  provider: '',
  title: '',
  url: '',
  page: null,
  target: 'the text',
  format: 'markdown',
  max_pages: 25,
  visual: false,
  status: 'ready',
  score: 52,
  grade: 'D',
  scoring_method: 'heuristic',
  content_hash: 'x',
  result: RESULT,
  pages: [],
  benchmark: { percentile: 75, compared_with: 4, engines: {}, similar: [{ audit: 'u0', target: 'Restore drills', score: 61, similarity: 0.8 }] },
  screenshot: null,
  batch: '',
  origin: 'studio',
  run: runRef(9),
  error: '',
  audited_at: '2026-10-22T09:00:00Z',
  ...rest,
});
const posts = (calls: Call[], path: string) => calls.filter((c) => c.method === 'POST' && c.path === path);

describe('<AieoWorkspace> audits', () => {
  it('audits a text as a run and opens it with its breakdown and evidence', async () => {
    const { api, calls } = fakePlatform({
      'POST /api/v2/aieo/audits/': () => ({ audit: audit({ status: 'pending', score: null, grade: '', result: {} }), run: runRef(9) }),
      'GET /api/v2/agent-runs/9/': () => agentRun('succeeded', { audit: 'u1', score: 52 }),
      'GET /api/v2/aieo/audits/u1/': () => audit(),
      'GET /api/v2/aieo/audits/': () => page([audit()]),
    });
    renderUi(<AieoWorkspace siteId={1} />, { api });
    const form = screen.getByRole('form', { name: 'Audit' });
    await userEvent.type(within(form).getByLabelText('Text to audit'), '# Backups');
    await userEvent.click(within(form).getByRole('switch', { name: /model's evaluation/ }));
    await userEvent.click(within(form).getByRole('button', { name: 'Audit' }));
    await waitFor(() => expect(posts(calls, '/api/v2/aieo/audits/')).toHaveLength(1));
    const sent = posts(calls, '/api/v2/aieo/audits/')[0];
    expect(sent?.body).toMatchObject({ kind: 'text', content: '# Backups', method: 'heuristic', site: 1 });
    expect(sent?.idempotencyKey).toBeTruthy();
    const opened = await screen.findByLabelText('Audit of the text');
    expect(await within(opened).findByText('Grade D')).toBeInTheDocument();
    expect(within(opened).getByLabelText('SEO 20')).toBeInTheDocument();
    expect(
      within(opened).getByRole('img', {
        name: 'The five dimensions: Citability (AIEO) 52, SEO 20, Readability 81.8, Humanity 100, Conversion (CRO) 0',
      }),
    ).toBeInTheDocument();
    expect(within(opened).getByText(/Explain why your content matters/)).toBeInTheDocument();
    expect(within(opened).getByText('Better than 75% of the audits here.')).toBeInTheDocument();
    expect(within(opened).getByText('Closest in meaning: Restore drills (61)')).toBeInTheDocument();
    await userEvent.click(within(opened).getByRole('button', { name: /Patterns \(2\)/ }));
    expect(await within(opened).findByText('1 tables, 2 lists, 7 headers')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Audit history' })).toBeInTheDocument();
  });

  it("shows a site audit's pages and its link map, and its report", async () => {
    const site = audit({
      kind: 'site',
      target: 'https://example.com/',
      url: 'https://example.com/',
      pages: [
        { url: 'https://example.com/', title: 'Home', found_by: 'seed', score: 40, grade: 'F', error: '' },
        { url: 'https://example.com/c/', title: '', found_by: 'link', score: null, grade: '', error: 'the site answered HTTP 500' },
      ],
      result: { ...RESULT, site: { link_map: { hubs: [{ url: 'https://example.com/a/', inbound: 3 }], orphans: ['https://example.com/b/'] } } },
    });
    const { api } = fakePlatform({
      'GET /api/v2/aieo/audits/': () => page([site]),
      'GET /api/v2/aieo/audits/u1/': () => site,
      'GET /api/v2/aieo/audits/u1/report/': () => ({ filename: 'example_com.md', markdown: '# AIEO Audit Report: example.com', html: '' }),
    });
    renderUi(<AieoWorkspace />, { api });
    await userEvent.click(await screen.findByRole('button', { name: 'https://example.com/' }));
    const opened = await screen.findByLabelText('Audit of https://example.com/');
    expect(await within(opened).findByText('the site answered HTTP 500')).toBeInTheDocument();
    expect(within(opened).getByText(/https:\/\/example.com\/a\/ \(3\)/)).toBeInTheDocument();
    expect(within(opened).getByText(/https:\/\/example.com\/b\//)).toBeInTheDocument();
    await userEvent.click(within(opened).getByRole('button', { name: 'Report' }));
    expect(await screen.findByRole('button', { name: 'Copy the Markdown' })).toBeInTheDocument();
  });
});

describe('<AieoWorkspace> rewrites and patterns', () => {
  it('rewrites a text into a draft beside the original, and a page into suggestions to review', async () => {
    const output = { markdown: 'Backups, defined.', score_before: 10, score_after: 30, uplift: 20, suggestions: [] };
    const { api, calls } = fakePlatform({
      'POST /api/v2/aieo/rewrites/': () => ({ run: runRef(9) }),
      'GET /api/v2/agent-runs/9/': () => agentRun('succeeded', output),
    });
    renderUi(<AieoWorkspace section="optimize" />, { api });
    await userEvent.click(screen.getByRole('radio', { name: 'A text (a draft)' }));
    await userEvent.type(screen.getByLabelText('Text'), 'Backups.');
    await userEvent.click(screen.getByRole('button', { name: 'Rewrite' }));
    await waitFor(() => expect(posts(calls, '/api/v2/aieo/rewrites/')[0]?.body).toMatchObject({ mode: 'optimize', content: 'Backups.', page_id: null }));
    expect(await screen.findByText('Score 10 → 30')).toBeInTheDocument();
    expect(screen.getByText('+20')).toBeInTheDocument();
    expect(document.querySelector('ins')?.textContent).toContain('defined');
  });

  it('lets a keeper change a pattern and applies one to a page as suggestions', async () => {
    const pattern = {
      id: 'p1',
      name: 'faq_injection',
      display_name: 'FAQ Injection',
      category: 'content',
      description: 'Anticipate and answer common questions inline',
      weight: 15,
      max_score: 15,
      boost_min: 15,
      boost_max: 25,
      body: '## What to Evaluate',
      enabled: true,
      bundled: true,
      created_at: '',
      updated_at: '',
    };
    const output = { markdown: '', score_before: 10, score_after: 30, uplift: 20, suggestions: [41, 42] };
    const { api, calls } = fakePlatform({
      'GET /api/v2/me': () => me(['aieo.change_pattern']),
      'GET /api/v2/aieo/patterns/': () => [pattern],
      'PATCH /api/v2/aieo/patterns/faq_injection/': ({ body }) => ({ ...pattern, ...(body as object) }),
      'GET /api/v2/content/pages/': () => page([{ id: 5, title: 'Nightly backups', type_label: 'Article page' }]),
      'POST /api/v2/aieo/patterns/faq_injection/apply/': () => ({ run: runRef(9) }),
      'GET /api/v2/agent-runs/9/': () => agentRun('succeeded', output),
    });
    const { go } = renderUi(<AieoWorkspace section="patterns" />, { api });
    await userEvent.click(await screen.findByRole('button', { name: 'FAQ Injection' }));
    const weight = await screen.findByLabelText('Weight');
    await userEvent.clear(weight);
    await userEvent.type(weight, '30');
    await userEvent.click(screen.getByRole('button', { name: 'Save the pattern' }));
    await waitFor(() => expect(calls.find((c) => c.method === 'PATCH')?.body).toMatchObject({ weight: 30, max_score: 15, enabled: true }));
    await userEvent.click(screen.getByLabelText('Page', { selector: 'input' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Nightly backups (Article page)' }));
    await userEvent.click(screen.getByRole('button', { name: 'Apply the pattern' }));
    await waitFor(() => expect(posts(calls, '/api/v2/aieo/patterns/faq_injection/apply/')[0]?.body).toMatchObject({ page_id: 5, content: '' }));
    expect(await screen.findByText(/2 suggestions wait on the page/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Review them' }));
    expect(go).toHaveBeenCalledWith({ to: 'review', runId: 9 });
  });

  it('shows a pattern read-only to someone who does not keep the library', async () => {
    const { api } = fakePlatform({
      'GET /api/v2/me': () => me([]),
      'GET /api/v2/aieo/patterns/': () => [{ id: 'p1', name: 'meta_context', display_name: 'Meta-Context', category: 'content', description: '', weight: 10, max_score: 10, boost_min: null, boost_max: null, body: 'Explain why.', enabled: false, bundled: true, created_at: '', updated_at: '' }],
    });
    renderUi(<AieoWorkspace section="patterns" />, { api });
    expect(await screen.findByText('off')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Meta-Context' }));
    expect(await screen.findByRole('document', { name: "The pattern's criteria" })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save the pattern' })).not.toBeInTheDocument();
  });
});

describe('<AieoWorkspace> agents, citations, connectors, priorities, reports, context', () => {
  it('runs an AIEO agent on a text and shows its structured answer', async () => {
    const agents = [
      { key: 'aieo-meta-creator', id: 'x', name: 'Meta creator', description: 'Five meta titles.', group: 'agent', structured: true },
      { key: 'aieo-evaluator', id: 'y', name: 'AIEO evaluator', description: '', group: 'evaluator', structured: true },
    ];
    const { api, calls } = fakePlatform({
      'GET /api/v2/aieo/agents/': () => agents,
      'GET /api/v2/content/pages/': () => EMPTY,
      'POST /api/v2/aieo/agents/run/': () => ({ run: runRef(9) }),
      'GET /api/v2/agent-runs/9/': () => agentRun('succeeded', { markdown: '**Backups**', json: { recommended_pair: { title: 'Backups' } } }),
    });
    renderUi(<AieoWorkspace section="agents" siteId={1} />, { api });
    await userEvent.click(screen.getByLabelText('Agent', { selector: 'input' }));
    expect(screen.queryByRole('option', { name: 'AIEO evaluator' })).not.toBeInTheDocument();
    await userEvent.click(await screen.findByRole('option', { name: 'Meta creator' }));
    await userEvent.type(screen.getByLabelText('Text'), 'Nightly backups explained.');
    await userEvent.click(screen.getByRole('button', { name: 'Run the agent' }));
    await waitFor(() =>
      expect(posts(calls, '/api/v2/aieo/agents/run/')[0]?.body).toEqual({ agent: 'aieo-meta-creator', content: 'Nightly backups explained.', page_id: null, site: 1, inputs: {} }),
    );
    expect(await screen.findByLabelText('The structured answer')).toHaveTextContent('recommended_pair');
  });

  it('tracks a question, asks its engines and shows the share of voice', async () => {
    const query = { ...OWNED, id: 'q1', prompt: 'Who explains backups best?', domain: 'example.com', engines: ['fake'], interval_days: 7, active: true, next_check_at: null, last_checked_at: null, latest: { fake: { cited: true, position: 2, status: 'ready' } } };
    const { api, calls } = fakePlatform({
      'GET /api/v2/ai/providers/': () => page([{ id: 'p', slug: 'fake', display_name: 'Fake', enabled: true }]),
      'POST /api/v2/aieo/citations/queries/': () => query,
      'GET /api/v2/aieo/citations/queries/': () => page([query]),
      'POST /api/v2/aieo/citations/queries/q1/check/': () => ({ checks: [] }),
      'GET /api/v2/aieo/citations/share/': () => ({
        days: 90,
        engines: [{ engine: 'fake', checks: 4, cited: 3, rate: 0.75 }],
        weeks: [{ week: '2026-10-19', engine: 'fake', checks: 4, cited: 3, rate: 0.75 }],
      }),
    });
    renderUi(<AieoWorkspace section="citations" />, { api });
    const form = screen.getByRole('form', { name: 'Track a question' });
    await userEvent.type(within(form).getByLabelText('A question people ask AI engines'), 'Who explains backups best?');
    await userEvent.type(within(form).getByLabelText('The site to look for'), 'example.com');
    await userEvent.click(within(form).getByRole('button', { name: 'Track it' }));
    await waitFor(() => expect(posts(calls, '/api/v2/aieo/citations/queries/')[0]?.body).toMatchObject({ prompt: 'Who explains backups best?', domain: 'example.com', interval_days: 7 }));
    expect(await screen.findByText('fake: cited #2')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Ask now' }));
    await waitFor(() => expect(posts(calls, '/api/v2/aieo/citations/queries/q1/check/')[0]?.idempotencyKey).toBeTruthy());
    expect(screen.getByLabelText('fake share of voice 75%')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Share of voice by week' })).toHaveTextContent('75% (3/4)');
  });

  it("sends a connector's credential once and never shows it", async () => {
    const saved = { id: 'c1', site: 1, kind: 'ga4', enabled: true, options: { property_id: '123' }, has_credential: true, status: 'idle', error: '', last_synced_at: null, can_edit: true, rows: null, created_at: '', updated_at: '' };
    let listed: unknown[] = [];
    const { api, calls } = fakePlatform({
      'GET /api/v2/aieo/connectors/': () => listed,
      'POST /api/v2/aieo/connectors/': () => {
        listed = [saved];
        return saved;
      },
      'POST /api/v2/aieo/connectors/c1/sync/': () => ({ ...saved, status: 'syncing' }),
    });
    renderUi(<AieoWorkspace section="connectors" siteId={1} />, { api });
    const ga4 = await screen.findByRole('form', { name: 'Google Analytics 4' });
    await userEvent.type(within(ga4).getByLabelText('property id'), '123');
    await userEvent.type(within(ga4).getByLabelText('Credential'), 'service-account-key');
    await userEvent.click(within(ga4).getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(posts(calls, '/api/v2/aieo/connectors/')[0]?.body).toEqual({ site: 1, kind: 'ga4', enabled: true, options: { property_id: '123' }, credential: 'service-account-key' }),
    );
    expect(await within(ga4).findByText(/set; type a new one to replace it/)).toBeInTheDocument();
    expect(within(ga4).getByLabelText('Credential')).toHaveValue('');
    await userEvent.click(within(ga4).getByRole('button', { name: 'Sync now' }));
    await waitFor(() => expect(posts(calls, '/api/v2/aieo/connectors/c1/sync/')).toHaveLength(1));
  });

  it('ranks the priorities, marks the quick wins, and asks for a site first', async () => {
    const row = (query: string, score: number) => ({ query, page: '/p', clicks: 1, impressions: 100, ctr: 0.01, position: 8, opportunity_score: score, components: {} });
    const { api } = fakePlatform({
      'GET /api/v2/aieo/priorities/': () => ({ site: 1, fetched_at: '2026-10-22T09:00:00Z', queue: [row('nightly backup', 87.4), row('restore', 50)], quick_wins: [row('nightly backup', 87.4)] }),
    });
    const first = renderUi(<AieoWorkspace section="priorities" />, { api });
    expect(screen.getByText(/Choose a site in the header/)).toBeInTheDocument();
    first.unmount();
    renderUi(<AieoWorkspace section="priorities" siteId={1} />, { api });
    const queue = await screen.findByRole('table', { name: 'Update queue' });
    expect(within(queue).getAllByText('quick win')).toHaveLength(1);
    expect(within(queue).getByText('87.4')).toBeInTheDocument();
  });

  it('audits a batch of sites and reads its summary once every audit has finished', async () => {
    const { api, calls } = fakePlatform({
      'POST /api/v2/aieo/audits/batch/': () => ({ batch: 'b1', audits: [] }),
      'GET /api/v2/aieo/audits/': () => page([audit({ url: 'https://example.com/', kind: 'url' }), audit({ id: 'u2', url: 'https://gone.example/', kind: 'url', status: 'failed', score: null, error: 'HTTP 404' })]),
      'GET /api/v2/aieo/audits/summary/': () => ({ filename: 'REPORT.md', markdown: '# AIEO Audit Summary Report', html: '' }),
    });
    renderUi(<AieoWorkspace section="reports" />, { api });
    await userEvent.type(screen.getByLabelText('Sites, one address per line'), 'https://example.com/\nhttps://gone.example/');
    await userEvent.click(screen.getByRole('button', { name: 'Audit them' }));
    await waitFor(() => expect(posts(calls, '/api/v2/aieo/audits/batch/')[0]?.body).toMatchObject({ urls: ['https://example.com/', 'https://gone.example/'], method: 'heuristic' }));
    expect(await screen.findByText('HTTP 404')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'The summary report' }));
    await waitFor(() => expect(calls.find((c) => c.path === '/api/v2/aieo/audits/summary/')?.query.get('batch')).toBe('b1'));
  });

  it("opens the lifecycle's stages and saves the brand context", async () => {
    const context = { site: 1, brand_voice: '# Brand Voice', style_guide: '', writing_examples: '', target_keywords: '', internal_links_map: '', competitor_analysis: '', seo_guidelines: '', cro_best_practices: '', features: '', competitors: { competitors: [], keywords: ['backup'], topics: [] }, keywords: ['backup'], updated_at: '2026-10-22T09:00:00Z' };
    const { api, calls } = fakePlatform({
      'GET /api/v2/aieo/lifecycle/': () => ({ topics: 4, research: 2, drafts: 1, rewrites: 1, review_required: 3, published: 9, landing_pages: 0, audits: 5, average_score: 41.2 }),
      'GET /api/v2/aieo/context/1/': () => context,
      'PUT /api/v2/aieo/context/1/': ({ body }) => ({ ...context, ...(body as object) }),
    });
    const { go } = renderUi(<AieoWorkspace section="context" siteId={1} />, { api });
    await userEvent.click(await screen.findByText('Topics'));
    expect(go).toHaveBeenCalledWith({ to: 'ideas' });
    expect(screen.getByText('Average score of 5 audits')).toBeInTheDocument();
    const form = await screen.findByRole('form', { name: 'Brand context' });
    expect(within(form).getByText(/Target keywords: backup/)).toBeInTheDocument();
    await userEvent.click(within(form).getByRole('button', { name: 'Save the context' }));
    await waitFor(() => expect(calls.find((c) => c.method === 'PUT')?.body).toMatchObject({ brand_voice: '# Brand Voice', competitors: { keywords: ['backup'] } }));
  });
});

describe('<PageScore>', () => {
  it("shows the page's last score, scores it again, and lands an optimize as suggestions", async () => {
    const onReview = vi.fn();
    const output = { markdown: '', score_before: 52, score_after: 60, uplift: 8, suggestions: [41] };
    const { api, calls } = fakePlatform({
      'GET /api/v2/aieo/audits/': () => page([audit({ kind: 'page', page: 5, target: 'Nightly backups' })]),
      'GET /api/v2/aieo/audits/u1/': () => audit({ kind: 'page', page: 5 }),
      'POST /api/v2/aieo/audits/': () => ({ audit: audit({ status: 'pending' }), run: runRef(8) }),
      'GET /api/v2/agent-runs/8/': () => agentRun('succeeded', {}, 8),
      'POST /api/v2/aieo/rewrites/': () => ({ run: runRef(9) }),
      'GET /api/v2/agent-runs/9/': () => agentRun('succeeded', output),
    });
    const { go } = renderUi(<PageScore pageId={5} onReview={onReview} />, { api });
    expect(await screen.findByText('Grade D')).toBeInTheDocument();
    expect(screen.getByLabelText('SEO 20')).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: /The five dimensions/ })).not.toBeInTheDocument(); // the panel's share: bars alone
    expect(calls.find((c) => c.path === '/api/v2/aieo/audits/')?.query.get('page')).toBe('5');
    await userEvent.click(screen.getByRole('button', { name: 'Score this page' }));
    await waitFor(() => expect(posts(calls, '/api/v2/aieo/audits/')[0]?.body).toMatchObject({ kind: 'page', page_id: 5, method: 'heuristic' }));
    await userEvent.click(screen.getByRole('button', { name: 'Rewrite' }));
    await waitFor(() => expect(posts(calls, '/api/v2/aieo/rewrites/')[0]?.body).toMatchObject({ mode: 'optimize', page_id: 5, content: '' }));
    expect(await screen.findByText(/1 suggestions wait on the page/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Review them' }));
    expect(onReview).toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Open AIEO' }));
    expect(go).toHaveBeenCalledWith({ to: 'aieo' });
  });

  it('says why a page it cannot change offers no rewrite', async () => {
    const { api } = fakePlatform({ 'GET /api/v2/aieo/audits/': () => EMPTY });
    renderUi(<PageScore pageId={5} dirty held="Locked by someone else." />, { api });
    expect(await screen.findByText('Not scored yet.')).toBeInTheDocument();
    expect(screen.getByText(/Save first/)).toBeInTheDocument();
    expect(screen.getByText('Locked by someone else.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Rewrite' })).not.toBeInTheDocument();
  });
});
