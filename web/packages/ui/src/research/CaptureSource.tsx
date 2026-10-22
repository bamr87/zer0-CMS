// Gather a source: a web page (fetched by the platform behind its guard —
// this only asks), a document upload (PDF, text, Markdown), a note, or a web
// search through a provider's own search tool, whose hits arrive as sources.
import { Alert, Button, FileInput, Group, NumberInput, SegmentedControl, Stack, Text, Textarea, TextInput } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { call, errorText } from '../call';
import { useApi } from '../context';
import { useRun } from './runs';

type Way = 'url' | 'upload' | 'note' | 'search';

export function CaptureSource({ collection }: { collection: string | null }) {
  const api = useApi();
  const qc = useQueryClient();
  const [way, setWay] = useState<Way>('url');
  const [url, setUrl] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState(5);
  const [searchRun, setSearchRun] = useState<number | null>(null);
  const run = useRun(searchRun);
  const searched = run.data?.is_final ?? false;
  useEffect(() => {
    if (searched) void qc.invalidateQueries({ queryKey: ['sources'] }); // the hits have arrived as sources
  }, [searched, qc]);
  const added = (message: string) => {
    notifications.show({ message });
    setUrl('');
    setFile(null);
    setTitle('');
    setText('');
    void qc.invalidateQueries({ queryKey: ['sources'] });
  };
  const capture = useMutation({
    mutationFn: async () => {
      if (way === 'url') {
        await call(api.POST('/api/v2/research/sources/', { body: { kind: 'url', url, collection } }));
      } else if (way === 'note') {
        await call(api.POST('/api/v2/research/sources/', { body: { kind: 'note', title, text, collection } }));
      } else if (way === 'search') {
        const started = await call(api.POST('/api/v2/research/sources/search/', { body: { query, max_results: hits, collection } }));
        setSearchRun(started.run.id);
      } else if (file) {
        await call(
          api.POST('/api/v2/research/sources/upload/', {
            body: { file: file.name, title, collection },
            bodySerializer: (body) => {
              const form = new FormData();
              form.append('file', file);
              if (body.title) form.append('title', body.title);
              if (body.collection) form.append('collection', body.collection);
              return form;
            },
          }),
        );
      }
    },
    onSuccess: () =>
      added({ url: 'Fetching the page…', upload: 'Document added', note: 'Note added', search: 'Searching the web…' }[way]),
  });
  const ready = { url: url.trim(), upload: file, note: text.trim(), search: query.trim() }[way];

  return (
    <Stack gap="xs" aria-label="Add a source">
      <SegmentedControl
        value={way}
        onChange={(value) => {
          setWay(value as Way);
          capture.reset(); // the last way's refusal is not this one's
        }}
        data={[
          { value: 'url', label: 'Web page' },
          { value: 'upload', label: 'Upload' },
          { value: 'note', label: 'Note' },
          { value: 'search', label: 'Search the web' },
        ]}
      />
      {way === 'url' ? <TextInput label="Page address" placeholder="https://…" value={url} onChange={(e) => setUrl(e.currentTarget.value)} /> : null}
      {way === 'upload' ? (
        <FileInput label="Document" description="A PDF, plain text or Markdown" accept=".pdf,.txt,.md,.markdown,application/pdf,text/plain,text/markdown" value={file} onChange={setFile} />
      ) : null}
      {way === 'upload' || way === 'note' ? <TextInput label="Title" value={title} onChange={(e) => setTitle(e.currentTarget.value)} /> : null}
      {way === 'note' ? <Textarea label="Note" autosize minRows={3} value={text} onChange={(e) => setText(e.currentTarget.value)} /> : null}
      {way === 'search' ? (
        <Group align="end" grow>
          <TextInput label="Search for" value={query} onChange={(e) => setQuery(e.currentTarget.value)} />
          <NumberInput label="Results" min={1} max={10} maw={120} value={hits} onChange={(value) => setHits(Number(value) || 5)} />
        </Group>
      ) : null}
      {capture.isError ? <Alert color="red">{errorText(capture.error)}</Alert> : null}
      {searchRun !== null && run.data && !run.data.is_final ? <Text size="sm" c="dimmed">Searching the web…</Text> : null}
      {run.data?.is_final && run.data.status !== 'succeeded' ? <Alert color="red">{run.data.error || `The search ${run.data.status}.`}</Alert> : null}
      <Group>
        <Button disabled={!ready} loading={capture.isPending} onClick={() => capture.mutate()}>
          {{ url: 'Capture', upload: 'Upload', note: 'Add note', search: 'Search' }[way]}
        </Button>
      </Group>
    </Stack>
  );
}
