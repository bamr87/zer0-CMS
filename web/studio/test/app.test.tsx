// The studio: an anonymous visitor gets the sign-in screen (allauth's
// headless API over the studio's own adapter, auth.tsx), signing in opens the
// studio — or goes back to the admin that sent them — and the person menu
// opens their account and signs out; every area of TARGET.md is in the navigation, an unbuilt
// one names its milestone, and a workspace's destinations become routes.
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';

import { App, bookmarkletFor, pathFor } from '../src/App';
import { AREAS } from '../src/areas';
import { arrivalFrom, createBrowserAuth, safeNext, SIGNED_IN_CALLBACK, type BrowserAuthOptions } from '../src/auth';
import { authConfig, authenticated, fakePlatform, noStream, pageDetail, Providers, refused, Reply, unauthenticated, type Handler } from '../../test/harness';

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

function renderStudio(
  path: string,
  platform: ReturnType<typeof platformFor> = platformFor(),
  leave?: (url: string) => void,
  options: Partial<BrowserAuthOptions> = {},
) {
  const auth = createBrowserAuth({ baseUrl: 'http://studio.test', fetch: platform.fetch, csrfToken: () => 'test-csrf', passkeys: null, ...options });
  render(
    <Providers>
      <MemoryRouter initialEntries={[path]}>
        <App api={platform.api} stream={noStream} auth={auth} leave={leave} />
      </MemoryRouter>
    </Providers>,
  );
  return platform;
}

const A = '/_allauth/browser/v1';
const ANONYMOUS = { authenticated: false, user: null, permissions: [], csrf_token: 'a' };

/** The studio for someone not signed in yet: allauth's fake answers, and whether it has signed them in. */
function signedOutPlatform(routes: Record<string, Handler> = {}) {
  const state = { signedIn: false };
  const platform = platformFor({
    'GET /api/v2/me': () => (state.signedIn ? SIGNED_IN : ANONYMOUS),
    [`GET ${A}/config`]: () => authConfig(),
    [`GET ${A}/auth/session`]: () => (state.signedIn ? authenticated() : unauthenticated()),
    [`POST ${A}/auth/login`]: ({ body }) => {
      if ((body as { password: string }).password !== 'zer0-demo') return refused('The username and/or password you specified are not correct.');
      state.signedIn = true;
      return authenticated();
    },
    ...routes,
  });
  return { ...platform, state };
}

describe('signing in', () => {
  it('shows the sign-in screen to an anonymous visitor and opens the studio after', async () => {
    const platform = renderStudio('/', signedOutPlatform());
    await userEvent.type(await screen.findByLabelText(/Username or email/), 'editor');
    await userEvent.type(screen.getByLabelText(/^Password/), 'zer0-demo');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('heading', { name: 'Home' })).toBeInTheDocument();
    const login = platform.calls.find((c) => c.path === `${A}/auth/login`);
    expect(login?.body).toEqual({ username: 'editor', password: 'zer0-demo' });
    expect(login?.csrf).toBe('test-csrf');
    expect(await screen.findByLabelText('Suggestions to review')).toHaveTextContent('3');
  });

  it('says why a sign-in was refused', async () => {
    renderStudio('/', signedOutPlatform());
    await userEvent.type(await screen.findByLabelText(/Username or email/), 'editor');
    await userEvent.type(screen.getByLabelText(/^Password/), 'wrong');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByText(/not correct/)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Home' })).toBeNull();
  });

  it('sends a person the admin sent here back to the admin, and nowhere else', async () => {
    const leave = vi.fn();
    renderStudio('/?next=%2Fadmin%2Fpages%2F', signedOutPlatform(), leave);
    await userEvent.type(await screen.findByLabelText(/Username or email/), 'editor');
    await userEvent.type(screen.getByLabelText(/^Password/), 'zer0-demo');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    await waitFor(() => expect(leave).toHaveBeenCalledWith('/admin/pages/'));
    expect(safeNext('//evil.example/')).toBeUndefined();
    expect(safeNext('https://evil.example/')).toBeUndefined();
    expect(safeNext('/\\evil.example')).toBeUndefined();
    expect(arrivalFrom('/account/verify-email/abc%3A1', '')).toEqual({ verifyKey: 'abc:1' });
    expect(arrivalFrom('/account/provider/callback', '?error=cancelled')).toEqual({ providerError: 'cancelled' });
  });

  it('leaves for an IdP with a form POST to allauth, carrying the CSRF token and where to come back', async () => {
    const submit = vi.fn();
    const platform = signedOutPlatform({
      [`GET ${A}/config`]: () => authConfig({ socialaccount: { providers: [{ id: 'corp', name: 'Corp SSO', flows: ['provider_redirect'] }] } }),
    });
    renderStudio('/', platform, undefined, { submit });
    await userEvent.click(await screen.findByRole('button', { name: 'Continue with Corp SSO' }));
    expect(submit).toHaveBeenCalledWith('http://studio.test/_allauth/browser/v1/auth/provider/redirect', {
      provider: 'corp',
      process: 'login',
      callback_url: SIGNED_IN_CALLBACK,
      csrfmiddlewaretoken: 'test-csrf',
    });
  });

  it('signs out through allauth', async () => {
    const platform = signedOutPlatform({
      [`DELETE ${A}/auth/session`]: () => {
        platform.state.signedIn = false;
        return unauthenticated();
      },
    });
    platform.state.signedIn = true;
    renderStudio('/', platform);
    await userEvent.click(await screen.findByRole('button', { name: /Signed in as editor/ }));
    expect(await screen.findByRole('menuitem', { name: 'Account and security' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('menuitem', { name: 'Sign out' }));
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument();
    expect(platform.calls.some((c) => c.method === 'DELETE' && c.path === `${A}/auth/session`)).toBe(true);
  });

  it('opens the account menu at /account and its tokens at /account/tokens', async () => {
    renderStudio(
      '/account/tokens',
      platformFor({
        'GET /api/v2/account/tokens/': () => [],
        [`GET ${A}/config`]: () => authConfig(),
      }),
    );
    expect(await screen.findByRole('heading', { name: 'Your account' })).toBeInTheDocument();
    expect(await screen.findByRole('tab', { name: 'API tokens', selected: true })).toBeInTheDocument();
    expect(pathFor({ to: 'account' })).toBe('/account');
    expect(pathFor({ to: 'account', section: 'sessions' })).toBe('/account/sessions');
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
    expect(pathFor({ to: 'outbox' })).toBe('/outbox');
    expect(pathFor({ to: 'outbox', tab: 'belt' })).toBe('/outbox');
    expect(pathFor({ to: 'outbox', tab: 'claims' })).toBe('/outbox/claims');
    expect(pathFor({ to: 'trial', id: 't1' })).toBe('/outbox/trials/t1');
    expect(pathFor({ to: 'claim-check', id: 'k1' })).toBe('/outbox/claims/k1');
    expect(pathFor({ to: 'aieo' })).toBe('/sites/aieo');
    expect(pathFor({ to: 'aieo', section: 'audit' })).toBe('/sites/aieo');
    expect(pathFor({ to: 'aieo', section: 'citations' })).toBe('/sites/aieo/citations');
  });

  it('opens the Outbox desk on its tabs, and a trial and a claim check at their addresses', async () => {
    const routes = {
      'GET /api/v2/outbox/belt/': () => ({ delivered: 0, dead_letters: 0, traces: 0, kinds: [], seq_gapless: true, ids_unique: true, pending: 0, stations: ['editor'], editor: 'editor', harness: '0.1.0' }),
      'GET /api/v2/outbox/belt/messages/': () => EMPTY,
      'GET /api/v2/outbox/belt/dead-letters/': () => [],
      'GET /api/v2/outbox/trials/': () => EMPTY,
      'GET /api/v2/outbox/trials/t1/': () => new Reply(404, { error: { code: 'resource.not_found', message: 'no trial t1', status: 404, details: [] } }),
      'GET /api/v2/outbox/claim-checks/k1/': () => new Reply(404, { error: { code: 'resource.not_found', message: 'no check k1', status: 404, details: [] } }),
    };
    renderStudio('/outbox', platformFor(routes));
    expect(await screen.findByRole('heading', { name: 'Outbox' })).toBeInTheDocument();
    expect(await screen.findByText('The relay has refused nothing.')).toBeInTheDocument();
    renderStudio('/outbox/trials', platformFor(routes));
    expect(await screen.findByText('No trial yet')).toBeInTheDocument();
    renderStudio('/outbox/trials/t1', platformFor(routes));
    expect(await screen.findByText('no trial t1')).toBeInTheDocument();
    renderStudio('/outbox/claims/k1', platformFor(routes));
    expect(await screen.findByText('no check k1')).toBeInTheDocument();
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
