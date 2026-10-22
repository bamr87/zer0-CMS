// Agent runs: the newest runs a person may see, and one run's steps as a
// timeline that grows live while the run works — the host opens the run's
// server-sent event stream (/api/v2/agent-runs/<id>/stream/) and this
// component only merges what arrives. A finished run links to its suggestions.
import { Alert, Anchor, Badge, Button, Code, Group, Loader, Stack, Table, Text, Timeline, Title } from '@mantine/core';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import type { Step } from '@zer0/api';
import { useEffect, useState } from 'react';

import { call, errorText } from './call';
import { useApi, useGo, useStream } from './context';

const FINAL = new Set(['succeeded', 'failed', 'refused', 'cancelled']);
const COLOR: Record<string, string> = { succeeded: 'teal', failed: 'red', refused: 'orange', cancelled: 'gray' };
const STREAM_EVENTS = ['step', 'status', 'end'] as const;

const isStep = (data: unknown): data is Step =>
  typeof data === 'object' && data !== null && typeof (data as { idx?: unknown }).idx === 'number';

export function RunStatus({ status }: { status: string }) {
  return (
    <Badge color={COLOR[status] ?? 'blue'} variant="light">
      {status}
    </Badge>
  );
}

export function RunTimeline({ runId }: { runId: number }) {
  const api = useApi();
  const go = useGo();
  const stream = useStream();
  const qc = useQueryClient();
  const run = useQuery({
    queryKey: ['run', runId],
    queryFn: () => call(api.GET('/api/v2/agent-runs/{id}/', { params: { path: { id: runId } } })),
  });
  const [arrived, setArrived] = useState<Step[]>([]);
  const [round, setRound] = useState(0);
  const final = run.data ? FINAL.has(run.data.status) : true;

  useEffect(() => {
    if (final) return undefined;
    return stream(`/api/v2/agent-runs/${runId}/stream/`, STREAM_EVENTS, (event, data) => {
      if (event === 'step' && isStep(data)) setArrived((steps) => [...steps.filter((s) => s.idx !== data.idx), data]);
      if (event === 'end') {
        void qc.invalidateQueries({ queryKey: ['run', runId] });
        setRound((n) => n + 1); // a stream that timed out on a live run is opened again
      }
    });
  }, [final, runId, stream, qc, round]);

  if (run.isPending) return <Loader />;
  if (run.isError) return <Alert color="red">{errorText(run.error)}</Alert>;
  const known = run.data.steps ?? [];
  const steps = [...known, ...arrived.filter((s) => !known.some((k) => k.idx === s.idx))].sort((a, b) => a.idx - b.idx);

  return (
    <Stack>
      <Group justify="space-between">
        <Group gap="xs">
          <Title order={3}>
            Run #{run.data.id} · {run.data.agent}
          </Title>
          <RunStatus status={run.data.status} />
          {final ? null : <Loader size="xs" aria-label="Running" />}
        </Group>
        <Button variant="light" onClick={() => go({ to: 'review', runId })}>
          Review its suggestions
        </Button>
      </Group>
      <Text size="sm" c="dimmed">
        {run.data.trigger} · {run.data.tokens} tokens · ${run.data.cost_usd} · started {new Date(run.data.created_at).toLocaleString()}
      </Text>
      {run.data.error ? <Alert color="red">{run.data.error}</Alert> : null}
      {steps.length === 0 ? (
        <Text c="dimmed">{final ? 'This run recorded no steps.' : 'Waiting for the first step…'}</Text>
      ) : (
        <Timeline active={steps.length - 1} bulletSize={18} lineWidth={2} aria-label="Run steps">
          {steps.map((step) => (
            <Timeline.Item key={step.idx} title={`${step.kind} · ${step.name}`} color={step.error ? 'red' : undefined}>
              <Text size="xs" c="dimmed">
                step {step.idx} · {step.latency_ms} ms{step.tokens ? ` · ${step.tokens} tokens` : ''}
              </Text>
              {step.error ? (
                <Text size="sm" c="red">
                  {step.error}
                </Text>
              ) : null}
            </Timeline.Item>
          ))}
        </Timeline>
      )}
      {typeof run.data.output === 'object' && run.data.output !== null && 'note' in run.data.output ? (
        <Code block>{String((run.data.output as { note: unknown }).note)}</Code>
      ) : null}
    </Stack>
  );
}

export function RunList() {
  const api = useApi();
  const go = useGo();
  const runs = useQuery({ queryKey: ['runs'], queryFn: () => call(api.GET('/api/v2/agent-runs/')) });
  if (runs.isPending) return <Loader />;
  if (runs.isError) return <Alert color="red">{errorText(runs.error)}</Alert>;
  if (runs.data.results.length === 0) return <Text c="dimmed">No agent runs yet.</Text>;
  return (
    <Table highlightOnHover>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>Run</Table.Th>
          <Table.Th>Agent</Table.Th>
          <Table.Th>Status</Table.Th>
          <Table.Th>Trigger</Table.Th>
          <Table.Th>Started</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {runs.data.results.map((r) => (
          <Table.Tr key={r.id}>
            <Table.Td>
              <Anchor component="button" type="button" onClick={() => go({ to: 'run', id: r.id })}>
                #{r.id}
              </Anchor>
            </Table.Td>
            <Table.Td>{r.agent}</Table.Td>
            <Table.Td>
              <RunStatus status={r.status} />
            </Table.Td>
            <Table.Td>{r.trigger}</Table.Td>
            <Table.Td>{new Date(r.created_at).toLocaleString()}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
