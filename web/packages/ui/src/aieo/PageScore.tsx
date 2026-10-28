// The editor's citability panel (Write → Citability): the open page's last
// audit — its score, the five dimensions and the worst gaps — scored again on
// request (the saved draft, by the heuristics or a model's evaluation), and
// optimize, expand, scrub or rewrite, whose rewrite lands on this page as
// suggestions in the Suggestions tab. Nothing here changes the page.
import { Alert, Anchor, Button, Group, Stack, Switch, Text, Title } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { newKey, once, oneClick, RunProgress } from '../ai/shared';
import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { Rewrite } from './Rewrite';
import { ScoreCard } from './ScoreCard';
import { readScore } from './score';

interface Props {
  pageId: number;
  /** Unsaved edits: the audit and the rewrite read the saved draft. */
  dirty?: boolean;
  /** Why the page cannot be changed now (a lock), if it cannot. */
  held?: string | null;
  onReview?: () => void;
}

export function PageScore({ pageId, dirty, held, onReview }: Props) {
  const api = useApi();
  const go = useGo();
  const qc = useQueryClient();
  const [ai, setAi] = useState(false);
  const [runId, setRunId] = useState<number | null>(null);
  const latest = useQuery({
    queryKey: ['aieo', 'audits', 'page', pageId],
    queryFn: () => call(api.GET('/api/v2/aieo/audits/', { params: { query: { page: pageId, page_size: 1 } } })),
  });
  const last = latest.data?.results[0];
  const audit = useQuery({
    queryKey: ['aieo', 'audit', last?.id],
    enabled: last?.status === 'ready',
    queryFn: () => call(api.GET('/api/v2/aieo/audits/{public_id}/', { params: { path: { public_id: last?.id ?? '' } } })),
  });
  const score = useMutation({
    mutationFn: (key: string) =>
      call(
        api.POST('/api/v2/aieo/audits/', {
          params: { header: once(key) },
          body: { kind: 'page', page_id: pageId, method: ai ? 'ai' : 'heuristic', content: '', format: 'markdown', url: '', max_pages: 25, visual: false, provider: '', title: '' },
        }),
      ),
    onSuccess: (made) => setRunId(made.run.id),
  });
  return (
    <Stack gap="sm" aria-label="Citability">
      <Group justify="space-between">
        <Title order={4}>Citability</Title>
        <Anchor component="button" type="button" size="sm" onClick={() => go({ to: 'aieo' })}>
          Open AIEO
        </Anchor>
      </Group>
      {dirty ? <Alert color="yellow">Save first: the score and the rewrites read the saved draft.</Alert> : null}
      {latest.isError ? <Alert color="red">{errorText(latest.error)}</Alert> : null}
      {audit.data ? (
        <>
          <ScoreCard scored={readScore(audit.data.result, audit.data)} compact />
          <Text size="xs" c="dimmed">
            Scored {new Date(audit.data.audited_at ?? audit.data.created_at).toLocaleString()}.
          </Text>
        </>
      ) : last?.status === 'failed' ? (
        <Alert color="red">{last.error || 'The last audit failed.'}</Alert>
      ) : latest.isSuccess && !last ? (
        <Text size="sm" c="dimmed">
          Not scored yet.
        </Text>
      ) : null}
      <Group>
        <Switch label="A model's evaluation" checked={ai} onChange={(e) => setAi(e.currentTarget.checked)} />
        <Button size="xs" loading={score.isPending} onClick={oneClick(() => score.mutate(newKey()))}>
          Score this page
        </Button>
      </Group>
      {score.isError ? <Alert color="red">{errorText(score.error)}</Alert> : null}
      {runId ? (
        <RunProgress key={runId} runId={runId} onFinal={() => void qc.invalidateQueries({ queryKey: ['aieo'] })} />
      ) : null}
      <Title order={5}>Improve it</Title>
      {held ? <Alert color="gray">{held}</Alert> : <Rewrite pageId={pageId} onReview={onReview} />}
    </Stack>
  );
}
