// The sign-in screen (PLAN G3): everything a signed-out person can do, over
// django-allauth's headless API from the host (`useAuthHost`) — a password by
// username or email, a code sent to one's address, a passkey, an OpenID
// Connect IdP or GitHub (whichever allauth's configuration offers), sign-up
// where the deployment opened it — with a password or a passkey — and a
// password reset. allauth answers each
// step with the next one (a second factor, a code to verify an address, a
// reset code), so the screen follows the flow allauth says is pending and the
// person finishes where they started. Nothing here decides who may sign in:
// allauth does, and its sentences are shown as it wrote them.
import { Alert, Anchor, Button, Center, Divider, Group, Loader, Paper, PasswordInput, Stack, Text, TextInput, Title } from '@mantine/core';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';

import { useAuthHost } from '../context';
import { AuthError, authData, authResult, pendingFlow, type AuthConfig, type AuthFlow, type AuthHost, type AuthResponse } from './allauth';

/** Where a signed-out person arrived from: a link in an email, or back from an IdP. */
export interface Arrival {
  /** A verification key from an email's link (when verification is by link). */
  verifyKey?: string;
  /** A password-reset key from an email's link (when reset is by link). */
  resetKey?: string;
  /** What allauth said when a provider sign-in did not finish (`?error=`). */
  providerError?: string;
}

type Mode = 'password' | 'code' | 'signup' | 'reset';

export function useAuthConfig(auth: AuthHost | undefined) {
  return useQuery({
    queryKey: ['auth', 'config'],
    queryFn: async () => authData(await (auth as AuthHost).request<AuthConfig>('GET', '/config')),
    enabled: Boolean(auth),
    staleTime: 5 * 60_000,
  });
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function Problem({ error }: { error: unknown }) {
  return error ? <Alert color="red">{messageOf(error)}</Alert> : null;
}

function Form({ onSubmit, children }: { onSubmit: () => void; children: ReactNode }) {
  return (
    <form
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <Stack>{children}</Stack>
    </form>
  );
}

/** Renders the sign-in screen; `onSignedIn` runs once allauth says the person is signed in. */
export function SignInScreen({ onSignedIn, arrival = {} }: { onSignedIn: () => void; arrival?: Arrival }) {
  const auth = useAuthHost();
  const config = useAuthConfig(auth);
  const [mode, setMode] = useState<Mode>(arrival.resetKey ? 'reset' : 'password');
  const [step, setStep] = useState<AuthFlow | undefined>();
  const [notice, setNotice] = useState<string | undefined>(arrival.providerError ? `Signing in through the provider did not finish (${arrival.providerError}).` : undefined);
  // A flow left pending — a second factor asked for, then the page reloaded — is picked up where it was.
  const session = useQuery({
    queryKey: ['auth', 'session', 'pending'],
    queryFn: async () => (auth as AuthHost).request('GET', '/auth/session'),
    enabled: Boolean(auth),
  });
  const pendingOnLoad = session.data ? pendingFlow(session.data) : undefined;
  const current = step ?? pendingOnLoad;

  /** Whatever allauth answered: signed in, the next step, or (as an error) why not. */
  const answer = (response: AuthResponse) => {
    if (response.status === 200 && response.meta?.is_authenticated) {
      onSignedIn();
      return;
    }
    const next = pendingFlow(response);
    setStep(next);
    if (!next && response.status === 401) setNotice('Done. Sign in to go on.');
  };

  if (!auth) {
    return <Alert color="yellow">Signing in happens in the studio, in a browser. Here, set the platform token from the account menu there.</Alert>;
  }
  if (config.isPending || session.isPending) {
    return (
      <Center h="100vh">
        <Loader />
      </Center>
    );
  }
  if (config.isError) return <Alert color="red">{messageOf(config.error)}</Alert>;
  const offers = config.data;
  const startOver = async () => {
    await auth.request('DELETE', '/auth/session');
    setStep(undefined);
    setMode('password');
    void session.refetch();
  };
  return (
    <Center mih="100vh" p="md">
      <Paper p="xl" w={420} shadow="sm">
        <Stack>
          <Title order={2}>{TITLES[current?.id ?? mode] ?? 'Sign in to the studio'}</Title>
          {notice ? <Alert color="blue">{notice}</Alert> : null}
          {arrival.verifyKey && !current ? <VerifyByLink auth={auth} verifyKey={arrival.verifyKey} answer={answer} /> : null}
          {current ? (
            <Step auth={auth} flow={current} answer={answer} startOver={startOver} />
          ) : mode === 'password' ? (
            <PasswordSignIn auth={auth} offers={offers} answer={answer} setMode={setMode} />
          ) : mode === 'code' ? (
            <CodeRequest auth={auth} answer={answer} back={() => setMode('password')} />
          ) : mode === 'signup' ? (
            <SignUp auth={auth} answer={answer} back={() => setMode('password')} />
          ) : (
            <ResetRequest auth={auth} resetKey={arrival.resetKey} answer={answer} back={() => setMode('password')} />
          )}
        </Stack>
      </Paper>
    </Center>
  );
}

const TITLES: Record<string, string> = {
  password: 'Sign in to the studio',
  code: 'Sign in with a code',
  signup: 'Create an account',
  reset: 'Reset your password',
  mfa_authenticate: 'Your second factor',
  verify_email: 'Verify your address',
  login_by_code: 'Enter your sign-in code',
  password_reset_by_code: 'Choose a new password',
  provider_signup: 'Finish signing up',
  mfa_signup_webauthn: 'Make your passkey',
};

interface Props {
  auth: AuthHost;
  answer: (response: AuthResponse) => void;
}

function useAuthMutation<V>(run: (variables: V) => Promise<AuthResponse>, answer: (response: AuthResponse) => void) {
  return useMutation({ mutationFn: async (variables: V) => authResult(await run(variables)), onSuccess: answer });
}

function PasswordSignIn({ auth, offers, answer, setMode }: Props & { offers: AuthConfig; setMode: (mode: Mode) => void }) {
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const signIn = useAuthMutation(
    () => auth.request('POST', '/auth/login', { [login.includes('@') ? 'email' : 'username']: login, password }),
    answer,
  );
  const passkey = useAuthMutation(async () => {
    const options = authData(await auth.request<{ request_options: unknown }>('GET', '/auth/webauthn/login'));
    const credential = await auth.passkeys?.get(options.request_options);
    return auth.request('POST', '/auth/webauthn/login', { credential });
  }, answer);
  const providers = offers.socialaccount?.providers ?? [];
  return (
    <>
      <Form onSubmit={() => signIn.mutate(undefined)}>
        <Problem error={signIn.error} />
        <TextInput label="Username or email" name="username" autoComplete="username" required value={login} onChange={(e) => setLogin(e.currentTarget.value)} />
        <PasswordInput label="Password" name="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.currentTarget.value)} />
        <Button type="submit" loading={signIn.isPending}>
          Sign in
        </Button>
      </Form>
      <Group gap="xs" justify="space-between">
        {offers.account.login_by_code_enabled ? (
          <Anchor component="button" type="button" size="sm" onClick={() => setMode('code')}>
            Email me a sign-in code
          </Anchor>
        ) : null}
        <Anchor component="button" type="button" size="sm" onClick={() => setMode('reset')}>
          Forgot your password?
        </Anchor>
      </Group>
      {(offers.mfa?.passkey_login_enabled && auth.passkeys) || providers.length ? <Divider label="or" /> : null}
      <Problem error={passkey.error} />
      {offers.mfa?.passkey_login_enabled && auth.passkeys ? (
        <Button variant="default" loading={passkey.isPending} onClick={() => passkey.mutate(undefined)}>
          Sign in with a passkey
        </Button>
      ) : null}
      {providers.map((provider) => (
        <Button key={provider.id} variant="default" onClick={() => auth.redirectToProvider(provider.id, 'login')}>
          Continue with {provider.name}
        </Button>
      ))}
      {offers.account.is_open_for_signup ? (
        <Text size="sm" ta="center">
          New here?{' '}
          <Anchor component="button" type="button" size="sm" onClick={() => setMode('signup')}>
            Create an account
          </Anchor>
        </Text>
      ) : null}
    </>
  );
}

function Back({ onClick }: { onClick: () => void }) {
  return (
    <Anchor component="button" type="button" size="sm" onClick={onClick}>
      Back to signing in
    </Anchor>
  );
}

function CodeRequest({ auth, answer, back }: Props & { back: () => void }) {
  const [email, setEmail] = useState('');
  const ask = useAuthMutation(() => auth.request('POST', '/auth/code/request', { email }), answer);
  return (
    <Form onSubmit={() => ask.mutate(undefined)}>
      <Text size="sm">We send a code to your address; enter it on the next screen.</Text>
      <Problem error={ask.error} />
      <TextInput label="Email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.currentTarget.value)} />
      <Button type="submit" loading={ask.isPending}>
        Send me a code
      </Button>
      <Back onClick={back} />
    </Form>
  );
}

function SignUp({ auth, answer, back }: Props & { back: () => void }) {
  const [form, setForm] = useState({ email: '', username: '', password: '' });
  const signUp = useAuthMutation(() => auth.request('POST', '/auth/signup', form), answer);
  // Instead of a password, a passkey: allauth verifies the address first, then asks for the passkey (`mfa_signup_webauthn`).
  const byPasskey = useAuthMutation(() => auth.request('POST', '/auth/webauthn/signup', { email: form.email, username: form.username }), answer);
  const about = (param: string) => (signUp.error instanceof AuthError ? signUp.error.about(param) : undefined);
  const field = (name: keyof typeof form) => ({ value: form[name], onChange: (e: { currentTarget: { value: string } }) => setForm({ ...form, [name]: e.currentTarget.value }), error: about(name) });
  return (
    <Form onSubmit={() => signUp.mutate(undefined)}>
      {signUp.error instanceof AuthError && !signUp.error.errors.some((e) => e.param) ? <Problem error={signUp.error} /> : null}
      <TextInput label="Email" type="email" autoComplete="email" required {...field('email')} />
      <TextInput label="Username" autoComplete="username" required {...field('username')} />
      <PasswordInput label="Password" autoComplete="new-password" required {...field('password')} />
      <Button type="submit" loading={signUp.isPending}>
        Create the account
      </Button>
      {auth.passkeys ? (
        <>
          <Problem error={byPasskey.error} />
          <Button variant="default" loading={byPasskey.isPending} disabled={!form.email || !form.username} onClick={() => byPasskey.mutate(undefined)}>
            Use a passkey instead of a password
          </Button>
        </>
      ) : null}
      <Back onClick={back} />
    </Form>
  );
}

function PasskeySignUp({ auth, answer }: Props) {
  const [name, setName] = useState('');
  const make = useAuthMutation(async () => {
    const offered = authData(await auth.request<{ creation_options: unknown }>('GET', '/auth/webauthn/signup'));
    const credential = await auth.passkeys?.create(offered.creation_options);
    return auth.request('PUT', '/auth/webauthn/signup', { name, credential });
  }, answer);
  if (!auth.passkeys) return <Alert color="yellow">This window cannot make a passkey; finish in a browser that can.</Alert>;
  return (
    <Form onSubmit={() => make.mutate(undefined)}>
      <Text size="sm">Your address is verified. Now make the passkey you will sign in with.</Text>
      <Problem error={make.error} />
      <TextInput label="Name it" placeholder="This laptop" required value={name} onChange={(e) => setName(e.currentTarget.value)} />
      <Button type="submit" loading={make.isPending}>
        Make the passkey
      </Button>
    </Form>
  );
}

function ResetRequest({ auth, resetKey, answer, back }: Props & { resetKey?: string; back: () => void }) {
  const [email, setEmail] = useState('');
  const ask = useAuthMutation(() => auth.request('POST', '/auth/password/request', { email }), answer);
  if (resetKey) return <NewPassword auth={auth} resetKey={resetKey} answer={answer} />;
  return (
    <Form onSubmit={() => ask.mutate(undefined)}>
      <Text size="sm">We send a code to your address if it has an account.</Text>
      <Problem error={ask.error} />
      <TextInput label="Email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.currentTarget.value)} />
      <Button type="submit" loading={ask.isPending}>
        Send me a reset code
      </Button>
      <Back onClick={back} />
    </Form>
  );
}

function NewPassword({ auth, resetKey, answer }: Props & { resetKey?: string }) {
  const [key, setKey] = useState(resetKey ?? '');
  const [password, setPassword] = useState('');
  const reset = useAuthMutation(() => auth.request('POST', '/auth/password/reset', { key, password }), answer);
  const about = (param: string) => (reset.error instanceof AuthError ? reset.error.about(param) : undefined);
  return (
    <Form onSubmit={() => reset.mutate(undefined)}>
      {reset.error instanceof AuthError && !about('password') ? <Problem error={reset.error} /> : null}
      {resetKey ? null : <TextInput label="Code" autoComplete="one-time-code" required value={key} onChange={(e) => setKey(e.currentTarget.value)} />}
      <PasswordInput label="New password" autoComplete="new-password" required value={password} error={about('password')} onChange={(e) => setPassword(e.currentTarget.value)} />
      <Button type="submit" loading={reset.isPending}>
        Set the password
      </Button>
    </Form>
  );
}

function VerifyByLink({ auth, verifyKey, answer }: Props & { verifyKey: string }) {
  const verify = useAuthMutation(() => auth.request('POST', '/auth/email/verify', { key: verifyKey }), answer);
  const sent = useRef(false);
  useEffect(() => {
    if (!sent.current) {
      sent.current = true;
      verify.mutate(undefined);
    }
  }, [verify]);
  if (verify.isError) return <Problem error={verify.error} />;
  return verify.isSuccess ? <Alert color="green">Your address is verified.</Alert> : <Loader size="sm" />;
}

/** The step allauth says is pending, and what finishes it. */
function Step({ auth, flow, answer, startOver }: Props & { flow: AuthFlow; startOver: () => void }) {
  let body: ReactNode;
  if (flow.id === 'mfa_authenticate') body = <SecondFactor auth={auth} flow={flow} answer={answer} />;
  else if (flow.id === 'verify_email') body = <CodeStep auth={auth} answer={answer} path="/auth/email/verify" field="key" hint="We sent a code to your address." resend="/auth/email/verify/resend" />;
  else if (flow.id === 'login_by_code') body = <CodeStep auth={auth} answer={answer} path="/auth/code/confirm" field="code" hint="We sent a sign-in code to your address." />;
  else if (flow.id === 'password_reset_by_code') body = <NewPassword auth={auth} answer={answer} />;
  else if (flow.id === 'provider_signup') body = <ProviderSignUp auth={auth} answer={answer} />;
  else if (flow.id === 'mfa_signup_webauthn') body = <PasskeySignUp auth={auth} answer={answer} />;
  else body = <Text>allauth is waiting for a step this screen does not know ({flow.id}).</Text>;
  return (
    <>
      {body}
      <Anchor component="button" type="button" size="sm" onClick={startOver}>
        Start over
      </Anchor>
    </>
  );
}

function CodeStep({ auth, answer, path, field, hint, resend }: Props & { path: string; field: 'key' | 'code'; hint: string; resend?: string }) {
  const [code, setCode] = useState('');
  const confirm = useAuthMutation(() => auth.request('POST', path, { [field]: code }), answer);
  const again = useMutation({ mutationFn: async () => authResult(await auth.request('POST', resend ?? path)) });
  return (
    <Form onSubmit={() => confirm.mutate(undefined)}>
      <Text size="sm">{hint}</Text>
      <Problem error={confirm.error ?? again.error} />
      <TextInput label="Code" autoComplete="one-time-code" required value={code} onChange={(e) => setCode(e.currentTarget.value)} />
      <Button type="submit" loading={confirm.isPending}>
        Go on
      </Button>
      {resend ? (
        <Anchor component="button" type="button" size="sm" onClick={() => again.mutate()}>
          {again.isSuccess ? 'Sent again' : 'Send the code again'}
        </Anchor>
      ) : null}
    </Form>
  );
}

function SecondFactor({ auth, flow, answer }: Props & { flow: AuthFlow }) {
  const [code, setCode] = useState('');
  const types = flow.types ?? [];
  const confirm = useAuthMutation(() => auth.request('POST', '/auth/2fa/authenticate', { code }), answer);
  const passkey = useAuthMutation(async () => {
    const options = authData(await auth.request<{ request_options: unknown }>('GET', '/auth/webauthn/authenticate'));
    const credential = await auth.passkeys?.get(options.request_options);
    return auth.request('POST', '/auth/webauthn/authenticate', { credential });
  }, answer);
  const codes = types.includes('totp') || types.includes('recovery_codes');
  return (
    <>
      <Problem error={confirm.error ?? passkey.error} />
      {codes ? (
        <Form onSubmit={() => confirm.mutate(undefined)}>
          <TextInput
            label={types.includes('totp') ? 'The code from your authenticator app, or a recovery code' : 'A recovery code'}
            name="code"
            autoComplete="one-time-code"
            required
            value={code}
            onChange={(e) => setCode(e.currentTarget.value)}
          />
          <Button type="submit" loading={confirm.isPending}>
            Verify
          </Button>
        </Form>
      ) : null}
      {types.includes('webauthn') && auth.passkeys ? (
        <Button variant="default" loading={passkey.isPending} onClick={() => passkey.mutate(undefined)}>
          Use a passkey
        </Button>
      ) : null}
    </>
  );
}

function ProviderSignUp({ auth, answer }: Props) {
  const [form, setForm] = useState({ email: '', username: '' });
  const finish = useAuthMutation(() => auth.request('POST', '/auth/provider/signup', form), answer);
  const about = (param: string) => (finish.error instanceof AuthError ? finish.error.about(param) : undefined);
  return (
    <Form onSubmit={() => finish.mutate(undefined)}>
      <Text size="sm">Your provider signed you in; choose how you appear here.</Text>
      <TextInput label="Email" type="email" required value={form.email} error={about('email')} onChange={(e) => setForm({ ...form, email: e.currentTarget.value })} />
      <TextInput label="Username" required value={form.username} error={about('username')} onChange={(e) => setForm({ ...form, username: e.currentTarget.value })} />
      <Button type="submit" loading={finish.isPending}>
        Finish
      </Button>
    </Form>
  );
}
