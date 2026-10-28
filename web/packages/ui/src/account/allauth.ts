// django-allauth's headless API as @zer0/ui speaks it (PLAN G3): the shapes of
// the answers the sign-in screen and the account menu read, the host seam that
// carries the requests (`AuthHost`, which the studio supplies over its browser
// session — web/studio/src/auth.tsx — and the extension's webviews leave out),
// and one way to read an answer. The API is allauth's, documented by allauth
// (its OpenAPI specification); only the subset the screens use is typed here.
import type { ComponentType } from 'react';

export type AuthMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export interface AuthUser {
  id: number;
  username?: string;
  email?: string;
  display: string;
  has_usable_password: boolean;
}

/** A flow allauth offers or has pending, e.g. `login`, `mfa_authenticate`, `verify_email`, `reauthenticate`. */
export interface AuthFlow {
  id: string;
  is_pending?: boolean;
  /** For `mfa_authenticate` and `mfa_reauthenticate`: the factors the person has. */
  types?: string[];
  /** For `provider_redirect` and `provider_token`. */
  providers?: string[];
}

export interface AuthErrorItem {
  message: string;
  code: string;
  param?: string;
}

/** Every answer: allauth's status, its data and meta, or its errors. */
export interface AuthResponse<T = unknown> {
  status: number;
  data?: T;
  meta?: { is_authenticated?: boolean; [key: string]: unknown };
  errors?: AuthErrorItem[];
}

export interface Provider {
  id: string;
  name: string;
  flows: string[];
}

export interface AuthConfig {
  account: {
    login_methods?: string[];
    is_open_for_signup: boolean;
    login_by_code_enabled: boolean;
    password_reset_by_code_enabled?: boolean;
    email_verification_by_code_enabled: boolean;
  };
  socialaccount?: { providers: Provider[] };
  mfa?: { supported_types: string[]; passkey_login_enabled: boolean };
  usersessions?: { track_activity: boolean };
}

export interface Authenticator {
  type: 'totp' | 'recovery_codes' | 'webauthn';
  created_at: number;
  last_used_at: number | null;
  id?: number;
  name?: string;
  is_passwordless?: boolean;
  total_code_count?: number;
  unused_code_count?: number;
  unused_codes?: string[];
}

export interface UserSession {
  id: number;
  user_agent: string;
  ip: string;
  created_at: number;
  is_current: boolean;
  last_seen_at?: number;
}

export interface ProviderAccount {
  uid: string;
  display: string;
  provider: { id: string; name: string };
}

/**
 * What a host that holds a browser session gives @zer0/ui for allauth. Every
 * answer resolves — a 401 is how allauth says "not signed in" or "this flow is
 * pending" — and only a network failure rejects.
 */
export interface AuthHost {
  /** One request to `/_allauth/browser/v1` + `path`, with the session cookie and the CSRF token. */
  request<T = unknown>(method: AuthMethod, path: string, body?: unknown): Promise<AuthResponse<T>>;
  /** Leaves the page for an IdP or GitHub (allauth's form POST); the person comes back to the studio. */
  redirectToProvider(provider: string, process: 'login' | 'connect'): void;
  /** WebAuthn through the browser — JSON options in, the credential as JSON out; absent where there is none. */
  passkeys?: {
    create(options: unknown): Promise<unknown>;
    get(options: unknown): Promise<unknown>;
  };
  /** Draws an otpauth:// address as a QR code for an authenticator app; absent, the setup key is shown alone. */
  QrCode?: ComponentType<{ value: string; size?: number }>;
}

/** An answer that is neither a success nor a pending flow: what allauth said, field by field. */
export class AuthError extends Error {
  constructor(
    readonly status: number,
    readonly errors: AuthErrorItem[],
  ) {
    super(errors.length ? errors.map((e) => e.message).join(' ') : `HTTP ${status}`);
  }

  /** What allauth said about one input, to show beside it. */
  about(param: string): string | undefined {
    return this.errors.filter((e) => e.param === param).map((e) => e.message).join(' ') || undefined;
  }
}

/** The flows of a 401, by id. */
export function flowsOf(response: AuthResponse): Record<string, AuthFlow> {
  const flows = (response.data as { flows?: AuthFlow[] } | undefined)?.flows ?? [];
  return Object.fromEntries(flows.map((flow) => [flow.id, flow]));
}

/** The flow a 401 says is pending — the step the person is in the middle of — if any. */
export function pendingFlow(response: AuthResponse): AuthFlow | undefined {
  return Object.values(flowsOf(response)).find((flow) => flow.is_pending);
}

/** Whether a 401 asks the person to confirm who they are again before the change goes through. */
export function needsReauthentication(response: AuthResponse): AuthFlow | undefined {
  if (response.status !== 401) return undefined;
  const flows = flowsOf(response);
  return flows.reauthenticate ?? flows.mfa_reauthenticate;
}

/** A success's data, a 401's answer as it is (a flow to continue), or an AuthError. */
export function authResult<T>(response: AuthResponse<T>): AuthResponse<T> {
  if (response.status >= 400 && response.status !== 401) throw new AuthError(response.status, response.errors ?? []);
  return response;
}

/** The data of an answer that must succeed; anything else is an AuthError. */
export function authData<T>(response: AuthResponse<T>): T {
  if (response.status !== 200 || response.data === undefined) throw new AuthError(response.status, response.errors ?? []);
  return response.data;
}
