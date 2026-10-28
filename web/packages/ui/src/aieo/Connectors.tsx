// A site's data connections — GA4 (top pages), Search Console (queries) and
// DataForSEO (search results for its keywords) — configured by people with
// `aieo.change_connector` who edit the site: the credential is typed once,
// sent once and never shown again (only whether one is set); a sync runs in
// a worker and keeps its rows. Priorities read Search Console's last rows.
import { Alert, Badge, Button, Group, Paper, PasswordInput, SimpleGrid, Stack, Switch, Table, Text, TextInput, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { AieoConnector, AieoConnectorKind } from '@zer0/api';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi } from '../context';

const KINDS: { kind: AieoConnectorKind; title: string; option: string; placeholder: string; credential: string }[] = [
  { kind: 'ga4', title: 'Google Analytics 4', option: 'property_id', placeholder: '123456789', credential: "A service account's JSON key" },
  { kind: 'gsc', title: 'Search Console', option: 'site_url', placeholder: 'sc-domain:example.com', credential: "A service account's JSON key" },
  { kind: 'dataforseo', title: 'DataForSEO', option: 'keywords', placeholder: 'backup, restore', credential: 'login:password' },
];

export function Connectors({ siteId }: { siteId?: number }) {
  const api = useApi();
  const connectors = useQuery({
    queryKey: ['aieo', 'connectors', siteId],
    enabled: siteId !== undefined,
    queryFn: () => call(api.GET('/api/v2/aieo/connectors/', { params: { query: { site: siteId } } })),
    refetchInterval: (query) => ((query.state.data ?? []).some((c) => c.status === 'syncing') ? 2000 : false),
  });
  if (siteId === undefined) return <Alert color="gray">Choose a site in the header to connect it.</Alert>;
  return (
    <SimpleGrid cols={{ base: 1, lg: 3 }}>
      {connectors.isError ? <Alert color="red">{errorText(connectors.error)}</Alert> : null}
      {KINDS.map((spec) => (
        <ConnectorCard key={spec.kind} siteId={siteId} spec={spec} row={(connectors.data ?? []).find((c) => c.kind === spec.kind)} />
      ))}
    </SimpleGrid>
  );
}

function optionText(row: AieoConnector | undefined, option: string): string {
  const value = (row?.options as Record<string, unknown> | undefined)?.[option];
  return Array.isArray(value) ? value.join(', ') : typeof value === 'string' ? value : '';
}

function ConnectorCard({ siteId, spec, row }: { siteId: number; spec: (typeof KINDS)[number]; row?: AieoConnector }) {
  const api = useApi();
  const qc = useQueryClient();
  const [enabled, setEnabled] = useState(row?.enabled ?? true);
  const [option, setOption] = useState(optionText(row, spec.option));
  const [credential, setCredential] = useState('');
  const refresh = () => void qc.invalidateQueries({ queryKey: ['aieo', 'connectors'] });
  const value = spec.option === 'keywords' ? option.split(',').map((k) => k.trim()).filter(Boolean) : option.trim();
  const options = { ...((row?.options as Record<string, unknown> | undefined) ?? {}), [spec.option]: value };
  const save = useMutation({
    mutationFn: () => {
      const secret = credential ? { credential } : {};
      return row
        ? call(api.PATCH('/api/v2/aieo/connectors/{public_id}/', { params: { path: { public_id: row.id } }, body: { enabled, options, ...secret } }))
        : call(api.POST('/api/v2/aieo/connectors/', { body: { site: siteId, kind: spec.kind, enabled, options, ...secret } }));
    },
    onSuccess: () => {
      setCredential('');
      notifications.show({ message: `${spec.title} saved` });
      refresh();
    },
  });
  const sync = useMutation({
    mutationFn: () => call(api.POST('/api/v2/aieo/connectors/{public_id}/sync/', { params: { path: { public_id: row?.id ?? '' } } })),
    onSuccess: refresh,
  });
  return (
    <Paper withBorder p="md" component="form" aria-label={spec.title} onSubmit={(e) => e.preventDefault()}>
      <Stack gap="sm">
        <Group justify="space-between">
          <Title order={5}>{spec.title}</Title>
          {row ? <Badge color={row.status === 'ok' ? 'teal' : row.status === 'failed' ? 'red' : 'gray'}>{row.status}</Badge> : <Badge color="gray">not connected</Badge>}
        </Group>
        <Switch label="On" checked={enabled} onChange={(e) => setEnabled(e.currentTarget.checked)} />
        <TextInput label={spec.option.replace('_', ' ')} placeholder={spec.placeholder} value={option} onChange={(e) => setOption(e.currentTarget.value)} />
        <PasswordInput
          label="Credential"
          description={`${spec.credential} — ${row?.has_credential ? 'set; type a new one to replace it' : 'not set'}`}
          value={credential}
          onChange={(e) => setCredential(e.currentTarget.value)}
          autoComplete="off"
        />
        <Group>
          <Button size="xs" loading={save.isPending} onClick={() => save.mutate()}>
            Save
          </Button>
          <Button size="xs" variant="light" disabled={!row || row.status === 'syncing'} loading={sync.isPending} onClick={() => sync.mutate()}>
            Sync now
          </Button>
        </Group>
        {save.isError ? <Alert color="red">{errorText(save.error)}</Alert> : null}
        {sync.isError ? <Alert color="red">{errorText(sync.error)}</Alert> : null}
        {row?.error ? <Alert color="red">{row.error}</Alert> : null}
        {row?.last_synced_at ? (
          <Text size="xs" c="dimmed">
            {row.rows ?? 0} rows · synced {new Date(row.last_synced_at).toLocaleString()}
          </Text>
        ) : null}
      </Stack>
    </Paper>
  );
}

/** The ranked content-update queue and the quick wins, from Search Console's last rows (AIEO's opportunity rule). */
export function Priorities({ siteId }: { siteId?: number }) {
  const api = useApi();
  const priorities = useQuery({
    queryKey: ['aieo', 'priorities', siteId],
    enabled: siteId !== undefined,
    queryFn: () => call(api.GET('/api/v2/aieo/priorities/', { params: { query: { site: siteId } } })),
  });
  if (siteId === undefined) return <Alert color="gray">Choose a site in the header to see its priorities.</Alert>;
  if (priorities.isError) return <Alert color="red">{errorText(priorities.error)}</Alert>;
  const data = priorities.data;
  if (!data) return null;
  if (!data.fetched_at) return <Alert color="gray">Connect Search Console and sync it: priorities are ranked from its queries.</Alert>;
  const wins = new Set(data.quick_wins.map((q) => `${q.query} ${q.page}`));
  return (
    <Stack gap="xs">
      <Text size="sm" c="dimmed">
        From Search Console's rows of {new Date(data.fetched_at).toLocaleString()}; a quick win scores 60 or more.
      </Text>
      <Table aria-label="Update queue">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Query</Table.Th>
            <Table.Th>Page</Table.Th>
            <Table.Th>Position</Table.Th>
            <Table.Th>Impressions</Table.Th>
            <Table.Th>CTR</Table.Th>
            <Table.Th>Opportunity</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {data.queue.map((q) => (
            <Table.Tr key={`${q.query} ${q.page}`}>
              <Table.Td>
                {q.query} {wins.has(`${q.query} ${q.page}`) ? <Badge size="xs" color="teal">quick win</Badge> : null}
              </Table.Td>
              <Table.Td>{q.page}</Table.Td>
              <Table.Td>{q.position}</Table.Td>
              <Table.Td>{q.impressions}</Table.Td>
              <Table.Td>{Math.round(q.ctr * 1000) / 10}%</Table.Td>
              <Table.Td>{q.opportunity_score}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}
