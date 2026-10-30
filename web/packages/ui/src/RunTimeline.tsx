// Agent runs: the newest runs a person may see, and one run's steps as a
// timeline that grows live while the run works — the host opens the run's
// server-sent event stream (/api/v2/agent-runs/<id>/stream/) and this
// component only merges what arrives. The stream ends when the run is final
// or after its time limit; a live run's stream is opened again after a short
// pause, and one that broke after a pause that grows with each failure.
// A finished run links to its suggestions. `useLiveRun` is that following, for
// every screen that starts a run and shows it working (the AI workspaces). A
// run is addressed by its public id, a UUID (P-D6); `shortId` is how a screen
// names one to a person, as a short commit hash names a commit.
import { Alert, Anchor, Badge, Button, Code, Group, Loader, Stack, Table, Text, Timeline, Title } from '@mantine/core';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import type { Step } from '@zer0/api';
import { useEffect, useRef, useState } from 'react';

import { call, errorText } from './call';
import { useApi, useGo, useStream } from './context';

const COLOR: Record<string, string> = { succeeded: 'teal', failed: 'red', refused: 'orange', cancelled: 'gray' };
const STREAM_EVENTS = ['step', 'status', 'end'] as const;
const PAUSE_MS = 1000;
const LONGEST_PAUSE_MS = 30_000;

const isStep = (data: unknown): data is Step =>
  typeof data === 'object' && data !== null && typeof (data as { idx?: unknown }).idx === 'number';
const isFinal = (data: unknown) => typeof data === 'object' && data !== null && (data as { is_final?: unknown }).is_final === true;

/** A run's public id as a person reads it: its first eight characters (every address uses the whole id). */
export const shortId = (id: string) => id.slice(0, 8);

export function RunStatus({ status }: { status: string }) {
  return (
    <Badge color={COLOR[status] ?? 'blue'} variant="light">
      {status}
    </Badge>
  );
}

/**
 * A run with its steps, kept live while it works: the steps the stream
 * delivers are merged into the ones the run was read with, a final status
 * reads the run again, and a stream that ended or broke on a live run is
 * opened again after a pause.
 */
export function useLiveRun(runId: string) {
  const api = useApi();
  const stream = useStream();
  const qc = useQueryClient();
  const run = useQuery({
    queryKey: ['run', runId],
    queryFn: () => call(api.GET('/api/v2/agent-runs/{public_id}/', { params: { path: { public_id: runId } } })),
  });
  const [arrived, setArrived] = useState<Step[]>([]);
  const [round, setRound] = useState(0);
  const failures = useRef(0);
  const final = run.data?.is_final ?? true;

  useEffect(() => {
    if (final) return undefined;
    let finished = false;
    let again: ReturnType<typeof setTimeout> | undefined;
    const refresh = () => void qc.invalidateQueries({ queryKey: ['run', runId] });
    const close = stream(`/api/v2/agent-runs/${runId}/stream/`, STREAM_EVENTS, (event, data) => {
      if (event === 'step' || event === 'status') failures.current = 0;
      if (event === 'step' && isStep(data)) setArrived((steps) => [...steps.filter((s) => s.idx !== data.idx), data]);
      if (event === 'status') {
        finished = isFinal(data);
        refresh();
      }
      if (event === 'error' || (event === 'end' && !finished)) {
        refresh();
        const pause = event === 'error' ? Math.min(PAUSE_MS * 2 ** failures.current++, LONGEST_PAUSE_MS) : PAUSE_MS;
        again = setTimeout(() => setRound((n) => n + 1), pause);
      }
    });
    return () => {
      close();
      clearTimeout(again);
    };
  }, [final, runId, stream, qc, round]);

  const known = run.data?.steps ?? [];
  const steps = [...known, ...arrived.filter((s) => !known.some((k) => k.idx === s.idx))].sort((a, b) => a.idx - b.idx);
  return { run, steps, final };
}

export function RunTimeline({ runId }: { runId: string }) {
  const go = useGo();
  const { run, steps, final } = useLiveRun(runId);

  if (run.isPending) return <Loader />;
  if (run.isError) return <Alert color="red">{errorText(run.error)}</Alert>;

  return (
    <Stack>
      <Group justify="space-between">
        <Group gap="xs">
          <Title order={3}>
            Run {shortId(run.data.id)} · {run.data.agent}
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
              <Anchor component="button" type="button" ff="monospace" title={r.id} onClick={() => go({ to: 'run', id: r.id })}>
                {shortId(r.id)}
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
