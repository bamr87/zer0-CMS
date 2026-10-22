// The editor's AI panel (Write): run an assistant or a pipeline on the open
// page — the whole page, one block, or text selected in a block — and its
// answer lands on the page as suggestions from the assistant agent, never as
// an edit: new blocks at the end, or the block replaced (just the selection
// swapped, when there is one). The run is followed live; when it is done the
// Suggestions tab shows the change as diffs to accept or reject. The platform
// reads the saved draft, so a selection is taken from a block as saved.
import { Alert, Button, Group, SegmentedControl, Select, Stack, Text, Textarea, Title } from '@mantine/core';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { Block, PageDetail, Run } from '@zer0/api';
import { useEffect, useState } from 'react';

import { call, errorText } from '../call';
import { useApi } from '../context';
import { isRecord, options, RunProgress, useAssistants, usePipelines } from './shared';

interface Selected {
  blockId: string;
  text: string;
}

/** Text selected inside a block of the editor (`data-block-id`), or null: from a field's own selection, else the document's. */
export function selectedInBlock(): Selected | null {
  const active = document.activeElement;
  if (active instanceof HTMLTextAreaElement || active instanceof HTMLInputElement) {
    const text = active.value.slice(active.selectionStart ?? 0, active.selectionEnd ?? 0);
    const blockId = active.closest<HTMLElement>('[data-block-id]')?.dataset.blockId;
    return text.trim() && blockId ? { blockId, text } : null;
  }
  const selection = document.getSelection();
  const node = selection?.anchorNode ?? null;
  const element = node instanceof Element ? node : (node?.parentElement ?? null);
  const blockId = element?.closest<HTMLElement>('[data-block-id]')?.dataset.blockId;
  const text = selection?.toString() ?? '';
  return text.trim() && blockId ? { blockId, text } : null;
}

const preview = (block: Block) => {
  const value = block.value;
  const text = typeof value === 'string' ? value : isRecord(value) ? Object.values(value).filter((v) => typeof v === 'string').join(' ') : '';
  const plain = text.replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();
  return plain.length > 40 ? `${plain.slice(0, 40)}…` : plain;
};

const quote = (text: string) => (text.length > 50 ? `${text.slice(0, 50)}…` : text);

interface Props {
  page: PageDetail;
  /** Unsaved edits in the editor: the run reads the saved draft. */
  dirty: boolean;
  /** Why the page cannot change now (a lock), if it cannot. */
  held?: string | null;
  /** Show the page's suggestions (the editor's Suggestions tab). */
  onReview: () => void;
}

export function AiPanel({ page, dirty, held, onReview }: Props) {
  const api = useApi();
  const qc = useQueryClient();
  const assistants = useAssistants();
  const pipelines = usePipelines();
  const [kind, setKind] = useState<'assistant' | 'pipeline'>('assistant');
  const [source, setSource] = useState<string | null>(null);
  const [scope, setScope] = useState('page');
  const [selected, setSelected] = useState<Selected | null>(null);
  const [prompt, setPrompt] = useState('');
  const [runId, setRunId] = useState<number | null>(null);
  const [done, setDone] = useState<Run | null>(null);

  // A selection made in a block is offered (and chosen) as what to work on; one made elsewhere — in this panel — is not.
  useEffect(() => {
    const read = () => {
      const found = selectedInBlock();
      if (found) {
        setSelected(found);
        setScope('selection');
      }
    };
    document.addEventListener('selectionchange', read);
    return () => document.removeEventListener('selectionchange', read);
  }, []);

  const blocks = page.body.flatMap((block, i) => (block.id ? [{ value: `block:${block.id}`, label: `Block ${i + 1} · ${block.type} · ${preview(block)}`, id: block.id }] : []));
  const where = (blockId: string) => blocks.findIndex((b) => b.id === blockId) + 1;
  const scopes = [
    { value: 'page', label: 'The whole page' },
    ...(selected ? [{ value: 'selection', label: `The selection in block ${where(selected.blockId)}: “${quote(selected.text)}”` }] : []),
    ...blocks.map(({ value, label }) => ({ value, label })),
  ];
  const run = useMutation({
    mutationFn: async () => {
      const blockId = scope === 'selection' ? (selected?.blockId ?? '') : scope.startsWith('block:') ? scope.slice(6) : '';
      const body = { prompt, page_id: page.id, suggest: true, block_id: blockId, selection: scope === 'selection' ? (selected?.text ?? '') : '' };
      const path = { params: { path: { public_id: source ?? '' } } };
      const accepted = await call(
        kind === 'assistant' ? api.POST('/api/v2/ai/assistants/{public_id}/run/', { ...path, body }) : api.POST('/api/v2/ai/pipelines/{public_id}/run/', { ...path, body }),
      );
      return accepted.run.id;
    },
    onSuccess: (id) => {
      setDone(null);
      setRunId(id);
    },
  });
  const finished = (final: Run) => {
    setDone(final);
    void qc.invalidateQueries({ queryKey: ['page', page.id] });
    void qc.invalidateQueries({ queryKey: ['inbox'] });
  };
  const proposed = done && isRecord(done.output) && Array.isArray(done.output.suggestions) ? done.output.suggestions.length : 0;
  const choices = kind === 'assistant' ? options(assistants.data?.results) : options(pipelines.data?.results);
  const canRun = !held && source !== null && (kind === 'pipeline' || prompt.trim() !== '');

  return (
    <Stack gap="sm">
      <Title order={4}>Ask AI</Title>
      <Text size="sm" c="dimmed">
        The answer arrives as suggestions on this page — nothing changes until you accept them.
      </Text>
      {held ? <Alert color="gray">{held}</Alert> : null}
      {dirty ? <Alert color="yellow">You have unsaved edits: the assistant reads the saved draft. Save first to include them.</Alert> : null}
      <SegmentedControl
        aria-label="Ask"
        value={kind}
        onChange={(next) => {
          setKind(next === 'pipeline' ? 'pipeline' : 'assistant');
          setSource(null);
        }}
        data={[
          { value: 'assistant', label: 'An assistant' },
          { value: 'pipeline', label: 'A pipeline' },
        ]}
      />
      <Select label={kind === 'assistant' ? 'Assistant' : 'Pipeline'} placeholder="Choose one" data={choices} value={source} searchable onChange={setSource} />
      <Select
        label="Work on"
        description={scope === 'page' ? 'Its answer is added at the end of the page.' : 'Its answer takes the place of what you chose.'}
        data={scopes}
        value={scope}
        allowDeselect={false}
        onChange={(next) => setScope(next ?? 'page')}
      />
      <Textarea
        label="What should it do?"
        placeholder={scope === 'page' ? 'e.g. Write a two-sentence summary for the end' : 'e.g. Make it shorter and plainer'}
        autosize
        minRows={2}
        value={prompt}
        onChange={(e) => setPrompt(e.currentTarget.value)}
      />
      <Group>
        <Button disabled={!canRun} loading={run.isPending} onClick={() => run.mutate()}>
          Suggest
        </Button>
      </Group>
      {run.isError ? <Alert color="red">{errorText(run.error)}</Alert> : null}
      {runId ? <RunProgress key={runId} runId={runId} onFinal={finished} /> : null}
      {done && done.status === 'succeeded' ? (
        <Alert color="teal" title={`${proposed} suggestion${proposed === 1 ? '' : 's'} on this page`}>
          <Button size="xs" variant="light" onClick={onReview}>
            Review them
          </Button>
        </Alert>
      ) : null}
      {done && done.status !== 'succeeded' ? (
        <Alert color="red" title={`The run ${done.status}`}>
          {done.error || 'It proposed nothing.'}
        </Alert>
      ) : null}
    </Stack>
  );
}
