// A research brief on a topic from a collection (AIEO's: intent, keywords,
// angles, outline, link opportunities) — a run of the bundled writer,
// followed here; a person reads it and may keep it in the collection as a note.
import { Alert, Button, Group, Paper, Stack, Text, TextInput } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi } from '../context';
import { field, useRun } from './runs';

export function ResearchBrief({ collection }: { collection: string }) {
  const api = useApi();
  const qc = useQueryClient();
  const [topic, setTopic] = useState('');
  const [runId, setRunId] = useState<string | null>(null);
  const run = useRun(runId);
  const markdown = String(field(run.data?.output, 'markdown') ?? '');
  const write = useMutation({
    mutationFn: () =>
      call(api.POST('/api/v2/research/collections/{public_id}/research-brief/', { params: { path: { public_id: collection } }, body: { topic } })),
    onSuccess: (started) => setRunId(started.run.id),
  });
  const keep = useMutation({
    mutationFn: () =>
      call(api.POST('/api/v2/research/sources/', { body: { kind: 'note', title: `Research brief: ${topic}`, text: markdown, collection } })),
    onSuccess: () => {
      notifications.show({ message: 'Kept in the collection as a note' });
      void qc.invalidateQueries({ queryKey: ['sources'] });
    },
  });
  const writing = write.isPending || (runId !== null && !run.data?.is_final);

  return (
    <Stack>
      <Group align="end">
        <TextInput label="Topic" flex={1} value={topic} onChange={(e) => setTopic(e.currentTarget.value)} />
        <Button disabled={!topic.trim()} loading={writing} onClick={() => write.mutate()}>
          Write a research brief
        </Button>
      </Group>
      {write.isError ? <Alert color="red">{errorText(write.error)}</Alert> : null}
      {run.data?.is_final && run.data.status !== 'succeeded' ? <Alert color="red">{run.data.error || `The brief ${run.data.status}.`}</Alert> : null}
      {markdown ? (
        <Paper withBorder p="sm">
          <Text size="sm" style={{ whiteSpace: 'pre-wrap' }} aria-label="Research brief">
            {markdown}
          </Text>
          <Group mt="sm">
            <Button variant="light" loading={keep.isPending} onClick={() => keep.mutate()}>
              Keep it as a note
            </Button>
          </Group>
        </Paper>
      ) : null}
    </Stack>
  );
}
