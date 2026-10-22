// Ideas alike in meaning: the pairs close enough to be one idea, each with a
// merge a person decides on, and the groups of related ideas. The platform
// reads them from the vectors its workers stored, so this asks nothing of a
// model; an idea saved a moment ago may still be "being read".
import { Alert, Anchor, Badge, Button, Card, Group, Loader, Stack, Text, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { call, errorText } from '../call';
import { useApi } from '../context';

export function Clusters({ board, onOpen }: { board: string; onOpen: (id: string) => void }) {
  const api = useApi();
  const qc = useQueryClient();
  const found = useQuery({
    queryKey: ['clusters', board],
    queryFn: () => call(api.GET('/api/v2/ideas/clusters/', { params: { query: { board } } })),
  });
  const merge = useMutation({
    mutationFn: ({ keep, other }: { keep: string; other: string }) =>
      call(api.POST('/api/v2/ideas/{public_id}/merge/', { params: { path: { public_id: keep } }, body: { other } })),
    onSuccess: (idea) => {
      notifications.show({ message: `Merged into “${idea.title}”` });
      void qc.invalidateQueries({ queryKey: ['ideas'] });
      void qc.invalidateQueries({ queryKey: ['clusters'] });
    },
  });

  if (found.isPending) return <Loader />;
  if (found.isError) return <Alert color="red">{errorText(found.error)}</Alert>;
  const { duplicates, clusters, pending } = found.data;
  const link = (idea: { id: string; title: string }) => (
    <Anchor component="button" type="button" onClick={() => onOpen(idea.id)}>
      {idea.title}
    </Anchor>
  );

  return (
    <Stack>
      {merge.isError ? <Alert color="red">{errorText(merge.error)}</Alert> : null}
      <Title order={4}>Likely duplicates</Title>
      {duplicates.length === 0 ? <Text c="dimmed">No two ideas here are close enough to be one.</Text> : null}
      {duplicates.map(({ a, b, similarity }) => (
        <Card key={`${a.id}-${b.id}`} withBorder padding="sm" aria-label={`Duplicate pair ${a.title}`}>
          <Group justify="space-between">
            <Stack gap={2}>
              {link(a)}
              {link(b)}
            </Stack>
            <Group gap="xs">
              <Badge variant="light">{Math.round(similarity * 100)}% alike</Badge>
              <Button size="xs" loading={merge.isPending} onClick={() => merge.mutate({ keep: a.id, other: b.id })}>
                Merge the second into the first
              </Button>
            </Group>
          </Group>
        </Card>
      ))}
      <Title order={4}>Clusters</Title>
      {clusters.length === 0 ? <Text c="dimmed">No ideas here are alike yet.</Text> : null}
      {clusters.map((cluster, i) => (
        <Card key={cluster.ideas.map((idea) => idea.id).join()} withBorder padding="sm" aria-label={`Cluster ${i + 1}`}>
          <Stack gap={4}>
            {cluster.ideas.map((idea) => (
              <Group key={idea.id} gap="xs">
                {link(idea)}
                <Badge size="xs" variant="outline">
                  {idea.status}
                </Badge>
              </Group>
            ))}
          </Stack>
        </Card>
      ))}
      {pending.length ? (
        <Text size="sm" c="dimmed">
          {pending.length} idea{pending.length === 1 ? ' is' : 's are'} still being read.
        </Text>
      ) : null}
    </Stack>
  );
}
