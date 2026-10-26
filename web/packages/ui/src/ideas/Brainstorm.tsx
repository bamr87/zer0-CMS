// A brainstorm session: ask an assistant (the bundled Brainstormer) for
// angles, headlines or outlines; its reply is a run of the platform's
// assistant agent, followed here until it finishes, and its ideas are kept
// only when a person picks them — nothing becomes an idea unseen. Asking
// again continues the same conversation, so "more like the second" works.
import { Alert, Button, Checkbox, Group, Loader, NumberInput, Paper, SegmentedControl, Stack, Text, Textarea } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi } from '../context';

type Kind = 'angles' | 'headlines' | 'outlines';
interface Proposed {
  title: string;
  notes: string;
  kind: string;
}

const WAITING = new Set(['queued', 'running']);

function proposed(result: unknown): Proposed[] {
  const ideas = typeof result === 'object' && result !== null ? (result as { ideas?: unknown }).ideas : undefined;
  if (!Array.isArray(ideas)) return [];
  return ideas.filter((idea): idea is Proposed => typeof idea === 'object' && idea !== null && typeof (idea as Proposed).title === 'string');
}

export function Brainstorm({ boardId }: { boardId?: string | null }) {
  const api = useApi();
  const qc = useQueryClient();
  const [kind, setKind] = useState<Kind>('angles');
  const [count, setCount] = useState(8);
  const [prompt, setPrompt] = useState('');
  const [session, setSession] = useState<{ conversation: string; reply: string } | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const ask = useMutation({
    mutationFn: () =>
      call(api.POST('/api/v2/ideas/brainstorm/', { body: { prompt, kind, count, board: boardId ?? null, conversation: session?.conversation ?? null } })),
    onSuccess: (started) => {
      setSession({ conversation: started.conversation, reply: started.reply.id });
      setPicked([]);
    },
  });
  const replyId = session?.reply ?? '';
  const reply = useQuery({
    queryKey: ['message', replyId],
    enabled: replyId !== '',
    queryFn: () => call(api.GET('/api/v2/ai/messages/{public_id}/', { params: { path: { public_id: replyId } } })),
    refetchInterval: (query) => (WAITING.has(query.state.data?.status ?? 'queued') ? 1500 : false),
  });
  const ideas = reply.data?.status === 'completed' ? proposed(reply.data.result) : [];
  const keep = useMutation({
    mutationFn: () => call(api.POST('/api/v2/ideas/keep/', { body: { message: replyId, picks: picked.map(Number), board: boardId ?? null } })),
    onSuccess: (kept) => {
      notifications.show({ message: `Kept ${kept.ideas.length} idea${kept.ideas.length === 1 ? '' : 's'}` });
      setPicked([]);
      void qc.invalidateQueries({ queryKey: ['ideas'] });
    },
  });
  const thinking = ask.isPending || (reply.isFetched && WAITING.has(reply.data?.status ?? ''));
  const failure = ask.error ?? keep.error;

  return (
    <Stack gap="sm" aria-label="Brainstorm">
      <SegmentedControl
        value={kind}
        onChange={(value) => setKind(value as Kind)}
        data={[
          { value: 'angles', label: 'Angles' },
          { value: 'headlines', label: 'Headlines' },
          { value: 'outlines', label: 'Outlines' },
        ]}
      />
      <Textarea
        label={session ? 'Ask for more' : 'What should we brainstorm?'}
        description={session ? 'Continues this session: “more like the second”, “funnier”, “for beginners”.' : undefined}
        autosize
        minRows={2}
        value={prompt}
        onChange={(e) => setPrompt(e.currentTarget.value)}
      />
      <Group align="end">
        <NumberInput label="How many" min={1} max={20} w={120} value={count} onChange={(value) => setCount(Number(value) || 8)} />
        <Button disabled={!prompt.trim()} loading={thinking} onClick={() => ask.mutate()}>
          {session ? 'Brainstorm more' : 'Brainstorm'}
        </Button>
        {session ? (
          <Button variant="subtle" onClick={() => setSession(null)}>
            New session
          </Button>
        ) : null}
      </Group>
      {failure ? <Alert color="red">{errorText(failure)}</Alert> : null}
      {thinking && !ask.isPending ? (
        <Group gap="xs">
          <Loader size="xs" />
          <Text size="sm" c="dimmed">
            The assistant is thinking…
          </Text>
        </Group>
      ) : null}
      {reply.data?.status === 'failed' ? <Alert color="red">{reply.data.error || 'The brainstorm failed.'}</Alert> : null}
      {ideas.length ? (
        <Paper withBorder p="sm">
          <Checkbox.Group label="Keep the ideas you want" value={picked} onChange={setPicked}>
            <Stack gap="xs" mt="xs">
              {ideas.map((idea, i) => (
                <Checkbox key={`${i}-${idea.title}`} value={String(i)} label={`${idea.title} (${idea.kind})`} description={idea.notes} />
              ))}
            </Stack>
          </Checkbox.Group>
          <Group mt="sm">
            <Button disabled={!picked.length} loading={keep.isPending} onClick={() => keep.mutate()}>
              Keep {picked.length || ''} idea{picked.length === 1 ? '' : 's'}
            </Button>
          </Group>
        </Paper>
      ) : null}
    </Stack>
  );
}
