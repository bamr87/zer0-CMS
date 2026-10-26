// A brief an idea became (the AI layer's): write it — a run, followed here —
// read what came back, and make it a draft page whose text arrives as
// suggestions to accept in the editor. Nothing here publishes.
import { Alert, Badge, Button, Card, Group, ScrollArea, Stack, Text } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { PagePicker } from '../PagePicker';

const COLOR: Record<string, string> = { ready: 'teal', applied: 'blue', failed: 'red', generating: 'yellow' };

export function BriefCard({ briefId }: { briefId: string }) {
  const api = useApi();
  const go = useGo();
  const qc = useQueryClient();
  const path = { params: { path: { public_id: briefId } } };
  const [parent, setParent] = useState<number | null>(null);
  const brief = useQuery({
    queryKey: ['brief', briefId],
    queryFn: () => call(api.GET('/api/v2/ai/briefs/{public_id}/', path)),
    refetchInterval: (query) => (query.state.data?.status === 'generating' ? 1500 : false),
  });
  const refresh = () => void qc.invalidateQueries({ queryKey: ['brief', briefId] });
  const write = useMutation({ mutationFn: () => call(api.POST('/api/v2/ai/briefs/{public_id}/generate/', path)), onSuccess: refresh });
  const apply = useMutation({
    mutationFn: () => call(api.POST('/api/v2/ai/briefs/{public_id}/apply/', { ...path, body: parent ? { parent } : {} })),
    onSuccess: (applied) => go({ to: 'page', id: applied.page_id }),
  });

  if (!brief.data) return brief.isError ? <Alert color="red">{errorText(brief.error)}</Alert> : null;
  const { status, title, markdown, error, page } = brief.data;
  const failure = write.error ?? apply.error;
  return (
    <Card withBorder padding="sm" aria-label="Brief">
      <Stack gap="xs">
        <Group justify="space-between">
          <Text fw={600}>{title || 'Brief'}</Text>
          <Badge color={COLOR[status] ?? 'gray'} variant="light">
            {status}
          </Badge>
        </Group>
        {error ? <Alert color="red">{error}</Alert> : null}
        {failure ? <Alert color="red">{errorText(failure)}</Alert> : null}
        {status === 'draft' || status === 'failed' ? (
          <Button loading={write.isPending} onClick={() => write.mutate()}>
            Write it
          </Button>
        ) : null}
        {status === 'generating' ? <Text c="dimmed">Being written…</Text> : null}
        {status === 'ready' ? (
          <>
            <ScrollArea.Autosize mah={240}>
              <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
                {markdown}
              </Text>
            </ScrollArea.Autosize>
            {brief.data.parent ? null : <PagePicker label="Where the draft goes" parents value={parent} onChange={setParent} />}
            <Button loading={apply.isPending} disabled={!brief.data.parent && !parent} onClick={() => apply.mutate()}>
              Make it a draft
            </Button>
          </>
        ) : null}
        {status === 'applied' && page ? (
          <Button variant="light" onClick={() => go({ to: 'page', id: page })}>
            Open the draft
          </Button>
        ) : null}
      </Stack>
    </Card>
  );
}
