// Signing in: the studio's auth adapter (PLAN G3). The one file that speaks
// django-allauth's headless API for the studio — its browser client
// (`/_allauth/browser/v1/…`, the session cookie, Django's CSRF token on every
// unsafe request), the form POST that leaves for an IdP or GitHub, WebAuthn
// through the browser, and the QR code an authenticator app scans — handed to
// @zer0/ui as its `AuthHost`, whose screens (`SignInScreen`, the account menu)
// do the rest. Who is signed in is still `GET /api/v2/me` (content/api/session.py),
// which every screen reads for the person and their permissions. A signed-out
// person sent here by the Wagtail or Django admin (`?next=/admin/…`) goes back
// there once signed in.
import { Alert, Center, Loader } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { csrfFromCookie, type Me } from '@zer0/api';
import { call, SignInScreen, useApi, useAuthHost, errorText, type Arrival, type AuthHost, type AuthMethod, type AuthResponse } from '@zer0/ui';
import { QRCodeSVG } from 'qrcode.react';
import type { ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router';

export type Person = NonNullable<Me['user']>;

const HEADLESS = '/_allauth/browser/v1';
/** Where allauth sends a person back after connecting an IdP or GitHub to their account (and after a provider error, HEADLESS_FRONTEND_URLS). */
export const PROVIDER_CALLBACK = '/studio/account/provider/callback';
/** Where a sign-in through a provider comes back to: the studio's home (with `?error=` if it did not finish, which the sign-in screen shows). */
export const SIGNED_IN_CALLBACK = '/studio/';

export interface BrowserAuthOptions {
  /** Defaults to the page's own origin. */
  baseUrl?: string;
  /** Defaults to the global fetch; tests inject their own. */
  fetch?: (request: Request) => Promise<Response>;
  /** Defaults to the CSRF cookie of the page. */
  csrfToken?: () => string | undefined;
  /** Leaves the page with a form POST; tests record it instead. */
  submit?: (action: string, fields: Record<string, string>) => void;
  /** WebAuthn; defaults to the browser's, where it has one. */
  passkeys?: AuthHost['passkeys'] | null;
}

function postForm(action: string, fields: Record<string, string>) {
  const form = document.createElement('form');
  form.method = 'POST';
  form.action = action;
  for (const [name, value] of Object.entries(fields)) {
    const input = document.createElement('input');
    input.type = 'hidden';
    input.name = name;
    input.value = value;
    form.append(input);
  }
  document.body.append(form);
  form.submit();
}

/** The browser's WebAuthn, with allauth's JSON options parsed and the credential sent back as JSON. */
function browserPasskeys(): AuthHost['passkeys'] {
  const PKC = typeof window !== 'undefined' ? window.PublicKeyCredential : undefined;
  if (!PKC || typeof PKC.parseCreationOptionsFromJSON !== 'function' || !navigator.credentials) return undefined;
  const asJson = (credential: Credential | null) => {
    if (!(credential instanceof PKC)) throw new Error('The browser made no passkey.');
    return credential.toJSON();
  };
  return {
    create: async (options) => {
      const { publicKey } = options as { publicKey: PublicKeyCredentialCreationOptionsJSON };
      return asJson(await navigator.credentials.create({ publicKey: PKC.parseCreationOptionsFromJSON(publicKey) }));
    },
    get: async (options) => {
      const { publicKey } = options as { publicKey: PublicKeyCredentialRequestOptionsJSON };
      return asJson(await navigator.credentials.get({ publicKey: PKC.parseRequestOptionsFromJSON(publicKey) }));
    },
  };
}

export function createBrowserAuth(options: BrowserAuthOptions = {}): AuthHost {
  const base = options.baseUrl ?? '';
  const send = options.fetch ?? ((request: Request) => fetch(request));
  const csrf = options.csrfToken ?? (() => csrfFromCookie(document.cookie));
  const passkeys = options.passkeys === null ? undefined : (options.passkeys ?? browserPasskeys());
  return {
    async request<T>(method: AuthMethod, path: string, body?: unknown): Promise<AuthResponse<T>> {
      const headers: Record<string, string> = { Accept: 'application/json' };
      const token = method === 'GET' ? undefined : csrf();
      if (token) headers['X-CSRFToken'] = token;
      if (body !== undefined) headers['Content-Type'] = 'application/json';
      const response = await send(
        new Request(`${base}${HEADLESS}${path}`, {
          method,
          headers,
          credentials: 'same-origin',
          ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
        }),
      );
      const text = await response.text();
      try {
        return { status: response.status, ...(JSON.parse(text) as Omit<AuthResponse<T>, 'status'>) };
      } catch {
        return { status: response.status, errors: [{ code: 'not_json', message: text.slice(0, 200) || response.statusText }] };
      }
    },
    redirectToProvider(provider, process) {
      (options.submit ?? postForm)(`${base}${HEADLESS}/auth/provider/redirect`, {
        provider,
        process,
        callback_url: process === 'connect' ? PROVIDER_CALLBACK : SIGNED_IN_CALLBACK,
        csrfmiddlewaretoken: csrf() ?? '',
      });
    },
    passkeys,
    QrCode: ({ value, size }) => <QRCodeSVG value={value} size={size ?? 160} marginSize={2} title="Scan with your authenticator app" />,
  };
}

export const browserAuth = createBrowserAuth();

export function useMe() {
  const api = useApi();
  return useQuery({ queryKey: ['me'], queryFn: () => call(api.GET('/api/v2/me')), staleTime: 60_000 });
}

export function useSignOut() {
  const api = useApi();
  const auth = useAuthHost();
  const qc = useQueryClient();
  return useMutation({
    // allauth ends the session; who is signed in now (no one) comes with a fresh CSRF token.
    mutationFn: async () => {
      await auth?.request('DELETE', '/auth/session');
      return call(api.GET('/api/v2/me'));
    },
    // The screen follows `me` at once; everything the person's session read goes with it.
    onSuccess: (me) => {
      qc.setQueryData(['me'], me);
      qc.removeQueries({ predicate: (query) => query.queryKey[0] !== 'me' });
    },
  });
}

/** A path on this platform to go back to, or undefined: never another site, never a protocol-relative URL. */
export function safeNext(value: string | null): string | undefined {
  return value && value.startsWith('/') && !value.startsWith('//') && !value.startsWith('/\\') ? value : undefined;
}

/** What the address says about how the person arrived: a link from an email, a provider's return, where to go next. */
export function arrivalFrom(pathname: string, search: string): Arrival & { next?: string } {
  const query = new URLSearchParams(search);
  const verify = /^\/account\/verify-email\/([^/]+)\/?$/.exec(pathname)?.[1];
  const reset = /^\/account\/password\/reset\/([^/]+)\/?$/.exec(pathname)?.[1];
  return {
    ...(verify ? { verifyKey: decodeURIComponent(verify) } : {}),
    ...(reset ? { resetKey: decodeURIComponent(reset) } : {}),
    ...(query.get('error') ? { providerError: query.get('error') ?? '' } : {}),
    ...(safeNext(query.get('next')) ? { next: safeNext(query.get('next')) } : {}),
  };
}

/** Renders `children` for a signed-in person, the sign-in screen otherwise. */
export function SignedIn({ children, leave }: { children: (person: Person) => ReactNode; leave?: (url: string) => void }) {
  const me = useMe();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { pathname, search } = useLocation();
  if (me.isPending) {
    return (
      <Center h="100vh">
        <Loader />
      </Center>
    );
  }
  if (me.isError) return <Alert color="red">{errorText(me.error)}</Alert>;
  if (me.data.user) return children(me.data.user);
  const arrival = arrivalFrom(pathname, search);
  const signedIn = async () => {
    await qc.invalidateQueries({ queryKey: ['me'] });
    const next = arrival.next;
    if (next?.startsWith('/studio')) void navigate(next.slice('/studio'.length) || '/');
    else if (next) (leave ?? ((url: string) => window.location.assign(url)))(next);
    else if (pathname.startsWith('/account/')) void navigate('/');
  };
  return <SignInScreen arrival={arrival} onSignedIn={() => void signedIn()} />;
}
