// The book assistant beside a chapter (or a book's outline): pick a task —
// draft, continue, revise a passage, check continuity, critique, outline — add
// an instruction, and run it. The run reads the book's own material (what it
// reads is one click away); its writing arrives as suggestions on the chapter
// to accept or reject, its continuity findings and critique are shown here, and
// an outline is handed to the caller to offer. Nothing is written by running.
import { Alert, Badge, Blockquote, Button, Card, Code, Group, Loader, Paper, ScrollArea, SegmentedControl, Stack, Text, Textarea } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { RunStatus } from '../RunTimeline';
import { useFollowRun, type BookTaskKey, type Finding, type TaskOutput } from './types';

const SEVERITY: Record<string, string> = { high: 'red', medium: 'orange', low: 'gray' };
const KEEP = new Set(['run', 'book-tasks', 'book-context']);

interface Props {
  bookId: number;
  /** The chapter's page id; without one, the book's own tasks (the outline). */
  chapterId?: number;
  /** Offered a finished outline's Markdown when the person asks to compare it. */
  onOutline?: (markdown: string) => void;
}

export function BookAssist({ bookId, chapterId, onOutline }: Props) {
  const api = useApi();
  const go = useGo();
  const qc = useQueryClient();
  const tasks = useQuery({ queryKey: ['book-tasks'], queryFn: () => call(api.GET('/api/v2/books/tasks/')) });
  const offered = (tasks.data ?? []).filter((t) => t.chapter === (chapterId !== undefined));
  const [task, setTask] = useState<BookTaskKey | null>(null);
  const chosen = offered.find((t) => t.key === task) ?? offered[0];
  const [instruction, setInstruction] = useState('');
  const [selection, setSelection] = useState('');
  const [runId, setRunId] = useState<number | null>(null);
  const [showContext, setShowContext] = useState(false);
  const start = useMutation({
    mutationFn: () =>
      call(
        api.POST('/api/v2/books/{id}/assist/', {
          params: { path: { id: bookId } },
          body: { task: chosen?.key ?? 'draft', chapter: chapterId, instruction, selection: chosen?.key === 'revise' ? selection : '' },
        }),
      ),
    onSuccess: (accepted) => setRunId(accepted.run.id),
  });
  const run = useFollowRun(runId);
  const output = (run.data?.output ?? {}) as TaskOutput;
  const finished = run.data?.status === 'succeeded';
  const context = useQuery({
    queryKey: ['book-context', bookId, chapterId, chosen?.key],
    enabled: showContext && chosen !== undefined,
    queryFn: () =>
      call(api.GET('/api/v2/books/{id}/context/', { params: { path: { id: bookId }, query: { chapter: chapterId, task: chosen?.key } } })),
  });

  useEffect(() => {
    // A finished run may have proposed suggestions: the chapter's count, the inbox and the book are stale.
    if (finished) void qc.invalidateQueries({ predicate: (q) => !KEEP.has(String(q.queryKey[0])) });
  }, [finished, qc]);

  if (tasks.isPending) return <Loader size="sm" />;
  if (tasks.isError) return <Alert color="red">{errorText(tasks.error)}</Alert>;
  if (chosen === undefined) return null;

  return (
    <Card withBorder padding="sm">
      <Stack gap="xs">
        <Text fw={600}>Book assistant</Text>
        {offered.length > 1 ? (
          <SegmentedControl
            size="xs"
            fullWidth
            data={offered.map((t) => ({ value: t.key, label: t.label }))}
            value={chosen.key}
            onChange={(value) => setTask(value as BookTaskKey)}
          />
        ) : null}
        <Text size="xs" c="dimmed">
          {chosen.description} {chosen.suggests ? 'It arrives as suggestions to accept or reject.' : ''}
        </Text>
        {chosen.key === 'revise' ? (
          <Textarea
            label="Passage to revise"
            description="Copy it from the chapter exactly."
            autosize
            minRows={2}
            value={selection}
            onChange={(e) => setSelection(e.currentTarget.value)}
          />
        ) : null}
        <Textarea
          label="Instruction"
          description="Optional: what to aim for."
          autosize
          minRows={1}
          value={instruction}
          onChange={(e) => setInstruction(e.currentTarget.value)}
        />
        <Group gap="xs">
          <Button
            size="xs"
            loading={start.isPending || (runId !== null && !run.data?.is_final)}
            disabled={chosen.key === 'revise' && !selection.trim()}
            onClick={() => start.mutate()}
          >
            {chosen.label}
          </Button>
          <Button size="xs" variant="subtle" onClick={() => setShowContext(!showContext)}>
            {showContext ? 'Hide' : 'What it reads'}
          </Button>
        </Group>
        {start.isError ? <Alert color="red">{errorText(start.error)}</Alert> : null}
        {showContext && context.data ? (
          <ScrollArea.Autosize mah={320}>
            <Code block className="zer0-prose">
              {context.data.text}
            </Code>
          </ScrollArea.Autosize>
        ) : null}
        {run.data ? (
          <Group gap="xs">
            <Text size="sm">Run #{run.data.id}</Text>
            <RunStatus status={run.data.status} />
            <Button size="compact-xs" variant="subtle" onClick={() => runId !== null && go({ to: 'run', id: runId })}>
              Steps
            </Button>
          </Group>
        ) : null}
        {run.data?.error ? <Alert color="red">{run.data.error}</Alert> : null}
        {finished && runId !== null ? <Result output={output} runId={runId} onOutline={onOutline} /> : null}
      </Stack>
    </Card>
  );
}

function Result({ output, runId, onOutline }: { output: TaskOutput; runId: number; onOutline?: (markdown: string) => void }) {
  const go = useGo();
  if (output.suggestions) {
    return (
      <Alert color="blue" title={`${output.suggestions.length} suggestion${output.suggestions.length === 1 ? '' : 's'} to review`}>
        <Text size="sm">The chapter has not changed: accept them in its Suggestions tab, or in Review.</Text>
        <Button size="xs" mt="xs" variant="light" onClick={() => go({ to: 'review', runId })}>
          Review this run
        </Button>
      </Alert>
    );
  }
  const findings = output.json?.findings;
  if (output.task === 'check' && findings) {
    return (
      <Stack gap="xs">
        <Text size="sm" fw={500}>
          {output.json?.summary}
        </Text>
        {findings.length === 0 ? <Text size="sm" c="dimmed">No findings.</Text> : null}
        {findings.map((finding, i) => (
          <FindingCard key={i} finding={finding} />
        ))}
      </Stack>
    );
  }
  if (output.task === 'outline' && output.markdown && onOutline) {
    const markdown = output.markdown;
    return (
      <Button size="xs" variant="light" onClick={() => onOutline(markdown)}>
        Compare with the outline
      </Button>
    );
  }
  return (
    <Paper withBorder p="sm">
      <Text size="sm" className="zer0-prose">
        {output.markdown}
      </Text>
    </Paper>
  );
}

function FindingCard({ finding }: { finding: Finding }) {
  return (
    <Paper withBorder p="xs">
      <Group gap="xs">
        <Badge color={SEVERITY[finding.severity] ?? 'gray'} size="sm">
          {finding.severity}
        </Badge>
        <Badge variant="outline" size="sm">
          {finding.kind}
        </Badge>
      </Group>
      {finding.quote ? (
        <Blockquote p="xs" mt="xs">
          {finding.quote}
        </Blockquote>
      ) : null}
      <Text size="sm" mt={4}>
        {finding.problem}
      </Text>
      <Text size="sm" c="dimmed">
        {finding.suggestion}
      </Text>
    </Paper>
  );
}
