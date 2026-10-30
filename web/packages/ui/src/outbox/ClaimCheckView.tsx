// One claim check on its own page: where it stands (read again until the worker has finished), a verdict per claim
// — the draft's answer, the answer the sources support now, which verifier won and why it passed or blocked — and,
// once a person gives the truth for every claim, its resolution: whether the winner and the draft were right, and
// each verifier's and the draft's Brier score. Opening the draft is the editor's next step; the desk changes nothing.
import { Alert, Anchor, Badge, Button, Group, Loader, Stack, Table, Text, TextInput, Title } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ClaimCheckDetail } from '@zer0/api';
import { useState } from 'react';

import { newKey, once, oneClick } from '../ai/shared';
import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { parseJson, POLL_MS, RunStatusBadge, shown, useCan, WAITING, when, YesNo } from './shared';

export function ClaimCheckView({ checkId }: { checkId: string }) {
  const api = useApi();
  const go = useGo();
  const check = useQuery({
    queryKey: ['claim-check', checkId],
    queryFn: () => call(api.GET('/api/v2/outbox/claim-checks/{public_id}/', { params: { path: { public_id: checkId } } })),
    refetchInterval: (q) => (WAITING.has(q.state.data?.status ?? null) || WAITING.has(q.state.data?.resolution_status ?? null) ? POLL_MS : false),
  });
  if (check.isPending) return <Loader aria-label="Loading the check" />;
  if (check.isError) return <Alert color="red">{errorText(check.error)}</Alert>;
  const c = check.data;
  const verdicts = c.report?.claims ?? [];
  const resolution = new Map((c.resolutions ?? []).map((r) => [r.claim_id, r]));
  return (
    <Stack>
      <Anchor component="button" type="button" size="sm" onClick={() => go({ to: 'outbox', tab: 'claims' })}>
        ← Claim desk
      </Anchor>
      <Group justify="space-between">
        <Title order={2}>{c.title || 'Claim check'}</Title>
        <Group gap="xs">
          <RunStatusBadge status={c.status} />
          {c.report ? <YesNo value={c.report.pass} yes="every claim passes" no="blocked" /> : null}
        </Group>
      </Group>
      <Text size="sm" c="dimmed">
        {c.author ? `${c.author}'s draft · ` : ''}checked {when(c.created_at)} by {c.requested_by ?? 'someone gone'} · closes at tick {c.closes_at_tick}, second
        verifier {c.lag_b} ticks behind
      </Text>
      {c.page ? (
        <Anchor component="button" type="button" onClick={() => c.page && go({ to: 'page', id: c.page.id })}>
          Open the draft: {c.page.title}
        </Anchor>
      ) : null}
      {c.error ? <Alert color="red" title="The check failed">{c.error}</Alert> : null}
      {WAITING.has(c.status) ? <Text c="dimmed">The worker is racing the verifiers…</Text> : null}
      {verdicts.length ? (
        <Table aria-label="Verdicts">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Claim</Table.Th>
              <Table.Th>The draft says</Table.Th>
              <Table.Th>The sources support</Table.Th>
              <Table.Th>Verdict</Table.Th>
              <Table.Th>Winner</Table.Th>
              <Table.Th>Resolution</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {verdicts.map((v) => {
              const r = resolution.get(v.claim_id);
              return (
                <Table.Tr key={v.claim_id}>
                  <Table.Td>
                    <Text fw={600}>{v.claim_id}</Text>
                    <Text size="sm">{v.question}</Text>
                  </Table.Td>
                  <Table.Td>{shown(v.draft_answer)}</Table.Td>
                  <Table.Td>{v.supported_answer === null ? '—' : shown(v.supported_answer)}</Table.Td>
                  <Table.Td>
                    <Badge color={v.verdict === 'pass' ? 'teal' : 'red'} variant="light">
                      {v.verdict}
                    </Badge>
                    <Text size="xs" c="dimmed">
                      {v.reason.replaceAll('_', ' ')}
                    </Text>
                  </Table.Td>
                  <Table.Td>{v.winner_from ? `${v.winner_from} at ${v.winner_confidence} (env ${v.winner_env_seq} of ${v.latest_env_seq})` : '—'}</Table.Td>
                  <Table.Td>
                    {r ? (
                      <Stack gap={2}>
                        <Text size="sm">truth: {shown(r.truth)}</Text>
                        <YesNo value={r.draft_correct} yes="draft right" no="draft wrong" />
                        <Text size="xs">
                          Brier {Object.entries(r.brier).map(([agent, score]) => `${agent} ${score}`).join(', ')}
                          {r.draft_brier !== null ? ` · draft ${r.draft_brier}` : ''}
                        </Text>
                      </Stack>
                    ) : (
                      '—'
                    )}
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      ) : null}
      {c.status === 'succeeded' ? <Resolve check={c} /> : null}
    </Stack>
  );
}

/** The truth for every claim of a check: each answer is JSON when it reads as JSON (a number, a list), else text. */
function Resolve({ check }: { check: ClaimCheckDetail }) {
  const api = useApi();
  const qc = useQueryClient();
  const canResolve = useCan('change_claimcheck');
  const [truth, setTruth] = useState<Record<string, string>>(() => {
    const known = check.truth ?? {};
    return Object.fromEntries(check.claims.map((claim) => [claim.id, known[claim.id] === undefined ? '' : shown(known[claim.id])]));
  });
  const resolve = useMutation({
    mutationFn: ({ key }: { key: string }) => {
      const body = Object.fromEntries(Object.entries(truth).map(([id, text]) => [id, parseJson(text).error ? text : parseJson(text).value]));
      return call(api.POST('/api/v2/outbox/claim-checks/{public_id}/resolve/', { params: { path: { public_id: check.id }, header: once(key) }, body: { truth: body } }));
    },
    onSuccess: (resolved) => {
      qc.setQueryData(['claim-check', check.id], resolved);
      void qc.invalidateQueries({ queryKey: ['claim-checks'] });
    },
  });
  const busy = WAITING.has(check.resolution_status);
  const ready = Object.values(truth).every((text) => text.trim() !== '');
  return (
    <Stack
      component="form"
      aria-label="Resolve"
      onSubmit={(e) => {
        e.preventDefault();
        resolve.mutate({ key: newKey() });
      }}
    >
      <Title order={4}>{check.resolution_status === 'succeeded' ? 'Resolved' : 'Resolve against the truth'}</Title>
      <Text size="sm" c="dimmed">
        Once you know what was true, the worker re-scores each claim from its own ledger.
        {check.resolved_at ? ` Last resolved ${when(check.resolved_at)}.` : ''}
      </Text>
      {check.claims.map((claim) => (
        <TextInput
          key={claim.id}
          label={`Truth for ${claim.id}`}
          description={claim.question}
          value={truth[claim.id] ?? ''}
          onChange={(e) => {
            const value = e.currentTarget.value;
            setTruth((now) => ({ ...now, [claim.id]: value }));
          }}
        />
      ))}
      {check.resolution_error ? <Alert color="red">{check.resolution_error}</Alert> : null}
      {resolve.isError ? <Alert color="red">{errorText(resolve.error)}</Alert> : null}
      {busy ? <Text c="dimmed">Resolving…</Text> : null}
      <Group>
        <Button type="submit" disabled={!canResolve || !ready || busy} loading={resolve.isPending} onClick={oneClick()}>
          {check.resolution_status === 'succeeded' ? 'Resolve again' : 'Resolve'}
        </Button>
      </Group>
    </Stack>
  );
}
