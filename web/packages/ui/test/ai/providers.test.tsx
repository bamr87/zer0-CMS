// Providers and models: everyone sees a provider's status and nobody its
// configuration unless they configure providers; a credential only goes in —
// typed into an empty field, sent once, never shown or echoed back — and a
// test or a model sync is a run followed live, after which the list is read
// again: one check at a time, a double click starting one run, each request
// with its Idempotency-Key. The catalog filters through the platform.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { ModelCatalog, ProviderList, shortId } from '../../src';
import { fakePlatform, held, renderUi } from '../../../../test/harness';
import { agentRun, liveStream, me, OTHER_RUN, page, RUN, runRef } from './fixtures';

const provider = (overrides: Record<string, unknown> = {}) => ({
  id: 'p-anthropic',
  slug: 'anthropic',
  display_name: 'Anthropic',
  enabled: true,
  is_default: false,
  default_model: '',
  monthly_budget_usd: null,
  has_credential: false,
  credential_source: '',
  capabilities: ['complete', 'structured', 'tools'],
  last_health: {},
  checked_at: null,
  created_at: '2026-10-22T09:00:00Z',
  updated_at: '2026-10-22T09:00:00Z',
  ...overrides,
});
const CONFIG = { base_url: '', organization: '', project: '', extra: {} };

describe('<ProviderList>', () => {
  it('shows every provider’s status, and no configuration to someone who does not configure them', async () => {
    const { api } = fakePlatform({
      'GET /api/v2/me': () => me(),
      'GET /api/v2/ai/providers/': () => page([provider({ is_default: true, has_credential: true, last_health: { ok: true } }), provider({ id: 'p-openai', slug: 'openai', display_name: 'OpenAI', enabled: false, credential_source: 'OPENAI_API_KEY' })]),
    });
    renderUi(<ProviderList />, { api });
    const table = await screen.findByRole('table', { name: 'Providers' });
    const [, anthropic, openai] = within(table).getAllByRole('row');
    expect(anthropic).toHaveTextContent('default');
    expect(anthropic).toHaveTextContent('healthy');
    expect(anthropic).toHaveTextContent('set');
    expect(openai).toHaveTextContent('disabled');
    expect(openai).toHaveTextContent('not set — uses OPENAI_API_KEY');
    expect(screen.queryByRole('button', { name: 'Configure' })).toBeNull();
  });

  it('sends a typed credential once and never shows it again', async () => {
    let stored = false;
    const { api, calls } = fakePlatform({
      'GET /api/v2/me': () => me(['ai.change_providerconfig']),
      'GET /api/v2/ai/providers/': () => page([provider({ ...CONFIG, has_credential: stored })]),
      'PATCH /api/v2/ai/providers/p-anthropic/': ({ body }) => {
        if (typeof body === 'object' && body !== null && 'credential' in body) stored = Boolean((body as { credential: string }).credential);
        return provider({ ...CONFIG, has_credential: stored, credential_source: stored ? 'database' : '' });
      },
    });
    renderUi(<ProviderList />, { api });
    await userEvent.click(await screen.findByRole('button', { name: 'Configure' }));
    const drawer = await screen.findByRole('dialog', { name: 'Configure Anthropic' });
    expect(within(drawer).getByText('Credential: not set')).toBeInTheDocument();
    const secret = within(drawer).getByLabelText('Credential');
    expect(secret).toHaveValue('');
    await userEvent.type(secret, 'sk-ant-secret');
    await userEvent.click(within(drawer).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(within(drawer).getByText('Credential: set')).toBeInTheDocument());
    const patches = () => calls.filter((c) => c.method === 'PATCH').map((c) => c.body as Record<string, unknown>);
    expect(patches()[0]).toMatchObject({ credential: 'sk-ant-secret', enabled: true, extra: {} });
    expect(within(drawer).getByLabelText('Replace the credential')).toHaveValue('');
    expect(screen.queryByDisplayValue('sk-ant-secret')).toBeNull();
    expect(document.body.textContent).not.toContain('sk-ant-secret');
    // Saving again without typing one sends no credential: the stored one stays.
    await userEvent.clear(within(drawer).getByLabelText('Default model'));
    await userEvent.type(within(drawer).getByLabelText('Default model'), 'claude-sonnet-5-5');
    await userEvent.click(within(drawer).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(patches()).toHaveLength(2));
    expect(patches()[1]).not.toHaveProperty('credential');
    expect(patches()[1]).toMatchObject({ default_model: 'claude-sonnet-5-5' });
    // Removing it is asked for explicitly, and sends an empty credential.
    await userEvent.click(within(drawer).getByLabelText(/Remove the stored credential/));
    await userEvent.click(within(drawer).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(patches()).toHaveLength(3));
    expect(patches()[2]).toMatchObject({ credential: '' });
    await waitFor(() => expect(within(drawer).getByText('Credential: not set')).toBeInTheDocument());
  });

  it('tests a provider as a run followed live, then reads the list again; sets the default', async () => {
    let health = {};
    const { stream, finish } = liveStream();
    let status = 'running';
    const { api, calls } = fakePlatform({
      'GET /api/v2/me': () => me(['ai.change_providerconfig']),
      'GET /api/v2/ai/providers/': () => page([provider({ ...CONFIG, last_health: health })]),
      'POST /api/v2/ai/providers/p-anthropic/test/': () => ({ run: runRef() }),
      'POST /api/v2/ai/providers/p-anthropic/sync-models/': () => ({ run: runRef() }),
      'POST /api/v2/ai/providers/p-anthropic/set-default/': () => provider({ ...CONFIG, is_default: true }),
      [`GET /api/v2/agent-runs/${RUN}/`]: () => agentRun(status, { ok: true }),
    });
    renderUi(<ProviderList />, { api, stream });
    await userEvent.click(await screen.findByRole('button', { name: 'Test anthropic' }));
    expect(await screen.findByRole('status', { name: `Run ${shortId(RUN)}` })).toHaveTextContent('running');
    await waitFor(() => expect(stream).toHaveBeenCalledWith(`/api/v2/agent-runs/${RUN}/stream/`, ['step', 'status', 'end'], expect.any(Function)));
    health = { ok: true };
    status = 'succeeded';
    finish();
    expect(await screen.findByText('healthy')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: "Sync anthropic's models" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith('/sync-models/'))).toBe(true));
    await userEvent.click(screen.getByRole('button', { name: 'Make anthropic the default' }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith('/set-default/'))).toBe(true));
  });

  it('starts one check for a double click, with an Idempotency-Key, and holds every check while it is out', async () => {
    const testing = held({ run: runRef() });
    const { api, calls } = fakePlatform({
      'GET /api/v2/me': () => me(['ai.change_providerconfig']),
      'GET /api/v2/ai/providers/': () => page([provider(CONFIG), provider({ ...CONFIG, id: 'p-openai', slug: 'openai', display_name: 'OpenAI' })]),
      'POST /api/v2/ai/providers/p-anthropic/test/': () => testing.reply,
      'POST /api/v2/ai/providers/p-anthropic/sync-models/': () => ({ run: runRef(OTHER_RUN) }),
      [`GET /api/v2/agent-runs/${RUN}/`]: () => agentRun('running'),
    });
    renderUi(<ProviderList />, { api });
    await userEvent.dblClick(await screen.findByRole('button', { name: 'Test anthropic' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Test anthropic' })).toBeDisabled());
    expect(screen.getByRole('button', { name: "Sync anthropic's models" })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Test openai' })).toBeDisabled();
    const tests = calls.filter((c) => c.path.endsWith('/test/'));
    expect(tests).toHaveLength(1);
    expect(tests[0]?.idempotencyKey).toMatch(/^[0-9a-f-]{32,36}$/);
    testing.answer();
    expect(await screen.findByRole('status', { name: `Run ${shortId(RUN)}` })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: "Sync anthropic's models" })).toBeEnabled());
    await userEvent.dblClick(screen.getByRole('button', { name: "Sync anthropic's models" }));
    await waitFor(() => expect(calls.filter((c) => c.path.endsWith('/sync-models/'))).toHaveLength(1));
    expect(calls.find((c) => c.path.endsWith('/sync-models/'))?.idempotencyKey).not.toBe(tests[0]?.idempotencyKey);
  });
});

describe('<ModelCatalog>', () => {
  const model = (id: string, provider: string, active = true) => ({
    id: `m-${id}`,
    provider,
    model_id: id,
    display_name: id.toUpperCase(),
    description: '',
    capabilities: { structured_output: true, tools: true, vision: false },
    input_usd_per_mtok: '3.0000',
    output_usd_per_mtok: '15.0000',
    active,
    synced_at: '2026-10-22T09:00:00Z',
  });

  it('filters by provider and activity through the platform, and by name here', async () => {
    const { api, calls } = fakePlatform({
      'GET /api/v2/ai/providers/': () => page([provider()]),
      'GET /api/v2/ai/models/': ({ url }) => page(url.searchParams.get('provider') === 'anthropic' ? [model('claude-a', 'anthropic')] : [model('claude-a', 'anthropic'), model('gpt-b', 'openai')]),
    });
    renderUi(<ModelCatalog />, { api });
    const table = await screen.findByRole('table', { name: 'Models' });
    expect(within(table).getByText('gpt-b')).toBeInTheDocument();
    expect(within(table).getAllByText('structured output')).toHaveLength(2);
    expect(calls.at(-1)?.query.get('active')).toBe('true');
    await userEvent.click(screen.getByRole('combobox', { name: 'Provider' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Anthropic' }));
    await waitFor(() => expect(screen.queryByText('gpt-b')).toBeNull());
    expect(calls.at(-1)?.query.get('provider')).toBe('anthropic');
    await userEvent.type(screen.getByLabelText('Name'), 'nothing like it');
    expect(await screen.findByText('No model matches')).toBeInTheDocument();
  });

  it('points an empty catalog at the providers, where a sync fills it', async () => {
    const { api } = fakePlatform({ 'GET /api/v2/ai/providers/': () => page([]), 'GET /api/v2/ai/models/': () => page([]) });
    const { go } = renderUi(<ModelCatalog />, { api });
    await userEvent.click(await screen.findByRole('button', { name: 'Go to the providers' }));
    expect(go).toHaveBeenCalledWith({ to: 'ai', section: 'providers' });
  });
});
