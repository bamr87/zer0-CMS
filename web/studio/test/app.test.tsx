// The studio: an anonymous visitor gets the sign-in form and signing in
// opens the studio; every area of TARGET.md is in the navigation, an unbuilt
// one names its milestone, and a workspace's destinations become routes.
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';

import { App, bookmarkletFor, pathFor } from '../src/App';
import { AREAS } from '../src/areas';
import { fakePlatform, noStream, pageDetail, Providers, Reply, type Handler } from '../../test/harness';

const PERSON = { id: 1, username: 'editor', name: 'Demo Editor', email: 'editor@example.com', is_staff: true, is_superuser: false };
const SIGNED_IN = { authenticated: true, user: PERSON, permissions: [], csrf_token: 'b' };
const EMPTY = { count: 0, next: null, previous: null, results: [] };

const platformFor = (routes: Record<string, Handler> = {}) =>
  fakePlatform({
    'GET /api/v2/me': () => SIGNED_IN,
    'GET /api/v2/sites/': () => [{ id: 1, name: 'Demo site', hostname: 'demo.localhost', port: 80, is_default: false, root_page_id: 3 }],
    'GET /api/v2/review/suggestions/': () => ({ ...EMPTY, count: 3 }),
    'GET /api/v2/agent-runs/': () => ({ results: [] }),
    'GET /api/v2/content/pages/': () => EMPTY,
    'GET /api/v2/content/types/': () => [],
    ...routes,
  });

function renderStudio(path: string, platform = platformFor()) {
  render(
    <Providers>
      <MemoryRouter initialEntries={[path]}>
        <App api={platform.api} stream={noStream} />
      </MemoryRouter>
    </Providers>,
  );
  return platform;
}

describe('signing in', () => {
  it('shows the sign-in form to an anonymous visitor and opens the studio after', async () => {
    let signedIn = false;
    const platform = renderStudio(
      '/',
      platformFor({
        'GET /api/v2/me': () => (signedIn ? SIGNED_IN : { authenticated: false, user: null, permissions: [], csrf_token: 'a' }),
        'POST /api/v2/session/login': () => {
          signedIn = true;
          return SIGNED_IN;
        },
      }),
    );
    await userEvent.type(await screen.findByLabelText(/Username/), 'editor');
    await userEvent.type(screen.getByLabelText(/Password/), 'zer0-demo');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('heading', { name: 'Home' })).toBeInTheDocument();
    expect(platform.calls.find((c) => c.path === '/api/v2/session/login')?.body).toEqual({ username: 'editor', password: 'zer0-demo' });
    expect(await screen.findByLabelText('Suggestions to review')).toHaveTextContent('3');
  });

  it('says why a sign-in was refused', async () => {
    renderStudio(
      '/',
      platformFor({
        'GET /api/v2/me': () => ({ authenticated: false, user: null, permissions: [], csrf_token: 'a' }),
        'POST /api/v2/session/login': () =>
          new Reply(400, {
            error: { code: 'auth.invalid_credentials', message: 'the username or the password is not right', status: 400, details: [] },
          }),
      }),
    );
    await userEvent.type(await screen.findByLabelText(/Username/), 'editor');
    await userEvent.type(screen.getByLabelText(/Password/), 'wrong');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByText('the username or the password is not right')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Home' })).toBeNull();
  });
});

describe('the shell and its routes', () => {
  it('puts every area in the navigation and names the milestone of an unbuilt one', async () => {
    const planned = AREAS.find((area) => area.milestone);
    if (!planned) throw new Error('every area is built: this test can go');
    renderStudio(planned.path);
    const nav = await screen.findByRole('navigation', { name: 'Areas' });
    for (const area of AREAS) expect(within(nav).getByText(area.label)).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: planned.label })).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`arrives with PLAN ${planned.milestone}`))).toBeInTheDocument();
  });

  it('opens the Ideas and Research workspaces and a source at /research/sources/:id', async () => {
    const routes = {
      'GET /api/v2/ideas/boards/': () => EMPTY,
      'GET /api/v2/ideas/': () => EMPTY,
      'GET /api/v2/research/collections/': () => EMPTY,
      'GET /api/v2/research/sources/': () => EMPTY,
    };
    renderStudio('/ideas', platformFor(routes));
    expect(await screen.findByRole('heading', { name: 'Ideas' })).toBeInTheDocument();
    expect(await screen.findByText('Inbox')).toBeInTheDocument();
    renderStudio('/research', platformFor(routes));
    expect(await screen.findByRole('heading', { name: 'Research' })).toBeInTheDocument();
    expect(await screen.findByText('All sources')).toBeInTheDocument();
    renderStudio('/research/sources/s1', platformFor({ 'GET /api/v2/research/sources/s1/': () => new Reply(404, { error: { code: 'resource.not_found', message: 'no source s1', status: 404, details: [] } }) }));
    expect(await screen.findByText('no source s1')).toBeInTheDocument();
  });

  it('takes a page from the bookmarklet into Research, to capture on the person’s word', async () => {
    const routes = { 'GET /api/v2/research/collections/': () => EMPTY, 'GET /api/v2/research/sources/': () => EMPTY };
    const platform = renderStudio('/research?url=https%3A%2F%2Fexample.com%2Fa', platformFor(routes));
    expect(await screen.findByLabelText('Page address')).toHaveValue('https://example.com/a');
    expect(platform.calls.some((c) => c.method === 'POST')).toBe(false);
    expect(screen.getByText(bookmarkletFor(window.location.origin))).toBeInTheDocument();
    expect(bookmarkletFor('https://cms.example')).toBe(
      "javascript:void(open('https://cms.example/studio/research?url='+encodeURIComponent(location.href)))",
    );
  });

  it('opens the editor at /write/:id and the inbox for one run at /review?run=', async () => {
    renderStudio('/write/5', platformFor({ 'GET /api/v2/content/pages/5/': () => pageDetail() }));
    expect(await screen.findByRole('heading', { name: 'Nightly backups' })).toBeInTheDocument();
    renderStudio('/review?run=7');
    expect(await screen.findByRole('heading', { name: 'Review run #7' })).toBeInTheDocument();
  });

  it('maps every destination a workspace asks for to a route', () => {
    expect(pathFor({ to: 'page', id: 5 })).toBe('/write/5');
    expect(pathFor({ to: 'pages' })).toBe('/write');
    expect(pathFor({ to: 'create' })).toBe('/create');
    expect(pathFor({ to: 'run', id: 9 })).toBe('/ai/runs/9');
    expect(pathFor({ to: 'review', runId: 9 })).toBe('/review?run=9');
    expect(pathFor({ to: 'review' })).toBe('/review');
    expect(pathFor({ to: 'ideas' })).toBe('/ideas');
    expect(pathFor({ to: 'research' })).toBe('/research');
    expect(pathFor({ to: 'source', id: 's1' })).toBe('/research/sources/s1');
    expect(pathFor({ to: 'books' })).toBe('/books');
    expect(pathFor({ to: 'book', id: 20 })).toBe('/books/20');
    expect(pathFor({ to: 'chapter', book: 20, id: 31 })).toBe('/books/20/chapters/31');
    expect(pathFor({ to: 'aieo' })).toBe('/sites/aieo');
    expect(pathFor({ to: 'aieo', section: 'audit' })).toBe('/sites/aieo');
    expect(pathFor({ to: 'aieo', section: 'citations' })).toBe('/sites/aieo/citations');
  });

  it('opens the AIEO workspace at /sites/aieo and a section at /sites/aieo/:section', async () => {
    renderStudio('/sites/aieo', platformFor({ 'GET /api/v2/aieo/audits/': () => EMPTY }));
    expect(await screen.findByRole('heading', { name: 'AIEO' })).toBeInTheDocument();
    expect(await screen.findByRole('form', { name: 'Audit' })).toBeInTheDocument();
    renderStudio('/sites/aieo/patterns', platformFor({ 'GET /api/v2/aieo/patterns/': () => [] }));
    expect(await screen.findByRole('table', { name: 'Pattern library' })).toBeInTheDocument();
  });

  it('opens the shelf at /books', async () => {
    renderStudio('/books', platformFor({ 'GET /api/v2/books/': () => [] }));
    expect(await screen.findByRole('heading', { name: 'Books' })).toBeInTheDocument();
    expect(await screen.findByText('No books yet.')).toBeInTheDocument();
    expect(screen.queryByText(/arrives with PLAN G9/)).toBeNull();
  });
});
