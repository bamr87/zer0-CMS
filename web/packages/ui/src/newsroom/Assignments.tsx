// Assignments: the stories in the making that are mine, or my desks' — with
// their status, deadline (late ones marked) and slot — soonest due first.
import { Alert, Anchor, Badge, Loader, SegmentedControl, Stack, Table, Text } from '@mantine/core';
import { useState } from 'react';

import { errorText } from '../call';
import { IN_PROGRESS, shownOf, statusOf, useStories, when, type StoriesQuery } from './shared';

export function Assignments({ query, onOpen }: { query: StoriesQuery; onOpen: (id: string) => void }) {
  const [scope, setScope] = useState('mine');
  const stories = useStories({
    ...query,
    status: IN_PROGRESS,
    ...(scope === 'mine' ? { assignee: 'me' } : { my_desks: true }),
  });
  const rows = [...(stories.data?.results ?? [])].sort((a, b) => (a.deadline ?? '9999').localeCompare(b.deadline ?? '9999'));
  return (
    <Stack>
      <SegmentedControl
        w="fit-content"
        value={scope}
        onChange={setScope}
        data={[
          { value: 'mine', label: 'Assigned to me' },
          { value: 'desks', label: 'My desks' },
        ]}
      />
      {shownOf(stories.data) ? <Alert color="yellow">{shownOf(stories.data)}: pick a desk to see the rest.</Alert> : null}
      {stories.isPending ? (
        <Loader />
      ) : stories.isError ? (
        <Alert color="red">{errorText(stories.error)}</Alert>
      ) : rows.length === 0 ? (
        <Text c="dimmed">Nothing in the making here.</Text>
      ) : (
        <Table highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Story</Table.Th>
              <Table.Th>Desk</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th>Reporter</Table.Th>
              <Table.Th>Deadline</Table.Th>
              <Table.Th>Runs</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((story) => (
              <Table.Tr key={story.id}>
                <Table.Td>
                  <Anchor component="button" type="button" ta="left" onClick={() => onOpen(story.id)}>
                    {story.headline}
                  </Anchor>
                </Table.Td>
                <Table.Td>{story.desk_name}</Table.Td>
                <Table.Td>
                  <Badge variant="light" color={statusOf(story.status).color}>
                    {statusOf(story.status).label}
                  </Badge>
                </Table.Td>
                <Table.Td>{story.assignee?.name ?? '—'}</Table.Td>
                <Table.Td c={story.deadline && new Date(story.deadline) < new Date() ? 'red' : undefined}>{when(story.deadline)}</Table.Td>
                <Table.Td>{story.slot_date ?? '—'}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}
