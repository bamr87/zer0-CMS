// A page's revisions, newest first: compare any one with the latest (each
// changed field and the body as Markdown, diffed) and revert to it — which
// makes a new draft revision with its content and never publishes.
import { Alert, Badge, Button, Group, Loader, Stack, Table, Text, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { call, errorText } from './call';
import { useApi } from './context';
import { DiffView } from './DiffView';

const asText = (value: unknown) => (typeof value === 'string' ? value : value == null ? '' : JSON.stringify(value));

export function RevisionHistory({ pageId, canEdit }: { pageId: number; canEdit: boolean }) {
  const api = useApi();
  const qc = useQueryClient();
  const [selected, setSelected] = useState<number | null>(null);
  const path = { path: { id: pageId } };
  const revisions = useQuery({
    queryKey: ['revisions', pageId],
    queryFn: () => call(api.GET('/api/v2/content/pages/{id}/revisions/', { params: { ...path, query: { page_size: 50 } } })),
  });
  const latest = revisions.data?.results[0]?.id;
  const compare = useQuery({
    queryKey: ['compare', pageId, selected, latest],
    enabled: selected !== null && latest !== undefined && selected !== latest,
    queryFn: () =>
      call(api.GET('/api/v2/content/pages/{id}/revisions/compare/', { params: { ...path, query: { a: selected ?? 0, b: latest ?? 0 } } })),
  });
  const revert = useMutation({
    mutationFn: (revision: number) =>
      call(api.POST('/api/v2/content/pages/{id}/revisions/{revision_id}/revert/', { params: { path: { id: pageId, revision_id: revision } } })),
    onSuccess: (page) => {
      qc.setQueryData(['page', pageId], page);
      void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'page' });
      setSelected(null);
      notifications.show({ message: 'Reverted: the old content is now the latest draft' });
    },
  });

  if (revisions.isPending) return <Loader />;
  if (revisions.isError) return <Alert color="red">{errorText(revisions.error)}</Alert>;

  return (
    <Stack>
      {revert.isError ? <Alert color="red">{errorText(revert.error)}</Alert> : null}
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Saved</Table.Th>
            <Table.Th>By</Table.Th>
            <Table.Th />
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {revisions.data.results.map((r) => (
            <Table.Tr key={r.id}>
              <Table.Td>{new Date(r.created_at).toLocaleString()}</Table.Td>
              <Table.Td>{r.user ?? '—'}</Table.Td>
              <Table.Td>
                <Group gap={4}>
                  {r.is_latest ? <Badge variant="light">latest</Badge> : null}
                  {r.is_live ? <Badge color="teal" variant="light">live</Badge> : null}
                  {r.approved_go_live_at ? <Badge color="blue" variant="light">scheduled</Badge> : null}
                </Group>
              </Table.Td>
              <Table.Td>
                {r.is_latest ? null : (
                  <Group gap="xs" justify="end">
                    <Button size="xs" variant="default" onClick={() => setSelected(r.id)}>
                      Compare with latest
                    </Button>
                    {canEdit ? (
                      <Button size="xs" variant="light" loading={revert.isPending} onClick={() => revert.mutate(r.id)}>
                        Revert to this
                      </Button>
                    ) : null}
                  </Group>
                )}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {compare.isFetching ? <Loader size="sm" /> : null}
      {compare.data ? (
        <Stack gap="sm" aria-label="Revision diff">
          <Title order={4}>Changes since revision #{compare.data.a.id}</Title>
          {compare.data.changed.length === 0 ? <Text c="dimmed">The two revisions have the same content.</Text> : null}
          {compare.data.changed.map((name) => (
            <Stack key={name} gap={4}>
              <Text fw={600}>{name}</Text>
              {name === 'body' ? (
                <DiffView before={compare.data.a.markdown} after={compare.data.b.markdown} />
              ) : (
                <DiffView before={asText(compare.data.a.fields[name])} after={asText(compare.data.b.fields[name])} />
              )}
            </Stack>
          ))}
        </Stack>
      ) : null}
    </Stack>
  );
}
