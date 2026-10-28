# `accounts/` — how people sign in, and what they sign in with

> Sign-in, sign-up, codes, second factors, passkeys, IdPs and the session list on django-allauth, served headless to the studio; the admins' sign-in routed to it; and a person's scoped API token for a client that is not a browser.

PLAN G3 and TARGET.md § Capabilities (accounts and access). Nothing here hand-rolls an auth flow: django-allauth (`account`, `socialaccount` with `openid_connect` and `github`, `mfa`, `usersessions`, `headless`) is configured in `config/settings/base.py` § Accounts and does the work; this app holds what allauth asks the platform and the token allauth does not have. Every screen is React in `web/` — the studio's sign-in and account menu (`@zer0/ui`'s `SignInScreen` and `AccountWorkspace`, over the studio's adapter `web/studio/src/auth.tsx`) — never a template here (`HEADLESS_ONLY`).

| Module | What it is |
|---|---|
| `adapter.py` | allauth's adapters: an agent principal (`agent:<slug>`) never signs in by any route (password, code, IdP, passkey); sign-up follows `SIGNUP_OPEN`, except that an OpenID Connect IdP the operator configured provisions its people (single sign-on) |
| `providers.py` | `SOCIALACCOUNT_PROVIDERS` from the environment: one `openid_connect` app per IdP in `OIDC_PROVIDERS`, GitHub when `GITHUB_LOGIN_CLIENT_ID` is set; `OIDC_GROUP_MAP` parsed. Imports no model, so the settings read it |
| `groups.py` | The IdP's groups claim → Wagtail groups, at every sign-in through an IdP: mapped groups follow the claim, others are never touched, nobody becomes staff |
| `views.py` | `/admin/login/` and `/django-admin/login/`: a signed-out person is sent to the studio's sign-in (`LOGIN_URL`) with where they were going, so no admin form signs anyone in around a second factor |
| `models.py`, `tokens.py` | `UserToken` (`zer0u_…`): hashed (`tokens.HashedToken`, shared with `agents.AgentToken`), expiring, revoked rather than deleted, with **scopes** — `read` (GET, HEAD, OPTIONS and GraphQL queries) and `write` (everything else the person may do) |
| `auth.py` | `UserTokenAuthentication` for REST: the token's person, and a read-only token refused on anything but a read, before any view. GraphQL applies the same rule (`api/views.py`) |
| `services.py` | Issuing (90 days by default, 1 to 365 from the account menu, never-expiring only on the command line; a superuser's only when asked for), listing and revoking tokens |
| `api.py`, `serializers.py`, `urls.py` | `/api/v2/account/tokens/`: list, issue (from a signed-in session only — a token never issues another), revoke (a token may revoke itself) |
| `management/commands/user_token.py` | The operator's `manage.py user_token USERNAME --name … [--days N] [--read-only] [--superuser] [--list] [--revoke PREFIX]` |

## Signing in

The studio speaks allauth's headless **browser** API at `/_allauth/browser/v1/` (allauth documents it: its OpenAPI specification); `GET /api/v2/me` stays, for the person, their permissions and the CSRF cookie. What a person can do there, each a test in `tests/accounts/`:

- **A password**, by username or email (`test_signin.py`); agents refused; CSRF on every unsafe request.
- **An address verified before the first sign-in** (`ACCOUNT_EMAIL_VERIFICATION`, `mandatory` by default): by a code sent to it, in the screen that asked. An account an operator made verifies its address at its first sign-in; one with no address cannot sign in while verification is mandatory — give it one, or set `optional`. `seed_demo`'s person is verified already.
- **Sign-up** where `SIGNUP_OPEN` is true, the address verified by code (`test_signup.py`); a new account has no group and sees nothing until an operator (or the IdP's groups) gives it one.
- **A code by email** instead of a password (`ACCOUNT_LOGIN_BY_CODE_ENABLED`), and **a password reset by code**; a reset never says whether an address has an account.
- **Second factors** (`test_mfa.py`): TOTP (with recovery codes, made with the first factor) and passkeys (WebAuthn), which also sign in on their own — and where sign-up is open, a passkey instead of a password from the start (the address verified first; on while verification is mandatory). The tests use a software authenticator (`tests/accounts/authenticator.py`) that python-fido2 verifies like a device. Changing a factor or the password asks for the password (or a factor) again first — allauth's reauthentication, which a sign-in a while ago does not satisfy.
- **OpenID Connect IdPs and GitHub** (`test_providers.py`, a fake IdP and a fake GitHub, recorded in `tests/accounts/fixtures/fake_idp.json`): the studio's button POSTs to allauth, which redirects with state and PKCE; the IdP returns to `/accounts/oidc/<id>/login/callback/` (GitHub to `/accounts/github/login/callback/`), and allauth sends the person back to the studio. The IdP's access token is not kept.
- **The session list**: every session a person has, ended from the account menu. Sessions are recorded when they start, not touched on every request (`USERSESSIONS_TRACK_ACTIVITY` is off, for the reason authenticating writes nothing in a request).

## Settings and environment

| Variable | Default | What it sets |
|---|---|---|
| `SIGNUP_OPEN` | `false` | Whether anyone may sign up (and sign up through GitHub) |
| `ACCOUNT_EMAIL_VERIFICATION` | `mandatory` | `mandatory` (by code), `optional` or `none` (by link, to `/studio/account/verify-email/<key>`) |
| `ACCOUNT_LOGIN_BY_CODE_ENABLED` | `true` | Signing in with a code sent by email |
| `ACCOUNT_REAUTHENTICATION_TIMEOUT` | `300` | Seconds a confirmed password counts before a security change asks again |
| `PASSWORD_MIN_LENGTH` | `12` | The password policy's length; Django's similarity, common-password and numeric validators also apply |
| `SESSION_COOKIE_AGE`, `SESSION_EXPIRE_AT_BROWSER_CLOSE` | two weeks, `false` | The session policy (the cookie is HttpOnly and SameSite=Lax; Secure in production) |
| `MFA_WEBAUTHN_ALLOW_INSECURE_ORIGIN` | `false` (`true` in development) | Passkeys on plain http (localhost) |
| `OIDC_PROVIDERS` and `OIDC_<ID>_SERVER_URL`, `_CLIENT_ID`, `_CLIENT_SECRET`, `_NAME`, `_SCOPES`, `_PKCE` | none | One OpenID Connect IdP per id (`providers.py`); the callback to register at the IdP is `<origin>/accounts/oidc/<id>/login/callback/` |
| `OIDC_GROUP_MAP`, `OIDC_GROUPS_CLAIM` | none, `groups` | The IdP's groups → Wagtail groups (a JSON object) |
| `GITHUB_LOGIN_CLIENT_ID`, `GITHUB_LOGIN_CLIENT_SECRET` | none | Sign-in with GitHub (an OAuth app; callback `<origin>/accounts/github/login/callback/`) |

Email (codes, verification) goes through the platform's `EMAIL_BACKEND` (newsroom/README.md). No secret is logged: `ops.logging` redacts token shapes, and a missing variable is named in the startup error, never its value.

## API tokens

A person issues their own in the studio's account menu (**API tokens**): a name, 7 to 365 days, read-only or read and write; the token is shown once. The VS Code extension sends it (`Authorization: Bearer zer0u_…`, pasted with **zer0-CMS: Set platform token**) and is that person on REST and GraphQL. The extension's account tab lists and revokes tokens through its host; signing in, second factors and sessions stay in the studio, because a webview holds no browser session.
