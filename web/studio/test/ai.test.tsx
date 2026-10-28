// The studio's AI and Create areas (G8): each section is a tab and a route,
// a row opens under its section, the editor opens on a page's suggestions,
// and every destination the AI workspaces ask for maps to its route.
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';

import { App, pathFor } from '../src/App';
import { fakePlatform, noStream, nth, pageDetail, Providers, type Handler } from '../../test/harness';

const PERSON = { id: 1, username: 'editor', name: 'Demo Editor', email: 'editor@example.com', is_staff: false, is_superuser: false };
const EMPTY = { count: 0, next: null, previous: null, results: [] };

function renderStudio(path: string, routes: Record<string, Handler> = {}) {
  const platform = fakePlatform({
    'GET /api/v2/me': () => ({ authenticated: true, user: PERSON, permissions: [], csrf_token: 'b' }),
    'GET /api/v2/sites/': () => [],
    'GET /api/v2/agent-runs/': () => ({ results: [] }),
    'GET /api/v2/ai/assistants/': () => EMPTY,
    'GET /api/v2/ai/pipelines/': () => EMPTY,
    'GET /api/v2/ai/output-schemas/': () => EMPTY,
    'GET /api/v2/ai/briefs/': () => EMPTY,
    'GET /api/v2/ai/conversations/': () => EMPTY,
    'GET /api/v2/ai/providers/': () => EMPTY,
    'GET /api/v2/ai/models/': () => EMPTY,
    'GET /api/v2/content/pages/': () => EMPTY,
    ...routes,
  });
  render(
    <Providers>
      <MemoryRouter initialEntries={[path]}>
        <App api={platform.api} stream={noStream} />
      </MemoryRouter>
    </Providers>,
  );
  return platform;
}

describe('the AI area', () => {
  it('opens on the runs, and every section is a tab that is a route', async () => {
    renderStudio('/ai');
    expect(await screen.findByRole('heading', { name: 'AI' })).toBeInTheDocument();
    expect(await screen.findByText('No agent runs yet.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'Assistants' }));
    expect(await screen.findByText('No assistants yet')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'Output schemas' }));
    expect(await screen.findByText('No output schemas yet')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'Models' }));
    expect(await screen.findByText('No models in the catalog yet')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'Runs' }));
    expect(await screen.findByText('No agent runs yet.')).toBeInTheDocument();
  });

  it('opens a new assistant and a pipeline under their sections', async () => {
    renderStudio('/ai/assistants/new', { 'GET /api/v2/ai/assistants/tools/': () => [] });
    expect(await screen.findByRole('heading', { name: 'New assistant' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Assistants' })).toHaveAttribute('aria-selected', 'true');
    renderStudio('/ai/pipelines/new');
    expect(await screen.findByRole('heading', { name: 'New pipeline' })).toBeInTheDocument();
  });

  it('lists the automations under their tab and opens a new one (G16)', async () => {
    renderStudio('/ai/automations', {
      'GET /api/v2/automations/': () => EMPTY,
      'GET /api/v2/automations/options/': () => ({ events: ['content.page.published'], stages: [], agents: [], samples: {} }),
    });
    expect(await screen.findByText('No automations yet')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Automations' })).toHaveAttribute('aria-selected', 'true');
    await userEvent.click(nth(screen.getAllByRole('button', { name: 'New automation' })));
    expect(await screen.findByRole('heading', { name: 'New automation' })).toBeInTheDocument();
  });
});

describe('the Create area', () => {
  it('creates a page, a brief or a conversation, one tab each', async () => {
    renderStudio('/create', { 'GET /api/v2/content/pages/': () => ({ ...EMPTY, results: [] }) });
    expect(await screen.findByRole('heading', { name: 'Create' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'Briefs' }));
    expect(await screen.findByText('No briefs yet')).toBeInTheDocument();
    await userEvent.click(nth(screen.getAllByRole('button', { name: 'New brief' })));
    expect(await screen.findByRole('heading', { name: 'New brief' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'Conversations' }));
    expect(await screen.findByText('No conversations yet')).toBeInTheDocument();
  });

  it('opens the editor on a page’s suggestions', async () => {
    renderStudio('/write/5?tab=suggestions', {
      'GET /api/v2/content/pages/5/': () => pageDetail(),
      'GET /api/v2/review/suggestions/': () => EMPTY,
    });
    expect(await screen.findByRole('tab', { name: 'Suggestions (0)' })).toHaveAttribute('aria-selected', 'true');
  });
});

describe('Home', () => {
  it('shows the AI providers’ status, a step from configuring them', async () => {
    const provider = (slug: string, overrides: Record<string, unknown>) => ({
      id: `p-${slug}`,
      slug,
      display_name: slug === 'anthropic' ? 'Anthropic' : slug,
      enabled: true,
      is_default: false,
      default_model: '',
      monthly_budget_usd: null,
      has_credential: true,
      credential_source: 'database',
      capabilities: [],
      last_health: {},
      checked_at: null,
      created_at: '',
      updated_at: '',
      ...overrides,
    });
    renderStudio('/', {
      'GET /api/v2/review/suggestions/': () => EMPTY,
      'GET /api/v2/ai/providers/': () => ({
        ...EMPTY,
        results: [provider('anthropic', { is_default: true, last_health: { ok: true } }), provider('openai', { last_health: { ok: false } }), provider('fake', { enabled: false })],
      }),
    });
    const status = await screen.findByLabelText('Provider status');
    expect(status).toHaveTextContent('Default: Anthropic');
    expect(status).toHaveTextContent('healthy');
    expect(status).toHaveTextContent('2 enabled · 1 failing its last check');
    await userEvent.click(screen.getByRole('button', { name: 'Open the providers' }));
    expect(await screen.findByRole('tab', { name: 'Providers' })).toHaveAttribute('aria-selected', 'true');
  });
});

describe('the AI destinations', () => {
  it('map to their routes', () => {
    expect(pathFor({ to: 'page', id: 5, tab: 'suggestions' })).toBe('/write/5?tab=suggestions');
    expect(pathFor({ to: 'ai' })).toBe('/ai');
    expect(pathFor({ to: 'ai', section: 'runs' })).toBe('/ai');
    expect(pathFor({ to: 'ai', section: 'providers' })).toBe('/ai/providers');
    expect(pathFor({ to: 'assistant' })).toBe('/ai/assistants/new');
    expect(pathFor({ to: 'assistant', id: 'a1' })).toBe('/ai/assistants/a1');
    expect(pathFor({ to: 'pipeline', id: 'p1' })).toBe('/ai/pipelines/p1');
    expect(pathFor({ to: 'schema' })).toBe('/ai/schemas/new');
    expect(pathFor({ to: 'conversation', id: 'c1' })).toBe('/ai/conversations/c1');
    expect(pathFor({ to: 'brief', id: 'b1' })).toBe('/create/briefs/b1');
    expect(pathFor({ to: 'brief' })).toBe('/create/briefs/new');
    expect(pathFor({ to: 'briefs' })).toBe('/create/briefs');
    expect(pathFor({ to: 'ai', section: 'automations' })).toBe('/ai/automations');
    expect(pathFor({ to: 'automation' })).toBe('/ai/automations/new');
    expect(pathFor({ to: 'automation', id: 'au1' })).toBe('/ai/automations/au1');
  });
});
