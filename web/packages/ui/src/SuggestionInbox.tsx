// The review inbox: every pending suggestion a person may decide, grouped by
// the agent run that proposed it, each with its rationale and its change as a
// diff. Accept one, reject one with a reason, or accept all of a run that are
// shown here — one draft revision per page, never a publish. "All" is what
// the person sees: the ids of the shown suggestions go with the request, so a
// filtered or shortened view never accepts what it did not show. The platform
// re-checks rights, locks and the page's current state on every decision; a
// suggestion whose block has gone is marked stale and cannot be accepted.
import { Alert, Anchor, Badge, Button, Card, Group, Loader, Paper, Stack, Text, TextInput } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Suggestion } from '@zer0/api';
import { useState } from 'react';

import { call, errorText } from './call';
import { useApi, useGo } from './context';
import { DiffView } from './DiffView';

interface Filters {
  siteId?: number;
  pageId?: number;
  runId?: number;
  /** Why accepting is held back (unsaved edits, a lock): accepting makes a new revision. */
  holdAccept?: string;
}

export function SuggestionInbox({ siteId, pageId, runId, holdAccept }: Filters) {
  const api = useApi();
  const go = useGo();
  const qc = useQueryClient();
  const query = { site: siteId, page_id: pageId, run: runId, page_size: 100 };
  const inbox = useQuery({
    queryKey: ['inbox', query],
    queryFn: () => call(api.GET('/api/v2/review/suggestions/', { params: { query } })),
  });
  const done = (message: string) => {
    notifications.show({ message });
    void qc.invalidateQueries();
  };
  const decide = useMutation({
    mutationFn: ({ id, decision, reason }: { id: number; decision: 'accept' | 'reject'; reason?: string }) =>
      call(api.POST('/api/v2/suggestions/{id}/{decision}/', { params: { path: { id, decision } }, body: reason ? { reason } : {} })),
    onSuccess: (_, { decision }) => done(decision === 'accept' ? 'Accepted as a draft revision' : 'Rejected'),
  });
  const acceptRun = useMutation({
    mutationFn: ({ run, ids }: { run: number; ids: number[] }) =>
      call(api.POST('/api/v2/review/runs/{run_id}/accept/', { params: { path: { run_id: run } }, body: { ids } })),
    onSuccess: (result) => done(`Accepted ${result.accepted.length} suggestion(s) as ${result.revision_ids.length} draft revision(s)`),
  });

  if (inbox.isPending) return <Loader />;
  if (inbox.isError) return <Alert color="red">{errorText(inbox.error)}</Alert>;
  if (inbox.data.count === 0) return <Text c="dimmed">Nothing to review.</Text>;

  const runs = new Map<number, Suggestion[]>();
  for (const s of inbox.data.results) runs.set(s.run_id ?? 0, [...(runs.get(s.run_id ?? 0) ?? []), s]);
  const failure = decide.error ?? acceptRun.error;

  return (
    <Stack>
      {holdAccept ? <Alert color="yellow">{holdAccept}</Alert> : null}
      {failure ? <Alert color="red">{errorText(failure)}</Alert> : null}
      {[...runs.entries()].map(([run, items]) => {
        const acceptable = items.filter((s) => !s.change.stale).map((s) => s.id);
        return (
          <Card key={run} withBorder padding="md">
            <Group justify="space-between" mb="sm">
              <Group gap="xs">
                <Text fw={600}>{run ? `Run #${run}` : 'Without a run'}</Text>
                {items[0]?.agent ? <Badge variant="light">{items[0].agent}</Badge> : null}
                <Text size="sm" c="dimmed">
                  {items.length} suggestion{items.length === 1 ? '' : 's'}
                </Text>
              </Group>
              {run ? (
                <Group gap="xs">
                  <Button variant="subtle" size="xs" onClick={() => go({ to: 'run', id: run })}>
                    Open run
                  </Button>
                  <Button
                    size="xs"
                    disabled={!!holdAccept || acceptable.length === 0}
                    loading={acceptRun.isPending}
                    onClick={() => acceptRun.mutate({ run, ids: acceptable })}
                  >
                    Accept all {acceptable.length} shown of run #{run}
                  </Button>
                </Group>
              ) : null}
            </Group>
            <Stack gap="sm">
              {items.map((s) => (
                <SuggestionCard
                  key={s.id}
                  suggestion={s}
                  busy={decide.isPending}
                  held={!!holdAccept}
                  onOpen={() => go({ to: 'page', id: s.target.id })}
                  onAccept={() => decide.mutate({ id: s.id, decision: 'accept' })}
                  onReject={(reason) => decide.mutate({ id: s.id, decision: 'reject', reason })}
                />
              ))}
            </Stack>
          </Card>
        );
      })}
    </Stack>
  );
}

interface CardProps {
  suggestion: Suggestion;
  busy: boolean;
  held: boolean;
  onOpen: () => void;
  onAccept: () => void;
  onReject: (reason: string) => void;
}

function SuggestionCard({ suggestion: s, busy, held, onOpen, onAccept, onReject }: CardProps) {
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState('');
  return (
    <Paper p="sm" aria-label={`Suggestion ${s.id}`} component="article">
      <Group gap="xs" mb={4}>
        <Anchor component="button" type="button" fw={600} onClick={onOpen}>
          {s.target.title}
        </Anchor>
        <Badge variant="outline">{s.change.label}</Badge>
        {s.change.stale ? (
          <Badge color="red" title="The block it changes is gone">
            stale
          </Badge>
        ) : null}
      </Group>
      {s.rationale ? (
        <Text size="sm" c="dimmed" mb="xs">
          {s.rationale}
        </Text>
      ) : null}
      <DiffView before={s.change.before} after={s.change.after} />
      <Group gap="xs" mt="sm">
        <Button size="xs" disabled={s.change.stale || busy || held} onClick={onAccept}>
          Accept
        </Button>
        <Button size="xs" variant="default" disabled={busy} onClick={() => setRejecting(!rejecting)}>
          Reject…
        </Button>
      </Group>
      {rejecting ? (
        <Group mt="xs" align="end">
          <TextInput label="Why reject it?" value={reason} onChange={(e) => setReason(e.currentTarget.value)} flex={1} />
          <Button size="xs" color="red" disabled={busy} onClick={() => onReject(reason)}>
            Reject
          </Button>
        </Group>
      ) : null}
    </Paper>
  );
}
