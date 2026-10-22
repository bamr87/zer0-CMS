// The model catalog: every model the providers' syncs found, filtered by
// provider, by whether it is active, and by name — with what each can do
// and what it costs. The catalog fills from a provider's "Sync models"
// (Providers); an assistant picks its model from here.
import { Alert, Badge, Button, EmptyState, Group, Loader, SegmentedControl, Select, Stack, Table, Text, TextInput } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import type { ModelEntry } from '@zer0/api';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { ALL, isRecord, useProviders } from './shared';

const price = (value: string | null) => (value === null ? '—' : `$${Number(value)}`);

function abilities(model: ModelEntry) {
  const found = isRecord(model.capabilities) ? model.capabilities : {};
  return Object.entries(found)
    .filter(([, on]) => on === true)
    .map(([name]) => name.replace(/_/g, ' '));
}

export function ModelCatalog() {
  const api = useApi();
  const go = useGo();
  const providers = useProviders();
  const [provider, setProvider] = useState('');
  const [active, setActive] = useState('active');
  const [text, setText] = useState('');
  const query = { ...ALL, ordering: 'model_id', ...(provider ? { provider } : {}), ...(active === 'all' ? {} : { active: active === 'active' }) };
  const models = useQuery({ queryKey: ['ai', 'models', query], queryFn: () => call(api.GET('/api/v2/ai/models/', { params: { query } })) });
  const needle = text.trim().toLowerCase();
  const shown = (models.data?.results ?? []).filter((m) => !needle || `${m.model_id} ${m.display_name}`.toLowerCase().includes(needle));

  return (
    <Stack>
      <Group align="end">
        <Select
          label="Provider"
          data={[{ value: '', label: 'Every provider' }, ...(providers.data?.results ?? []).map((p) => ({ value: p.slug, label: p.display_name || p.slug }))]}
          value={provider}
          allowDeselect={false}
          onChange={(next) => setProvider(next ?? '')}
        />
        <SegmentedControl
          aria-label="Which models"
          value={active}
          onChange={setActive}
          data={[
            { value: 'active', label: 'Active' },
            { value: 'inactive', label: 'Inactive' },
            { value: 'all', label: 'All' },
          ]}
        />
        <TextInput label="Name" placeholder="Filter by name" value={text} onChange={(e) => setText(e.currentTarget.value)} />
      </Group>
      {models.isPending ? <Loader aria-label="Loading models" /> : null}
      {models.isError ? <Alert color="red">{errorText(models.error)}</Alert> : null}
      {models.data && shown.length === 0 ? (
        <EmptyState
          title={models.data.results.length ? 'No model matches' : 'No models in the catalog yet'}
          description={models.data.results.length ? 'Change the filters to see more.' : "A provider's model sync fills the catalog."}
        >
          {models.data.results.length ? null : (
            <Button variant="light" onClick={() => go({ to: 'ai', section: 'providers' })}>
              Go to the providers
            </Button>
          )}
        </EmptyState>
      ) : null}
      {shown.length ? (
        <Table aria-label="Models">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Model</Table.Th>
              <Table.Th>Provider</Table.Th>
              <Table.Th>Can</Table.Th>
              <Table.Th>Input / output per million tokens</Table.Th>
              <Table.Th>Synced</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {shown.map((m) => (
              <Table.Tr key={m.id}>
                <Table.Td>
                  <Text fw={500}>{m.display_name || m.model_id}</Text>
                  <Text size="xs" c="dimmed" ff="monospace">
                    {m.model_id}
                  </Text>
                  {m.active ? null : (
                    <Badge size="xs" color="gray" variant="light">
                      inactive
                    </Badge>
                  )}
                </Table.Td>
                <Table.Td>{m.provider}</Table.Td>
                <Table.Td>
                  <Group gap={4}>
                    {abilities(m).map((a) => (
                      <Badge key={a} size="xs" variant="outline">
                        {a}
                      </Badge>
                    ))}
                  </Group>
                </Table.Td>
                <Table.Td>
                  {price(m.input_usd_per_mtok)} / {price(m.output_usd_per_mtok)}
                </Table.Td>
                <Table.Td>{m.synced_at ? new Date(m.synced_at).toLocaleString() : 'never'}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      ) : null}
    </Stack>
  );
}
