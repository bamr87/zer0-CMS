// The studio's Distribution area: its destinations are routes, the queue opens
// at /distribution, a post at /distribution/posts/:id, and a channel at
// /distribution/channels/:id — where LinkedIn's consent screen sends the person
// back (`?connecting=1`) while the platform finishes the connection.
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';

import { App, pathFor } from '../src/App';
import { AREAS } from '../src/areas';
import { fakePlatform, noStream, Providers, type Handler } from '../../test/harness';

const SIGNED_IN = {
  authenticated: true,
  user: { id: 1, username: 'editor', name: 'Demo Editor', email: 'editor@example.com', is_staff: true, is_superuser: false },
  permissions: [],
  csrf_token: 'b',
};
const EMPTY = { count: 0, next: null, previous: null, results: [] };

function renderStudio(path: string, routes: Record<string, Handler> = {}) {
  const platform = fakePlatform({
    'GET /api/v2/me': () => SIGNED_IN,
    'GET /api/v2/sites/': () => [{ id: 1, name: 'Demo site', hostname: 'demo.localhost', port: 80, is_default: false, root_page_id: 3 }],
    'GET /api/v2/distribution/posts/': () => EMPTY,
    'GET /api/v2/distribution/channels/': () => EMPTY,
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

describe('the Distribution area', () => {
  it('is built: no milestone, and its destinations are routes', () => {
    expect(AREAS.find((area) => area.path === '/distribution')?.milestone).toBeUndefined();
    expect(pathFor({ to: 'distribution' })).toBe('/distribution');
    expect(pathFor({ to: 'distribution', tab: 'channels' })).toBe('/distribution?tab=channels');
    expect(pathFor({ to: 'distribution-post', id: 'p1' })).toBe('/distribution/posts/p1');
    expect(pathFor({ to: 'channel', id: 'c1' })).toBe('/distribution/channels/c1');
  });

  it('opens on the queue, and a channel LinkedIn sent the person back to', async () => {
    renderStudio('/distribution');
    expect(await screen.findByRole('heading', { name: 'Distribution' })).toBeInTheDocument();
    expect(await screen.findByText(/Nothing in the queue/)).toBeInTheDocument();
    renderStudio('/distribution/channels/c1?connecting=1', {
      'GET /api/v2/distribution/channels/c1/': () => ({
        id: 'c1', site: 1, site_name: 'Demo site', kind: 'linkedin', kind_label: 'LinkedIn', name: 'The page', settings: {},
        newsletter: null, newsletter_name: '', has_credential: false, secret_fields: ['access_token', 'refresh_token'],
        connecting: true, account: '', scopes: [], connected_at: null, expires_at: null, refresh_expires_at: null, checked_at: null,
        last_check: {}, last_error: '', auto_draft: false, armed: false, deployment_armed: false, can_manage: true,
        created_at: '2026-10-20T09:00:00Z', updated_at: '2026-10-20T09:00:00Z',
      }),
      'GET /api/v2/distribution/channels/c1/ledger-file/': () => ({ filename: 'linkedin-c1.json', content: '{}\n' }),
    });
    expect(await screen.findByText(/the platform is finishing the connection/)).toBeInTheDocument();
  });
});
