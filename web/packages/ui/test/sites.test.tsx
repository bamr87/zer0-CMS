// The Sites area (PLAN G4): the registry with what the platform manages of
// each site, registering a checkout (its first sync starts and the site
// opens), a site's sync, write-back and doctor started with an
// Idempotency-Key and followed live, cancel, the registry fields and the
// per-site settings saved, the doctor's findings filtered, and a person who
// may not manage the site seeing no actions. The platform is a fake behind the
// real client; the job's log arrives over a fake stream.
import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { JobLog, SitesWorkspace, SiteView, type OpenStream } from '../src';
import { fakePlatform, nth, Reply, renderUi } from '../../../test/harness';

const managed = (overrides: Record<string, unknown> = {}) => ({
  key: 'drsai',
  checkout: 'sites/drsai',
  content_source: 'files',
  render: 'jekyll-theme',
  theme_tag: 'v1.31.3',
  server: 'github-pages',
  domains: [],
  deploy_target: '/drsai/',
  last_synced_at: '2026-10-22T09:00:00Z',
  last_exported_at: null,
  last_doctor_at: '2026-10-22T09:05:00Z',
  errors: 0,
  warnings: 1,
  ...overrides,
});

const site = (overrides: Record<string, unknown> = {}) => ({
  id: 3,
  name: 'drsai',
  hostname: 'drsai.localhost',
  port: 80,
  is_default: false,
  root_page_id: 9,
  managed: managed(),
  can_manage: true,
  ...overrides,
});

const job = (overrides: Record<string, unknown> = {}) => ({
  id: 'b0b0b0b0-0000-4000-8000-000000000001',
  kind: 'sync',
  status: 'running',
  is_final: false,
  site: 3,
  params: {},
  created_by: 'admin',
  created_at: '2026-10-22T10:00:00Z',
  started_at: '2026-10-22T10:00:01Z',
  finished_at: null,
  cancel_requested: false,
  result: {},
  error: '',
  artifacts: [],
  ...overrides,
});

const detail = (overrides: Record<string, unknown> = {}) => ({
  ...site(),
  pages: { total: 18, live: 16, drafts: 2 },
  files: 17,
  jobs: [job({ status: 'succeeded', is_final: true, result: { created: 17 } })],
  ...overrides,
});

const SETTINGS = {
  seo_title_suffix: '',
  seo_description: '',
  seo_image: '',
  noindex: false,
  ga4_measurement_id: '',
  search_console_property: '',
  navigation: [{ label: 'Books', url: '/books/' }],
  brand_voice: '',
  banned_patterns: [{ name: 'synergy', pattern: '\\bsynerg\\w*', flags: 'i' }],
  chapter_builtin_bans: true,
  skin: '',
  design_tokens: {},
  monthly_budget_usd: null,
};

describe('<SitesWorkspace>', () => {
  it('lists every site with how it renders, where its files are and what the doctor found', async () => {
    const { api } = fakePlatform({
      'GET /api/v2/sites/': () => [site(), site({ id: 4, name: 'Elsewhere', hostname: 'x.localhost', managed: null, can_manage: false })],
      'GET /api/v2/sites/discover/': () => [],
    });
    const { go } = renderUi(<SitesWorkspace />, { api });
    const row = (await screen.findByRole('button', { name: 'drsai' })).closest('tr') as HTMLElement;
    expect(within(row).getByText('Jekyll theme v1.31.3 · github-pages')).toBeInTheDocument();
    expect(within(row).getByText('sites/drsai')).toBeInTheDocument();
    expect(within(row).getByText('1 warning')).toBeInTheDocument();
    expect(screen.getByText('Not managed: register its checkout below.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'drsai' }));
    expect(go).toHaveBeenCalledWith({ to: 'site', id: 3 });
  });

  it('registers a checkout the workspace declares and opens the new site', async () => {
    const { api, calls } = fakePlatform({
      'GET /api/v2/sites/': () => [],
      'GET /api/v2/sites/discover/': () => [
        { key: 'wargames', checkout: 'sites/wargames', render: 'jekyll-theme', theme_tag: 'v1.31.3', server: 'jekyll-4', deploy_target: '/wargames/' },
      ],
      'POST /api/v2/sites/': () => new Reply(201, { site: site({ id: 7, name: 'wargames' }), job: job() }),
    });
    const { go } = renderUi(<SitesWorkspace />, { api });
    await userEvent.click(await screen.findByLabelText('A known checkout', { selector: 'input' }));
    await userEvent.click(await screen.findByRole('option', { name: 'wargames — sites/wargames' }));
    expect(screen.getByRole('textbox', { name: 'Key' })).toHaveValue('wargames');
    await userEvent.click(screen.getByRole('button', { name: 'Register and sync' }));
    await waitFor(() => expect(go).toHaveBeenCalledWith({ to: 'site', id: 7 }));
    expect(nth(calls.filter((c) => c.method === 'POST')).body).toEqual({ checkout: 'sites/wargames', key: 'wargames' });
  });

  it('shows no registration to someone who may not manage sites', async () => {
    const { api } = fakePlatform({
      'GET /api/v2/sites/': () => [site({ can_manage: false })],
      'GET /api/v2/sites/discover/': () => new Reply(403, { error: { code: 'auth.forbidden', message: 'no', status: 403, details: [] } }),
    });
    renderUi(<SitesWorkspace />, { api });
    expect(await screen.findByRole('button', { name: 'drsai' })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText('Register a site')).not.toBeInTheDocument());
  });
});

describe('<SiteView>', () => {
  /** A host stream that records each opening and lets the test send events on the newest. */
  function recordingStream() {
    const sends: ((event: string, data: unknown) => void)[] = [];
    const stream = vi.fn<OpenStream>((_path, _events, onEvent) => {
      sends.push(onEvent);
      return () => undefined;
    });
    const send = (event: string, data: unknown = {}) => act(() => sends.at(-1)?.(event, data));
    return { stream, send };
  }

  it('starts a sync with an Idempotency-Key and follows its log live until it ends', async () => {
    let state = job();
    const { stream, send } = recordingStream();
    const { api, calls } = fakePlatform({
      'GET /api/v2/sites/3/': () => detail(),
      'POST /api/v2/sites/3/sync/': () => new Reply(202, { job: state }),
      [`GET /api/v2/jobs/${state.id}/`]: () => ({ ...state, lines: [{ idx: 0, at: '2026-10-22T10:00:01Z', level: 'info', text: 'Reading sites/drsai …' }] }),
    });
    renderUi(<SiteView siteId={3} />, { api, stream });
    await userEvent.click(await screen.findByRole('button', { name: 'Sync' }));
    expect(await screen.findByText('Reading sites/drsai …')).toBeInTheDocument();
    const post = nth(calls.filter((c) => c.method === 'POST'));
    expect(post.path).toBe('/api/v2/sites/3/sync/');
    expect(post.idempotencyKey).toMatch(/.{16,}/);
    expect(stream).toHaveBeenCalledWith(`/api/v2/jobs/${state.id}/stream/`, ['line', 'status', 'end'], expect.any(Function));
    send('line', { idx: 1, at: '2026-10-22T10:00:02Z', level: 'warning', text: 'about.md: changed in Wagtail since the last import' });
    expect(await screen.findByText('about.md: changed in Wagtail since the last import')).toBeInTheDocument();
    state = job({ status: 'succeeded', is_final: true, finished_at: '2026-10-22T10:00:03Z' });
    send('status', { id: state.id, status: 'succeeded', is_final: true, error: '' });
    expect(await screen.findByText('succeeded')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument();
  });

  it('writes back with drafts when asked, and a busy site says so', async () => {
    const { api, calls } = fakePlatform({
      'GET /api/v2/sites/3/': () => detail(),
      'POST /api/v2/sites/3/export/': () =>
        new Reply(409, { error: { code: 'job.busy', message: 'a sync job is already running for this site', status: 409, details: [] } }),
    });
    renderUi(<SiteView siteId={3} />, { api });
    await userEvent.click(await screen.findByRole('switch', { name: 'Write back drafts too' }));
    await userEvent.click(screen.getByRole('button', { name: 'Write back' }));
    expect(await screen.findByText('a sync job is already running for this site')).toBeInTheDocument();
    expect(nth(calls.filter((c) => c.method === 'POST')).body).toEqual({ include_drafts: true });
  });

  it('cancels a running job', async () => {
    const running = job({ kind: 'export' });
    let cancelled = false;
    const { api, calls } = fakePlatform({
      [`GET /api/v2/jobs/${running.id}/`]: () => ({ ...running, cancel_requested: cancelled, lines: [] }),
      [`POST /api/v2/jobs/${running.id}/cancel/`]: () => {
        cancelled = true;
        return { ...running, cancel_requested: true };
      },
    });
    renderUi(<JobLog jobId={running.id} />, { api });
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }));
    expect(await screen.findByRole('button', { name: 'Stopping…' })).toBeDisabled();
    expect(calls.some((c) => c.path === `/api/v2/jobs/${running.id}/cancel/`)).toBe(true);
  });

  it('reads an artifact through the API when asked', async () => {
    const done = job({ kind: 'doctor', status: 'succeeded', is_final: true, artifacts: [{ name: 'findings.jsonl', media_type: 'application/x-ndjson', size: 20 }] });
    const { api } = fakePlatform({
      [`GET /api/v2/jobs/${done.id}/`]: () => ({ ...done, lines: [] }),
      [`GET /api/v2/jobs/${done.id}/artifacts/findings.jsonl/`]: () => '{"rule":"no-zer0-json"}',
    });
    renderUi(<JobLog jobId={done.id} />, { api });
    await userEvent.click(await screen.findByRole('button', { name: 'Show findings.jsonl' }));
    expect(await screen.findByLabelText('findings.jsonl')).toHaveTextContent('no-zer0-json');
  });

  it('saves the renderer and its Jekyll server, and shows the platform’s refusal', async () => {
    let body: unknown;
    const { api } = fakePlatform({
      'GET /api/v2/sites/3/': () => detail({ managed: managed({ render: 'react', theme_tag: '', server: '' }) }),
      'PATCH /api/v2/sites/3/': ({ body: sent }) => {
        body = sent;
        return new Reply(422, {
          error: { code: 'validation.failed', message: 'the Jekyll-theme option needs the theme’s tag and a Jekyll server', status: 422, details: [] },
        });
      },
    });
    renderUi(<SiteView siteId={3} />, { api });
    await userEvent.click(await screen.findByLabelText('Renders with', { selector: 'input' }));
    await userEvent.click(await screen.findByRole('option', { name: 'The Jekyll-theme option' }));
    await userEvent.type(screen.getByRole('textbox', { name: 'Theme tag' }), 'v1.31.3');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('the Jekyll-theme option needs the theme’s tag and a Jekyll server')).toBeInTheDocument();
    expect(body).toMatchObject({ render: 'jekyll-theme', theme_tag: 'v1.31.3', content_source: 'files', domains: [] });
  });

  it('edits the settings — the menu, the voice and the built-in bans on its books’ chapters — and saves them', async () => {
    let body: Record<string, unknown> = {};
    const { api } = fakePlatform({
      'GET /api/v2/sites/3/': () => detail(),
      'GET /api/v2/sites/3/settings/': () => SETTINGS,
      'PATCH /api/v2/sites/3/settings/': ({ body: sent }) => {
        body = sent as Record<string, unknown>;
        return { ...SETTINGS, ...body };
      },
    });
    renderUi(<SiteView siteId={3} />, { api });
    await userEvent.click(await screen.findByRole('tab', { name: 'Settings' }));
    await screen.findByRole('textbox', { name: 'Brand voice' });
    const adds = screen.getAllByRole('button', { name: 'Add' }); // the design tokens', the banned phrases', then the menu's
    await userEvent.click(nth(adds, adds.length - 1));
    await userEvent.type(screen.getByRole('textbox', { name: 'Label 2' }), 'About');
    await userEvent.type(screen.getByRole('textbox', { name: 'Link 2' }), '/about/');
    await userEvent.type(screen.getByRole('textbox', { name: 'Brand voice' }), 'Plain and warm.');
    await userEvent.click(screen.getByRole('switch', { name: /^Built-in bans on its books' chapters/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Save settings' }));
    expect(await screen.findByText('Saved.')).toBeInTheDocument();
    expect(body.navigation).toEqual([
      { label: 'Books', url: '/books/' },
      { label: 'About', url: '/about/' },
    ]);
    expect(body.brand_voice).toBe('Plain and warm.');
    expect(body.banned_patterns).toEqual([{ name: 'synergy', pattern: '\\bsynerg\\w*' }]);
    expect(body.chapter_builtin_bans).toBe(false);
  });

  it('adds a banned phrase to the site’s brand rules and shows the platform’s refusal of a broken pattern', async () => {
    const { api } = fakePlatform({
      'GET /api/v2/sites/3/': () => detail(),
      'GET /api/v2/sites/3/settings/': () => SETTINGS,
      'PATCH /api/v2/sites/3/settings/': () =>
        new Reply(422, {
          error: { code: 'validation.failed', message: 'validation failed', status: 422, details: [{ field: 'banned_patterns.1.pattern', code: 'invalid', message: 'not a regular expression: missing ), unterminated subpattern' }] },
        }),
    });
    renderUi(<SiteView siteId={3} />, { api });
    await userEvent.click(await screen.findByRole('tab', { name: 'Settings' }));
    expect(await screen.findByRole('textbox', { name: 'Pattern 1' })).toHaveValue('\\bsynerg\\w*');
    const adds = screen.getAllByRole('button', { name: 'Add' });
    await userEvent.click(nth(adds, 1));
    await userEvent.type(screen.getByRole('textbox', { name: 'Phrase 2' }), 'disrupt');
    await userEvent.type(screen.getByRole('textbox', { name: 'Pattern 2' }), 'disrupt(');
    await userEvent.click(screen.getByRole('button', { name: 'Save settings' }));
    expect(await screen.findAllByText(/not a regular expression/)).not.toHaveLength(0); // by the field, and in the save's alert
  });

  it('filters the doctor’s findings by severity', async () => {
    const { api, calls } = fakePlatform({
      'GET /api/v2/sites/3/': () => detail(),
      'GET /api/v2/sites/3/findings/': ({ url }) =>
        url.searchParams.get('severity') === 'error'
          ? []
          : [{ check_id: 'cms', severity: 'warning', file: 'zer0.json', line: null, rule: 'no-zer0-json', evidence: 'no zer0.json', fingerprint: 'abc123def456' }],
    });
    renderUi(<SiteView siteId={3} />, { api });
    await userEvent.click(await screen.findByRole('tab', { name: 'Findings' }));
    expect(await screen.findByText('no-zer0-json')).toBeInTheDocument();
    await userEvent.click(screen.getByText('Errors'));
    expect(await screen.findByText('Nothing found — or the doctor has not run yet.')).toBeInTheDocument();
    expect(calls.some((c) => c.query.get('severity') === 'error')).toBe(true);
  });

  it('shows no actions to someone who may not manage the site', async () => {
    const { api } = fakePlatform({ 'GET /api/v2/sites/3/': () => detail({ can_manage: false }) });
    renderUi(<SiteView siteId={3} />, { api });
    expect(await screen.findByText('Pages')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Sync' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument();
  });
});
