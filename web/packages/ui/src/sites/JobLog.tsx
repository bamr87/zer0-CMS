// A job and its log, kept live while it runs: the host opens the job's
// server-sent event stream (/api/v2/jobs/<id>/stream/) and this only merges
// what arrives, by line number, as the run timeline does for an
// agent run. A stream that ends on a running job is opened again after a pause,
// and one that broke after a pause that grows with each failure. A person who
// may manage the job's site can cancel it while it is queued or running, and
// read what it left behind (its artifacts), fetched through the API client so
// the extension's webviews show them too.
import { Alert, Badge, Button, Code, Group, Loader, ScrollArea, Stack, Text, Title } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { JobLine } from '@zer0/api';
import { useEffect, useRef, useState } from 'react';

import { call, errorText } from '../call';
import { useApi, useStream } from '../context';

export const JOB_COLOR: Record<string, string> = { succeeded: 'teal', failed: 'red', cancelled: 'gray', running: 'blue', queued: 'yellow' };
const LEVEL_COLOR: Record<string, string | undefined> = { warning: 'orange', error: 'red' };
const EVENTS = ['line', 'status', 'end'] as const;
const PAUSE_MS = 1000;
const LONGEST_PAUSE_MS = 30_000;

const isLine = (data: unknown): data is JobLine =>
  typeof data === 'object' && data !== null && typeof (data as { idx?: unknown }).idx === 'number';
const isFinal = (data: unknown) => typeof data === 'object' && data !== null && (data as { is_final?: unknown }).is_final === true;

export function JobStatus({ status }: { status: string }) {
  return (
    <Badge color={JOB_COLOR[status] ?? 'blue'} variant="light">
      {status}
    </Badge>
  );
}

/** A job with its log, the lines the stream delivers merged into the ones it was read with. */
export function useLiveJob(jobId: string) {
  const api = useApi();
  const stream = useStream();
  const qc = useQueryClient();
  const job = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => call(api.GET('/api/v2/jobs/{public_id}/', { params: { path: { public_id: jobId } } })),
  });
  const [arrived, setArrived] = useState<JobLine[]>([]);
  const [round, setRound] = useState(0);
  const failures = useRef(0);
  const final = job.data?.is_final ?? true;
  const known = job.data?.lines ?? [];
  const lines = [...known, ...arrived.filter((l) => !known.some((k) => k.idx === l.idx))].sort((a, b) => a.idx - b.idx);

  useEffect(() => {
    if (final) return undefined;
    let finished = false;
    let again: ReturnType<typeof setTimeout> | undefined;
    const refresh = () => void qc.invalidateQueries({ queryKey: ['job', jobId] });
    const close = stream(`/api/v2/jobs/${jobId}/stream/`, EVENTS, (event, data) => {
      if (event === 'line' || event === 'status') failures.current = 0;
      if (event === 'line' && isLine(data)) setArrived((seen) => [...seen.filter((l) => l.idx !== data.idx), data]);
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
  }, [final, jobId, stream, qc, round]);

  return { job, lines, final };
}

export function JobLog({ jobId, title }: { jobId: string; title?: string }) {
  const api = useApi();
  const qc = useQueryClient();
  const { job, lines, final } = useLiveJob(jobId);
  const cancel = useMutation({
    mutationFn: () => call(api.POST('/api/v2/jobs/{public_id}/cancel/', { params: { path: { public_id: jobId } } })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['job', jobId] }),
  });

  if (job.isPending) return <Loader />;
  if (job.isError) return <Alert color="red">{errorText(job.error)}</Alert>;
  const j = job.data;
  return (
    <Stack gap="xs">
      <Group justify="space-between">
        <Group gap="xs">
          <Title order={4}>{title ?? `${j.kind} job`}</Title>
          <JobStatus status={j.status} />
          {final ? null : <Loader size="xs" aria-label="Running" />}
        </Group>
        {final ? null : (
          <Button size="xs" variant="light" color="red" loading={cancel.isPending} disabled={j.cancel_requested} onClick={() => cancel.mutate()}>
            {j.cancel_requested ? 'Stopping…' : 'Cancel'}
          </Button>
        )}
      </Group>
      <Text size="xs" c="dimmed">
        {j.created_by ? `${j.created_by} · ` : ''}started {new Date(j.created_at).toLocaleString()}
        {j.finished_at ? ` · ended ${new Date(j.finished_at).toLocaleString()}` : ''}
      </Text>
      {cancel.isError ? <Alert color="red">{errorText(cancel.error)}</Alert> : null}
      {j.error ? <Alert color="red">{j.error}</Alert> : null}
      <ScrollArea.Autosize mah={360} type="auto">
        <Code block aria-label="Job log">
          {lines.length === 0
            ? final
              ? 'This job wrote no log.'
              : 'Waiting for the first line…'
            : lines.map((line) => (
                <Text key={line.idx} component="span" size="xs" c={LEVEL_COLOR[line.level ?? 'info']} style={{ display: 'block' }}>
                  {line.text}
                </Text>
              ))}
        </Code>
      </ScrollArea.Autosize>
      {j.artifacts.map((artifact) => (
        <Artifact key={artifact.name} jobId={jobId} name={artifact.name} size={artifact.size} />
      ))}
    </Stack>
  );
}

function Artifact({ jobId, name, size }: { jobId: string; name: string; size: number }) {
  const api = useApi();
  const [open, setOpen] = useState(false);
  const content = useQuery({
    queryKey: ['job-artifact', jobId, name],
    enabled: open,
    queryFn: () =>
      call(api.GET('/api/v2/jobs/{public_id}/artifacts/{name}/', { params: { path: { public_id: jobId, name } }, parseAs: 'text' })),
  });
  return (
    <Stack gap={4}>
      <Group gap="xs">
        <Button size="xs" variant="subtle" onClick={() => setOpen(!open)}>
          {open ? 'Hide' : 'Show'} {name}
        </Button>
        <Text size="xs" c="dimmed">
          {size.toLocaleString()} characters
        </Text>
      </Group>
      {open && content.isPending ? <Loader size="xs" /> : null}
      {open && content.isError ? <Alert color="red">{errorText(content.error)}</Alert> : null}
      {open && content.data !== undefined ? (
        <ScrollArea.Autosize mah={240} type="auto">
          <Code block aria-label={name}>
            {content.data}
          </Code>
        </ScrollArea.Autosize>
      ) : null}
    </Stack>
  );
}
