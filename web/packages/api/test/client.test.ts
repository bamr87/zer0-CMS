// The session client: same-origin requests, Django's CSRF token on every
// unsafe one and on no safe one, read from the cookie unless the host gives it.
import { describe, expect, it } from 'vitest';

import { createSessionClient, csrfFromCookie } from '../src';

function recorder() {
  const seen: Request[] = [];
  const fetch = async (request: Request) => {
    seen.push(request);
    return new Response(JSON.stringify({ authenticated: false, user: null, permissions: [], csrf_token: 't' }), {
      headers: { 'Content-Type': 'application/json' },
    });
  };
  return { seen, fetch };
}

describe('createSessionClient', () => {
  it('sends the CSRF token on unsafe requests only, and the session cookie', async () => {
    const { seen, fetch } = recorder();
    const api = createSessionClient({ baseUrl: 'http://studio.test', fetch, csrfToken: () => 'abc' });
    await api.GET('/api/v2/me');
    await api.POST('/api/v2/session/logout');
    expect(seen.map((r) => [r.method, r.headers.get('X-CSRFToken')])).toEqual([
      ['GET', null],
      ['POST', 'abc'],
    ]);
    expect(seen[1]?.credentials).toBe('same-origin');
  });

  it('reads the token from the page’s cookie by default', async () => {
    document.cookie = 'theme=dark';
    document.cookie = 'csrftoken=from-cookie';
    const { seen, fetch } = recorder();
    await createSessionClient({ baseUrl: 'http://studio.test', fetch }).POST('/api/v2/session/logout');
    expect(seen[0]?.headers.get('X-CSRFToken')).toBe('from-cookie');
    expect(csrfFromCookie('a=1; csrftoken=xyz; b=2')).toBe('xyz');
    expect(csrfFromCookie('a=1')).toBeUndefined();
  });
});
