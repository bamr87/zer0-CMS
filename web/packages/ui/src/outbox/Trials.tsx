// Arena trials: the harness's three offline policy agents race on a task card (a scout, a fast claimant and a
// slow one), the worker runs it, and the trial keeps its scored result. The list shows each trial's outcome; a
// trial opens on its own page (TrialView). A card is JSON as the harness's tasks/*.json have it; `lag_b` widens or
// closes the race without editing the card.
import { Alert, Button, Group, NumberInput, Stack, Textarea, Title } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { TaskCard, Trial } from '@zer0/api';
import { useState } from 'react';

import { newKey, once, oneClick, Rows } from '../ai/shared';
import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { parseJson, POLL_MS, RunStatusBadge, shown, useCan, WAITING, when, YesNo } from './shared';

/** A card to start from: the harness's stale-fact family, where the environment moves mid-race. */
export const EXAMPLE_CARD: TaskCard = {
  id: 'T-stale-fact',
  family: 'stale_fact',
  question: 'What is the live status code for service hydra?',
  expected_answer: 'green',
  closes_at_tick: 8,
  deadline_ping_tick: 7,
  lag_b: 2,
  max_env_lag: 0,
  inversion_confidence: 0.75,
  a_sticky: false,
  env_schedule: [
    { tick: 0, env_seq: 1, fact: 'hydra status probe returns amber', answer_hint: 'amber', note: 'initial reading' },
    { tick: 4, env_seq: 2, fact: 'hydra flipped to green after failover', answer_hint: 'green', note: 'environment moved' },
  ],
};

export function Trials() {
  const api = useApi();
  const go = useGo();
  const trials = useQuery({
    queryKey: ['trials'],
    queryFn: () => call(api.GET('/api/v2/outbox/trials/', { params: { query: { page_size: 100 } } })),
    refetchInterval: (q) => (q.state.data?.results.some((t) => WAITING.has(t.status)) ? POLL_MS : false),
  });
  return (
    <Stack>
      <StartTrial onStarted={(trial) => go({ to: 'trial', id: trial.id })} />
      <Title order={4}>Trials</Title>
      <Rows<Trial>
        label="Trials"
        query={trials}
        name={(t) => `${t.task.id} — ${t.task.question}`}
        onOpen={(t) => go({ to: 'trial', id: t.id })}
        columns={[
          { title: 'Status', cell: (t) => <RunStatusBadge status={t.status} /> },
          { title: 'Winner', cell: (t) => (t.result?.winner ? `${t.result.winner.from ?? '—'}: ${shown(t.result.winner.answer)}` : '—') },
          { title: 'Correct', cell: (t) => <YesNo value={t.result?.correct} yes="right" no="wrong" /> },
          { title: 'Started', cell: (t) => when(t.created_at) },
        ]}
        empty={{ title: 'No trial yet', description: 'Run a task card to race the harness’s agents on it.' }}
      />
    </Stack>
  );
}

function StartTrial({ onStarted }: { onStarted: (trial: Trial) => void }) {
  const api = useApi();
  const qc = useQueryClient();
  const canStart = useCan('add_trial');
  const [card, setCard] = useState(() => JSON.stringify(EXAMPLE_CARD, null, 2));
  const [lag, setLag] = useState<number | ''>('');
  const parsed = parseJson(card);
  const start = useMutation({
    mutationFn: ({ key }: { key: string }) =>
      call(
        api.POST('/api/v2/outbox/trials/', {
          body: { task: parsed.value as TaskCard, lag_b: lag === '' ? null : lag },
          params: { header: once(key) },
        }),
      ),
    onSuccess: (trial) => {
      void qc.invalidateQueries({ queryKey: ['trials'] });
      onStarted(trial);
    },
  });
  return (
    <Stack
      component="form"
      aria-label="Run a trial"
      onSubmit={(e) => {
        e.preventDefault();
        start.mutate({ key: newKey() });
      }}
    >
      <Title order={4}>Run a trial</Title>
      <Textarea
        label="Task card"
        description="JSON, as the harness's tasks/*.json"
        autosize
        minRows={6}
        maxRows={20}
        ff="monospace"
        value={card}
        onChange={(e) => setCard(e.currentTarget.value)}
        error={parsed.error}
      />
      <Group align="flex-end">
        <NumberInput label="Claimant B's lag (ticks)" description="Empty keeps the card's" min={0} max={100} w={220} value={lag} onChange={(v) => setLag(typeof v === 'number' ? v : '')} />
        <Button type="submit" disabled={!canStart || Boolean(parsed.error)} loading={start.isPending} onClick={oneClick()}>
          Run trial
        </Button>
      </Group>
      {start.isError ? <Alert color="red">{errorText(start.error)}</Alert> : null}
    </Stack>
  );
}
