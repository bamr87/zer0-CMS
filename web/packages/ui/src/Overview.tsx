// Home: what needs attention — the review queue, the latest agent runs, the
// pages edited most recently and the AI providers' status — each a step away
// from where to act on it.
import { Anchor, Button, Card, Group, SimpleGrid, Stack, Text, Title } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';

import { ProviderStatus } from './ai/Providers';
import { call } from './call';
import { useApi, useGo } from './context';
import { RunStatus, shortId } from './RunTimeline';
import { StatusBadge } from './StatusBadge';

export function Overview({ siteId }: { siteId?: number }) {
  const api = useApi();
  const go = useGo();
  const inboxQuery = { site: siteId, page_size: 1 };
  const recentQuery = { site: siteId, ordering: '-latest_revision_created_at', page_size: 6 };
  const inbox = useQuery({ queryKey: ['inbox', inboxQuery], queryFn: () => call(api.GET('/api/v2/review/suggestions/', { params: { query: inboxQuery } })) });
  const runs = useQuery({ queryKey: ['runs'], queryFn: () => call(api.GET('/api/v2/agent-runs/')) });
  const recent = useQuery({ queryKey: ['pages', recentQuery], queryFn: () => call(api.GET('/api/v2/content/pages/', { params: { query: recentQuery } })) });

  return (
    <SimpleGrid cols={{ base: 1, md: 2, xl: 4 }}>
      <Card withBorder>
        <Title order={4}>To review</Title>
        <Text size="xl" fw={700} my="sm" aria-label="Suggestions to review">
          {inbox.data?.count ?? '…'}
        </Text>
        <Text size="sm" c="dimmed" mb="sm">
          suggestions waiting for a decision
        </Text>
        <Button variant="light" onClick={() => go({ to: 'review' })}>
          Open the inbox
        </Button>
      </Card>
      <Card withBorder>
        <Title order={4} mb="sm">
          Recent runs
        </Title>
        <Stack gap={6}>
          {(runs.data?.results ?? []).slice(0, 6).map((r) => (
            <Group key={r.id} justify="space-between">
              <Anchor component="button" type="button" title={r.id} onClick={() => go({ to: 'run', id: r.id })}>
                {r.agent} · {shortId(r.id)}
              </Anchor>
              <RunStatus status={r.status} />
            </Group>
          ))}
          {runs.data?.results.length === 0 ? <Text c="dimmed">No runs yet.</Text> : null}
        </Stack>
      </Card>
      <Card withBorder>
        <Title order={4} mb="sm">
          Recently edited
        </Title>
        <Stack gap={6}>
          {(recent.data?.results ?? []).map((p) => (
            <Group key={p.id} justify="space-between" wrap="nowrap">
              <Anchor component="button" type="button" onClick={() => go({ to: 'page', id: p.id })} truncate>
                {p.title}
              </Anchor>
              <StatusBadge status={p.status} />
            </Group>
          ))}
          {recent.data?.results.length === 0 ? <Text c="dimmed">No pages yet.</Text> : null}
        </Stack>
      </Card>
      <ProviderStatus />
    </SimpleGrid>
  );
}
