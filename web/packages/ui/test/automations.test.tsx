// Automations (PLAN G16): listed with their trigger and whether they run; a
// new one is made paused from a trigger, a condition and ordered actions
// (once, however it is clicked), and opened; its condition is tried against
// the trigger's sample payload; its actions are reordered by dragging from
// the keyboard (@dnd-kit) and saved in the new order; its secret is shown
// once and kept while it is open; it is enabled and paused; a dry run says
// what it would do and a real run (with an Idempotency-Key) shows up in its
// history, each action's outcome linking to what it made; it exports and
// imports as YAML; someone else's is read-only. Nothing reaches a network.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AutomationEditor, AutomationList } from '../src';
import { fakePlatform, renderUi, type Handler } from '../../../test/harness';
import { EMPTY, page } from './ai/fixtures';

const automation = (overrides: Record<string, unknown> = {}) => ({
  id: 'au1',
  owner: 'editor',
  site: null,
  visibility: 'private',
  can_edit: true,
  created_at: '2026-10-22T09:00:00Z',
  updated_at: '2026-10-22T09:00:00Z',
  name: 'Findings to ideas',
  description: '',
  enabled: false,
  trigger: { kind: 'hook', hook: 'monitor.finding' },
  condition: "data.severity == 'high'",
  actions: [
    { kind: 'idea', title: 'Fix {{ data.url }}' },
    { kind: 'email', to: ['desk@example.com'], subject: 'A finding' },
  ],
  on_error: 'stop',
  max_runs_per_hour: 60,
  webhook_url: null,
  secret: null,
  last_run: null,
  ...overrides,
});

const OPTIONS = {
  events: ['content.page.published', 'content.suggestion.created', 'agent.run.completed'],
  stages: ['assigned', 'drafting', 'editing', 'copy'],
  agents: [{ slug: 'seo', name: 'SEO' }],
  samples: {
    event: { 'content.page.published': { type: 'content.page.published', data: { page_id: 42 } } },
    schedule: { scheduled_at: '2026-10-22T09:00:00+00:00', cron: '0 9 * * 1-5' },
    webhook: { body: {}, headers: {} },
    source: { source: { title: 'A wire item' } },
    hook: { hook: 'monitor.finding', by: 'monitor', site: null, data: { severity: 'high', url: 'https://example.com/a' } },
  },
};

const run = (overrides: Record<string, unknown> = {}) => ({
  id: 'r1',
  automation: 'au1',
  automation_name: 'Findings to ideas',
  trigger: 'test',
  status: 'succeeded',
  matched: true,
  payload: { data: { severity: 'high' } },
  outcomes: [
    { index: 0, kind: 'idea', status: 'succeeded', input: { title: 'Fix https://example.com/a' }, result: { idea: 'i1' }, ms: 4 },
    { index: 1, kind: 'assistant', status: 'succeeded', input: { prompt: 'Why?' }, result: { run: 12 }, ms: 6 },
    { index: 2, kind: 'email', status: 'failed', input: { subject: 'A finding' }, error: 'the mail server is down', ms: 2 },
  ],
  error: 'an action failed',
  created_at: '2026-10-22T09:05:00Z',
  started_at: '2026-10-22T09:05:00Z',
  finished_at: '2026-10-22T09:05:01Z',
  ...overrides,
});

function platform(routes: Record<string, Handler> = {}) {
  return fakePlatform({
    'GET /api/v2/automations/options/': () => OPTIONS,
    'GET /api/v2/automations/au1/': () => automation(),
    'GET /api/v2/automations/runs/': () => EMPTY,
    'GET /api/v2/sites/': () => [],
    'GET /api/v2/ai/assistants/': () => EMPTY,
    'GET /api/v2/ai/pipelines/': () => EMPTY,
    'GET /api/v2/ai/output-schemas/': () => EMPTY,
    'GET /api/v2/ideas/boards/': () => page([{ id: 'b1', name: 'Fixes' }]),
    ...routes,
  });
}

describe('<AutomationList>', () => {
  it('lists automations with their trigger and whether they run, and opens one', async () => {
    const { api } = platform({
      'GET /api/v2/automations/': () =>
        page([automation(), automation({ id: 'au2', name: 'Morning brief', enabled: true, trigger: { kind: 'schedule', cron: '0 9 * * 1-5' } })]),
    });
    const { go } = renderUi(<AutomationList />, { api });
    const table = await screen.findByRole('table', { name: 'Automations' });
    expect(within(table).getByText('On the hook monitor.finding')).toBeInTheDocument();
    expect(within(table).getByText('On 0 9 * * 1-5 (UTC)')).toBeInTheDocument();
    expect(within(table).getByText('Paused')).toBeInTheDocument();
    expect(within(table).getByText('On')).toBeInTheDocument();
    await userEvent.click(within(table).getByRole('button', { name: 'Morning brief' }));
    expect(go).toHaveBeenCalledWith({ to: 'automation', id: 'au2' });
  });

  it('imports a YAML document as a new automation and opens it', async () => {
    const document = 'name: Findings to ideas\ntrigger:\n  kind: hook\n  hook: monitor.finding\n';
    const { api, calls } = platform({
      'GET /api/v2/automations/': () => EMPTY,
      'POST /api/v2/automations/import/': () => automation({ id: 'au9', secret: 's3cret' }),
    });
    const { go } = renderUi(<AutomationList />, { api });
    await userEvent.click(await screen.findByRole('button', { name: 'Import an automation' }));
    await userEvent.click(screen.getByRole('textbox', { name: 'The document' }));
    await userEvent.paste(document);
    await userEvent.click(screen.getByRole('button', { name: 'Import' }));
    await waitFor(() => expect(go).toHaveBeenCalledWith({ to: 'automation', id: 'au9' }));
    expect(calls.find((c) => c.path === '/api/v2/automations/import/')?.body).toEqual({ yaml: document });
  });
});

describe('<AutomationEditor>', () => {
  afterEach(() => vi.restoreAllMocks());

  it('makes a paused automation from a trigger, a condition and its actions, once however it is clicked', async () => {
    const { api, calls } = platform({ 'POST /api/v2/automations/': ({ body }) => ({ ...automation(), ...(body as object), id: 'au7', secret: 's3cret' }) });
    const { go } = renderUi(<AutomationEditor />, { api });
    expect(await screen.findByRole('heading', { name: 'New automation' })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/^Name/), 'Findings to ideas');
    await userEvent.click(screen.getByRole('combobox', { name: 'What fires it' }));
    await userEvent.click(await screen.findByRole('option', { name: 'A named hook' }));
    expect(screen.getByRole('textbox', { name: 'Hook' })).toHaveValue('monitor.finding');
    await userEvent.click(screen.getByRole('textbox', { name: 'Condition' }));
    await userEvent.paste("data.severity == 'high'");
    await userEvent.click(screen.getByRole('combobox', { name: 'Add an action' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Capture an idea' }));
    const idea = screen.getByRole('listitem', { name: 'Action 1' });
    await userEvent.click(within(idea).getByRole('textbox', { name: /^Title/ }));
    await userEvent.paste('Fix {{ data.url }}');
    await userEvent.click(within(idea).getByRole('combobox', { name: 'Board' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Fixes' }));
    await userEvent.click(screen.getByRole('combobox', { name: 'Add an action' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Send an email' }));
    const email = screen.getByRole('listitem', { name: 'Action 2' });
    const to = within(email).getAllByLabelText(/^To/).find((el) => el.tagName === 'INPUT' && el.getAttribute('type') !== 'hidden');
    if (!to) throw new Error('no To field');
    await userEvent.type(to, 'desk@example.com{Enter}');
    await userEvent.type(within(email).getByRole('textbox', { name: /^Subject/ }), 'A finding');
    await userEvent.dblClick(screen.getByRole('button', { name: 'Create (paused)' }));
    await waitFor(() => expect(go).toHaveBeenCalledWith({ to: 'automation', id: 'au7' }));
    const posts = calls.filter((c) => c.method === 'POST' && c.path === '/api/v2/automations/');
    expect(posts).toHaveLength(1);
    expect(posts[0]?.body).toEqual({
      name: 'Findings to ideas',
      description: '',
      visibility: 'private',
      site: null,
      trigger: { kind: 'hook', hook: 'monitor.finding' },
      condition: "data.severity == 'high'",
      on_error: 'stop',
      max_runs_per_hour: 60,
      actions: [
        { kind: 'idea', title: 'Fix {{ data.url }}', board: 'b1' },
        { kind: 'email', to: ['desk@example.com'], subject: 'A finding' },
      ],
    });
  });

  it('tries the condition against the trigger’s sample payload', async () => {
    const { api, calls } = platform({ 'POST /api/v2/automations/condition/': () => ({ matched: true, value: true, error: '' }) });
    renderUi(<AutomationEditor id="au1" />, { api });
    await userEvent.click(await screen.findByRole('button', { name: 'Try the condition' }));
    expect(await screen.findByLabelText('The condition’s verdict')).toHaveTextContent('Matches');
    expect(calls.find((c) => c.path === '/api/v2/automations/condition/')?.body).toEqual({
      condition: "data.severity == 'high'",
      payload: OPTIONS.samples.hook,
    });
  });

  it('moves an action by dragging it from the keyboard, and saves the actions in the new order', async () => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      const item = this.closest('li');
      const at = item?.parentElement ? [...item.parentElement.children].indexOf(item) : 0;
      return { x: 0, y: at * 200, top: at * 200, left: 0, right: 600, bottom: at * 200 + 180, width: 600, height: 180, toJSON: () => ({}) } as DOMRect;
    });
    const { api, calls } = platform({ 'PATCH /api/v2/automations/au1/': ({ body }) => ({ ...automation(), ...(body as object) }) });
    renderUi(<AutomationEditor id="au1" />, { api });
    const handle = await screen.findByRole('button', { name: 'Drag action 1' });
    handle.focus();
    await userEvent.keyboard('[Space]');
    await userEvent.keyboard('[ArrowDown]');
    await userEvent.keyboard('[Space]');
    await waitFor(() => expect(within(screen.getByRole('list', { name: 'Actions' })).getByRole('listitem', { name: 'Action 1' })).toHaveTextContent('Send an email'));
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    const saved = calls.find((c) => c.method === 'PATCH')?.body as { actions: { kind: string }[] };
    expect(saved.actions.map((a) => a.kind)).toEqual(['email', 'idea']);
  });

  it('shows its secret once and keeps it while it is open; enables and pauses it', async () => {
    let enabled = false;
    const { api } = platform({
      'GET /api/v2/automations/au1/': () => automation({ secret: 's3cret', enabled, trigger: { kind: 'webhook' }, webhook_url: 'http://studio.test/api/v2/automations/au1/webhook/' }),
      'POST /api/v2/automations/au1/enable/': () => {
        enabled = true;
        return automation({ enabled: true, updated_at: '2026-10-22T10:00:00Z', trigger: { kind: 'webhook' }, webhook_url: 'http://studio.test/api/v2/automations/au1/webhook/' });
      },
      'POST /api/v2/automations/au1/disable/': () => automation({ updated_at: '2026-10-22T11:00:00Z' }),
    });
    renderUi(<AutomationEditor id="au1" />, { api });
    expect(await screen.findByText('s3cret')).toBeInTheDocument();
    expect(screen.getByText('http://studio.test/api/v2/automations/au1/webhook/')).toBeInTheDocument();
    expect(screen.getByText('Paused')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Enable' }));
    expect(await screen.findByText('On')).toBeInTheDocument();
    expect(screen.getByText('s3cret')).toBeInTheDocument(); // the form opened again; the secret stayed
    await userEvent.click(screen.getByRole('button', { name: 'Pause' }));
    expect(await screen.findByText('Paused')).toBeInTheDocument();
  });

  it('says what a dry run would do, fires a real run with a key, and shows each action’s outcome', async () => {
    let runs = EMPTY as unknown;
    const { api, calls } = platform({
      'GET /api/v2/automations/runs/': () => runs,
      'POST /api/v2/automations/au1/dry-run/': () => ({
        matched: true,
        value: true,
        error: '',
        actions: [{ index: 0, kind: 'idea', input: { title: 'Fix https://example.com/a' } }],
      }),
      'POST /api/v2/automations/au1/test/': () => {
        runs = page([run()]);
        return run({ status: 'queued', outcomes: [] });
      },
    });
    const { go } = renderUi(<AutomationEditor id="au1" />, { api });
    expect(await screen.findByText(/No runs yet/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Dry run' }));
    const dry = await screen.findByLabelText('The dry run');
    expect(dry).toHaveTextContent('The condition matches; it would:');
    expect(within(dry).getByLabelText('Action 1 as it would run')).toHaveTextContent('Fix https://example.com/a');
    expect(calls.some((c) => c.path === '/api/v2/automations/au1/test/')).toBe(false);

    await userEvent.click(screen.getByRole('button', { name: 'Fire it now' }));
    await waitFor(() => expect(calls.some((c) => c.path === '/api/v2/automations/au1/test/')).toBe(true));
    const fired = calls.find((c) => c.path === '/api/v2/automations/au1/test/');
    expect(fired?.idempotencyKey).toBeTruthy();
    expect(fired?.body).toEqual({ payload: OPTIONS.samples.hook });
    await userEvent.click(await screen.findByRole('button', { name: /: succeeded$/ }));
    const outcomes = await screen.findByRole('list', { name: 'Outcomes' });
    expect(within(outcomes).getByRole('listitem', { name: 'Action 3' })).toHaveTextContent('the mail server is down');
    await userEvent.click(within(outcomes).getByRole('button', { name: 'Run #12' }));
    expect(go).toHaveBeenCalledWith({ to: 'run', id: 12 });
    await userEvent.click(within(outcomes).getByRole('button', { name: 'The idea' }));
    expect(go).toHaveBeenCalledWith({ to: 'ideas' });
  });

  it('exports itself as YAML', async () => {
    const yaml = 'name: Findings to ideas\ntrigger:\n  kind: hook\n  hook: monitor.finding\n';
    const { api } = platform({ 'GET /api/v2/automations/au1/export/': () => ({ name: 'Findings to ideas', yaml }) });
    renderUi(<AutomationEditor id="au1" />, { api });
    await userEvent.click(await screen.findByRole('button', { name: 'Export' }));
    expect(await screen.findByLabelText('The exported document')).toHaveTextContent('hook: monitor.finding');
    expect(screen.getByRole('link', { name: 'Download findings-to-ideas.yaml' })).toHaveAttribute('download', 'findings-to-ideas.yaml');
  });

  it('is read-only for someone it is shared with, whose runs stay its owner’s', async () => {
    const { api } = platform({ 'GET /api/v2/automations/au1/': () => automation({ owner: 'alice', can_edit: false, visibility: 'shared' }) });
    renderUi(<AutomationEditor id="au1" />, { api });
    expect(await screen.findByText(/alice shares this with you/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Name/)).toBeDisabled();
    for (const name of ['Save', 'Delete', 'Enable', 'Fire it now', 'Dry run']) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument();
    }
    expect(await screen.findByText(/Its runs are alice’s to see/)).toBeInTheDocument();
    expect(screen.queryByText(/No runs yet/)).not.toBeInTheDocument();
  });
});
