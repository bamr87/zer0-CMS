// One arena trial on its own page: where it stands (read again until the worker has finished), the scored result —
// who won with what, whether it was right, a confidence inversion, retractions, claims per agent — and the arena's
// ledger replayed a line per event, as `outbox watch` prints it.
import { Alert, Anchor, Code, Group, Loader, Stack, Table, Text, Title } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import type { ArenaRow } from '@zer0/api';

import { JsonView } from '../ai/shared';
import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { POLL_MS, RunStatusBadge, shown, WAITING, when, YesNo } from './shared';

/** One ledger line as the harness's `watch` prints it. */
export function watchLine(row: ArenaRow): string {
  const at = `t+${row.created_at_tick ?? row.tick ?? '?'}`;
  if (row.event === 'tick') return `t+${row.tick}  tick`;
  const answer = shown(row.payload?.answer);
  switch (row.type) {
    case 'task_open':
      return `${at}  task_open  ${shown(row.payload?.question)}`;
    case 'env_event':
      return `${at}  env=${row.env_seq}  ${shown(row.payload?.fact)}`;
    case 'claim':
      return `${at}  ${row.from} claim  conf=${row.confidence}  env=${row.env_seq}  ans=${answer}`;
    case 'retract':
      return `${at}  ${row.from} retract  parent=${row.parent_id}`;
    case 'deadline_ping':
      return `${at}  deadline ping  closes_at=${row.closes_at_tick}`;
    default:
      return `${at}  ${row.type ?? row.event ?? ''}`;
  }
}

export function TrialView({ trialId }: { trialId: string }) {
  const api = useApi();
  const go = useGo();
  const trial = useQuery({
    queryKey: ['trial', trialId],
    queryFn: () => call(api.GET('/api/v2/outbox/trials/{public_id}/', { params: { path: { public_id: trialId } } })),
    refetchInterval: (q) => (WAITING.has(q.state.data?.status ?? null) ? POLL_MS : false),
  });
  if (trial.isPending) return <Loader aria-label="Loading the trial" />;
  if (trial.isError) return <Alert color="red">{errorText(trial.error)}</Alert>;
  const t = trial.data;
  const r = t.result;
  return (
    <Stack>
      <Anchor component="button" type="button" size="sm" onClick={() => go({ to: 'outbox', tab: 'trials' })}>
        ← Trials
      </Anchor>
      <Group justify="space-between">
        <Title order={2}>{t.task.id}</Title>
        <RunStatusBadge status={t.status} />
      </Group>
      <Text>{t.task.question}</Text>
      <Text size="sm" c="dimmed">
        Started {when(t.created_at)} by {t.requested_by ?? 'someone gone'}
        {t.lag_b !== null && t.lag_b !== undefined ? ` · claimant B's lag ${t.lag_b} ticks` : ''}
        {t.run_dir ? ` · ${t.run_dir}` : ''}
      </Text>
      {t.error ? <Alert color="red" title="The trial failed">{t.error}</Alert> : null}
      {WAITING.has(t.status) ? <Text c="dimmed">The worker is running the arena…</Text> : null}
      {r ? (
        <Table aria-label="Result" w="auto">
          <Table.Tbody>
            <Table.Tr>
              <Table.Th>Winner</Table.Th>
              <Table.Td>{r.winner ? `${r.winner.from ?? '—'} answered ${shown(r.winner.answer)} at confidence ${r.winner.confidence} (env ${r.winner.env_seq})` : 'no claim stood at close'}</Table.Td>
            </Table.Tr>
            <Table.Tr>
              <Table.Th>Judged against</Table.Th>
              <Table.Td>{r.resolved ? shown(r.expected_answer) : 'nothing yet: the card leaves its answer open'}</Table.Td>
            </Table.Tr>
            <Table.Tr>
              <Table.Th>Correct</Table.Th>
              <Table.Td>
                <YesNo value={r.correct} yes="right" no="wrong" />
              </Table.Td>
            </Table.Tr>
            <Table.Tr>
              <Table.Th>Confidence inversion</Table.Th>
              <Table.Td>
                <YesNo value={r.confidence_inversion === null ? null : !r.confidence_inversion} yes="none" no="confidently wrong" />
              </Table.Td>
            </Table.Tr>
            <Table.Tr>
              <Table.Th>First to claim</Table.Th>
              <Table.Td>{r.first_claim_from ?? '—'}</Table.Td>
            </Table.Tr>
            <Table.Tr>
              <Table.Th>Claims, retractions</Table.Th>
              <Table.Td>
                {Object.entries(r.claims_per_agent)
                  .map(([agent, n]) => `${agent} ${n}`)
                  .join(', ') || 'none'}{' '}
                · {r.retracts} retracted
              </Table.Td>
            </Table.Tr>
          </Table.Tbody>
        </Table>
      ) : null}
      <Title order={4}>The arena's ledger</Title>
      {t.ledger.length ? (
        <Code block aria-label="Ledger">
          {t.ledger.map(watchLine).join('\n')}
        </Code>
      ) : (
        <Text c="dimmed">Nothing yet.</Text>
      )}
      <Title order={4}>Task card</Title>
      <JsonView label="Task card" value={t.task} />
    </Stack>
  );
}
