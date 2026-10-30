// Conversations: threads with an assistant (or a pipeline whose steps reply
// in turn), the whole history replayed to the provider on every turn — shown
// newest page first with earlier messages loaded on request, whole or
// filtered to one side or to the replies that failed. Send a message and
// watch the answer arrive by following its run; ask again (with the same
// assistant or another), delete a message, or promote one to a brief — to
// write from — or to a draft, which opens as a brief to review and apply.
// Every request that starts a run carries its Idempotency-Key, and its
// controls wait while it is out. Reachable from the AI area and from Create.
import { Alert, Badge, Button, Card, Group, Loader, Menu, Paper, SegmentedControl, Select, Stack, Text, Textarea, TextInput, Title } from '@mantine/core';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Conversation, Message } from '@zer0/api';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { ALL, isRecord, MarkdownView, newKey, once, oneClick, options, ReadOnlyNote, Rows, RunProgress, useAssistants, usePipelines } from './shared';

export function ConversationList({ siteId }: { siteId?: number }) {
  const api = useApi();
  const go = useGo();
  const assistants = useAssistants();
  const [title, setTitle] = useState('');
  const [assistant, setAssistant] = useState<string | null>(null);
  const query = { ...ALL, ordering: '-updated_at', ...(siteId ? { site: siteId } : {}) };
  const conversations = useQuery({
    queryKey: ['ai', 'conversations', query],
    queryFn: () => call(api.GET('/api/v2/ai/conversations/', { params: { query } })),
  });
  const start = useMutation({
    mutationFn: () => call(api.POST('/api/v2/ai/conversations/', { body: { title: title.trim() || 'New conversation', assistant, site: siteId ?? null } })),
    onSuccess: (made) => go({ to: 'conversation', id: made.id }),
  });
  const nameOf = (id: string | null | undefined) => assistants.data?.results.find((a) => a.id === id)?.name ?? '—';
  return (
    <Stack>
      <Card withBorder>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            start.mutate();
          }}
        >
          <Group align="end">
            <TextInput label="A new conversation" placeholder="What about?" value={title} onChange={(e) => setTitle(e.currentTarget.value)} />
            <Select label="With" placeholder="Choose an assistant" data={options(assistants.data?.results)} value={assistant} searchable onChange={setAssistant} />
            <Button type="submit" loading={start.isPending} onClick={oneClick()}>
              Start
            </Button>
          </Group>
          {start.isError ? <Alert color="red" mt="xs">{errorText(start.error)}</Alert> : null}
        </form>
      </Card>
      <Rows
        label="Conversations"
        query={conversations}
        name={(c) => c.title ?? 'New conversation'}
        onOpen={(c) => go({ to: 'conversation', id: c.id })}
        columns={[
          { title: 'With', cell: (c) => nameOf(c.assistant) },
          { title: 'Updated', cell: (c) => new Date(c.updated_at).toLocaleString() },
          { title: 'Owner', cell: (c) => c.owner ?? '—' },
        ]}
        empty={{ title: 'No conversations yet', description: 'Start one above: brainstorm, outline, or ask for a first draft.' }}
      />
    </Stack>
  );
}

/** Which messages a thread shows: all of them, one side's, or the replies that failed (the platform filters). */
const SHOW = {
  all: {},
  user: { role: 'user' },
  assistant: { role: 'assistant' },
  failed: { status: 'failed' },
} as const;
type Show = keyof typeof SHOW;

/** Messages a page: a thread opens on its newest, and earlier ones come a page at a time when asked for. */
const PAGE = 50;

/** The cursor in a next-page link, if there is one. */
const cursorOf = (next: string | null | undefined) => (next ? (new URL(next, 'http://studio.invalid').searchParams.get('cursor') ?? undefined) : undefined);

/**
 * A conversation's messages that the filter keeps, newest page first (`ordering=-seq`), each further page the
 * one before it. When the thread changes, only the pages already shown are read again.
 */
function useMessages(id: string, show: Show) {
  const api = useApi();
  return useInfiniteQuery({
    queryKey: ['ai', 'messages', id, show],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => {
      const query = { page_size: PAGE, ordering: '-seq' as const, ...SHOW[show], ...(pageParam ? { cursor: pageParam } : {}) };
      return call(api.GET('/api/v2/ai/conversations/{public_id}/messages/', { params: { path: { public_id: id }, query } }));
    },
    getNextPageParam: (last) => cursorOf(last.next),
  });
}

export function ConversationThread({ id }: { id: string }) {
  const api = useApi();
  const conversation = useQuery({
    queryKey: ['ai', 'conversation', id],
    queryFn: () => call(api.GET('/api/v2/ai/conversations/{public_id}/', { params: { path: { public_id: id } } })),
  });
  const [show, setShow] = useState<Show>('all');
  const messages = useMessages(id, show);
  // The platform sends the newest first; the thread reads top to bottom, oldest first.
  const shown = (messages.data?.pages ?? []).flatMap((page) => page.results).reverse();
  if (conversation.isPending) return <Loader aria-label="Loading the conversation" />;
  if (conversation.isError) return <Alert color="red">{errorText(conversation.error)}</Alert>;
  return (
    <Stack>
      <ThreadHeader conversation={conversation.data} />
      <ReadOnlyNote owner={conversation.data.owner} can={conversation.data.can_edit} />
      <SegmentedControl
        aria-label="Show"
        value={show}
        onChange={(next) => setShow(next in SHOW ? (next as Show) : 'all')}
        data={[
          { value: 'all', label: 'Every message' },
          { value: 'user', label: 'Yours' },
          { value: 'assistant', label: 'Answers' },
          { value: 'failed', label: 'Failed' },
        ]}
      />
      {messages.isPending ? <Loader aria-label="Loading the messages" /> : null}
      {messages.isError ? <Alert color="red">{errorText(messages.error)}</Alert> : null}
      {messages.data && shown.length === 0 ? <Text c="dimmed">{show === 'all' ? 'No messages yet: say something below.' : 'No message is shown by this filter.'}</Text> : null}
      {messages.hasNextPage ? (
        <Group justify="center">
          <Button variant="subtle" size="xs" loading={messages.isFetchingNextPage} onClick={() => void messages.fetchNextPage()}>
            Load earlier messages
          </Button>
        </Group>
      ) : null}
      <Stack component="ol" gap="sm" p={0} m={0} aria-label="Messages">
        {shown.map((m) => (
          <MessageItem key={m.id} message={m} conversation={conversation.data} />
        ))}
      </Stack>
      {conversation.data.can_edit ? <Composer conversation={conversation.data} /> : null}
    </Stack>
  );
}

function ThreadHeader({ conversation }: { conversation: Conversation }) {
  const api = useApi();
  const qc = useQueryClient();
  const assistants = useAssistants();
  const pipelines = usePipelines();
  const change = useMutation({
    mutationFn: (body: { assistant?: string | null; pipeline?: string | null }) =>
      call(api.PATCH('/api/v2/ai/conversations/{public_id}/', { params: { path: { public_id: conversation.id } }, body })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['ai', 'conversation', conversation.id] }),
  });
  return (
    <Stack gap="xs">
      <Title order={3}>{conversation.title}</Title>
      <Group align="end">
        <Select
          label="Who replies"
          data={[{ value: '', label: 'Nobody (notes only)' }, ...options(assistants.data?.results)]}
          value={conversation.assistant ?? ''}
          allowDeselect={false}
          disabled={!conversation.can_edit}
          onChange={(next) => change.mutate({ assistant: next || null })}
        />
        <Select
          label="Pipeline"
          description="Optional: its steps reply in turn"
          data={[{ value: '', label: 'None' }, ...options(pipelines.data?.results)]}
          value={conversation.pipeline ?? ''}
          allowDeselect={false}
          disabled={!conversation.can_edit}
          onChange={(next) => change.mutate({ pipeline: next || null })}
        />
      </Group>
      {change.isError ? <Alert color="red">{errorText(change.error)}</Alert> : null}
    </Stack>
  );
}

const WHO: Record<string, string> = { user: 'You', system: 'Note' };

function usage(message: Message) {
  const u = isRecord(message.usage) ? message.usage : {};
  const parts = [message.provider, message.model, typeof u.tokens === 'number' ? `${u.tokens} tokens` : '', typeof u.cost_usd === 'string' ? `$${u.cost_usd}` : ''];
  return parts.filter(Boolean).join(' · ');
}

function MessageItem({ message, conversation }: { message: Message; conversation: Conversation }) {
  const api = useApi();
  const go = useGo();
  const qc = useQueryClient();
  const assistants = useAssistants();
  const at = (key: string) => ({ params: { path: { public_id: message.id }, header: once(key) } });
  const refresh = () => void qc.invalidateQueries({ queryKey: ['ai', 'messages', conversation.id] });
  const rerun = useMutation({
    mutationFn: ({ assistant, key }: { assistant?: string; key: string }) =>
      call(api.POST('/api/v2/ai/messages/{public_id}/rerun/', { ...at(key), body: assistant ? { assistant } : {} })),
    onSuccess: refresh,
  });
  const promote = useMutation({
    mutationFn: ({ to, key }: { to: 'brief' | 'draft'; key: string }) => call(api.POST('/api/v2/ai/messages/{public_id}/promote/', { ...at(key), body: { to } })),
    onSuccess: ({ brief }) => {
      void qc.invalidateQueries({ queryKey: ['ai'] });
      go({ to: 'brief', id: brief.id });
    },
  });
  const remove = useMutation({ mutationFn: () => call(api.DELETE('/api/v2/ai/messages/{public_id}/', { params: { path: { public_id: message.id } } })), onSuccess: refresh });
  const who = message.role === 'assistant' ? (assistants.data?.results.find((a) => a.id === message.assistant)?.name ?? 'Assistant') : (WHO[message.role] ?? message.role);
  const working = message.status === 'queued' || message.status === 'running';
  // While one of this message's requests is out, its menu starts nothing else: each would be another run or brief.
  const busy = rerun.isPending || promote.isPending || remove.isPending;
  const failure = rerun.error ?? promote.error ?? remove.error;
  return (
    <Paper component="li" withBorder p="sm" style={{ listStyle: 'none' }} aria-label={`${who}, message ${message.seq}`} bg={message.role === 'user' ? 'var(--zer0-bg-inset)' : undefined}>
      <Group justify="space-between" mb={4}>
        <Group gap="xs">
          <Text fw={600} size="sm">
            {who}
          </Text>
          {message.status === 'completed' ? null : (
            <Badge size="sm" variant="light" color={message.status === 'failed' ? 'red' : 'blue'}>
              {message.status}
            </Badge>
          )}
        </Group>
        {conversation.can_edit && !working ? (
          <Menu position="bottom-end">
            <Menu.Target>
              <Button size="compact-xs" variant="subtle" loading={busy} aria-label={`Actions for message ${message.seq}`}>
                ⋯
              </Button>
            </Menu.Target>
            <Menu.Dropdown>
              {message.role === 'assistant' ? (
                <>
                  <Menu.Item disabled={busy} onClick={() => rerun.mutate({ key: newKey() })}>
                    Ask again
                  </Menu.Item>
                  {(assistants.data?.results ?? [])
                    .filter((a) => a.id !== message.assistant)
                    .slice(0, 8)
                    .map((a) => (
                      <Menu.Item key={a.id} disabled={busy} onClick={() => rerun.mutate({ assistant: a.id, key: newKey() })}>
                        Ask {a.name} instead
                      </Menu.Item>
                    ))}
                  <Menu.Divider />
                </>
              ) : null}
              <Menu.Item disabled={busy || !message.text.trim()} onClick={() => promote.mutate({ to: 'brief', key: newKey() })}>
                Promote to a brief
              </Menu.Item>
              <Menu.Item disabled={busy || !message.text.trim()} onClick={() => promote.mutate({ to: 'draft', key: newKey() })}>
                Promote to a draft
              </Menu.Item>
              <Menu.Divider />
              <Menu.Item color="red" disabled={busy} onClick={() => remove.mutate()}>
                Delete
              </Menu.Item>
            </Menu.Dropdown>
          </Menu>
        ) : null}
      </Group>
      {working && message.run ? <RunProgress runId={message.run.id} onFinal={refresh} /> : null}
      {message.text ? (
        message.role === 'assistant' ? (
          <MarkdownView markdown={message.text} label={`${who}'s answer`} />
        ) : (
          <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
            {message.text}
          </Text>
        )
      ) : null}
      {message.error ? (
        <Text size="sm" c="red">
          {message.error}
        </Text>
      ) : null}
      {usage(message) ? (
        <Text size="xs" c="dimmed" mt={4}>
          {usage(message)}
        </Text>
      ) : null}
      {failure ? <Alert color="red" mt="xs">{errorText(failure)}</Alert> : null}
    </Paper>
  );
}

function Composer({ conversation }: { conversation: Conversation }) {
  const api = useApi();
  const qc = useQueryClient();
  const assistants = useAssistants();
  const [text, setText] = useState('');
  const [assistant, setAssistant] = useState<string | null>(null);
  const [pipelineRun, setPipelineRun] = useState<string | null>(null);
  const refresh = () => void qc.invalidateQueries({ queryKey: ['ai', 'messages', conversation.id] });
  const at = (key: string) => ({ params: { path: { public_id: conversation.id }, header: once(key) } });
  const send = useMutation({
    mutationFn: (key: string) =>
      call(api.POST('/api/v2/ai/conversations/{public_id}/messages/', { ...at(key), body: { text, answer: true, ...(assistant ? { assistant } : {}) } })),
    onSuccess: () => {
      setText('');
      refresh();
    },
  });
  const runPipeline = useMutation({
    mutationFn: (key: string) => call(api.POST('/api/v2/ai/conversations/{public_id}/run-pipeline/', { ...at(key), body: { prompt: text } })),
    onSuccess: ({ run }) => {
      setText('');
      setPipelineRun(run.id);
      refresh();
    },
  });
  // One request at a time from the composer: the button waits, and so does Ctrl+Enter pressed again.
  const busy = send.isPending || runPipeline.isPending;
  const submit = () => {
    if (!busy && text.trim()) send.mutate(newKey());
  };
  const replier = assistant ?? conversation.assistant;
  const failure = send.error ?? runPipeline.error;
  return (
    <Card withBorder>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <Stack gap="xs">
          <Textarea
            label="Your message"
            description="Ctrl+Enter sends it."
            autosize
            minRows={2}
            value={text}
            onChange={(e) => setText(e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                submit();
              }
            }}
          />
          <Group align="end">
            <Select
              miw={260}
              label="Who answers this one"
              data={[{ value: '', label: 'The conversation’s assistant' }, ...options(assistants.data?.results)]}
              value={assistant ?? ''}
              allowDeselect={false}
              onChange={(next) => setAssistant(next || null)}
            />
            <Button type="submit" disabled={!text.trim() || busy} loading={send.isPending} onClick={oneClick()}>
              {replier ? 'Send' : 'Add a note'}
            </Button>
            {conversation.pipeline ? (
              <Button variant="light" disabled={busy} loading={runPipeline.isPending} onClick={oneClick(() => runPipeline.mutate(newKey()))}>
                Run the pipeline
              </Button>
            ) : null}
          </Group>
          {pipelineRun ? <RunProgress runId={pipelineRun} onFinal={refresh} /> : null}
          {failure ? <Alert color="red">{errorText(failure)}</Alert> : null}
        </Stack>
      </form>
    </Card>
  );
}
