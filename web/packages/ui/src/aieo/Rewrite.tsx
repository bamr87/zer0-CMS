// Optimize, expand, scrub or rewrite — or apply one pattern — as a run of
// AIEO's bundled assistant for it. On a page the rewrite arrives as
// suggestions there (each changed block), reviewed in the editor's
// Suggestions tab or the Review inbox; on a pasted text it is a draft shown
// beside the original. The score before and after comes with it.
import { Alert, Badge, Button, Group, Paper, SegmentedControl, Select, Stack, Text, Textarea, Title } from '@mantine/core';
import { useMutation } from '@tanstack/react-query';
import type { AieoRewriteMode, Run } from '@zer0/api';
import { useState } from 'react';

import { MarkdownView, newKey, once, oneClick, RunProgress } from '../ai/shared';
import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { DiffView } from '../DiffView';
import { PagePicker } from '../PagePicker';

const MODES: { value: AieoRewriteMode; label: string }[] = [
  { value: 'optimize', label: 'Optimize for citability' },
  { value: 'expand', label: 'Expand (definitions, FAQ, comparisons)' },
  { value: 'scrub', label: 'Scrub AI-writing tells' },
  { value: 'rewrite', label: 'Rewrite for clarity and depth' },
];

interface Props {
  siteId?: number;
  /** A pattern of the library: the rewrite applies it. */
  pattern?: { name: string; display_name: string };
  /** A page chosen already (the editor's panel). */
  pageId?: number;
  onReview?: () => void;
}

export function Rewrite({ siteId, pattern, pageId: fixedPage, onReview }: Props) {
  const api = useApi();
  const go = useGo();
  const [on, setOn] = useState<'page' | 'text'>('page');
  const [pageId, setPageId] = useState<number | null>(fixedPage ?? null);
  const [content, setContent] = useState('');
  const [mode, setMode] = useState<AieoRewriteMode>('optimize');
  const [style, setStyle] = useState<'preserve' | 'aggressive'>('preserve');
  const [runId, setRunId] = useState<number | null>(null);
  const [done, setDone] = useState<Run | null>(null);
  const page = fixedPage ?? (on === 'page' ? pageId : null);
  const start = useMutation({
    mutationFn: async (key: string) => {
      const header = once(key);
      const text = page ? '' : content;
      const made = pattern
        ? await call(
            api.POST('/api/v2/aieo/patterns/{name}/apply/', {
              params: { path: { name: pattern.name }, header },
              body: { page_id: page, content: text, style },
            }),
          )
        : await call(api.POST('/api/v2/aieo/rewrites/', { params: { header }, body: { mode, page_id: page, content: text, style, pattern: null } }));
      return made.run.id;
    },
    onSuccess: (id) => {
      setDone(null);
      setRunId(id);
    },
  });
  const ready = page || content.trim();

  return (
    <Stack gap="sm">
      {fixedPage === undefined ? (
        <SegmentedControl
          value={on}
          onChange={(v) => setOn(v === 'text' ? 'text' : 'page')}
          data={[
            { value: 'page', label: 'A page (suggestions)' },
            { value: 'text', label: 'A text (a draft)' },
          ]}
          aria-label="What to rewrite"
        />
      ) : null}
      {fixedPage === undefined && on === 'page' ? <PagePicker label="Page" value={pageId} onChange={setPageId} siteId={siteId} /> : null}
      {fixedPage === undefined && on === 'text' ? (
        <Textarea label="Text" autosize minRows={4} maxRows={14} value={content} onChange={(e) => setContent(e.currentTarget.value)} />
      ) : null}
      <Group align="end">
        {pattern ? (
          <Text size="sm">
            Apply <b>{pattern.display_name}</b>
          </Text>
        ) : (
          <Select label="Rewrite" data={MODES} value={mode} onChange={(v) => setMode((v as AieoRewriteMode) ?? 'optimize')} allowDeselect={false} w={300} />
        )}
        <Select
          label="Style"
          data={[
            { value: 'preserve', label: "Keep the author's voice" },
            { value: 'aggressive', label: 'Reshape freely' },
          ]}
          value={style}
          onChange={(v) => setStyle(v === 'aggressive' ? 'aggressive' : 'preserve')}
          allowDeselect={false}
          w={200}
        />
        <Button disabled={!ready} loading={start.isPending} onClick={oneClick(() => start.mutate(newKey()))}>
          {pattern ? 'Apply the pattern' : 'Rewrite'}
        </Button>
      </Group>
      {start.isError ? <Alert color="red">{errorText(start.error)}</Alert> : null}
      {runId ? <RunProgress key={runId} runId={runId} onFinal={setDone} /> : null}
      {done ? <Outcome run={done} original={content} onPage={Boolean(page)} onReview={onReview ?? (() => go({ to: 'review', runId: done.id }))} /> : null}
    </Stack>
  );
}

function Outcome({ run, original, onPage, onReview }: { run: Run; original: string; onPage: boolean; onReview: () => void }) {
  if (run.status !== 'succeeded') return <Alert color="red" title={`The rewrite ${run.status}`}>{run.error || 'It gave no answer.'}</Alert>;
  const out = run.output as { markdown?: string; score_before?: number; score_after?: number; uplift?: number; suggestions?: number[] };
  const markdown = out.markdown ?? '';
  const uplift = out.uplift ?? 0;
  return (
    <Paper withBorder p="md">
      <Stack gap="sm">
        <Group gap="xs">
          <Text size="sm">
            Score {out.score_before} → {out.score_after}
          </Text>
          <Badge color={uplift > 0 ? 'teal' : uplift < 0 ? 'red' : 'gray'}>
            {uplift > 0 ? '+' : ''}
            {uplift}
          </Badge>
        </Group>
        {onPage ? (
          <Group>
            <Text size="sm">{out.suggestions?.length ?? 0} suggestions wait on the page — nothing is changed until you accept them.</Text>
            <Button size="xs" variant="light" onClick={onReview}>
              Review them
            </Button>
          </Group>
        ) : (
          <>
            <Title order={5}>The draft, beside the original</Title>
            <DiffView before={original} after={markdown} />
            <MarkdownView markdown={markdown} label="The rewrite" />
          </>
        )}
      </Stack>
    </Paper>
  );
}
