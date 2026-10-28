// Accounts (PLAN G3), over a fake of django-allauth's headless API and the
// platform: the sign-in screen by password (username or email), its second
// factor, a code by email, a passkey, a provider, sign-up with the address
// verified by code, and a password reset — each step the one allauth says is
// pending; the account menu's TOTP set-up behind a password asked again, its
// sessions ended, and API tokens issued once (read-only), shown once and
// revoked — and, with no browser session (the extension), the tokens alone.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { AccountWorkspace, SignInScreen } from '../src';
import { authConfig, authenticated, fakeAuth, fakePlatform, Reply, refused, renderUi, unauthenticated, type Handler } from '../../../test/harness';

const A = '/_allauth/browser/v1';

function signInWith(routes: Record<string, Handler>, extra: Parameters<typeof fakeAuth>[1] = {}) {
  const platform = fakePlatform({ [`GET ${A}/config`]: () => authConfig(), [`GET ${A}/auth/session`]: () => unauthenticated(), ...routes });
  const auth = fakeAuth(platform.fetch, extra);
  const onSignedIn = vi.fn();
  renderUi(<SignInScreen onSignedIn={onSignedIn} />, { api: platform.api, auth });
  return { ...platform, auth, onSignedIn, body: (path: string) => platform.calls.filter((c) => c.path === `${A}${path}` && c.method !== 'GET').map((c) => c.body) };
}

async function typePassword(login: string, password = 'a long passphrase') {
  const field = await screen.findByLabelText(/Username or email/);
  await userEvent.clear(field);
  await userEvent.type(field, login);
  await userEvent.clear(screen.getByLabelText(/^Password/));
  await userEvent.type(screen.getByLabelText(/^Password/), password);
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
}

describe('the sign-in screen', () => {
  it('signs in with a username or an email and a password', async () => {
    const run = signInWith({ [`POST ${A}/auth/login`]: () => authenticated() });
    await typePassword('editor');
    await waitFor(() => expect(run.onSignedIn).toHaveBeenCalled());
    expect(run.body('/auth/login')).toEqual([{ username: 'editor', password: 'a long passphrase' }]);
    expect(run.calls.find((c) => c.path === `${A}/auth/login`)?.csrf).toBe('test-csrf');
    await typePassword('editor@example.com');
    await waitFor(() => expect(run.body('/auth/login')[1]).toEqual({ email: 'editor@example.com', password: 'a long passphrase' }));
  });

  it('says what allauth refused, and asks for the second factor allauth says is pending', async () => {
    let attempts = 0;
    const run = signInWith({
      [`POST ${A}/auth/login`]: () => (attempts++ ? unauthenticated({ id: 'mfa_authenticate', types: ['totp', 'recovery_codes'] }) : refused('The username and/or password you specified are not correct.')),
      [`POST ${A}/auth/2fa/authenticate`]: ({ body }) => ((body as { code: string }).code === '123456' ? authenticated('editor', ['password', 'mfa']) : refused('Incorrect code.', 'code')),
    });
    await typePassword('editor', 'nope');
    expect(await screen.findByText(/not correct/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('heading', { name: 'Your second factor' })).toBeInTheDocument();
    const code = screen.getByLabelText(/authenticator app, or a recovery code/);
    await userEvent.type(code, '000000');
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }));
    expect(await screen.findByText('Incorrect code.')).toBeInTheDocument();
    await userEvent.clear(code);
    await userEvent.type(code, '123456');
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }));
    await waitFor(() => expect(run.onSignedIn).toHaveBeenCalledTimes(1));
  });

  it('picks up a second factor left pending when the page reloaded', async () => {
    signInWith({ [`GET ${A}/auth/session`]: () => unauthenticated({ id: 'mfa_authenticate', types: ['recovery_codes'] }) });
    expect(await screen.findByLabelText(/^A recovery code/)).toBeInTheDocument();
  });

  it('offers a passkey and each provider allauth is configured with', async () => {
    const passkeys = { create: vi.fn(), get: vi.fn(async () => ({ id: 'cred' })) };
    const run = signInWith(
      {
        [`GET ${A}/config`]: () => authConfig({ socialaccount: { providers: [{ id: 'corp', name: 'Corp SSO', flows: ['provider_redirect'] }] } }),
        [`GET ${A}/auth/webauthn/login`]: () => ({ status: 200, data: { request_options: { publicKey: { challenge: 'c' } } } }),
        [`POST ${A}/auth/webauthn/login`]: () => authenticated('editor', ['mfa']),
      },
      { passkeys },
    );
    await userEvent.click(await screen.findByRole('button', { name: 'Continue with Corp SSO' }));
    expect(run.auth.redirectToProvider).toHaveBeenCalledWith('corp', 'login');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in with a passkey' }));
    await waitFor(() => expect(run.onSignedIn).toHaveBeenCalled());
    expect(passkeys.get).toHaveBeenCalledWith({ publicKey: { challenge: 'c' } });
    expect(run.body('/auth/webauthn/login')).toEqual([{ credential: { id: 'cred' } }]);
  });

  it('offers no passkey where the host has no WebAuthn, and no sign-up while it is closed', async () => {
    signInWith({});
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Sign in with a passkey' })).toBeNull();
    expect(screen.queryByText('Create an account')).toBeNull();
  });

  it('signs up where it is open, then verifies the address by the code sent to it', async () => {
    const run = signInWith({
      [`GET ${A}/config`]: () => authConfig({ account: { is_open_for_signup: true, login_by_code_enabled: false, email_verification_by_code_enabled: true } }),
      [`POST ${A}/auth/signup`]: ({ body }) =>
        (body as { password: string }).password.length < 12 ? refused('This password is too short.', 'password') : unauthenticated({ id: 'verify_email' }),
      [`POST ${A}/auth/email/verify`]: () => authenticated('lin'),
    });
    expect(screen.queryByText('Email me a sign-in code')).toBeNull();
    await userEvent.click(await screen.findByRole('button', { name: 'Create an account' }));
    await userEvent.type(screen.getByLabelText(/^Email/), 'lin@example.com');
    await userEvent.type(screen.getByLabelText(/^Username/), 'lin');
    await userEvent.type(screen.getByLabelText(/^Password/), 'short');
    await userEvent.click(screen.getByRole('button', { name: 'Create the account' }));
    expect(await screen.findByText('This password is too short.')).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/^Password/), ' but now long enough');
    await userEvent.click(screen.getByRole('button', { name: 'Create the account' }));
    expect(await screen.findByRole('heading', { name: 'Verify your address' })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/^Code/), 'ABCD-EFGH');
    await userEvent.click(screen.getByRole('button', { name: 'Go on' }));
    await waitFor(() => expect(run.onSignedIn).toHaveBeenCalled());
    expect(run.body('/auth/email/verify')).toEqual([{ key: 'ABCD-EFGH' }]);
  });

  it('signs up with a passkey instead of a password: the address verified, then the passkey made', async () => {
    const passkeys = { create: vi.fn(async () => ({ id: 'new-passkey' })), get: vi.fn() };
    const run = signInWith(
      {
        [`GET ${A}/config`]: () => authConfig({ account: { is_open_for_signup: true, login_by_code_enabled: true, email_verification_by_code_enabled: true } }),
        [`POST ${A}/auth/webauthn/signup`]: () => unauthenticated({ id: 'verify_email' }),
        [`POST ${A}/auth/email/verify`]: () => unauthenticated({ id: 'mfa_signup_webauthn' }),
        [`GET ${A}/auth/webauthn/signup`]: () => ({ status: 200, data: { creation_options: { publicKey: { challenge: 'c' } } } }),
        [`PUT ${A}/auth/webauthn/signup`]: () => authenticated('kim', ['mfa']),
      },
      { passkeys },
    );
    await userEvent.click(await screen.findByRole('button', { name: 'Create an account' }));
    await userEvent.type(screen.getByLabelText(/^Email/), 'kim@example.com');
    await userEvent.type(screen.getByLabelText(/^Username/), 'kim');
    await userEvent.click(screen.getByRole('button', { name: 'Use a passkey instead of a password' }));
    await userEvent.type(await screen.findByLabelText(/^Code/), 'ABCD-EFGH');
    await userEvent.click(screen.getByRole('button', { name: 'Go on' }));
    expect(await screen.findByRole('heading', { name: 'Make your passkey' })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/Name it/), 'Phone');
    await userEvent.click(screen.getByRole('button', { name: 'Make the passkey' }));
    await waitFor(() => expect(run.onSignedIn).toHaveBeenCalled());
    expect(run.body('/auth/webauthn/signup')).toEqual([{ email: 'kim@example.com', username: 'kim' }, { name: 'Phone', credential: { id: 'new-passkey' } }]);
    expect(passkeys.create).toHaveBeenCalledWith({ publicKey: { challenge: 'c' } });
  });

  it('signs in with a code sent by email', async () => {
    const run = signInWith({
      [`POST ${A}/auth/code/request`]: () => unauthenticated({ id: 'login_by_code' }),
      [`POST ${A}/auth/code/confirm`]: () => authenticated(),
    });
    await userEvent.click(await screen.findByRole('button', { name: 'Email me a sign-in code' }));
    await userEvent.type(screen.getByLabelText(/^Email/), 'editor@example.com');
    await userEvent.click(screen.getByRole('button', { name: 'Send me a code' }));
    await userEvent.type(await screen.findByLabelText(/^Code/), 'WXYZ-1234');
    await userEvent.click(screen.getByRole('button', { name: 'Go on' }));
    await waitFor(() => expect(run.onSignedIn).toHaveBeenCalled());
    expect(run.body('/auth/code/request')).toEqual([{ email: 'editor@example.com' }]);
    expect(run.body('/auth/code/confirm')).toEqual([{ code: 'WXYZ-1234' }]);
  });

  it('resets a password by a code, then asks the person to sign in with it', async () => {
    const run = signInWith({
      [`POST ${A}/auth/password/request`]: () => unauthenticated({ id: 'password_reset_by_code' }),
      [`POST ${A}/auth/password/reset`]: () => unauthenticated(),
    });
    await userEvent.click(await screen.findByRole('button', { name: 'Forgot your password?' }));
    await userEvent.type(screen.getByLabelText(/^Email/), 'editor@example.com');
    await userEvent.click(screen.getByRole('button', { name: 'Send me a reset code' }));
    await userEvent.type(await screen.findByLabelText(/^Code/), 'RSET-CODE');
    await userEvent.type(screen.getByLabelText(/New password/), 'a brand new passphrase');
    await userEvent.click(screen.getByRole('button', { name: 'Set the password' }));
    expect(await screen.findByText('Done. Sign in to go on.')).toBeInTheDocument();
    expect(run.body('/auth/password/reset')).toEqual([{ key: 'RSET-CODE', password: 'a brand new passphrase' }]);
    expect(run.onSignedIn).not.toHaveBeenCalled();
  });
});

const TOKEN = {
  id: '6f1c0000-0000-4000-8000-000000000001',
  name: 'VS Code',
  prefix: 'zer0u_abcdefgh',
  scopes: ['read', 'write'],
  state: 'active',
  created_at: '2026-10-27T10:00:00Z',
  last_used_at: null,
  expires_at: '2027-01-25T10:00:00Z',
  revoked_at: null,
  current: false,
};
const ME = { authenticated: true, user: { id: 1, username: 'editor', name: 'Ed', email: 'e@example.com', is_staff: true, is_superuser: false }, permissions: [], csrf_token: 'x' };

describe('the account menu', () => {
  it('sets up TOTP after the password is asked again, showing the key and its QR code', async () => {
    let active = false;
    let reauthenticated = false;
    const platform = fakePlatform({
      [`GET ${A}/config`]: () => authConfig(),
      [`GET ${A}/auth/session`]: () => authenticated(),
      [`GET ${A}/account/authenticators`]: () => ({ status: 200, data: active ? [{ type: 'totp', created_at: 1, last_used_at: null }, { type: 'recovery_codes', created_at: 1, last_used_at: null, total_code_count: 10, unused_code_count: 10 }] : [] }),
      [`GET ${A}/account/authenticators/totp`]: () => new Reply(404, { status: 404, meta: { secret: 'JBSWY3DPEHPK3PXP', totp_url: 'otpauth://totp/editor?secret=JBSWY3DPEHPK3PXP&issuer=zer0-CMS' } }),
      [`POST ${A}/account/authenticators/totp`]: () => {
        if (!reauthenticated) return new Reply(401, { status: 401, data: { flows: [{ id: 'reauthenticate' }] }, meta: { is_authenticated: true } });
        active = true;
        return { status: 200, data: { type: 'totp', created_at: 1, last_used_at: null } };
      },
      [`POST ${A}/auth/reauthenticate`]: ({ body }) => {
        reauthenticated = (body as { password: string }).password === 'a long passphrase';
        return reauthenticated ? authenticated() : refused('Incorrect password.', 'password');
      },
    });
    const QrCode = ({ value }: { value: string }) => <svg aria-label={`QR code for ${value}`} />;
    renderUi(<AccountWorkspace />, { api: platform.api, auth: fakeAuth(platform.fetch, { QrCode }) });
    expect(await screen.findByLabelText('Setup key')).toHaveTextContent('JBSW Y3DP EHPK 3PXP');
    expect(screen.getByLabelText(/QR code for otpauth:\/\/totp\/editor/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/Code from the app/), '123456');
    await userEvent.click(screen.getByRole('button', { name: 'Turn it on' }));
    const dialog = await screen.findByRole('dialog', { name: 'Confirm it is you' });
    await userEvent.type(within(dialog).getByLabelText(/^Password/), 'a long passphrase');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Confirm' }));
    expect(await screen.findByRole('button', { name: 'Turn it off' })).toBeInTheDocument();
    expect(await screen.findByText(/10 of 10 unused/)).toBeInTheDocument();
    const sent = platform.calls.filter((c) => c.path === `${A}/account/authenticators/totp` && c.method === 'POST').map((c) => c.body);
    expect(sent).toEqual([{ code: '123456' }, { code: '123456' }]);
  });

  it('lists the sessions and ends another one', async () => {
    const sessions = [
      { id: 1, user_agent: 'Firefox', ip: '10.0.0.1', created_at: 1793059200, is_current: true },
      { id: 2, user_agent: 'Safari on a phone', ip: '10.0.0.2', created_at: 1793059000, is_current: false },
    ];
    const platform = fakePlatform({
      [`GET ${A}/auth/sessions`]: () => ({ status: 200, data: sessions }),
      [`DELETE ${A}/auth/sessions`]: () => ({ status: 200, data: [sessions[0]] }),
    });
    renderUi(<AccountWorkspace section="sessions" />, { api: platform.api, auth: fakeAuth(platform.fetch) });
    const table = await screen.findByRole('table', { name: 'Sessions' });
    expect(await within(table).findByText('This one')).toBeInTheDocument();
    await userEvent.click(within(table).getByRole('button', { name: 'End' }));
    await waitFor(() => expect(screen.queryByText('Safari on a phone')).toBeNull());
    expect(platform.calls.find((c) => c.method === 'DELETE')?.body).toEqual({ sessions: [2] });
  });

  it('issues a read-only token, shows it once, and revokes one', async () => {
    let tokens = [TOKEN];
    const platform = fakePlatform({
      'GET /api/v2/me': () => ME,
      'GET /api/v2/account/tokens/': () => tokens,
      'POST /api/v2/account/tokens/': ({ body }) => {
        const issued = { ...TOKEN, id: '6f1c0000-0000-4000-8000-000000000002', name: (body as { name: string }).name, scopes: ['read'] };
        tokens = [issued, ...tokens];
        return new Reply(201, { token: issued, raw: 'zer0u_the-raw-token-shown-once' });
      },
      [`DELETE /api/v2/account/tokens/${TOKEN.id}/`]: () => ({ ...TOKEN, state: 'revoked' }),
    });
    renderUi(<AccountWorkspace section="tokens" />, { api: platform.api, auth: fakeAuth(platform.fetch) });
    await userEvent.type(await screen.findByLabelText(/Where it is used/), 'CI');
    await userEvent.click(screen.getByLabelText(/Read only/));
    await userEvent.click(screen.getByRole('button', { name: 'Issue a token' }));
    expect(await screen.findByLabelText('New token')).toHaveTextContent('zer0u_the-raw-token-shown-once');
    expect(platform.calls.find((c) => c.method === 'POST')?.body).toEqual({ name: 'CI', days: 90, scopes: ['read'], superuser: false });
    expect(screen.queryByText(/superuser/)).toBeNull();
    const table = await screen.findByRole('table', { name: 'API tokens' });
    expect(await within(table).findByText('CI')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Done' }));
    expect(screen.queryByLabelText('New token')).toBeNull();
    await userEvent.click(within(table).getByRole('button', { name: 'Revoke VS Code' }));
    await waitFor(() => expect(platform.calls.some((c) => c.method === 'DELETE')).toBe(true));
  });

  it('shows only the tokens where the host has no browser session', async () => {
    const platform = fakePlatform({ 'GET /api/v2/me': () => ME, 'GET /api/v2/account/tokens/': () => [{ ...TOKEN, current: true }] });
    renderUi(<AccountWorkspace />, { api: platform.api });
    expect(await screen.findByText(/managed in the studio/)).toBeInTheDocument();
    expect(await screen.findByText('This one')).toBeInTheDocument();
    expect(screen.queryByRole('tab')).toBeNull();
    expect(platform.calls.some((c) => c.path.startsWith('/_allauth'))).toBe(false);
  });
});
