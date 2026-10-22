// Signing in: the studio's auth adapter. It calls the platform's session
// endpoints (content/api/session.py: me, login, logout) and nothing else, so
// PLAN G3 swaps them for django-allauth's headless API in this one file.
import { Alert, Button, Center, Loader, Paper, PasswordInput, Stack, TextInput, Title } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Me } from '@zer0/api';
import { call, errorText, useApi } from '@zer0/ui';
import { useState, type ReactNode } from 'react';

export type Person = NonNullable<Me['user']>;

export function useMe() {
  const api = useApi();
  return useQuery({ queryKey: ['me'], queryFn: () => call(api.GET('/api/v2/me')), staleTime: 60_000 });
}

export function useSignOut() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => call(api.POST('/api/v2/session/logout')),
    onSuccess: (me) => {
      qc.clear();
      qc.setQueryData(['me'], me);
    },
  });
}

/** Renders `children` for a signed-in person, the sign-in form otherwise. */
export function SignedIn({ children }: { children: (person: Person) => ReactNode }) {
  const me = useMe();
  if (me.isPending) {
    return (
      <Center h="100vh">
        <Loader />
      </Center>
    );
  }
  if (me.isError) return <Alert color="red">{errorText(me.error)}</Alert>;
  return me.data.user ? children(me.data.user) : <SignIn />;
}

function SignIn() {
  const api = useApi();
  const qc = useQueryClient();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const login = useMutation({
    mutationFn: () => call(api.POST('/api/v2/session/login', { body: { username, password } })),
    onSuccess: (me) => qc.setQueryData(['me'], me),
  });
  return (
    <Center h="100vh" p="md">
      <Paper p="xl" w={380} shadow="sm">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            login.mutate();
          }}
        >
          <Stack>
            <Title order={2}>Sign in to the studio</Title>
            {login.isError ? <Alert color="red">{errorText(login.error)}</Alert> : null}
            <TextInput label="Username" name="username" autoComplete="username" required value={username} onChange={(e) => setUsername(e.currentTarget.value)} />
            <PasswordInput
              label="Password"
              name="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.currentTarget.value)}
            />
            <Button type="submit" loading={login.isPending}>
              Sign in
            </Button>
          </Stack>
        </form>
      </Paper>
    </Center>
  );
}
