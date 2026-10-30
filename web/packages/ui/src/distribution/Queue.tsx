// The queue: every post of the channels a person may see, filtered by status
// and channel, newest first — what waits for approval, what is going out, what
// went and what failed — and composing a new one. Opening a post asks the host
// to go to it, so a post's panel has an address.
import { Alert, Anchor, Badge, Button, Group, Loader, Modal, MultiSelect, Select, Table, Text } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import type { DistributionPostStatus } from '@zer0/api';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { ComposeForm } from './Compose';
import { kindLabel, STATUSES, statusOf, useChannels, when } from './shared';

export function Queue({ siteId }: { siteId?: number }) {
  const api = useApi();
  const go = useGo();
  const channels = useChannels(siteId);
  const [status, setStatus] = useState<string[]>([]);
  const [channel, setChannel] = useState<string | null>(null);
  const [composing, setComposing] = useState(false);
  const query = { site: siteId, channel: channel ?? undefined, status: status as DistributionPostStatus[], page_size: 200 };
  const posts = useQuery({
    queryKey: ['distribution', 'posts', query],
    queryFn: () => call(api.GET('/api/v2/distribution/posts/', { params: { query } })),
    refetchInterval: (q) => (q.state.data?.results.some((p) => p.status === 'publishing') ? 2000 : false),
  });
  const open = (id: string) => go({ to: 'distribution-post', id });
  return (
    <>
      <Group justify="space-between" align="flex-end">
        <Group align="flex-end">
          <MultiSelect
            label="Status"
            placeholder="Every status"
            data={STATUSES.map((s) => ({ value: s.value, label: s.label }))}
            value={status}
            onChange={setStatus}
            w={260}
            clearable
          />
          <Select
            label="Channel"
            placeholder="Every channel"
            data={(channels.data?.results ?? []).map((c) => ({ value: c.id, label: c.name }))}
            value={channel}
            onChange={setChannel}
            clearable
            w={220}
          />
        </Group>
        <Button onClick={() => setComposing(true)}>Compose a post</Button>
      </Group>
      {posts.isPending ? <Loader /> : null}
      {posts.isError ? <Alert color="red">{errorText(posts.error)}</Alert> : null}
      {posts.isSuccess && posts.data.results.length === 0 ? (
        <Text c="dimmed">
          Nothing in the queue. Compose a post from a page or a story — or turn on Auto draft on a channel, and every page of its site
          that goes live gets a draft.
        </Text>
      ) : null}
      {posts.isSuccess && posts.data.results.length > 0 ? (
        <Table highlightOnHover aria-label="The queue">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Post</Table.Th>
              <Table.Th>Channel</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th>Brand guard</Table.Th>
              <Table.Th>Drafted</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {posts.data.results.map((post) => {
              const errors = post.guard.filter((f) => f.level === 'error').length;
              return (
                <Table.Tr key={post.id}>
                  <Table.Td>
                    <Anchor component="button" type="button" onClick={() => open(post.id)}>
                      {post.title || post.page_title || 'Untitled'}
                    </Anchor>
                  </Table.Td>
                  <Table.Td>
                    {post.channel_name} <Text span size="xs" c="dimmed">({kindLabel(post.channel_kind)})</Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge color={statusOf(post.status).color}>{statusOf(post.status).label}</Badge>
                  </Table.Td>
                  <Table.Td>{errors ? <Badge color="red" variant="light">{errors} error(s)</Badge> : <Text size="sm">clean</Text>}</Table.Td>
                  <Table.Td>
                    <Text size="sm">
                      {when(post.created_at)} · {post.origin === 'person' ? (post.created_by ?? 'a person') : post.origin}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      ) : null}
      {posts.data && posts.data.count > posts.data.results.length ? (
        <Text size="sm" c="dimmed">
          Showing {posts.data.results.length} of {posts.data.count}: narrow the filters to see the rest.
        </Text>
      ) : null}
      <Modal opened={composing} onClose={() => setComposing(false)} title="Compose a post" size="lg" closeButtonProps={{ 'aria-label': 'Close' }}>
        <ComposeForm
          siteId={siteId}
          onDone={(post) => {
            setComposing(false);
            open(post.id);
          }}
        />
      </Modal>
    </>
  );
}
