// Channels: where a site's content goes — a LinkedIn page or profile, a
// WordPress site, a GitHub repository (as pull requests), a newsletter — and
// whether each can publish now: connected, armed by a person, armed for its
// kind by the deployment. A channel's panel changes its settings, takes a new
// credential (typed into an empty field, sent once, never shown), connects a
// LinkedIn account through LinkedIn's consent screen, asks the target whether
// the credential works, arms or disarms it, and holds its ledger file —
// downloaded byte for byte as every lane writes it, or imported from the
// extension's or a site's CI so what they published never goes twice.
// Removing a channel asks first, saying how many posts go with it; the
// platform refuses while its ledger holds anything (disconnect it instead).
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Code,
  FileButton,
  Group,
  Loader,
  Modal,
  PasswordInput,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { DistributionChannel, DistributionKind } from '@zer0/api';
import { useState } from 'react';

import { oneClick } from '../ai/shared';
import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { KINDS, kindLabel, SETTINGS, secretLabel, useChannel, useChannels, when } from './shared';

type Settings = Record<string, string>;

function stateOf(channel: DistributionChannel) {
  if (channel.connecting) return { label: 'connecting…', color: 'blue' };
  if (!channel.has_credential && channel.kind !== 'email') return { label: 'not connected', color: 'gray' };
  if (channel.last_error) return { label: 'needs attention', color: 'red' };
  if (channel.armed && channel.deployment_armed) return { label: 'armed', color: 'green' };
  return { label: 'connected, not armed', color: 'yellow' };
}

export function Channels({ siteId }: { siteId?: number }) {
  const go = useGo();
  const channels = useChannels(siteId);
  const [adding, setAdding] = useState(false);
  if (channels.isPending) return <Loader />;
  if (channels.isError) return <Alert color="red">{errorText(channels.error)}</Alert>;
  return (
    <Stack>
      <Group justify="flex-end">
        <Button variant={adding ? 'light' : 'filled'} onClick={() => setAdding((on) => !on)}>
          {adding ? 'Close the form' : 'New channel'}
        </Button>
      </Group>
      {adding ? <NewChannel siteId={siteId} onDone={(id) => go({ to: 'channel', id })} /> : null}
      {channels.data.results.length === 0 ? (
        <Text c="dimmed">No channels yet.</Text>
      ) : (
        <Table highlightOnHover aria-label="Channels">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Channel</Table.Th>
              <Table.Th>Kind</Table.Th>
              <Table.Th>Site</Table.Th>
              <Table.Th>Publishes as</Table.Th>
              <Table.Th>State</Table.Th>
              <Table.Th>Auto draft</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {channels.data.results.map((c) => (
              <Table.Tr key={c.id}>
                <Table.Td>
                  <Anchor component="button" type="button" onClick={() => go({ to: 'channel', id: c.id })}>
                    {c.name}
                  </Anchor>
                </Table.Td>
                <Table.Td>{c.kind_label}</Table.Td>
                <Table.Td>{c.site_name}</Table.Td>
                <Table.Td>{c.account || c.newsletter_name || '—'}</Table.Td>
                <Table.Td>
                  <Badge color={stateOf(c).color} variant="light">
                    {stateOf(c).label}
                  </Badge>
                </Table.Td>
                <Table.Td>{c.auto_draft ? 'on' : 'off'}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}

function SettingsFields({ kind, values, onChange }: { kind: DistributionKind; values: Settings; onChange: (v: Settings) => void }) {
  return (
    <>
      {SETTINGS[kind].map((field) => (
        <TextInput
          key={field.name}
          label={field.label}
          description={field.description}
          value={values[field.name] ?? ''}
          onChange={(e) => onChange({ ...values, [field.name]: e.currentTarget.value })}
        />
      ))}
    </>
  );
}

function NewsletterPicker({ siteId, value, onChange }: { siteId?: number; value: string | null; onChange: (id: string | null) => void }) {
  const api = useApi();
  const lists = useQuery({
    queryKey: ['newsroom', 'newsletters', siteId ?? null],
    queryFn: () => call(api.GET('/api/v2/newsroom/newsletters/', { params: { query: { site: siteId, page_size: 200 } } })),
  });
  return (
    <Select
      label="Newsletter"
      description="One of the site's newsletters: a post becomes an issue carrying its story, sent by the newsroom"
      data={(lists.data?.results ?? []).map((n) => ({ value: n.id, label: n.name }))}
      value={value}
      onChange={onChange}
    />
  );
}

function SitePicker({ value, onChange }: { value: number | null; onChange: (id: number | null) => void }) {
  const api = useApi();
  const sites = useQuery({ queryKey: ['sites'], queryFn: () => call(api.GET('/api/v2/sites/')) });
  return (
    <Select
      label="Site"
      data={(sites.data ?? []).map((s) => ({ value: String(s.id), label: s.name || s.hostname }))}
      value={value ? String(value) : null}
      onChange={(id) => onChange(id ? Number(id) : null)}
    />
  );
}

function NewChannel({ siteId, onDone }: { siteId?: number; onDone: (id: string) => void }) {
  const api = useApi();
  const qc = useQueryClient();
  const [site, setSite] = useState<number | null>(siteId ?? null);
  const [kind, setKind] = useState<DistributionKind>('linkedin');
  const [name, setName] = useState('');
  const [settings, setSettings] = useState<Settings>({});
  const [newsletter, setNewsletter] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () =>
      call(
        api.POST('/api/v2/distribution/channels/', {
          body: { site: site ?? 0, kind, name, settings, ...(kind === 'email' ? { newsletter } : {}) },
        }),
      ),
    onSuccess: (made) => {
      void qc.invalidateQueries({ queryKey: ['distribution'] });
      onDone(made.id);
    },
  });
  return (
    <Stack gap="xs" maw={560}>
      <Title order={4}>New channel</Title>
      <SitePicker value={site} onChange={setSite} />
      <Select
        label="Kind"
        data={KINDS}
        value={kind}
        allowDeselect={false}
        onChange={(v) => {
          setKind((v ?? 'linkedin') as DistributionKind);
          setSettings({});
        }}
      />
      <TextInput label="Name" value={name} onChange={(e) => setName(e.currentTarget.value)} />
      <SettingsFields kind={kind} values={settings} onChange={setSettings} />
      {kind === 'email' ? <NewsletterPicker siteId={site ?? undefined} value={newsletter} onChange={setNewsletter} /> : null}
      {create.error ? <Alert color="red">{errorText(create.error)}</Alert> : null}
      <Button w="fit-content" disabled={!site || !name.trim()} loading={create.isPending} onClick={oneClick(() => create.mutate())}>
        Add the channel
      </Button>
    </Stack>
  );
}

export function ChannelPanel({ channelId, connecting }: { channelId: string; connecting?: boolean }) {
  const channel = useChannel(channelId);
  if (channel.isPending) return <Loader />;
  if (channel.isError) return <Alert color="red">{errorText(channel.error)}</Alert>;
  return <Channel key={channel.data.updated_at} channel={channel.data} returned={connecting} />;
}

function Channel({ channel, returned }: { channel: DistributionChannel; returned?: boolean }) {
  const api = useApi();
  const go = useGo();
  const qc = useQueryClient();
  const path = { params: { path: { public_id: channel.id } } };
  const [name, setName] = useState(channel.name);
  const [settings, setSettings] = useState<Settings>(
    Object.fromEntries(Object.entries(channel.settings ?? {}).map(([k, v]) => [k, Array.isArray(v) ? v.join(' ') : String(v ?? '')])),
  );
  const [secrets, setSecrets] = useState<Settings>({});
  const [consent, setConsent] = useState<string | null>(null);
  const [imported, setImported] = useState<string | null>(null);
  const [removing, setRemoving] = useState(false);
  const refresh = () => qc.invalidateQueries({ queryKey: ['distribution'] });
  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) => call(api.PATCH('/api/v2/distribution/channels/{public_id}/', { ...path, body })),
    onSuccess: () => {
      setSecrets({});
      void refresh();
    },
  });
  const connect = useMutation({
    mutationFn: () => call(api.POST('/api/v2/distribution/channels/{public_id}/connect/', path)),
    onSuccess: (data) => setConsent(data.url),
  });
  const disconnect = useMutation({ mutationFn: () => call(api.POST('/api/v2/distribution/channels/{public_id}/disconnect/', path)), onSuccess: refresh });
  const check = useMutation({
    mutationFn: () => call(api.POST('/api/v2/distribution/channels/{public_id}/check/', path)),
    // The worker asks the target; read the channel again once it had time to answer.
    onSuccess: () => setTimeout(() => void refresh(), 1500),
  });
  const statistics = useMutation({ mutationFn: () => call(api.POST('/api/v2/distribution/channels/{public_id}/statistics/', path)) });
  const ledger = useQuery({
    queryKey: ['distribution', 'ledger-file', channel.id],
    queryFn: () => call(api.GET('/api/v2/distribution/channels/{public_id}/ledger-file/', path)),
  });
  const importLedger = useMutation({
    mutationFn: (content: string) => call(api.POST('/api/v2/distribution/channels/{public_id}/ledger-file/', { ...path, body: { content } })),
    onSuccess: (counts) => {
      setImported(`${counts.added} added, ${counts.kept} already here, ${counts.skipped} skipped`);
      void refresh();
    },
  });
  const remove = useMutation({
    mutationFn: () => call(api.DELETE('/api/v2/distribution/channels/{public_id}/', path)),
    onSuccess: () => {
      void refresh();
      go({ to: 'distribution', tab: 'channels' });
    },
  });
  // Only while the person decides: how many posts would go with the channel.
  const posts = useQuery({
    queryKey: ['distribution', 'posts', 'of-channel', channel.id],
    queryFn: () => call(api.GET('/api/v2/distribution/posts/', { params: { query: { channel: channel.id, page_size: 1 } } })),
    enabled: removing,
  });
  const failure = patch.error ?? connect.error ?? disconnect.error ?? check.error ?? statistics.error ?? importLedger.error;
  const typed = Object.fromEntries(Object.entries(secrets).filter(([, v]) => v.trim()));
  const cleanSettings = () => {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(settings)) if (v.trim()) out[k] = k === 'scopes' ? v.split(/\s+/) : v.trim();
    return out;
  };

  return (
    <Stack>
      <Group gap="xs">
        <Badge>{kindLabel(channel.kind)}</Badge>
        <Text size="sm" c="dimmed">
          {channel.site_name}
          {channel.account ? ` · publishes as ${channel.account}` : ''}
          {channel.expires_at ? ` · token expires ${when(channel.expires_at)}` : ''}
        </Text>
      </Group>
      {returned && channel.connecting ? <Alert color="blue">LinkedIn sent its answer; the platform is finishing the connection…</Alert> : null}
      {channel.last_error ? (
        <Alert color="red" title="Needs attention">
          {channel.last_error}
        </Alert>
      ) : null}
      {failure ? <Alert color="red">{errorText(failure)}</Alert> : null}

      <Title order={5}>Publishing</Title>
      <Switch
        label="Armed — this channel may publish (a post still needs a person's approval)"
        checked={channel.armed ?? false}
        disabled={!channel.can_manage}
        onChange={(e) => patch.mutate({ armed: e.currentTarget.checked })}
      />
      {!channel.deployment_armed ? (
        <Text size="sm" c="dimmed">
          This deployment does not publish to {channel.kind_label} yet: its operator sets the kind's switch (ZER0_
          {channel.kind.toUpperCase()}_PUBLISH=1).
        </Text>
      ) : null}
      <Switch
        label="Auto draft — every page of the site that goes live gets a draft post here (never a publish)"
        checked={channel.auto_draft ?? false}
        disabled={!channel.can_manage}
        onChange={(e) => patch.mutate({ auto_draft: e.currentTarget.checked })}
      />

      <Title order={5}>Settings</Title>
      <TextInput label="Name" value={name} disabled={!channel.can_manage} onChange={(e) => setName(e.currentTarget.value)} />
      <SettingsFields kind={channel.kind} values={settings} onChange={setSettings} />
      {channel.kind === 'email' ? <Text size="sm">Newsletter: {channel.newsletter_name}</Text> : null}
      <Group>
        <Button variant="default" disabled={!channel.can_manage} loading={patch.isPending} onClick={() => patch.mutate({ name, settings: cleanSettings() })}>
          Save the settings
        </Button>
      </Group>
      <Text size="xs" c="dimmed">
        Changing where the channel points — its author, address, user or repository — forgets its credential: it was given for the old one.
      </Text>

      {channel.secret_fields.length ? (
        <>
          <Title order={5}>Credential</Title>
          <Text size="sm">
            {channel.has_credential ? 'A credential is set. It is stored encrypted and never shown again.' : 'No credential is set.'}
          </Text>
          {channel.kind === 'linkedin' ? (
            <Group>
              <Button disabled={!channel.can_manage} loading={connect.isPending} onClick={() => connect.mutate()}>
                Connect with LinkedIn
              </Button>
              {consent ? (
                <Anchor href={consent} aria-label="Continue to LinkedIn">
                  Continue to LinkedIn’s consent screen →
                </Anchor>
              ) : null}
            </Group>
          ) : null}
          {channel.secret_fields.map((field) => (
            <PasswordInput
              key={field}
              label={channel.has_credential ? `Replace the ${secretLabel(field).toLowerCase()}` : secretLabel(field)}
              value={secrets[field] ?? ''}
              disabled={!channel.can_manage}
              onChange={(e) => setSecrets({ ...secrets, [field]: e.currentTarget.value })}
              autoComplete="off"
            />
          ))}
          <Group>
            <Button
              variant="default"
              disabled={!channel.can_manage || Object.keys(typed).length === 0}
              loading={patch.isPending}
              onClick={() => patch.mutate({ credentials: typed })}
            >
              Set the credential
            </Button>
            <Button variant="default" loading={check.isPending} disabled={!channel.can_manage || (!channel.has_credential && channel.kind !== 'email')} onClick={() => check.mutate()}>
              Check it
            </Button>
            {channel.has_credential ? (
              <Button variant="subtle" color="red" disabled={!channel.can_manage} loading={disconnect.isPending} onClick={() => disconnect.mutate()}>
                Disconnect
              </Button>
            ) : null}
          </Group>
          {channel.checked_at ? (
            <Text size="sm" c="dimmed">
              Checked {when(channel.checked_at)}: {channel.last_check?.ok ? 'it works' : 'it does not work'}.
            </Text>
          ) : null}
        </>
      ) : null}

      <Title order={5}>Ledger</Title>
      <Text size="sm">
        What this channel published, keyed by canonical URL, as the file the extension and a site’s CI read and write — so none of them
        publishes a page twice.
      </Text>
      <Group>
        {ledger.data ? (
          <Anchor href={`data:application/json;charset=utf-8,${encodeURIComponent(ledger.data.content)}`} download={ledger.data.filename}>
            Download the ledger file
          </Anchor>
        ) : null}
        <FileButton accept="application/json" onChange={(file) => file && void file.text().then((text) => importLedger.mutate(text))}>
          {(props) => (
            <Button {...props} variant="default" size="xs" disabled={!channel.can_manage} loading={importLedger.isPending}>
              Import a ledger file
            </Button>
          )}
        </FileButton>
        {channel.kind === 'linkedin' ? (
          <Button variant="default" size="xs" disabled={!channel.can_manage} loading={statistics.isPending} onClick={() => statistics.mutate()}>
            Read statistics now
          </Button>
        ) : null}
      </Group>
      {imported ? <Alert color="green">Imported: {imported}.</Alert> : null}
      {statistics.isSuccess ? <Text size="sm">The worker is reading LinkedIn’s statistics; they appear under Statistics.</Text> : null}
      {ledger.data ? <Code block>{ledger.data.content.length > 2000 ? `${ledger.data.content.slice(0, 2000)}…` : ledger.data.content}</Code> : null}

      <Group justify="flex-end">
        <Button variant="subtle" color="red" disabled={!channel.can_manage} onClick={() => setRemoving(true)}>
          Remove the channel…
        </Button>
      </Group>

      <Modal opened={removing} onClose={() => setRemoving(false)} title="Remove this channel?" closeButtonProps={{ 'aria-label': 'Close' }}>
        <Stack>
          <Text size="sm">
            {channel.name} goes{posts.data ? `, and its ${posts.data.count} post${posts.data.count === 1 ? '' : 's'} with it` : ''}. A channel whose
            ledger holds anything — a post that went out, or an attempt that may have — stays: its ledger is what keeps a page from going there
            twice, so disconnect it instead.
          </Text>
          {remove.error ? <Alert color="red">{errorText(remove.error)}</Alert> : null}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setRemoving(false)}>
              Cancel
            </Button>
            <Button color="red" loading={remove.isPending} onClick={() => remove.mutate()}>
              Remove it
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
