// Feeds: subscribe to an RSS or Atom feed (the platform refreshes it on a
// schedule and turns each new item into a source), see when each was last
// read and what went wrong, pause one, or refresh it now.
import { Alert, Button, Group, Select, Stack, Switch, Table, Text, TextInput } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi } from '../context';

const EVERY = [
  { value: '60', label: 'Every hour' },
  { value: '240', label: 'Every four hours' },
  { value: '1440', label: 'Every day' },
];

export function FeedsPanel({ collection }: { collection: string | null }) {
  const api = useApi();
  const qc = useQueryClient();
  const [url, setUrl] = useState('');
  const [every, setEvery] = useState('60');
  const feeds = useQuery({
    queryKey: ['feeds'],
    queryFn: () => call(api.GET('/api/v2/research/feeds/', { params: { query: { page_size: 100 } } })),
  });
  const refresh = () => void qc.invalidateQueries({ queryKey: ['feeds'] });
  const subscribe = useMutation({
    mutationFn: () =>
      call(api.POST('/api/v2/research/feeds/', { body: { url, interval_minutes: Number(every), collection } })),
    onSuccess: () => {
      setUrl('');
      notifications.show({ message: 'Subscribed: its items arrive as sources' });
      refresh();
    },
  });
  const toggle = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) =>
      call(api.PATCH('/api/v2/research/feeds/{public_id}/', { params: { path: { public_id: id } }, body: { active } })),
    onSuccess: refresh,
  });
  const now = useMutation({
    mutationFn: (id: string) => call(api.POST('/api/v2/research/feeds/{public_id}/refresh/', { params: { path: { public_id: id } } })),
    onSuccess: () => notifications.show({ message: 'Refreshing the feed…' }),
  });
  const failure = subscribe.error ?? toggle.error ?? now.error;

  return (
    <Stack>
      <Group align="end">
        <TextInput label="Feed address" placeholder="https://…/feed.xml" flex={1} value={url} onChange={(e) => setUrl(e.currentTarget.value)} />
        <Select label="Check it" data={EVERY} value={every} allowDeselect={false} onChange={(value) => setEvery(value ?? '60')} w={180} />
        <Button disabled={!url.trim()} loading={subscribe.isPending} onClick={() => subscribe.mutate()}>
          Subscribe
        </Button>
      </Group>
      {failure ? <Alert color="red">{errorText(failure)}</Alert> : null}
      {feeds.data?.results.length === 0 ? <Text c="dimmed">No feeds yet.</Text> : null}
      {feeds.data?.results.length ? (
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Feed</Table.Th>
              <Table.Th>Sources</Table.Th>
              <Table.Th>Last read</Table.Th>
              <Table.Th>On</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {feeds.data.results.map((feed) => (
              <Table.Tr key={feed.id}>
                <Table.Td>
                  <Text size="sm">{feed.title || feed.url}</Text>
                  {feed.error ? (
                    <Text size="xs" c="red">
                      {feed.error}
                    </Text>
                  ) : null}
                </Table.Td>
                <Table.Td>{feed.items}</Table.Td>
                <Table.Td>{feed.last_checked_at ? new Date(feed.last_checked_at).toLocaleString() : 'not yet'}</Table.Td>
                <Table.Td>
                  <Switch
                    aria-label={`Keep reading ${feed.title || feed.url}`}
                    checked={feed.active ?? true}
                    onChange={(e) => toggle.mutate({ id: feed.id, active: e.currentTarget.checked })}
                  />
                </Table.Td>
                <Table.Td>
                  <Button size="compact-xs" variant="light" onClick={() => now.mutate(feed.id)}>
                    Refresh now
                  </Button>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      ) : null}
    </Stack>
  );
}
