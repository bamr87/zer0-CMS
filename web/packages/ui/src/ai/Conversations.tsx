// Conversations: threads with an assistant (or a pipeline whose steps reply
// in turn), the whole history replayed to the provider on every turn. Send a
// message and watch the answer arrive by following its run; ask again (with
// the same assistant or another), delete a message, or promote one to a
// brief — to write from — or to a draft, which opens as a brief to review and
// apply. Reachable from the AI area and from Create.
import { Alert, Badge, Button, Card, Group, Loader, Menu, Paper, Select, Stack, Text, Textarea, TextInput, Title } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ApiClient, Conversation, Message } from '@zer0/api';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { ALL, isRecord, MarkdownView, options, ReadOnlyNote, Rows, RunProgress, useAssistants, usePipelines } from './shared';

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
            <Button type="submit" loading={start.isPending}>
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

/** Every message of a conversation, oldest first, following the cursor to the end. */
async function allMessages(api: ApiClient, id: string): Promise<Message[]> {
  const found: Message[] = [];
  let cursor: string | undefined;
  for (let page = 0; page < 25; page += 1) {
    const query = { page_size: 200, ...(cursor ? { cursor } : {}) };
    const batch = await call(api.GET('/api/v2/ai/conversations/{public_id}/messages/', { params: { path: { public_id: id }, query } }));
    found.push(...batch.results);
    cursor = batch.next ? (new URL(batch.next).searchParams.get('cursor') ?? undefined) : undefined;
    if (!cursor) break;
  }
  return found;
}

export function ConversationThread({ id }: { id: string }) {
  const api = useApi();
  const conversation = useQuery({
    queryKey: ['ai', 'conversation', id],
    queryFn: () => call(api.GET('/api/v2/ai/conversations/{public_id}/', { params: { path: { public_id: id } } })),
  });
  const messages = useQuery({ queryKey: ['ai', 'messages', id], queryFn: () => allMessages(api, id) });
  if (conversation.isPending) return <Loader aria-label="Loading the conversation" />;
  if (conversation.isError) return <Alert color="red">{errorText(conversation.error)}</Alert>;
  return (
    <Stack>
      <ThreadHeader conversation={conversation.data} />
      <ReadOnlyNote owner={conversation.data.owner} can={conversation.data.can_edit} />
      {messages.isPending ? <Loader aria-label="Loading the messages" /> : null}
      {messages.isError ? <Alert color="red">{errorText(messages.error)}</Alert> : null}
      {messages.data?.length === 0 ? <Text c="dimmed">No messages yet: say something below.</Text> : null}
      <Stack component="ol" gap="sm" p={0} m={0} aria-label="Messages">
        {(messages.data ?? []).map((m) => (
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
  const path = { params: { path: { public_id: message.id } } };
  const refresh = () => void qc.invalidateQueries({ queryKey: ['ai', 'messages', conversation.id] });
  const rerun = useMutation({
    mutationFn: (assistant?: string) => call(api.POST('/api/v2/ai/messages/{public_id}/rerun/', { ...path, body: assistant ? { assistant } : {} })),
    onSuccess: refresh,
  });
  const promote = useMutation({
    mutationFn: (to: 'brief' | 'draft') => call(api.POST('/api/v2/ai/messages/{public_id}/promote/', { ...path, body: { to } })),
    onSuccess: ({ brief }) => {
      void qc.invalidateQueries({ queryKey: ['ai'] });
      go({ to: 'brief', id: brief.id });
    },
  });
  const remove = useMutation({ mutationFn: () => call(api.DELETE('/api/v2/ai/messages/{public_id}/', path)), onSuccess: refresh });
  const who = message.role === 'assistant' ? (assistants.data?.results.find((a) => a.id === message.assistant)?.name ?? 'Assistant') : (WHO[message.role] ?? message.role);
  const working = message.status === 'queued' || message.status === 'running';
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
              <Button size="compact-xs" variant="subtle" aria-label={`Actions for message ${message.seq}`}>
                ⋯
              </Button>
            </Menu.Target>
            <Menu.Dropdown>
              {message.role === 'assistant' ? (
                <>
                  <Menu.Item onClick={() => rerun.mutate(undefined)}>Ask again</Menu.Item>
                  {(assistants.data?.results ?? [])
                    .filter((a) => a.id !== message.assistant)
                    .slice(0, 8)
                    .map((a) => (
                      <Menu.Item key={a.id} onClick={() => rerun.mutate(a.id)}>
                        Ask {a.name} instead
                      </Menu.Item>
                    ))}
                  <Menu.Divider />
                </>
              ) : null}
              <Menu.Item disabled={!message.text.trim()} onClick={() => promote.mutate('brief')}>
                Promote to a brief
              </Menu.Item>
              <Menu.Item disabled={!message.text.trim()} onClick={() => promote.mutate('draft')}>
                Promote to a draft
              </Menu.Item>
              <Menu.Divider />
              <Menu.Item color="red" onClick={() => remove.mutate()}>
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
  const [pipelineRun, setPipelineRun] = useState<number | null>(null);
  const refresh = () => void qc.invalidateQueries({ queryKey: ['ai', 'messages', conversation.id] });
  const path = { params: { path: { public_id: conversation.id } } };
  const send = useMutation({
    mutationFn: () => call(api.POST('/api/v2/ai/conversations/{public_id}/messages/', { ...path, body: { text, answer: true, ...(assistant ? { assistant } : {}) } })),
    onSuccess: () => {
      setText('');
      refresh();
    },
  });
  const runPipeline = useMutation({
    mutationFn: () => call(api.POST('/api/v2/ai/conversations/{public_id}/run-pipeline/', { ...path, body: { prompt: text } })),
    onSuccess: ({ run }) => {
      setText('');
      setPipelineRun(run.id);
      refresh();
    },
  });
  const replier = assistant ?? conversation.assistant;
  const failure = send.error ?? runPipeline.error;
  return (
    <Card withBorder>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          send.mutate();
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
              if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && text.trim()) {
                e.preventDefault();
                send.mutate();
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
            <Button type="submit" disabled={!text.trim()} loading={send.isPending}>
              {replier ? 'Send' : 'Add a note'}
            </Button>
            {conversation.pipeline ? (
              <Button variant="light" loading={runPipeline.isPending} onClick={() => runPipeline.mutate()}>
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
