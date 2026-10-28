// Reports: audit a list of sites together (each a run), watch them finish,
// and read the summary AIEO wrote for such a batch — the ranking, the score
// distribution, the pattern heatmap and the most common gaps — or one site's
// own report from its audit (the Audit tab).
import { Alert, Badge, Button, CopyButton, Group, Paper, Stack, Switch, Table, Text, Textarea, Title } from '@mantine/core';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { MarkdownView, newKey, once, oneClick } from '../ai/shared';
import { call, errorText } from '../call';
import { useApi } from '../context';
import { gradeColor } from './score';

export function Reports({ siteId }: { siteId?: number }) {
  const api = useApi();
  const [urls, setUrls] = useState('');
  const [ai, setAi] = useState(false);
  const [batch, setBatch] = useState<string | null>(null);
  const start = useMutation({
    mutationFn: (key: string) =>
      call(
        api.POST('/api/v2/aieo/audits/batch/', {
          params: { header: once(key) },
          body: { urls: urls.split('\n').map((u) => u.trim()).filter(Boolean), method: ai ? 'ai' : 'heuristic', site: siteId ?? null },
        }),
      ),
    onSuccess: (made) => setBatch(made.batch),
  });
  return (
    <Stack>
      <Paper withBorder p="md" component="form" aria-label="Audit several sites" onSubmit={(e) => e.preventDefault()}>
        <Stack gap="sm">
          <Textarea label="Sites, one address per line" autosize minRows={3} value={urls} onChange={(e) => setUrls(e.currentTarget.value)} />
          <Switch label="A model's evaluation of each" checked={ai} onChange={(e) => setAi(e.currentTarget.checked)} />
          <Group>
            <Button disabled={!urls.trim()} loading={start.isPending} onClick={oneClick(() => start.mutate(newKey()))}>
              Audit them
            </Button>
          </Group>
          {start.isError ? <Alert color="red">{errorText(start.error)}</Alert> : null}
        </Stack>
      </Paper>
      {batch ? <Batch batch={batch} /> : null}
    </Stack>
  );
}

function Batch({ batch }: { batch: string }) {
  const api = useApi();
  const [shown, setShown] = useState(false);
  const audits = useQuery({
    queryKey: ['aieo', 'batch', batch],
    queryFn: () => call(api.GET('/api/v2/aieo/audits/', { params: { query: { batch, page_size: 100 } } })),
    refetchInterval: (query) => ((query.state.data?.results ?? []).some((a) => ['pending', 'running'].includes(a.status)) ? 2000 : false),
  });
  const rows = audits.data?.results ?? [];
  const finished = rows.length > 0 && rows.every((a) => !['pending', 'running'].includes(a.status));
  const summary = useQuery({
    queryKey: ['aieo', 'summary', batch],
    enabled: shown && finished,
    queryFn: () => call(api.GET('/api/v2/aieo/audits/summary/', { params: { query: { batch } } })),
  });
  return (
    <Stack gap="xs">
      <Title order={4}>This batch</Title>
      <Table aria-label="Batch audits">
        <Table.Tbody>
          {rows.map((a) => (
            <Table.Tr key={a.id}>
              <Table.Td>{a.url}</Table.Td>
              <Table.Td>
                {a.status === 'ready' ? (
                  <Badge color={gradeColor(a.grade)}>
                    {a.score} · {a.grade}
                  </Badge>
                ) : (
                  <Badge variant="light" color={a.status === 'failed' ? 'red' : 'blue'}>
                    {a.status === 'failed' ? a.error || 'failed' : a.status}
                  </Badge>
                )}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <Group>
        <Button variant="light" disabled={!finished} onClick={() => setShown(true)}>
          The summary report
        </Button>
      </Group>
      {summary.isError ? <Alert color="red">{errorText(summary.error)}</Alert> : null}
      {summary.data ? (
        <Paper withBorder p="md">
          <CopyButton value={summary.data.markdown}>
            {({ copied, copy }) => (
              <Button size="xs" variant="default" onClick={copy}>
                {copied ? 'Copied' : 'Copy the Markdown'}
              </Button>
            )}
          </CopyButton>
          <MarkdownView markdown={summary.data.markdown} label="The summary report" />
        </Paper>
      ) : (
        <Text size="sm" c="dimmed">
          The summary is ready once every audit has finished.
        </Text>
      )}
    </Stack>
  );
}
