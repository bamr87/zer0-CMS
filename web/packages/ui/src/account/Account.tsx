// The account menu (PLAN G3): what a signed-in person manages about how they
// sign in — their password (changed, or set when they came through a provider),
// TOTP and its recovery codes, passkeys, the accounts of the providers they
// sign in with — the sessions they have open, ending any, and their API tokens.
// Every security change is allauth's, through the host (`useAuthHost`), and
// allauth asks for the password (or a factor) again before one goes through —
// a modal here, then the change is sent again. The tokens are the platform's
// own API (accounts/api.py) through the host's client, so a host with no
// browser session — the extension's webviews — still lists and revokes them.
import { Alert, Badge, Button, Checkbox, Code, CopyButton, Group, Modal, Paper, PasswordInput, Select, Stack, Table, Tabs, Text, TextInput, Title } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { createContext, use, useCallback, useState, type ReactNode } from 'react';

import { call, errorText } from '../call';
import { useApi, useAuthHost, type AccountSection } from '../context';
import {
  authData,
  authResult,
  needsReauthentication,
  type AuthFlow,
  type AuthHost,
  type AuthResponse,
  type Authenticator,
  type ProviderAccount,
  type UserSession,
} from './allauth';
import { useAuthConfig } from './SignIn';

const SECTIONS: { value: AccountSection; label: string }[] = [
  { value: 'security', label: 'Sign-in and security' },
  { value: 'sessions', label: 'Sessions' },
  { value: 'tokens', label: 'API tokens' },
];

const when = (seconds: number | null | undefined) => (seconds ? new Date(seconds * 1000).toLocaleString() : 'never');
const day = (iso: string | null | undefined, none = 'never') => (iso ? new Date(iso).toLocaleDateString() : none);
const messageOf = (error: unknown) => (error instanceof Error ? error.message : String(error));

export function AccountWorkspace({ section, onSection }: { section?: AccountSection; onSection?: (section: AccountSection) => void }) {
  const auth = useAuthHost();
  const [own, setOwn] = useState<AccountSection>(section ?? (auth ? 'security' : 'tokens'));
  const value = section ?? own;
  const pick = (next: AccountSection) => (onSection ? onSection(next) : setOwn(next));
  if (!auth) {
    return (
      <Stack>
        <Alert color="blue">Your password, second factors and sessions are managed in the studio. Here: your API tokens.</Alert>
        <Tokens />
      </Stack>
    );
  }
  return (
    <Reauthentication auth={auth}>
      <Tabs value={value} onChange={(next) => next && pick(next as AccountSection)} keepMounted={false}>
        <Tabs.List aria-label="Account">
          {SECTIONS.map((s) => (
            <Tabs.Tab key={s.value} value={s.value}>
              {s.label}
            </Tabs.Tab>
          ))}
        </Tabs.List>
        <Tabs.Panel value={value} pt="md">
          {value === 'security' ? <Security auth={auth} /> : value === 'sessions' ? <Sessions auth={auth} /> : <Tokens />}
        </Tabs.Panel>
      </Tabs>
    </Reauthentication>
  );
}

// ── Reauthentication ───────────────────────────────────────────────────────

type Guarded = <T>(run: () => Promise<AuthResponse<T>>) => Promise<AuthResponse<T>>;
const GuardContext = createContext<Guarded | null>(null);

/** Sends a change; when allauth asks who this is again, asks the person, then sends it once more. */
function useGuarded(): Guarded {
  const guarded = use(GuardContext);
  if (!guarded) throw new Error('useGuarded runs inside <Reauthentication>');
  return guarded;
}

function Reauthentication({ auth, children }: { auth: AuthHost; children: ReactNode }) {
  const [asking, setAsking] = useState<{ flow: AuthFlow; done: (ok: boolean) => void } | null>(null);
  const guarded = useCallback<Guarded>(
    async (run) => {
      const first = await run();
      const flow = needsReauthentication(first);
      if (!flow) return authResult(first);
      const ok = await new Promise<boolean>((done) => setAsking({ flow, done }));
      if (!ok) throw new Error('Not changed: who you are was not confirmed.');
      return authResult(await run());
    },
    [setAsking],
  );
  return (
    <GuardContext value={guarded}>
      {children}
      {asking ? (
        <ConfirmIdentity
          auth={auth}
          flow={asking.flow}
          onDone={(ok) => {
            asking.done(ok);
            setAsking(null);
          }}
        />
      ) : null}
    </GuardContext>
  );
}

function ConfirmIdentity({ auth, flow, onDone }: { auth: AuthHost; flow: AuthFlow; onDone: (ok: boolean) => void }) {
  const [secret, setSecret] = useState('');
  const byPassword = flow.id === 'reauthenticate';
  const confirm = useMutation({
    mutationFn: async () => authData(await auth.request('POST', byPassword ? '/auth/reauthenticate' : '/auth/2fa/reauthenticate', byPassword ? { password: secret } : { code: secret })),
    onSuccess: () => onDone(true),
  });
  return (
    <Modal opened onClose={() => onDone(false)} title="Confirm it is you" lockScroll={false}>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          confirm.mutate();
        }}
      >
        <Stack>
          <Text size="sm">This change needs your {byPassword ? 'password' : 'second factor'} again.</Text>
          {confirm.isError ? <Alert color="red">{messageOf(confirm.error)}</Alert> : null}
          {byPassword ? (
            <PasswordInput label="Password" autoComplete="current-password" required value={secret} onChange={(e) => setSecret(e.currentTarget.value)} />
          ) : (
            <TextInput label="Code" autoComplete="one-time-code" required value={secret} onChange={(e) => setSecret(e.currentTarget.value)} />
          )}
          <Button type="submit" loading={confirm.isPending}>
            Confirm
          </Button>
        </Stack>
      </form>
    </Modal>
  );
}

// ── Sign-in and security ───────────────────────────────────────────────────

function useAuthenticators(auth: AuthHost) {
  return useQuery({
    queryKey: ['auth', 'authenticators'],
    queryFn: async () => authData(await auth.request<Authenticator[]>('GET', '/account/authenticators')),
  });
}

function Security({ auth }: { auth: AuthHost }) {
  const config = useAuthConfig(auth);
  const session = useQuery({ queryKey: ['auth', 'session'], queryFn: async () => authData(await auth.request<{ user: { has_usable_password: boolean } }>('GET', '/auth/session')) });
  const authenticators = useAuthenticators(auth);
  const types = config.data?.mfa?.supported_types ?? [];
  const mine = authenticators.data ?? [];
  return (
    <Stack>
      <Password auth={auth} hasPassword={session.data?.user.has_usable_password ?? true} />
      {authenticators.isError ? <Alert color="red">{messageOf(authenticators.error)}</Alert> : null}
      {types.includes('totp') ? <Totp auth={auth} active={mine.some((a) => a.type === 'totp')} /> : null}
      {types.includes('recovery_codes') && mine.some((a) => a.type !== 'recovery_codes') ? (
        <RecoveryCodes auth={auth} codes={mine.find((a) => a.type === 'recovery_codes')} />
      ) : null}
      {types.includes('webauthn') ? <Passkeys auth={auth} keys={mine.filter((a) => a.type === 'webauthn')} /> : null}
      {config.data?.socialaccount?.providers.length ? <Providers auth={auth} /> : null}
    </Stack>
  );
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Paper withBorder p="md">
      <Stack gap="sm">
        <Title order={4}>{title}</Title>
        {children}
      </Stack>
    </Paper>
  );
}

function Password({ auth, hasPassword }: { auth: AuthHost; hasPassword: boolean }) {
  const guarded = useGuarded();
  const qc = useQueryClient();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const change = useMutation({
    mutationFn: () => guarded(() => auth.request('POST', '/account/password/change', hasPassword ? { current_password: current, new_password: next } : { new_password: next })),
    onSuccess: () => {
      setCurrent('');
      setNext('');
      void qc.invalidateQueries({ queryKey: ['auth', 'session'] });
    },
  });
  return (
    <Card title="Password">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          change.mutate();
        }}
      >
        <Stack gap="xs">
          {change.isError ? <Alert color="red">{messageOf(change.error)}</Alert> : null}
          {change.isSuccess ? <Alert color="green">Your password is changed.</Alert> : null}
          {hasPassword ? (
            <PasswordInput label="Current password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.currentTarget.value)} />
          ) : (
            <Text size="sm">You sign in through a provider; set a password to sign in without it too.</Text>
          )}
          <PasswordInput label="New password" autoComplete="new-password" required value={next} onChange={(e) => setNext(e.currentTarget.value)} />
          <Group>
            <Button type="submit" loading={change.isPending}>
              {hasPassword ? 'Change the password' : 'Set a password'}
            </Button>
          </Group>
        </Stack>
      </form>
    </Card>
  );
}

function Totp({ auth, active }: { auth: AuthHost; active: boolean }) {
  const guarded = useGuarded();
  const qc = useQueryClient();
  const [code, setCode] = useState('');
  const setup = useQuery({
    queryKey: ['auth', 'totp'],
    // Not active, allauth answers 404 with a fresh secret to activate; that is the answer this reads.
    queryFn: async () => (await auth.request<unknown>('GET', '/account/authenticators/totp')).meta as { secret?: string; totp_url?: string } | undefined,
    enabled: !active,
  });
  const refresh = () => {
    setCode('');
    void qc.invalidateQueries({ queryKey: ['auth'] });
  };
  const activate = useMutation({ mutationFn: () => guarded(() => auth.request('POST', '/account/authenticators/totp', { code })), onSuccess: refresh });
  const remove = useMutation({ mutationFn: () => guarded(() => auth.request('DELETE', '/account/authenticators/totp')), onSuccess: refresh });
  const { QrCode } = auth;
  if (active) {
    return (
      <Card title="Authenticator app (TOTP)">
        <Group justify="space-between">
          <Badge color="green">On</Badge>
          <Button variant="default" color="red" loading={remove.isPending} onClick={() => remove.mutate()}>
            Turn it off
          </Button>
        </Group>
        {remove.isError ? <Alert color="red">{messageOf(remove.error)}</Alert> : null}
      </Card>
    );
  }
  const secret = setup.data?.secret;
  return (
    <Card title="Authenticator app (TOTP)">
      <Text size="sm">Add this account to an authenticator app, then enter the code it shows. You get recovery codes with it.</Text>
      {secret && setup.data?.totp_url ? (
        <Group align="flex-start">
          {QrCode ? <QrCode value={setup.data.totp_url} size={160} /> : null}
          <Stack gap={4}>
            <Text size="sm">Setup key</Text>
            <Code aria-label="Setup key">{secret.match(/.{1,4}/g)?.join(' ')}</Code>
            <CopyButton value={secret}>{({ copied, copy }) => <Button size="xs" variant="default" onClick={copy}>{copied ? 'Copied' : 'Copy the key'}</Button>}</CopyButton>
          </Stack>
        </Group>
      ) : null}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          activate.mutate();
        }}
      >
        <Group align="flex-end">
          <TextInput label="Code from the app" autoComplete="one-time-code" required value={code} onChange={(e) => setCode(e.currentTarget.value)} />
          <Button type="submit" loading={activate.isPending}>
            Turn it on
          </Button>
        </Group>
      </form>
      {activate.isError ? <Alert color="red">{messageOf(activate.error)}</Alert> : null}
    </Card>
  );
}

function RecoveryCodes({ auth, codes }: { auth: AuthHost; codes?: Authenticator }) {
  const guarded = useGuarded();
  const qc = useQueryClient();
  const [shown, setShown] = useState<string[] | null>(null);
  const view = useMutation({
    mutationFn: async () => authData(await guarded(() => auth.request<Authenticator>('GET', '/account/authenticators/recovery-codes'))),
    onSuccess: (data) => setShown(data.unused_codes ?? []),
  });
  const regenerate = useMutation({
    mutationFn: async () => authData(await guarded(() => auth.request<Authenticator>('POST', '/account/authenticators/recovery-codes'))),
    onSuccess: (data) => {
      setShown(data.unused_codes ?? []);
      void qc.invalidateQueries({ queryKey: ['auth', 'authenticators'] });
    },
  });
  return (
    <Card title="Recovery codes">
      <Text size="sm">
        {codes ? `${codes.unused_code_count ?? 0} of ${codes.total_code_count ?? 0} unused.` : 'None yet.'} Each signs you in once when your other factors are not at hand.
      </Text>
      {view.isError || regenerate.isError ? <Alert color="red">{messageOf(view.error ?? regenerate.error)}</Alert> : null}
      {shown ? (
        <Code block aria-label="Recovery codes">
          {shown.join('\n')}
        </Code>
      ) : null}
      <Group>
        <Button variant="default" loading={view.isPending} onClick={() => view.mutate()}>
          Show them
        </Button>
        <Button variant="default" loading={regenerate.isPending} onClick={() => regenerate.mutate()}>
          Make new ones
        </Button>
      </Group>
    </Card>
  );
}

function Passkeys({ auth, keys }: { auth: AuthHost; keys: Authenticator[] }) {
  const guarded = useGuarded();
  const qc = useQueryClient();
  const [name, setName] = useState('');
  const refresh = () => void qc.invalidateQueries({ queryKey: ['auth', 'authenticators'] });
  const add = useMutation({
    mutationFn: async () => {
      const offered = authData(await guarded(() => auth.request<{ creation_options: unknown }>('GET', '/account/authenticators/webauthn?passwordless')));
      const credential = await auth.passkeys?.create(offered.creation_options);
      return guarded(() => auth.request('POST', '/account/authenticators/webauthn', { name, credential }));
    },
    onSuccess: () => {
      setName('');
      refresh();
    },
  });
  const remove = useMutation({ mutationFn: (id: number) => guarded(() => auth.request('DELETE', '/account/authenticators/webauthn', { authenticators: [id] })), onSuccess: refresh });
  return (
    <Card title="Passkeys">
      <Text size="sm">A passkey signs you in on its own, and is a second factor after your password.</Text>
      {keys.length ? (
        <Table>
          <Table.Tbody>
            {keys.map((key) => (
              <Table.Tr key={key.id}>
                <Table.Td>{key.name}</Table.Td>
                <Table.Td>added {when(key.created_at)}</Table.Td>
                <Table.Td>last used {when(key.last_used_at)}</Table.Td>
                <Table.Td>
                  <Button size="xs" variant="default" color="red" onClick={() => key.id !== undefined && remove.mutate(key.id)}>
                    Remove {key.name}
                  </Button>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      ) : null}
      {add.isError || remove.isError ? <Alert color="red">{messageOf(add.error ?? remove.error)}</Alert> : null}
      {auth.passkeys ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            add.mutate();
          }}
        >
          <Group align="flex-end">
            <TextInput label="Name it" placeholder="This laptop" required value={name} onChange={(e) => setName(e.currentTarget.value)} />
            <Button type="submit" loading={add.isPending}>
              Add a passkey
            </Button>
          </Group>
        </form>
      ) : (
        <Text size="sm">This window cannot make a passkey.</Text>
      )}
    </Card>
  );
}

function Providers({ auth }: { auth: AuthHost }) {
  const config = useAuthConfig(auth);
  const qc = useQueryClient();
  const accounts = useQuery({ queryKey: ['auth', 'providers'], queryFn: async () => authData(await auth.request<ProviderAccount[]>('GET', '/account/providers')) });
  const disconnect = useMutation({
    mutationFn: async (account: ProviderAccount) => authResult(await auth.request('DELETE', '/account/providers', { provider: account.provider.id, account: account.uid })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['auth', 'providers'] }),
  });
  const connected = accounts.data ?? [];
  return (
    <Card title="Sign in with">
      {disconnect.isError ? <Alert color="red">{messageOf(disconnect.error)}</Alert> : null}
      {connected.map((account) => (
        <Group key={`${account.provider.id}:${account.uid}`} justify="space-between">
          <Text size="sm">
            {account.provider.name}: {account.display}
          </Text>
          <Button size="xs" variant="default" onClick={() => disconnect.mutate(account)}>
            Disconnect {account.provider.name}
          </Button>
        </Group>
      ))}
      <Group>
        {(config.data?.socialaccount?.providers ?? [])
          .filter((provider) => !connected.some((account) => account.provider.id === provider.id))
          .map((provider) => (
            <Button key={provider.id} size="xs" variant="default" onClick={() => auth.redirectToProvider(provider.id, 'connect')}>
              Connect {provider.name}
            </Button>
          ))}
      </Group>
    </Card>
  );
}

// ── Sessions ───────────────────────────────────────────────────────────────

function Sessions({ auth }: { auth: AuthHost }) {
  const qc = useQueryClient();
  const sessions = useQuery({ queryKey: ['auth', 'sessions'], queryFn: async () => authData(await auth.request<UserSession[]>('GET', '/auth/sessions')) });
  const end = useMutation({
    mutationFn: async (ids: number[]) => authData(await auth.request<UserSession[]>('DELETE', '/auth/sessions', { sessions: ids })),
    onSuccess: (left) => qc.setQueryData(['auth', 'sessions'], left),
  });
  if (sessions.isError) return <Alert color="red">{messageOf(sessions.error)}</Alert>;
  const rows = sessions.data ?? [];
  const others = rows.filter((s) => !s.is_current).map((s) => s.id);
  return (
    <Stack>
      <Text size="sm">Where you are signed in. Ending a session signs that browser out.</Text>
      {end.isError ? <Alert color="red">{messageOf(end.error)}</Alert> : null}
      <Table aria-label="Sessions">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Browser</Table.Th>
            <Table.Th>Address</Table.Th>
            <Table.Th>Signed in</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((s) => (
            <Table.Tr key={s.id}>
              <Table.Td>{s.user_agent || 'unknown'}</Table.Td>
              <Table.Td>{s.ip}</Table.Td>
              <Table.Td>{when(s.created_at)}</Table.Td>
              <Table.Td>
                {s.is_current ? (
                  <Badge>This one</Badge>
                ) : (
                  <Button size="xs" variant="default" onClick={() => end.mutate([s.id])}>
                    End
                  </Button>
                )}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {others.length > 1 ? (
        <Group>
          <Button variant="default" color="red" loading={end.isPending} onClick={() => end.mutate(others)}>
            End every other session
          </Button>
        </Group>
      ) : null}
    </Stack>
  );
}

// ── API tokens (the platform's own API) ────────────────────────────────────

const DAYS = [
  { value: '7', label: '7 days' },
  { value: '30', label: '30 days' },
  { value: '90', label: '90 days' },
  { value: '365', label: 'A year' },
];

export function Tokens() {
  const api = useApi();
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ['me'], queryFn: () => call(api.GET('/api/v2/me')), staleTime: 60_000 });
  const tokens = useQuery({ queryKey: ['account', 'tokens'], queryFn: () => call(api.GET('/api/v2/account/tokens/')) });
  const [name, setName] = useState('');
  const [days, setDays] = useState('90');
  const [readOnly, setReadOnly] = useState(false);
  const [everything, setEverything] = useState(false);
  const [raw, setRaw] = useState<string | null>(null);
  const superuser = Boolean(me.data?.user?.is_superuser);
  const issue = useMutation({
    mutationFn: () =>
      call(
        api.POST('/api/v2/account/tokens/', {
          body: { name, days: Number(days), scopes: readOnly ? ['read'] : ['read', 'write'], superuser: superuser && everything },
        }),
      ),
    onSuccess: (issued) => {
      setRaw(issued.raw);
      setName('');
      void qc.invalidateQueries({ queryKey: ['account', 'tokens'] });
    },
  });
  const revoke = useMutation({
    mutationFn: (id: string) => call(api.DELETE('/api/v2/account/tokens/{public_id}/', { params: { path: { public_id: id } } })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['account', 'tokens'] }),
  });
  return (
    <Stack>
      <Text size="sm">A token lets a client that is not a browser — the VS Code extension, a script — act as you. Paste it into the extension with “zer0-CMS: Set platform token”.</Text>
      {raw ? (
        <Alert color="green" title="Your new token — copy it now; it is not shown again">
          <Group>
            <Code aria-label="New token">{raw}</Code>
            <CopyButton value={raw}>{({ copied, copy }) => <Button size="xs" onClick={copy}>{copied ? 'Copied' : 'Copy'}</Button>}</CopyButton>
            <Button size="xs" variant="default" onClick={() => setRaw(null)}>
              Done
            </Button>
          </Group>
        </Alert>
      ) : null}
      <Paper withBorder p="md">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            issue.mutate();
          }}
        >
          <Stack gap="xs">
            {issue.isError ? <Alert color="red">{errorText(issue.error)}</Alert> : null}
            <Group align="flex-end">
              <TextInput label="Where it is used" placeholder="VS Code on my laptop" required value={name} onChange={(e) => setName(e.currentTarget.value)} />
              <Select label="Expires after" data={DAYS} value={days} allowDeselect={false} onChange={(v) => setDays(v ?? '90')} />
            </Group>
            <Checkbox label="Read only — it cannot change anything" checked={readOnly} onChange={(e) => setReadOnly(e.currentTarget.checked)} />
            {superuser ? (
              <Checkbox
                label="I am a superuser: this token carries every permission I have"
                checked={everything}
                onChange={(e) => setEverything(e.currentTarget.checked)}
              />
            ) : null}
            <Group>
              <Button type="submit" loading={issue.isPending}>
                Issue a token
              </Button>
            </Group>
          </Stack>
        </form>
      </Paper>
      {tokens.isError ? <Alert color="red">{errorText(tokens.error)}</Alert> : null}
      {revoke.isError ? <Alert color="red">{errorText(revoke.error)}</Alert> : null}
      <Table aria-label="API tokens">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Name</Table.Th>
            <Table.Th>Starts with</Table.Th>
            <Table.Th>May</Table.Th>
            <Table.Th>Expires</Table.Th>
            <Table.Th>Last used</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {(tokens.data ?? []).map((token) => (
            <Table.Tr key={token.id}>
              <Table.Td>
                {token.name} {token.current ? <Badge size="xs">This one</Badge> : null}
              </Table.Td>
              <Table.Td>
                <Code>{token.prefix}…</Code>
              </Table.Td>
              <Table.Td>{token.scopes.includes('write') ? 'read and write' : 'read'}</Table.Td>
              <Table.Td>{day(token.expires_at)}</Table.Td>
              <Table.Td>{day(token.last_used_at)}</Table.Td>
              <Table.Td>
                {token.state === 'active' ? (
                  <Button size="xs" variant="default" color="red" onClick={() => revoke.mutate(token.id)}>
                    Revoke {token.name}
                  </Button>
                ) : (
                  <Badge color="gray">{token.state}</Badge>
                )}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}
