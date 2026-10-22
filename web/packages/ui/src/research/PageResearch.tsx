// The editor's research tab: the sources this page cites (cite another,
// drop one), a fact-check of the draft against them — and a collection, if
// chosen — whose corrections arrive as suggestions to accept in Review, and
// capturing an idea that came up while writing. Nothing here edits the page.
import { Alert, Anchor, Badge, Button, Card, Divider, Group, Loader, Select, Stack, Text, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { FactCheck } from '@zer0/api';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { CaptureIdea } from '../ideas/CaptureIdea';

const VERDICT: Record<string, string> = { supported: 'teal', contradicted: 'red', unsupported: 'orange' };

export function PageResearch({ pageId, pageTitle }: { pageId: number; pageTitle: string }) {
  const api = useApi();
  const go = useGo();
  const qc = useQueryClient();
  const [pick, setPick] = useState<string | null>(null);
  const [collection, setCollection] = useState<string | null>(null);
  const cited = useQuery({
    queryKey: ['citations', { page_id: pageId }],
    queryFn: () => call(api.GET('/api/v2/research/citations/', { params: { query: { page_id: pageId } } })),
  });
  const sources = useQuery({
    queryKey: ['sources', { page_size: 200 }],
    queryFn: () => call(api.GET('/api/v2/research/sources/', { params: { query: { page_size: 200 } } })),
  });
  const collections = useQuery({
    queryKey: ['collections', 'all'],
    queryFn: () => call(api.GET('/api/v2/research/collections/', { params: { query: { page_size: 200 } } })),
  });
  const checks = useQuery({
    queryKey: ['fact-checks', pageId],
    queryFn: () => call(api.GET('/api/v2/research/fact-checks/', { params: { query: { page_id: pageId, page_size: 5 } } })),
    refetchInterval: (q) => (q.state.data?.results[0]?.status === 'pending' ? 1500 : false),
  });
  const refreshCited = () => void qc.invalidateQueries({ queryKey: ['citations'] });
  const cite = useMutation({
    mutationFn: () => call(api.POST('/api/v2/research/citations/', { body: { source: pick ?? '', page: pageId } })),
    onSuccess: () => {
      setPick(null);
      refreshCited();
    },
  });
  const drop = useMutation({
    mutationFn: (id: string) => call(api.DELETE('/api/v2/research/citations/{public_id}/', { params: { path: { public_id: id } } })),
    onSuccess: refreshCited,
  });
  const check = useMutation({
    mutationFn: () => call(api.POST('/api/v2/research/fact-checks/', { body: { page_id: pageId, collection } })),
    onSuccess: () => {
      notifications.show({ message: 'Checking the draft against its sources…' });
      void qc.invalidateQueries({ queryKey: ['fact-checks', pageId] });
    },
  });
  const citedIds = new Set((cited.data?.results ?? []).map((c) => c.source));
  const failure = cite.error ?? drop.error ?? check.error;
  const latest = checks.data?.results[0];

  return (
    <Stack>
      {failure ? <Alert color="red">{errorText(failure)}</Alert> : null}
      <Card withBorder aria-label="Cited sources">
        <Title order={4} mb="xs">
          Sources this page cites
        </Title>
        {cited.isPending ? <Loader size="sm" /> : null}
        {cited.data?.results.length === 0 ? <Text size="sm" c="dimmed">None yet.</Text> : null}
        {(cited.data?.results ?? []).map((c) => (
          <Group key={c.id} justify="space-between" wrap="nowrap" mb={4}>
            <Anchor component="button" type="button" ta="left" onClick={() => go({ to: 'source', id: c.source })}>
              {c.source_title}
            </Anchor>
            <Button size="compact-xs" variant="subtle" color="red" onClick={() => drop.mutate(c.id)}>
              Remove
            </Button>
          </Group>
        ))}
        <Group align="end" mt="xs">
          <Select
            label="Cite a source"
            searchable
            flex={1}
            placeholder="Find a source"
            data={(sources.data?.results ?? []).filter((s) => !citedIds.has(s.id)).map((s) => ({ value: s.id, label: s.title || s.url }))}
            value={pick}
            onChange={setPick}
          />
          <Button disabled={!pick} loading={cite.isPending} onClick={() => cite.mutate()}>
            Cite
          </Button>
        </Group>
      </Card>
      <Card withBorder aria-label="Fact-check">
        <Title order={4} mb="xs">
          Fact-check this draft
        </Title>
        <Group align="end">
          <Select
            label="Also check against a collection"
            clearable
            flex={1}
            data={(collections.data?.results ?? []).map((c) => ({ value: c.id, label: c.name }))}
            value={collection}
            onChange={setCollection}
          />
          <Button loading={check.isPending || latest?.status === 'pending'} onClick={() => check.mutate()}>
            Fact-check
          </Button>
        </Group>
        {latest ? <Findings check={latest} onReview={(runId) => go({ to: 'review', runId })} /> : null}
      </Card>
      <Divider label="An idea came up?" />
      <CaptureIdea context={`From “${pageTitle}”.`} />
    </Stack>
  );
}

function Findings({ check, onReview }: { check: FactCheck; onReview: (runId: number) => void }) {
  if (check.status === 'pending') return <Text size="sm" c="dimmed" mt="sm">Checking the claims…</Text>;
  if (check.status === 'failed') return <Alert color="red" mt="sm">{check.error}</Alert>;
  const suggested = check.findings.filter((f) => f.suggestion !== null).length;
  const run = check.run;
  return (
    <Stack gap="xs" mt="sm" aria-label="Findings">
      <Text size="sm">{check.summary}</Text>
      {check.findings.map((f, i) => (
        <Card key={`${f.block}-${i}`} withBorder padding="xs">
          <Group gap="xs">
            <Badge color={VERDICT[f.verdict] ?? 'gray'} variant="light">
              {f.verdict}
            </Badge>
            <Text size="sm" fw={600}>
              {f.claim}
            </Text>
          </Group>
          <Text size="sm" c="dimmed">
            {f.explanation}
            {f.sources.length ? ` (${f.sources.map((s) => s.title).join(', ')})` : ''}
          </Text>
          {f.correction ? <Text size="sm">Suggested: {f.correction}</Text> : null}
          {f.error ? (
            <Text size="xs" c="red">
              {f.error}
            </Text>
          ) : null}
        </Card>
      ))}
      {suggested && run ? (
        <Button variant="light" onClick={() => onReview(run.id)}>
          Review {suggested} suggested correction{suggested === 1 ? '' : 's'}
        </Button>
      ) : null}
    </Stack>
  );
}
