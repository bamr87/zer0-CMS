// One source: where it came from and how its fetch went, its summary, the
// entities it names and the passages an assistant suggests quoting (each
// kept as a quote only when a person says so), its quotes, the pages that
// cite it — and citing it on another — who sees it, and the text the platform
// extracted.
import { Alert, Anchor, Badge, Button, Card, Divider, Group, Loader, ScrollArea, Stack, Text, Textarea, TextInput, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Source } from '@zer0/api';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { PagePicker } from '../PagePicker';
import { Sharing, sharedOf } from '../Sharing';
import { entities, strings, WAITING } from './runs';

export function SourceView({ sourceId }: { sourceId: string }) {
  const api = useApi();
  const go = useGo();
  const qc = useQueryClient();
  const path = { params: { path: { public_id: sourceId } } };
  const source = useQuery({
    queryKey: ['source', sourceId],
    queryFn: () => call(api.GET('/api/v2/research/sources/{public_id}/', path)),
    refetchInterval: (q) => {
      const data = q.state.data;
      return data && (WAITING.has(data.status) || WAITING.has(data.summary_run?.status ?? '')) ? 1500 : false;
    },
  });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['source', sourceId] });
    void qc.invalidateQueries({ queryKey: ['sources'] });
  };
  const summarize = useMutation({ mutationFn: () => call(api.POST('/api/v2/research/sources/{public_id}/summarize/', path)), onSuccess: refresh });
  const refetch = useMutation({ mutationFn: () => call(api.POST('/api/v2/research/sources/{public_id}/refetch/', path)), onSuccess: refresh });
  const remove = useMutation({
    mutationFn: () => call(api.DELETE('/api/v2/research/sources/{public_id}/', path)),
    onSuccess: () => {
      refresh();
      go({ to: 'research' });
    },
  });

  if (source.isPending) return <Loader />;
  if (source.isError) return <Alert color="red">{errorText(source.error)}</Alert>;
  const s = source.data;
  const summarizing = WAITING.has(s.summary_run?.status ?? '');
  const failure = summarize.error ?? refetch.error ?? remove.error;

  return (
    <Stack>
      <Group justify="space-between" align="start">
        <Stack gap={2}>
          <Title order={2}>{s.title || s.url || 'Untitled'}</Title>
          <Group gap="xs">
            <Badge variant="light">{s.kind}</Badge>
            <Badge color={s.status === 'ready' ? 'teal' : s.status === 'failed' ? 'red' : 'yellow'} variant="light">
              {s.status}
            </Badge>
            {s.robots ? <Badge variant="outline">robots.txt: {s.robots}</Badge> : null}
          </Group>
          <Text size="sm" c="dimmed">
            {[s.author, s.site_name, s.published].filter(Boolean).join(' · ')}
          </Text>
          {s.url ? (
            <Anchor href={s.url} target="_blank" rel="noreferrer" size="sm">
              {s.url}
            </Anchor>
          ) : null}
        </Stack>
        <Group gap="xs">
          {s.kind === 'url' ? (
            <Button variant="default" loading={refetch.isPending} onClick={() => refetch.mutate()}>
              Fetch again
            </Button>
          ) : null}
          <Button variant="subtle" color="red" loading={remove.isPending} onClick={() => remove.mutate()}>
            Delete
          </Button>
        </Group>
      </Group>
      {s.error ? <Alert color="red" title="The page could not be fetched">{s.error}</Alert> : null}
      {failure ? <Alert color="red">{errorText(failure)}</Alert> : null}
      <Card withBorder>
        <Group justify="space-between" mb="xs">
          <Title order={4}>Summary</Title>
          <Button size="xs" variant="light" disabled={!s.text || summarizing} loading={summarize.isPending || summarizing} onClick={() => summarize.mutate()}>
            {s.summary ? 'Summarize again' : 'Summarize'}
          </Button>
        </Group>
        {s.summary_run?.status === 'failed' ? <Alert color="red">The summary failed; try again.</Alert> : null}
        {s.summary ? (
          <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
            {s.summary}
          </Text>
        ) : (
          <Text size="sm" c="dimmed">
            {summarizing ? 'Being summarized…' : 'No summary yet.'}
          </Text>
        )}
        {entities(s.entities).length ? (
          <Group gap={4} mt="sm" aria-label="Entities">
            {entities(s.entities).map((e) => (
              <Badge key={`${e.kind}-${e.name}`} variant="outline" size="sm">
                {e.name} · {e.kind}
              </Badge>
            ))}
          </Group>
        ) : null}
        <Highlights source={s} />
      </Card>
      <Quotes sourceId={s.id} />
      <CitedBy sourceId={s.id} />
      <WhoSees key={`${s.visibility}-${s.site}`} source={s} />
      <Divider label="Extracted text" />
      <ScrollArea.Autosize mah={420}>
        <Text size="sm" style={{ whiteSpace: 'pre-wrap' }} aria-label="Extracted text">
          {s.text || 'No text yet.'}
        </Text>
      </ScrollArea.Autosize>
    </Stack>
  );
}

/** The passages the summarizer suggests quoting: each becomes a quote only when kept. */
function Highlights({ source }: { source: Source }) {
  const api = useApi();
  const qc = useQueryClient();
  const keep = useMutation({
    mutationFn: (text: string) => call(api.POST('/api/v2/research/quotes/', { body: { source: source.id, text } })),
    onSuccess: () => {
      notifications.show({ message: 'Kept as a quote' });
      void qc.invalidateQueries({ queryKey: ['quotes', source.id] });
    },
  });
  const passages = strings(source.highlights);
  if (!passages.length) return null;
  return (
    <Stack gap={4} mt="sm" aria-label="Suggested quotes">
      <Text size="sm" fw={600}>
        Worth quoting
      </Text>
      {passages.map((passage) => (
        <Group key={passage} justify="space-between" wrap="nowrap">
          <Text size="sm" fs="italic">
            “{passage}”
          </Text>
          <Button size="compact-xs" variant="light" onClick={() => keep.mutate(passage)}>
            Keep as a quote
          </Button>
        </Group>
      ))}
    </Stack>
  );
}

function Quotes({ sourceId }: { sourceId: string }) {
  const api = useApi();
  const qc = useQueryClient();
  const [text, setText] = useState('');
  const [where, setWhere] = useState('');
  const quotes = useQuery({
    queryKey: ['quotes', sourceId],
    queryFn: () => call(api.GET('/api/v2/research/quotes/', { params: { query: { source: sourceId } } })),
  });
  const refresh = () => void qc.invalidateQueries({ queryKey: ['quotes', sourceId] });
  const add = useMutation({
    mutationFn: () => call(api.POST('/api/v2/research/quotes/', { body: { source: sourceId, text, location: where } })),
    onSuccess: () => {
      setText('');
      setWhere('');
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => call(api.DELETE('/api/v2/research/quotes/{public_id}/', { params: { path: { public_id: id } } })),
    onSuccess: refresh,
  });
  return (
    <Card withBorder aria-label="Quotes">
      <Title order={4} mb="xs">
        Quotes
      </Title>
      {(quotes.data?.results ?? []).map((q) => (
        <Group key={q.id} justify="space-between" wrap="nowrap" mb={4}>
          <Text size="sm">
            “{q.text}” {q.location ? <Text span c="dimmed">({q.location})</Text> : null}
          </Text>
          <Button size="compact-xs" variant="subtle" color="red" onClick={() => remove.mutate(q.id)}>
            Remove
          </Button>
        </Group>
      ))}
      <Group align="end" mt="xs">
        <Textarea label="A passage to keep" autosize flex={1} value={text} onChange={(e) => setText(e.currentTarget.value)} />
        <TextInput label="Where" placeholder="p. 4" w={100} value={where} onChange={(e) => setWhere(e.currentTarget.value)} />
        <Button disabled={!text.trim()} loading={add.isPending} onClick={() => add.mutate()}>
          Keep
        </Button>
      </Group>
      {add.isError || remove.isError ? <Alert color="red" mt="xs">{errorText(add.error ?? remove.error)}</Alert> : null}
    </Card>
  );
}

/** Who sees the source: only its owner may change it, which the platform checks. */
function WhoSees({ source }: { source: Source }) {
  const api = useApi();
  const qc = useQueryClient();
  const [shared, setShared] = useState(sharedOf(source));
  const save = useMutation({
    mutationFn: () => call(api.PATCH('/api/v2/research/sources/{public_id}/', { params: { path: { public_id: source.id } }, body: shared })),
    onSuccess: () => {
      notifications.show({ message: 'Saved who sees it' });
      void qc.invalidateQueries({ queryKey: ['source', source.id] });
    },
  });
  const was = sharedOf(source);
  return (
    <Card withBorder aria-label="Sharing">
      <Group align="end">
        <Sharing value={shared} onChange={setShared} />
        <Button variant="light" disabled={shared.visibility === was.visibility && shared.site === was.site} loading={save.isPending} onClick={() => save.mutate()}>
          Save
        </Button>
      </Group>
      {save.isError ? <Alert color="red" mt="xs">{errorText(save.error)}</Alert> : null}
    </Card>
  );
}

function CitedBy({ sourceId }: { sourceId: string }) {
  const api = useApi();
  const go = useGo();
  const qc = useQueryClient();
  const [page, setPage] = useState<number | null>(null);
  const citations = useQuery({
    queryKey: ['citations', { source: sourceId }],
    queryFn: () => call(api.GET('/api/v2/research/citations/', { params: { query: { source: sourceId } } })),
  });
  const cite = useMutation({
    mutationFn: () => call(api.POST('/api/v2/research/citations/', { body: { source: sourceId, page } })),
    onSuccess: () => {
      setPage(null);
      notifications.show({ message: 'Cited on the page' });
      void qc.invalidateQueries({ queryKey: ['citations'] });
    },
  });
  return (
    <Card withBorder aria-label="Cited by">
      <Title order={4} mb="xs">
        Cited by
      </Title>
      {(citations.data?.results ?? []).map((c) => {
        const pageId = c.page;
        return pageId ? (
          <Anchor key={c.id} component="button" type="button" display="block" onClick={() => go({ to: 'page', id: pageId })}>
            {c.page_title}
          </Anchor>
        ) : null;
      })}
      {citations.data?.results.length === 0 ? <Text size="sm" c="dimmed">No page cites it yet.</Text> : null}
      <Group align="end" mt="xs">
        <PagePicker label="Cite it on a page" value={page} onChange={setPage} />
        <Button disabled={!page} loading={cite.isPending} onClick={() => cite.mutate()}>
          Cite
        </Button>
      </Group>
      {cite.isError ? <Alert color="red" mt="xs">{errorText(cite.error)}</Alert> : null}
    </Card>
  );
}
