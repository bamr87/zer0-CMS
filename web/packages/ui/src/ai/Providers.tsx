// Providers: every adapter in the platform's registry with its status —
// enabled, the default, whether a credential is set, its capabilities and its
// last health check. People who configure providers (`ai.change_providerconfig`)
// also edit one's configuration, test it, sync its models into the catalog and
// make it the default; a test and a sync are runs, followed live — one at a
// time, each request with its Idempotency-Key. A credential only ever goes in:
// the platform never sends one back, so this screen shows "set" or "not set"
// and its input starts empty every time. Home shows the default provider's
// status (ProviderStatus).
import { Alert, Badge, Button, Card, Checkbox, Drawer, Group, JsonInput, Loader, PasswordInput, Stack, Switch, Table, Text, TextInput, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { Provider } from '@zer0/api';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { fieldError, isRecord, newKey, once, oneClick, RunProgress, useCanConfigure, useProviders } from './shared';

type Check = 'test' | 'sync-models';

function health(provider: Provider) {
  const last = isRecord(provider.last_health) ? provider.last_health : {};
  if (!('ok' in last)) return <Badge color="gray" variant="light">unchecked</Badge>;
  return last.ok ? (
    <Badge color="teal" variant="light">healthy</Badge>
  ) : (
    <Badge color="red" variant="light" title={typeof last.error === 'string' ? last.error : undefined}>
      failing
    </Badge>
  );
}

function credential(provider: Provider) {
  if (provider.has_credential) return 'set';
  return provider.credential_source ? `not set — uses ${provider.credential_source}` : 'not set';
}

/** For Home: the default provider and its last check, and how many providers are on and failing. */
export function ProviderStatus() {
  const go = useGo();
  const providers = useProviders();
  const on = (providers.data?.results ?? []).filter((p) => p.enabled);
  const preferred = on.find((p) => p.is_default);
  const failing = on.filter((p) => isRecord(p.last_health) && p.last_health.ok === false).length;
  return (
    <Card withBorder>
      <Title order={4} mb="sm">
        AI providers
      </Title>
      {providers.isError ? <Text c="red">{errorText(providers.error)}</Text> : null}
      {providers.data ? (
        <Stack gap={6} aria-label="Provider status">
          <Group justify="space-between" wrap="nowrap">
            <Text size="sm">{preferred ? `Default: ${preferred.display_name || preferred.slug}` : 'No default chosen: the platform’s setting decides'}</Text>
            {preferred ? health(preferred) : null}
          </Group>
          <Text size="sm" c="dimmed">
            {on.length} enabled{failing ? ` · ${failing} failing its last check` : ''}
          </Text>
        </Stack>
      ) : null}
      <Button variant="light" mt="sm" onClick={() => go({ to: 'ai', section: 'providers' })}>
        Open the providers
      </Button>
    </Card>
  );
}

export function ProviderList() {
  const api = useApi();
  const qc = useQueryClient();
  const canConfigure = useCanConfigure();
  const providers = useProviders();
  const [editing, setEditing] = useState<Provider | null>(null);
  const [checks, setChecks] = useState<Record<string, number>>({});
  const refresh = () => void qc.invalidateQueries({ queryKey: ['ai'] });
  // One check at a time: every Test and Sync button waits while one is out, and a double click asks once.
  const check = useMutation({
    mutationFn: ({ provider, kind, key }: { provider: Provider; kind: Check; key: string }) => {
      const params = { params: { path: { public_id: provider.id }, header: once(key) } };
      return call(
        kind === 'test'
          ? api.POST('/api/v2/ai/providers/{public_id}/test/', params)
          : api.POST('/api/v2/ai/providers/{public_id}/sync-models/', params),
      );
    },
    onSuccess: ({ run }, { provider }) => setChecks((current) => ({ ...current, [provider.id]: run.id })),
  });
  const checking = (provider: Provider, kind: Check) => check.isPending && check.variables.provider.id === provider.id && check.variables.kind === kind;
  const start = (provider: Provider, kind: Check) => {
    if (!check.isPending) check.mutate({ provider, kind, key: newKey() });
  };
  const makeDefault = useMutation({
    mutationFn: (provider: Provider) => call(api.POST('/api/v2/ai/providers/{public_id}/set-default/', { params: { path: { public_id: provider.id } } })),
    onSuccess: (provider) => {
      notifications.show({ message: `${provider.display_name || provider.slug} is the default provider` });
      refresh();
    },
  });

  if (providers.isPending) return <Loader aria-label="Loading providers" />;
  if (providers.isError) return <Alert color="red">{errorText(providers.error)}</Alert>;
  const failure = check.error ?? makeDefault.error;
  return (
    <Stack>
      <Text size="sm" c="dimmed">
        {canConfigure
          ? 'Configure a provider, test it, sync its models and choose the default. A credential is stored encrypted and never shown again.'
          : 'The model providers the platform can use. People who configure providers change them.'}
      </Text>
      {failure ? <Alert color="red">{errorText(failure)}</Alert> : null}
      <Table aria-label="Providers">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Provider</Table.Th>
            <Table.Th>Status</Table.Th>
            <Table.Th>Credential</Table.Th>
            <Table.Th>Health</Table.Th>
            <Table.Th>Can</Table.Th>
            {canConfigure ? <Table.Th>Actions</Table.Th> : null}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {providers.data.results.map((p) => (
            <Table.Tr key={p.id}>
              <Table.Td>
                <Group gap={6}>
                  <Text fw={600}>{p.display_name || p.slug}</Text>
                  {p.is_default ? <Badge size="sm">default</Badge> : null}
                </Group>
                <Text size="xs" c="dimmed">
                  {p.slug}
                  {p.default_model ? ` · ${p.default_model}` : ''}
                </Text>
                {checks[p.id] ? <RunProgress runId={checks[p.id] ?? 0} onFinal={refresh} /> : null}
              </Table.Td>
              <Table.Td>
                <Badge color={p.enabled ? 'teal' : 'gray'} variant="light">
                  {p.enabled ? 'enabled' : 'disabled'}
                </Badge>
              </Table.Td>
              <Table.Td>{credential(p)}</Table.Td>
              <Table.Td>{health(p)}</Table.Td>
              <Table.Td>
                <Group gap={4}>
                  {p.capabilities.map((c) => (
                    <Badge key={c} size="xs" variant="outline">
                      {c}
                    </Badge>
                  ))}
                </Group>
              </Table.Td>
              {canConfigure ? (
                <Table.Td>
                  <Group gap={4}>
                    <Button size="xs" variant="default" onClick={() => setEditing(p)}>
                      Configure
                    </Button>
                    <Button size="xs" variant="default" loading={checking(p, 'test')} disabled={check.isPending} onClick={oneClick(() => start(p, 'test'))} aria-label={`Test ${p.slug}`}>
                      Test
                    </Button>
                    <Button
                      size="xs"
                      variant="default"
                      loading={checking(p, 'sync-models')}
                      disabled={check.isPending}
                      onClick={oneClick(() => start(p, 'sync-models'))}
                      aria-label={`Sync ${p.slug}'s models`}
                    >
                      Sync models
                    </Button>
                    {p.is_default ? null : (
                      <Button
                        size="xs"
                        variant="subtle"
                        disabled={!p.enabled || makeDefault.isPending}
                        loading={makeDefault.isPending && makeDefault.variables.id === p.id}
                        onClick={() => makeDefault.mutate(p)}
                        aria-label={`Make ${p.slug} the default`}
                      >
                        Make default
                      </Button>
                    )}
                  </Group>
                </Table.Td>
              ) : null}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <Drawer opened={editing !== null} onClose={() => setEditing(null)} position="right" size="md" title={editing ? `Configure ${editing.display_name || editing.slug}` : ''}>
        {editing ? <ProviderForm key={editing.id} provider={editing} onSaved={(saved) => setEditing(saved)} /> : null}
      </Drawer>
    </Stack>
  );
}

function ProviderForm({ provider, onSaved }: { provider: Provider; onSaved: (provider: Provider) => void }) {
  const api = useApi();
  const qc = useQueryClient();
  const [form, setForm] = useState({
    display_name: provider.display_name ?? '',
    enabled: provider.enabled ?? true,
    default_model: provider.default_model ?? '',
    base_url: provider.base_url ?? '',
    organization: provider.organization ?? '',
    project: provider.project ?? '',
    monthly_budget_usd: provider.monthly_budget_usd ?? '',
    extra: JSON.stringify(provider.extra ?? {}, null, 2),
  });
  const [secret, setSecret] = useState('');
  const [forget, setForget] = useState(false);
  const save = useMutation({
    mutationFn: () => {
      const body = {
        ...form,
        monthly_budget_usd: form.monthly_budget_usd.trim() || null,
        extra: JSON.parse(form.extra || '{}') as unknown,
        // The credential goes only when someone typed one, or asked to remove it.
        ...(secret ? { credential: secret } : forget ? { credential: '' } : {}),
      };
      return call(api.PATCH('/api/v2/ai/providers/{public_id}/', { params: { path: { public_id: provider.id } }, body }));
    },
    onSuccess: (saved) => {
      setSecret('');
      setForget(false);
      notifications.show({ message: `${saved.display_name || saved.slug} saved` });
      void qc.invalidateQueries({ queryKey: ['ai'] });
      onSaved(saved);
    },
  });
  const set = (key: keyof typeof form, value: string | boolean) => setForm((current) => ({ ...current, [key]: value }));
  const error = save.error;
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <Stack>
        <TextInput label="Name" value={form.display_name} onChange={(e) => set('display_name', e.currentTarget.value)} error={fieldError(error, 'display_name')} />
        <Switch
          label="Enabled"
          description={provider.is_default ? 'The default provider stays enabled; choose another default first.' : undefined}
          checked={form.enabled}
          disabled={provider.is_default}
          onChange={(e) => set('enabled', e.currentTarget.checked)}
        />
        <TextInput label="Default model" placeholder="the adapter's own" value={form.default_model} onChange={(e) => set('default_model', e.currentTarget.value)} error={fieldError(error, 'default_model')} />
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            Credential: {credential(provider)}
          </Text>
          <PasswordInput
            label={provider.has_credential ? 'Replace the credential' : 'Credential'}
            description="Stored encrypted and never shown again. Leave it empty to keep what is there."
            autoComplete="off"
            value={secret}
            onChange={(e) => setSecret(e.currentTarget.value)}
            error={fieldError(error, 'credential')}
          />
          {provider.has_credential ? (
            <Checkbox label="Remove the stored credential (the environment's is used again)" checked={forget} disabled={!!secret} onChange={(e) => setForget(e.currentTarget.checked)} />
          ) : null}
        </Stack>
        <TextInput label="Base URL" description="A row with its own base URL needs its own credential; changing it drops the stored one." value={form.base_url} onChange={(e) => set('base_url', e.currentTarget.value)} error={fieldError(error, 'base_url')} />
        <Group grow>
          <TextInput label="Organization" value={form.organization} onChange={(e) => set('organization', e.currentTarget.value)} />
          <TextInput label="Project" value={form.project} onChange={(e) => set('project', e.currentTarget.value)} />
        </Group>
        <TextInput label="Monthly budget (USD)" description="New runs are refused once it is spent this month; empty for none." inputMode="decimal" value={form.monthly_budget_usd} onChange={(e) => set('monthly_budget_usd', e.currentTarget.value)} error={fieldError(error, 'monthly_budget_usd')} />
        <JsonInput label="Adapter options" description="Only the options this adapter declares (timeout, max_retries, effort …)." autosize minRows={3} value={form.extra} onChange={(value) => set('extra', value)} validationError="This is not valid JSON" error={fieldError(error, 'extra')} />
        {error ? <Alert color="red">{errorText(error)}</Alert> : null}
        <Group justify="end">
          <Button type="submit" loading={save.isPending}>
            Save
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
