// The claim desk: a draft's factual claims checked against what their sources said over time. Each claim races
// two verifiers in the harness's arena, in the worker, and gets a verdict — pass when the answer the sources
// support now agrees with the draft, block with a reason otherwise. The desk only advises: it never edits or
// publishes a page, and the editor decides. Once the truth is known a check is resolved (ClaimCheckView), and
// calibration averages the Brier scores of every resolved check per verifier and per draft author.
import { Alert, Button, Group, NumberInput, Stack, Table, Text, Textarea, TextInput, Title } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Claim, ClaimCheck, TimelineRow } from '@zer0/api';
import { useState } from 'react';

import { newKey, once, oneClick, Rows } from '../ai/shared';
import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { PagePicker } from '../PagePicker';
import { parseJson, POLL_MS, RunStatusBadge, useCan, WAITING, when, YesNo } from './shared';

/** Claims and a timeline to start from: one claim the sources moved away from after the draft, one they still hold. */
export const EXAMPLE_CLAIMS: Claim[] = [
  { id: 'hydra-status', question: 'What status does hydra report?', answer: 'amber', sources: ['probe'], confidence: 0.8 },
  { id: 'hydra-region', question: 'Which region serves hydra?', answer: 'eu-west', sources: ['runbook'], confidence: 0.9 },
];
export const EXAMPLE_TIMELINE: TimelineRow[] = [
  { tick: 0, source: 'probe', says: 'amber', fact: 'probe returns amber' },
  { tick: 0, source: 'runbook', says: 'eu-west', fact: 'runbook names eu-west' },
  { tick: 4, source: 'probe', says: 'green', fact: 'hydra flipped to green after failover' },
];

export function ClaimDesk() {
  const api = useApi();
  const go = useGo();
  const checks = useQuery({
    queryKey: ['claim-checks'],
    queryFn: () => call(api.GET('/api/v2/outbox/claim-checks/', { params: { query: { page_size: 100 } } })),
    refetchInterval: (q) => (q.state.data?.results.some((c) => WAITING.has(c.status) || WAITING.has(c.resolution_status)) ? POLL_MS : false),
  });
  return (
    <Stack>
      <NewCheck onStarted={(check) => go({ to: 'claim-check', id: check.id })} />
      <Title order={4}>Checks</Title>
      <Rows<ClaimCheck>
        label="Claim checks"
        query={checks}
        name={(c) => c.title || `${c.claim_count} claim${c.claim_count === 1 ? '' : 's'}`}
        onOpen={(c) => go({ to: 'claim-check', id: c.id })}
        columns={[
          { title: 'Author', cell: (c) => c.author || '—' },
          { title: 'Status', cell: (c) => <RunStatusBadge status={c.status} /> },
          { title: 'Verdict', cell: (c) => <YesNo value={c.passed} yes="pass" no="block" /> },
          { title: 'Resolved', cell: (c) => (c.resolution_status ? <RunStatusBadge status={c.resolution_status} /> : '—') },
          { title: 'Checked', cell: (c) => when(c.created_at) },
        ]}
        empty={{ title: 'No check yet', description: 'Check a draft’s claims against what their sources said.' }}
      />
      <CalibrationPanel />
    </Stack>
  );
}

function NewCheck({ onStarted }: { onStarted: (check: ClaimCheck) => void }) {
  const api = useApi();
  const qc = useQueryClient();
  const canStart = useCan('add_claimcheck');
  const [title, setTitle] = useState('');
  const [author, setAuthor] = useState('');
  const [page, setPage] = useState<number | null>(null);
  const [claims, setClaims] = useState(() => JSON.stringify(EXAMPLE_CLAIMS, null, 2));
  const [timeline, setTimeline] = useState(() => JSON.stringify(EXAMPLE_TIMELINE, null, 2));
  const [closes, setCloses] = useState(8);
  const [lag, setLag] = useState(2);
  const parsedClaims = parseJson(claims);
  const parsedTimeline = parseJson(timeline);
  const start = useMutation({
    mutationFn: ({ key }: { key: string }) =>
      call(
        api.POST('/api/v2/outbox/claim-checks/', {
          body: {
            title,
            author,
            page,
            claims: parsedClaims.value as Claim[],
            timeline: parsedTimeline.value as TimelineRow[],
            closes_at_tick: closes,
            lag_b: lag,
          },
          params: { header: once(key) },
        }),
      ),
    onSuccess: (check) => {
      void qc.invalidateQueries({ queryKey: ['claim-checks'] });
      onStarted(check);
    },
  });
  const listError = (parsed: { value?: unknown; error?: string }) => parsed.error ?? (Array.isArray(parsed.value) ? undefined : 'A JSON list');
  const claimsError = listError(parsedClaims);
  const timelineError = listError(parsedTimeline);
  return (
    <Stack
      component="form"
      aria-label="Check claims"
      onSubmit={(e) => {
        e.preventDefault();
        start.mutate({ key: newKey() });
      }}
    >
      <Title order={4}>Check a draft's claims</Title>
      <Group grow>
        <TextInput label="Title" value={title} onChange={(e) => setTitle(e.currentTarget.value)} />
        <TextInput label="Author" description="Whose draft: calibration scores them" value={author} onChange={(e) => setAuthor(e.currentTarget.value)} />
      </Group>
      <PagePicker label="The draft" description="Optional: the page the claims are from. The desk never changes it." value={page} onChange={setPage} />
      <Group grow align="flex-start">
        <Textarea label="Claims" description="id, question, answer, confidence, sources" autosize minRows={6} maxRows={18} ff="monospace" value={claims} onChange={(e) => setClaims(e.currentTarget.value)} error={claimsError} />
        <Textarea label="Source timeline" description="tick, source, says, fact, note" autosize minRows={6} maxRows={18} ff="monospace" value={timeline} onChange={(e) => setTimeline(e.currentTarget.value)} error={timelineError} />
      </Group>
      <Group align="flex-end">
        <NumberInput label="Closes at tick" min={1} max={1000} w={140} value={closes} onChange={(v) => setCloses(Number(v) || 8)} />
        <NumberInput label="Second verifier's lag" min={0} max={100} w={180} value={lag} onChange={(v) => setLag(Number(v) || 0)} />
        <Button type="submit" disabled={!canStart || Boolean(claimsError || timelineError)} loading={start.isPending} onClick={oneClick()}>
          Check claims
        </Button>
      </Group>
      {start.isError ? <Alert color="red">{errorText(start.error)}</Alert> : null}
    </Stack>
  );
}

function CalibrationPanel() {
  const api = useApi();
  const calibration = useQuery({
    queryKey: ['claim-checks', 'calibration'],
    queryFn: () => call(api.GET('/api/v2/outbox/claim-checks/calibration/')),
  });
  const c = calibration.data;
  return (
    <Stack gap="xs" aria-label="Calibration">
      <Title order={4}>Calibration</Title>
      {calibration.isError ? <Alert color="red">{errorText(calibration.error)}</Alert> : null}
      {c && c.resolved === 0 ? <Text c="dimmed">No check is resolved yet: give a check the truth to score it.</Text> : null}
      {c && c.resolved > 0 ? (
        <>
          <Text size="sm">
            {c.resolved} resolved claim{c.resolved === 1 ? '' : 's'}; the winning verifier was right {Math.round(c.winner_accuracy * 100)}% of the time. Mean
            Brier score: 0 is perfect, 0.25 is a coin flip at 0.5.
          </Text>
          <Group align="flex-start" grow>
            <BrierTable label="Verifiers" rows={c.verifiers} />
            <BrierTable label="Authors" rows={c.authors} />
          </Group>
        </>
      ) : null}
    </Stack>
  );
}

function BrierTable({ label, rows }: { label: string; rows: { name: string; n: number; brier: number }[] }) {
  return (
    <Table aria-label={label}>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{label}</Table.Th>
          <Table.Th>Claims</Table.Th>
          <Table.Th>Brier</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {rows.map((row) => (
          <Table.Tr key={row.name}>
            <Table.Td>{row.name}</Table.Td>
            <Table.Td>{row.n}</Table.Td>
            <Table.Td>{row.brier.toFixed(4)}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
